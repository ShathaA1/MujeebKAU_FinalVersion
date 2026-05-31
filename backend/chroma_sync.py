"""
chroma_sync.py
==============
Incremental ChromaDB synchronisation — DB chunks ➜ embeddings ➜ Chroma.

Rules enforced here:
  • Only NEW chunks are indexed (chunks whose Chroma ID is absent from the
    collection are upserted; existing IDs are left untouched).
  • When a document is deleted from the DB, its vectors are purged from Chroma.
  • No re-chunking is performed. KnowledgeChunk rows are used as-is.
  • Academic Calendar chunks (stored as AcademicEvent rows, not KnowledgeChunk)
    are not touched by this module.

Public API:
  sync_document_chunks(doc_id, db)    – index only new chunks for one document
  remove_document_from_chroma(doc_id) – delete all vectors for one document
  sync_all_chunks(db)                 – full incremental sync (used by reindex_rag)
  validate_and_fix_integrity(db)      – detect & fix duplicates, orphans, bad metadata
"""



# =============================================================================
# Standard Library Imports
# =============================================================================

import os              # Used for file paths and directory handling
import re              # Used for regular expression pattern matching
from typing import List, Optional, Set, Dict  # Type hints for cleaner code


# =============================================================================
# Environment Variables & API Configuration
# =============================================================================

from dotenv import load_dotenv
from openai import OpenAI

# Get the current backend directory path
BASE_DIR = os.path.dirname(os.path.abspath(__file__))

# Load environment variables from .env file
# (API keys, secrets, configuration values)
load_dotenv(os.path.join(BASE_DIR, ".env"))


# =============================================================================
# ChromaDB Initialization
# =============================================================================

import chromadb

# Local persistent storage path for ChromaDB vectors
CHROMA_PATH = os.path.join(BASE_DIR, "chroma_db")

# Create a persistent Chroma client
# Persistent means vectors remain saved even after restarting the server
_chroma_client = chromadb.PersistentClient(path=CHROMA_PATH)


# Create or load the shared Chroma collection used by the RAG system
_collection = _chroma_client.get_or_create_collection(

    # Collection name shared with rag.py
    name="mujeeb_knowledge_ollama",

    # Cosine similarity is used for semantic vector comparison
    metadata={"hnsw:space": "cosine"},
)

# ── Embedding client ───────────────────────────────────────────────────────────
_DEEPSA_API_KEY  = os.getenv("OPENAI_API_KEY", "")
_DEEPSA_BASE_URL = "https://alapi.deep.sa/v1"
_EMBED_MODEL     = "deep-sa/alEmbedding"

_embed_client = OpenAI(
    base_url=_DEEPSA_BASE_URL,
    api_key=_DEEPSA_API_KEY,
)

# ── Batch size for embedding calls ────────────────────────────────────────────
# deep.sa may reject very large batches; 20 is safe for Arabic long-form text.
_EMBED_BATCH_SIZE = 20


# ─────────────────────────────────────────────────────────────────────────────
# Internal helpers
# ─────────────────────────────────────────────────────────────────────────────

def _embed_batch(texts: List[str]) -> List[List[float]]:
    """Call the embedding API for a batch of texts and return vectors."""
    
    response = _embed_client.embeddings.create(
        model=_EMBED_MODEL,
        # قائمة النصوص اللي نحولها إلى vectors
        input=texts,
    )
    data = sorted(response.data, key=lambda d: d.index)
    # Return only embeddings in the correct order
    return [d.embedding for d in data]



# Stable chunk IDs are used for neighbour expansion,
# incremental synchronization, and organized update/delete operations.
def _chunk_id(doc_id: int, chunk_order: int) -> str:
    """
    Stable Chroma vector ID that matches the pattern used by rag.py.

    Format:  doc_{doc_id}_chunk_{chunk_order}
    This is the canonical ID format — rag.py's neighbour expansion
    and _parse_chunk_id() rely on exactly this pattern.
    """
    return f"doc_{doc_id}_chunk_{chunk_order}"


