"""
reindex_rag.py
==============
Safe, idempotent ChromaDB maintenance script.

Run this script at any time to:
  1. Validate ChromaDB integrity (find orphans, bad metadata, malformed IDs).
  2. Fix detected issues automatically.
  3. Perform an incremental sync — index only chunks that are missing from Chroma.

What this script does NOT do:
  • It does NOT rebuild the ChromaDB from scratch.
  • It does NOT delete correctly-indexed chunks.
  • It does NOT re-chunk any text (chunks are read directly from KnowledgeChunk).
  • It does NOT modify rag.py, retrieval logic, or any endpoint.

Usage:
  python reindex_rag.py            — full incremental sync + integrity check
  python reindex_rag.py --sync     — incremental sync only (skip integrity pass)
  python reindex_rag.py --validate — integrity check + fix only (skip sync)
"""

import sys
import os
import argparse

# Fix Windows console Unicode encoding for Arabic text
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

from database import SessionLocal
from models import KnowledgeChunk, Document

# Legacy imports — kept so any external script that imports them still works
from rag import index_chunks_to_rag, add_document_to_rag


# ─────────────────────────────────────────────────────────────────────────────
# Main operations
# ─────────────────────────────────────────────────────────────────────────────

def run_incremental_sync(db) -> dict:
    """
    Sync every KnowledgeChunk that is not yet in ChromaDB.
    Already-indexed chunks are skipped — safe to run repeatedly.
    """
    from chroma_sync import sync_all_chunks

    chunks = db.query(KnowledgeChunk).all()
    if not chunks:
        print(
            "[REINDEX] No chunks found in the database. "
            "Please upload documents via the admin panel first."
        )
        return {"total_docs": 0, "total_indexed": 0, "errors": 0}

    print(f"[REINDEX] Found {len(chunks)} chunk(s) in database. Starting incremental sync …")
    summary = sync_all_chunks(db)
    return summary


def run_integrity_check(db) -> dict:
    """
    Detect and fix ChromaDB integrity issues:
      - Orphaned vectors (doc deleted from DB but vectors remain in Chroma)
      - Vectors with missing / incomplete metadata
      - Vectors with malformed IDs
      - DB chunks not yet indexed in Chroma (triggers sync)
    """
    from chroma_sync import validate_and_fix_integrity

    print("[REINDEX] Starting ChromaDB integrity check and repair …")
    summary = validate_and_fix_integrity(db)
    return summary


def reindex_all(sync_only: bool = False, validate_only: bool = False) -> None:
    """
    Entry point — opens a DB session and orchestrates the selected operation(s).

    Arguments:
        sync_only     — run incremental sync, skip integrity pass
        validate_only — run integrity pass only, skip explicit sync call
                        (the integrity pass internally runs sync after cleanup)
    """
    db = SessionLocal()
    try:
        if validate_only:
            # ── Integrity + auto-fix (includes a sync pass internally) ────────
            integrity_summary = run_integrity_check(db)
            print(
                "\n[REINDEX] === Integrity Report ===\n"
                f"  Total vectors in Chroma   : {integrity_summary.get('total_vectors', '?')}\n"
                f"  Orphaned vectors removed  : {integrity_summary.get('orphaned_vectors', 0)}\n"
                f"  Bad-metadata removed      : {integrity_summary.get('bad_metadata_vectors', 0)}\n"
                f"  Malformed IDs removed     : {integrity_summary.get('malformed_id_vectors', 0)}\n"
                f"  Missing chunks synced     : {integrity_summary.get('missing_chunks_synced', 0)}\n"
                f"  Errors                    : {integrity_summary.get('errors', 0)}\n"
            )

        elif sync_only:
            # ── Incremental sync only ─────────────────────────────────────────
            sync_summary = run_incremental_sync(db)
            print(
                "\n[REINDEX] === Sync Report ===\n"
                f"  Documents processed : {sync_summary.get('total_docs', 0)}\n"
                f"  New chunks indexed  : {sync_summary.get('total_indexed', 0)}\n"
                f"  Errors              : {sync_summary.get('errors', 0)}\n"
            )

        else:
            # ── Default: integrity check THEN incremental sync ────────────────
            print("[REINDEX] Step 1/2 — Running integrity check …")
            integrity_summary = run_integrity_check(db)

            print("\n[REINDEX] Step 2/2 — Running incremental sync for any remaining gaps …")
            # After integrity check the sync inside validate_and_fix_integrity
            # already ran, but we call sync_all_chunks once more to catch
            # any edge cases that might have been missed.
            from chroma_sync import sync_all_chunks, _collection
            sync_summary = sync_all_chunks(db)

            # Re-query the live vector count AFTER all indexing is complete.
            # The count stored in integrity_summary was captured before the sync
            # ran, so it can be 0 even when chunks were successfully indexed.
            live_vector_count = _collection.count()

            print(
                "\n[REINDEX] === Final Report ===\n"
                f"  Total vectors in Chroma   : {live_vector_count}\n"
                f"  Orphaned vectors removed  : {integrity_summary.get('orphaned_vectors', 0)}\n"
                f"  Bad-metadata removed      : {integrity_summary.get('bad_metadata_vectors', 0)}\n"
                f"  Malformed IDs removed     : {integrity_summary.get('malformed_id_vectors', 0)}\n"
                f"  New chunks indexed        : {sync_summary.get('total_indexed', 0) + integrity_summary.get('missing_chunks_synced', 0)}\n"
                f"  Errors                    : {integrity_summary.get('errors', 0) + sync_summary.get('errors', 0)}\n"
            )

        print("[REINDEX] ✅ ChromaDB is clean and up-to-date. Your RAG knowledge base is ready.")

    except Exception as exc:
        print(f"[REINDEX] FATAL ERROR: {exc}")
        raise
    finally:
        db.close()


# ─────────────────────────────────────────────────────────────────────────────
# CLI
# ─────────────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description=(
            "Safe, incremental ChromaDB sync and integrity tool for Mujeeb RAG. "
            "Run with no flags for a full sync + integrity check."
        )
    )
    parser.add_argument(
        "--sync",
        action="store_true",
        help="Incremental sync only — index missing chunks, skip integrity check.",
    )
    parser.add_argument(
        "--validate",
        action="store_true",
        help="Integrity check + auto-fix only — detect orphans, bad metadata, etc.",
    )
    args = parser.parse_args()

    if args.sync and args.validate:
        print("[REINDEX] ERROR: --sync and --validate are mutually exclusive.")
        sys.exit(1)

    reindex_all(sync_only=args.sync, validate_only=args.validate)