# Retrieve all existing chunk/vector IDs in ChromaDB for a specific document
# to support incremental synchronization, duplicate checking, and delete operations.
def _get_all_ids_for_doc(doc_id: int) -> List[str]:
    """
    Return ALL vector IDs in Chroma that belong to `doc_id`.

    Uses a metadata `where` filter on the `doc_id` field.
    Falls back to an empty list on any error.
    """
    try:
        result = _collection.get(
            where={"doc_id": str(doc_id)},
            include=["metadatas"],   # at least one include field required by Chroma
        )
        return result.get("ids", [])
    except Exception as exc:
        print(f"[CHROMA_SYNC] Warning: could not fetch IDs for doc_id={doc_id}: {exc}")
        return []

# Convert existing Chroma vector IDs into a set
# for faster duplicate checking during incremental synchronization
def _existing_ids_for_doc(doc_id: int) -> Set[str]:
    """Return the set of vector IDs already stored in Chroma for a document."""
    return set(_get_all_ids_for_doc(doc_id))



def _resolve_college(db, college_id: Optional[int]) -> str:
    """Resolve a CollegeID to a college name string (or empty string)."""
    if not college_id:
        return ""
    try:
        from models import College
        college = db.query(College).filter(College.CollegeID == college_id).first()
        return college.Name if college else ""
    except Exception:
        return ""


# def _get_all_doc_ids_in_chroma() -> Set[str]:
#     """
#     Return the set of all distinct doc_id values currently in the Chroma
#     collection (as strings).  Used by the orphan-detection pass.
#     """
#     try:
#         total = _collection.count()
#         if total == 0:
#             return set()

#         result = _collection.get(include=["metadatas"])
#         ids_found: Set[str] = set()
#         for meta in result.get("metadatas", []):
#             if meta and "doc_id" in meta:
#                 ids_found.add(str(meta["doc_id"]))
#         return ids_found
#     except Exception as exc:
#         print(f"[CHROMA_SYNC] Warning: could not enumerate Chroma doc_ids: {exc}")
#         return set()


# ─────────────────────────────────────────────────────────────────────────────
# Public API
# ─────────────────────────────────────────────────────────────────────────────

def sync_document_chunks(doc_id: int, db) -> int:
    """
    Index ONLY the new KnowledgeChunk rows for `doc_id` into ChromaDB.

    Chunks that already have a matching vector ID in Chroma are skipped so
    the call is always safe to make (idempotent for already-indexed chunks).

    Returns the number of newly indexed chunks.
    """
    from models import KnowledgeChunk, Document

    # Fetch the parent document for metadata
    doc = db.query(Document).filter(Document.DocumentID == doc_id).first()
    if not doc:
        print(f"[CHROMA_SYNC] Document {doc_id} not found in DB — skipping.")
        return 0

    doc_type = doc.DocumentType or ""
    college  = _resolve_college(db, doc.CollegeID)
    title    = doc.FileName or f"Document_{doc_id}"

    # Fetch all chunks for this document, sorted by ChunkOrder
    # جلب جميع الـ chunks الخاصة بالوثيقة من قاعدة البيانات
    # مع الحفاظ على ترتيبها الأصلي باستخدام ChunkOrder
    chunks = (
        db.query(KnowledgeChunk)
        .filter(KnowledgeChunk.DocID == doc_id)
        .order_by(KnowledgeChunk.ChunkOrder)
        .all()
    )

    if not chunks:
        print(f"[CHROMA_SYNC] No KnowledgeChunk rows found for doc_id={doc_id}.")
        return 0



    # Determine which IDs are already in Chroma
    existing_ids = _existing_ids_for_doc(doc_id)

    # Resolve each chunk's canonical ID; use ChunkID as fallback if ChunkOrder is None
    def _resolve_chunk_order(c) -> int:
        return c.ChunkOrder if c.ChunkOrder is not None else c.ChunkID

# تصفية الـ chunks واستبعاد الـ chunks المفهرسة مسبقاً
# للاحتفاظ فقط بالـ chunks الجديدة التي تحتاج embedding و indexing
    # Filter to only truly new chunks
    new_chunks = [
        c for c in chunks
        if _chunk_id(doc_id, _resolve_chunk_order(c)) not in existing_ids
    ]

# إذا كانت جميع الـ chunks موجودة مسبقاً داخل Chroma
# يتم إيقاف العملية لتجنب إعادة الـ indexing
    if not new_chunks:
        print(
            f"[CHROMA_SYNC] All {len(chunks)} chunk(s) for doc_id={doc_id} "
            f"already indexed — nothing to do."
        )
        return 0

    print(
        f"[CHROMA_SYNC] Indexing {len(new_chunks)} new chunk(s) for doc_id={doc_id} "
        f"(type={doc_type}, college={college or 'all'}) …"
    )



    # Process in batches to avoid oversized API requests
    indexed = 0
    for batch_start in range(0, len(new_chunks), _EMBED_BATCH_SIZE):
        batch = new_chunks[batch_start: batch_start + _EMBED_BATCH_SIZE]

        texts = []
        ids   = []
        metadatas = []

        for c in batch:
            text = (c.ChunkText or "").strip()
            if not text:
                print(f"[CHROMA_SYNC]   Skipping empty ChunkID={c.ChunkID}")
                continue
 # تحديد ترتيب الـ chunk وإنشاء ID ثابت له
            order = _resolve_chunk_order(c)
            texts.append(text)
            ids.append(_chunk_id(doc_id, order))
            metadatas.append(
                {
                    "doc_id":      str(doc_id),
                    "title":       title,
                    "doc_type":    doc_type,
                    "college":     college,
                    "user_type":   (doc.UserType or "all").lower(),
                    # stored as both names so old and new code can read it
                    "chunk_index": order,
                    "chunk_order": order,
                }
            )

        if not texts:
            continue  # entire sub-batch was empty

        try:
              # تخزين الـ embeddings والوثائق والـ metadata داخل ChromaDB
            embeddings = _embed_batch(texts)
            _collection.upsert(
                embeddings=embeddings,
                documents=texts,
                metadatas=metadatas,
                ids=ids,
            )
            indexed += len(texts)
            print(
                f"[CHROMA_SYNC]   batch [{batch_start}:{batch_start + len(batch)}] "
                f"upserted OK ({len(texts)} chunks)"
            )
        except Exception as exc:
            print(
                f"[CHROMA_SYNC] ERROR embedding/upserting batch "
                f"[{batch_start}:{batch_start + len(batch)}] for doc_id={doc_id}: {exc}"
            )

    print(f"[CHROMA_SYNC] Done — {indexed}/{len(new_chunks)} new chunk(s) indexed for doc_id={doc_id}.")
    return indexed


def remove_document_from_chroma(doc_id: int) -> int:
    """
    Delete ALL vector records for `doc_id` from ChromaDB.

    This should be called after the document row has been deleted from the DB
    (cascade deletes the KnowledgeChunk rows, so we use Chroma metadata filter).

    Returns the number of IDs deleted.
    """
    try:
        existing_ids = _get_all_ids_for_doc(doc_id)
        if not existing_ids:
            print(f"[CHROMA_SYNC] No vectors found in Chroma for doc_id={doc_id} — nothing to delete.")
            return 0

        _collection.delete(ids=existing_ids)
        print(f"[CHROMA_SYNC] Removed {len(existing_ids)} vector(s) for doc_id={doc_id} from Chroma.")
        return len(existing_ids)

    except Exception as exc:
        print(f"[CHROMA_SYNC] ERROR removing doc_id={doc_id} from Chroma: {exc}")
        return 0


def sync_all_chunks(db) -> dict:
    """
    Full incremental sync: iterate over every Document that has KnowledgeChunk
    rows and index any chunks not yet present in Chroma.

    Used by reindex_rag.py as a safe, idempotent rebuild command.

    Returns a summary dict with total_docs, total_indexed, errors.
    """
    from models import KnowledgeChunk

    # Find all doc_ids that have at least one KnowledgeChunk
    doc_ids = [
        row[0]
        for row in db.query(KnowledgeChunk.DocID).distinct().all()
    ]

    if not doc_ids:
        print("[CHROMA_SYNC] No KnowledgeChunk rows found in DB.")
        return {"total_docs": 0, "total_indexed": 0, "errors": 0}

    print(f"[CHROMA_SYNC] Starting full sync for {len(doc_ids)} document(s) …")

    total_indexed = 0
    errors        = 0

    for doc_id in doc_ids:
        try:
            n = sync_document_chunks(doc_id, db)
            total_indexed += n
        except Exception as exc:
            print(f"[CHROMA_SYNC] ERROR syncing doc_id={doc_id}: {exc}")
            errors += 1

    print(
        f"[CHROMA_SYNC] Full sync complete — "
        f"{total_indexed} new chunk(s) indexed across {len(doc_ids)} doc(s), "
        f"{errors} error(s)."
    )

    return {
        "total_docs":    len(doc_ids),
        "total_indexed": total_indexed,
        "errors":        errors,
    }

# فحص سلامة بيانات ChromaDB واكتشاف المشاكل مثل:
# orphaned vectors, malformed IDs, incomplete metadata
# ثم تنظيف البيانات غير الصحيحة وتشغيل incremental sync لتعويض أي بيانات ناقصة
def validate_and_fix_integrity(db) -> dict:
    """
    Audit ChromaDB for integrity issues and fix them automatically.

    Checks performed:
      1. Duplicate IDs within the collection (Chroma prevents true dupes via
         upsert, but we verify the ID format is correct).
      2. Orphaned vectors — vectors whose doc_id no longer exists in the DB.
      3. Vectors with missing or malformed metadata fields.
      4. Vectors whose ID does not match the canonical  doc_{id}_chunk_{order}
         pattern (legacy IDs from old indexing runs).
      5. DB chunks that are missing from Chroma (triggers a sync pass).

    Returns a summary dict describing what was found and fixed.
    """
    from models import Document, KnowledgeChunk

    print("[INTEGRITY] Starting ChromaDB integrity check …")

    summary = {
        "total_vectors":         0,
        "orphaned_vectors":      0,
        "bad_metadata_vectors":  0,
        "malformed_id_vectors":  0,
        "missing_chunks_synced": 0,
        "errors":                0,
    }

    # ── Step 1: Fetch everything from Chroma ──────────────────────────────────
    try:
        total = _collection.count()
        summary["total_vectors"] = total
        print(f"[INTEGRITY] Collection contains {total} vectors.")

        if total == 0:
            print("[INTEGRITY] Collection is empty — running full sync instead.")
            sync_result = sync_all_chunks(db)
            summary["missing_chunks_synced"] = sync_result["total_indexed"]
            return summary

        all_data = _collection.get(include=["metadatas", "documents"])
    except Exception as exc:
        print(f"[INTEGRITY] ERROR fetching collection data: {exc}")
        summary["errors"] += 1
        return summary

    all_ids       = all_data.get("ids", [])
    all_metadatas = all_data.get("metadatas", [])

    # ── Step 2: Get valid doc_ids from the DB ─────────────────────────────────
    try:
        valid_doc_ids: Set[str] = {
            str(row[0])
            for row in db.query(Document.DocumentID).all()
        }
    except Exception as exc:
        print(f"[INTEGRITY] ERROR fetching Document IDs from DB: {exc}")
        summary["errors"] += 1
        return summary

    # ── Step 3: Scan each vector ──────────────────────────────────────────────
    _ID_PATTERN = re.compile(r"^doc_(\d+)_chunk_(\d+)$")

    orphan_ids      : List[str] = []
    bad_meta_ids    : List[str] = []
    malformed_ids   : List[str] = []

    for vec_id, meta in zip(all_ids, all_metadatas):

        # 3a. Check ID format
        m = _ID_PATTERN.match(vec_id)
        if not m:
            print(f"[INTEGRITY]   Malformed ID: {vec_id!r}")
            malformed_ids.append(vec_id)
            continue

        id_doc_id = m.group(1)

        # 3b. Check for orphaned vectors (doc_id not in DB)
        if id_doc_id not in valid_doc_ids:
            print(f"[INTEGRITY]   Orphaned vector: {vec_id!r} (doc_id={id_doc_id} not in DB)")
            orphan_ids.append(vec_id)
            continue

        # 3c. Check metadata completeness
        if not meta:
            print(f"[INTEGRITY]   Missing metadata for vector: {vec_id!r}")
            bad_meta_ids.append(vec_id)
            continue

        required_fields = {"doc_id", "doc_type", "chunk_index", "user_type"}
        missing_fields  = required_fields - set(meta.keys())
        if missing_fields:
            print(f"[INTEGRITY]   Incomplete metadata for {vec_id!r} — missing: {missing_fields}")
            bad_meta_ids.append(vec_id)

    # ── Step 4: Delete orphaned vectors ───────────────────────────────────────
    if orphan_ids:
        try:
            _collection.delete(ids=orphan_ids)
            print(f"[INTEGRITY] Deleted {len(orphan_ids)} orphaned vector(s).")
            summary["orphaned_vectors"] = len(orphan_ids)
        except Exception as exc:
            print(f"[INTEGRITY] ERROR deleting orphaned vectors: {exc}")
            summary["errors"] += 1

    # ── Step 5: Delete malformed-ID vectors ───────────────────────────────────
    if malformed_ids:
        try:
            _collection.delete(ids=malformed_ids)
            print(f"[INTEGRITY] Deleted {len(malformed_ids)} malformed-ID vector(s).")
            summary["malformed_id_vectors"] = len(malformed_ids)
        except Exception as exc:
            print(f"[INTEGRITY] ERROR deleting malformed-ID vectors: {exc}")
            summary["errors"] += 1

    # ── Step 6: Delete vectors with bad/incomplete metadata ───────────────────
    if bad_meta_ids:
        try:
            _collection.delete(ids=bad_meta_ids)
            print(f"[INTEGRITY] Deleted {len(bad_meta_ids)} incomplete-metadata vector(s) (will re-sync).")
            summary["bad_metadata_vectors"] = len(bad_meta_ids)
        except Exception as exc:
            print(f"[INTEGRITY] ERROR deleting bad-metadata vectors: {exc}")
            summary["errors"] += 1

    # ── Step 7: Full incremental sync to fill any gaps created above ──────────
    print("[INTEGRITY] Running incremental sync to fill gaps after cleanup …")
    try:
        sync_result = sync_all_chunks(db)
        summary["missing_chunks_synced"] = sync_result["total_indexed"]
    except Exception as exc:
        print(f"[INTEGRITY] ERROR during post-cleanup sync: {exc}")
        summary["errors"] += 1

    print(
        f"[INTEGRITY] Integrity check complete. "
        f"Orphans removed: {summary['orphaned_vectors']}, "
        f"Bad metadata removed: {summary['bad_metadata_vectors']}, "
        f"Malformed IDs removed: {summary['malformed_id_vectors']}, "
        f"Missing chunks synced: {summary['missing_chunks_synced']}, "
        f"Errors: {summary['errors']}."
    )
    return summary
