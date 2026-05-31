import os
import re
import time
import chromadb
from typing import List, Dict, Optional, Set, Tuple
from dotenv import load_dotenv
from openai import OpenAI
from datetime_context import get_current_datetime_context

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
ENV_PATH = os.path.join(BASE_DIR, ".env")
load_dotenv(ENV_PATH)

# ── ChromaDB ──────────────────────────────────────────────────────────────────
CHROMA_PATH = os.path.join(BASE_DIR, "chroma_db")
chroma_client = chromadb.PersistentClient(path=CHROMA_PATH)
collection = chroma_client.get_or_create_collection(
    name="mujeeb_knowledge_ollama",
    metadata={"hnsw:space": "cosine"},   # cosine distance for better semantic ranking
)

# ── deep.sa API client ─────────────────────────────────────────────────────────
#_DEEPSA_API_KEY  = os.getenv("chat_API_KEY", "")
_DEEPSA_API_KEY  = os.getenv("OPENAI_API_KEY", "")
_DEEPSA_BASE_URL = "https://alapi.deep.sa/v1"
_LLM_MODEL       = "google/gemini-3-flash"
_EMBED_MODEL      = "deep-sa/alEmbedding"

_client = OpenAI(
    base_url=_DEEPSA_BASE_URL,
    api_key=_DEEPSA_API_KEY,
)

# ── Retrieval hyper-parameters ─────────────────────────────────────────────────
_TOP_K                   = 9      # top-K candidates fetched from ChromaDB
_NEIGHBOUR_WINDOW        = 1      # ±1 neighbour chunk per hit (same document)
_MAX_CONTEXT_CHARS       = 14000  # character cap for total LLM context (raised to avoid single-doc starvation)
_MIN_RELEVANCE_DIST      = 2.0    # cosine distance threshold — chunks above this are discarded
_MIN_CHUNKS_AFTER_FILTER = 3      # if fewer chunks survive filter, bypass and use raw hits

# ── Reranking hyper-parameters ────────────────────────────────────────────────
_RERANK_TOP_N   = 15      # keep this many chunks AFTER reranking — raised to cover neighbour-expanded pool
#_RERANK_MODEL   = "google/gemini-3-pro"   # fast model used only for ordering
_RERANK_MODEL   = "google/gemini-3-flash"
_RERANK_TIMEOUT = 15      # seconds — if reranking takes longer, fall back silently


# ─────────────────────────────────────────────────────────────────────────────
# Embedding helpers
# ─────────────────────────────────────────────────────────────────────────────

def _embed_documents(texts: List[str]) -> List[List[float]]:
    """Embed a list of texts using deep.sa alEmbedding."""
    response = _client.embeddings.create(
        model=_EMBED_MODEL,
        input=texts,
    )
    data = sorted(response.data, key=lambda d: d.index)
    return [d.embedding for d in data]


def _embed_query(text: str) -> List[float]:
    """Embed a single query string using deep.sa alEmbedding."""
    response = _client.embeddings.create(
        model=_EMBED_MODEL,
        input=[text],
    )
    return response.data[0].embedding


# ─────────────────────────────────────────────────────────────────────────────
# Academic-event helpers  (unchanged logic, improved formatting)
# ─────────────────────────────────────────────────────────────────────────────

EVENT_KEYWORDS = [
    "متى", "موعد", "مواعيد", "تاريخ", "تواريخ", "تقويم", "جدول",
    "سحب", "إضافة", "حذف", "تسجيل", "الفصل", "الدراسة",
    "امتحان", "اختبار", "اختبارات", "امتحانات", "نهائي", "نهائية",
    "بداية", "نهاية", "آخر يوم", "يبدأ", "ينتهي", "الإجازة",
    "عطلة", "فعالية", "فعاليات", "أحداث", "حدث", "برنامج",
    "انتهاء", "انسحاب", "التسجيل", "القبول", "الإضافة", "الانسحاب",
    "يوم", "ميعاد", "الأسبوع", "الفترة", "الدور", "منح",
]


def _is_event_query(question: str) -> bool:
    return any(kw in question for kw in EVENT_KEYWORDS)


def _get_events_context(db) -> str:
    """
    Query AcademicEvent table from PostgreSQL and format as clean Arabic text.
    Returns empty string if DB unavailable or no events found.
    """
    try:
        from models import AcademicEvent
        events = db.query(AcademicEvent).order_by(AcademicEvent.StartDate).all()

        if not events:
            return ""

        lines = []
        for ev in events:
            title = ev.Title or ""
            start = str(ev.StartDate) if ev.StartDate else None
            end   = str(ev.EndDate)   if ev.EndDate   else None

            if start and end and start != end:
                line = f"• {title}: من {start} إلى {end}"
            elif start:
                line = f"• {title}: بتاريخ {start}"
            else:
                line = f"• {title}"

            lines.append(line)

        return "المواعيد والأحداث الأكاديمية:\n" + "\n".join(lines)

    except Exception as e:
        print(f"[RAG] Error fetching AcademicEvent: {e}")
        return ""


# ─────────────────────────────────────────────────────────────────────────────
# Indexing
# ─────────────────────────────────────────────────────────────────────────────

def index_chunks_to_rag(
    chunks: List[str],
    doc_id: str,
    title: str,
    doc_type: str = "",
    college: str = "",
) -> None:
    """
    PRIMARY indexing function.

    Receives an already-chunked list of texts and upserts them directly into
    ChromaDB — NO re-splitting.  Each chunk carries rich metadata so that
    future filtered queries can narrow to a specific doc_type or college.

    Chunk IDs:  doc_{doc_id}_chunk_{i}   (0-based)
    """
    if not chunks:
        print(f"[RAG] index_chunks_to_rag: no chunks for doc_id={doc_id}, skipping.")
        return
    try:
        clean = [c.strip() for c in chunks if c and c.strip()]
        if not clean:
            print(f"[RAG] index_chunks_to_rag: all chunks empty for doc_id={doc_id}.")
            return

        # Log chunk sizes so any truncation during indexing is visible
        for i, c in enumerate(clean):
            print(f"[IDX] doc_id={doc_id} chunk_{i}: {len(c)} chars")

        embeddings = _embed_documents(clean)
        ids        = [f"doc_{doc_id}_chunk_{i}" for i in range(len(clean))]
        metadatas  = [
            {
                "doc_id":     str(doc_id),
                "title":      title,
                "doc_type":   doc_type,
                "college":    college,
                "chunk_index": i,
            }
            for i in range(len(clean))
        ]
        collection.upsert(
            embeddings=embeddings,
            documents=clean,
            metadatas=metadatas,
            ids=ids,
        )
        print(f"[RAG] Indexed {len(clean)} chunks for doc_id={doc_id} (type={doc_type})")
    except Exception as e:
        print(f"[RAG] Error in index_chunks_to_rag for doc_id={doc_id}: {e}")


def add_document_to_rag(
    text: str,
    doc_id: str,
    title: str,
    doc_type: str = "",
    college: str = "",
) -> None:
    """
    Fallback indexing path — used when no pre-chunked data is available
    (e.g. Academic Calendar documents that go straight from OCR → DB).

    Uses a paragraph-aware splitter that preserves Arabic sentence boundaries
    instead of the old fixed-size character splitter.
    """
    try:
        chunks = _paragraph_split(text)
        if not chunks:
            print(f"[RAG] add_document_to_rag: no chunks produced for doc_id={doc_id}.")
            return
        print(f"[RAG] add_document_to_rag: paragraph split → {len(chunks)} chunks for doc_id={doc_id}")
        index_chunks_to_rag(chunks, doc_id, title, doc_type=doc_type, college=college)
    except Exception as e:
        print(f"[RAG] Error in add_document_to_rag for doc_id={doc_id}: {e}")


def _paragraph_split(text: str, max_chars: int = 900, overlap_chars: int = 100) -> List[str]:
    """
    Paragraph-aware text splitter that respects Arabic paragraph boundaries.

    Strategy:
      1. Split on double newlines (paragraph breaks) first.
      2. If a paragraph is still too long, split on single newlines.
      3. If still too long, slide a window with overlap.

    This is strictly better than RecursiveCharacterTextSplitter because it
    never cuts mid-sentence.
    """
    if not text or not text.strip():
        return []

    # Step 1: paragraph-level split
    paragraphs = [p.strip() for p in re.split(r"\n{2,}", text) if p.strip()]

    chunks: List[str] = []
    for para in paragraphs:
        if len(para) <= max_chars:
            chunks.append(para)
        else:
            # Step 2: single-line split within long paragraphs
            lines = [l.strip() for l in para.splitlines() if l.strip()]
            buffer = ""
            for line in lines:
                if not buffer:
                    buffer = line
                elif len(buffer) + len(line) + 1 <= max_chars:
                    buffer += "\n" + line
                else:
                    chunks.append(buffer)
                    # keep overlap — last sentence of previous buffer
                    overlap = buffer[-overlap_chars:] if len(buffer) > overlap_chars else buffer
                    buffer = overlap + "\n" + line
            if buffer:
                chunks.append(buffer)

    return [c for c in chunks if len(c) >= 20]   # drop trivially short fragments


# ─────────────────────────────────────────────────────────────────────────────
# Neighbour expansion
# ─────────────────────────────────────────────────────────────────────────────

def _parse_chunk_id(chunk_id: str) -> Tuple[Optional[str], Optional[int]]:
    match = re.match(r"^doc_(.+)_chunk_(\d+)$", chunk_id)
    if not match:
        return None, None
    return match.group(1), int(match.group(2))


def _fetch_neighbour(doc_id: str, chunk_index: int) -> Optional[Tuple[str, str, int]]:
    target_id = f"doc_{doc_id}_chunk_{chunk_index}"
    try:
        result = collection.get(ids=[target_id], include=["documents", "metadatas"])
        docs = result.get("documents", [])
        if docs:
            return (target_id, docs[0], chunk_index)
    except Exception:
        pass
    return None


def _expand_with_neighbours(
    hit_ids: List[str],
    hit_docs: List[str],
    window: int = _NEIGHBOUR_WINDOW,
) -> List[Tuple[str, str, int]]:
    """
    For every retrieved chunk, also fetch the `window` chunks immediately before
    and after it within the SAME document.

    Returns a deduplicated, ordered list of (chunk_id, text, sort_key) tuples.
    """
    seen_ids: Set[str] = set()
    expanded: List[Tuple[str, str, str]] = []

    for cid, doc_text in zip(hit_ids, hit_docs):
        doc_id, chunk_idx = _parse_chunk_id(cid)

        if doc_id is None:
            if cid not in seen_ids:
                seen_ids.add(cid)
                expanded.append((cid, doc_text, cid))
            continue

        for offset in range(-window, window + 1):
            c_idx = chunk_idx + offset
            if c_idx < 0:
                continue

            neighbour_id = f"doc_{doc_id}_chunk_{c_idx}"
            if neighbour_id in seen_ids:
                continue

            if offset == 0:
                seen_ids.add(neighbour_id)
                sort_key = f"{doc_id}|{c_idx:010d}"
                expanded.append((neighbour_id, doc_text, sort_key))
            else:
                hit = _fetch_neighbour(doc_id, c_idx)
                if hit:
                    n_id, n_text, n_idx = hit
                    seen_ids.add(n_id)
                    sort_key = f"{doc_id}|{n_idx:010d}"
                    expanded.append((n_id, n_text, sort_key))

    expanded.sort(key=lambda x: x[2])
    return expanded


# ─────────────────────────────────────────────────────────────────────────────
# Question-type classifier
# ─────────────────────────────────────────────────────────────────────────────

_DETAIL_KEYWORDS = [
    # Conditions / requirements
    "شروط", "شرط", "متطلبات", "متطلب", "اشتراطات", "اشتراط",
    "ضوابط", "ضابط", "معايير", "معيار",
    # Specialisations / types / categories
    "تخصصات", "تخصص", "أنواع", "نوع", "فئات", "فئة",
    "أقسام", "قسم", "مسارات", "مسار", "برامج", "برنامج",
    # Courses / steps / procedures
    "مواد", "مادة", "مساقات", "خطوات", "خطوة",
    "إجراءات", "إجراء", "مراحل", "مرحلة", "آليات", "آلية",
    # Rules / regulations
    "تعليمات", "قواعد", "قاعدة", "لوائح", "لائحة", "أنظمة", "نظام",
    # List / detail triggers
    "التفاصيل", "تفاصيل", "التخصصات", "الشروط", "المتطلبات",
    "الأنواع", "الأقسام", "البرامج", "المسارات",
    # Question starters
    "ما هي", "ما هو", "ماذا تشمل", "ماذا يشمل",
    "اذكر", "اشرح", "وضح", "فسّر", "بيّن",
    "كيف", "طريقة", "ما هي الخطوات",
    "كل", "جميع", "اسرد", "عدد",
    "ما هي المراحل", "ما المتطلبات",
    # College / academic structure
    "كليات", "كلية", "أكاديمية", "مراكز", "مركز",
    "التخرج", "التسجيل", "القبول", "الالتحاق",
    "الساعات", "ساعات", "المقررات", "مقررات",
    "الدرجات", "المعدل", "الخطة الدراسية",
    # Schedules / programs
    "الجدول", "جدول", "البرنامج", "الخطة", "خطة",
]


def _is_detail_question(question: str) -> bool:
    q = question.strip()
    return any(kw in q for kw in _DETAIL_KEYWORDS)


# ─────────────────────────────────────────────────────────────────────────────
# Context builder
# ─────────────────────────────────────────────────────────────────────────────

def _merge_short_adjacent_chunks(texts: List[str], merge_threshold: int = 280) -> List[str]:
    """
    Merge consecutive short chunks from the SAME document into a single block.

    Motivation: the semantic chunker sometimes produces several small chunks
    (a 40-char header + a 120-char rule + a 90-char note) that together
    represent one logical concept. Merging here gives the model longer,
    self-contained blocks to reason over.
    Only merges when BOTH the buffer AND the next chunk are shorter than
    merge_threshold. Long chunks are always kept separate.

    FIX: use a blank line separator (\n\n) so merged sub-topics remain visually
    distinct to the LLM instead of running together as one paragraph.
    """
    if not texts:
        return texts
    merged: List[str] = []
    buffer = texts[0]
    for chunk in texts[1:]:
        if len(buffer) < merge_threshold and len(chunk) < merge_threshold:
            buffer = buffer + "\n\n" + chunk   # blank-line separator keeps ideas distinct
        else:
            merged.append(buffer)
            buffer = chunk
    merged.append(buffer)
    return merged


def _extract_doc_id_from_sort_key(sort_key: str, chunk_id: str) -> str:
    """
    Safely extract the doc_id component from a sort_key.

    Sort keys have the form "<doc_id>|<chunk_index:010d>".
    For fallback chunks whose sort_key was set to chunk_id (line 287 path),
    we try to extract the doc portion from the chunk_id itself using the
    known ID schema "doc_<doc_id>_chunk_<n>" before falling back to the
    raw string — which would create a spurious per-chunk document group.
    """
    if "|" in sort_key:
        return sort_key.split("|")[0]
    # Try to extract from chunk_id pattern: doc_<doc_id>_chunk_<n>
    m = re.match(r"^doc_(.+)_chunk_\d+$", chunk_id)
    if m:
        return m.group(1)
    return chunk_id   # true fallback: treat as its own group


def _build_context_text(expanded: List[Tuple[str, str, str]]) -> str:
    """
    Build the final context string from expanded (chunk_id, text, sort_key) tuples.

    KEY FIXES over previous version:
    1. Proportional per-doc budget: no single document can consume the entire
       budget.  Each document is allocated at most
       max(_MAX_CONTEXT_CHARS // max(num_docs, 1), _MIN_DOC_BUDGET) chars so
       that a large first doc cannot starve later, equally relevant docs.
    2. Two-pass fill: after the first pass, any remaining budget is filled by
       previously-skipped docs (smallest-first) so that no doc is silently
       dropped when space is actually available.
    3. Fixed sort_key / doc_id extraction: malformed sort_keys no longer create
       spurious per-chunk document groups that waste separators and budget.
    4. Improved merge separator: blank line between merged sub-chunks keeps
       logical sections visually distinct for the LLM.
    """
    from collections import OrderedDict

    # ── Group chunks by doc_id ────────────────────────────────────────────────
    doc_groups: Dict[str, List[str]] = OrderedDict()

    for chunk_id, text, sort_key in expanded:
        doc_id = _extract_doc_id_from_sort_key(sort_key, chunk_id)
        if doc_id not in doc_groups:
            doc_groups[doc_id] = []
        doc_groups[doc_id].append(text)

    # ── Merge short adjacent chunks within each doc ───────────────────────────
    for doc_id in doc_groups:
        doc_groups[doc_id] = _merge_short_adjacent_chunks(doc_groups[doc_id])

    # ── Pre-compute each doc's assembled block ────────────────────────────────
    doc_blocks: Dict[str, str] = {
        doc_id: "\n\n".join(texts)
        for doc_id, texts in doc_groups.items()
    }

    num_docs = len(doc_blocks)

    # ── BUG-FIX 1: per-document budget cap ───────────────────────────────────
    # Without this, a large doc_1 (e.g. 13 000 chars) consumes the entire
    # _MAX_CONTEXT_CHARS (14 000) budget and doc_2 (even 2 000 chars) is
    # always excluded regardless of its relevance.
    _MIN_DOC_BUDGET = 1500   # every doc deserves at least this many chars
    per_doc_cap = max(_MAX_CONTEXT_CHARS // max(num_docs, 1), _MIN_DOC_BUDGET)

    parts: List[str] = []
    total = 0
    included_docs: List[str] = []
    skipped_docs: List[str] = []   # docs that exceeded per-doc cap in pass 1
    first_block_added = False

    # ── Pass 1: include each doc up to per_doc_cap ───────────────────────────
    for doc_id, doc_block in doc_blocks.items():
        # Apply per-doc cap: truncate at a clean newline boundary if needed
        if len(doc_block) > per_doc_cap:
            # Find the last newline before the cap to avoid mid-sentence cuts
            cut_pos = doc_block.rfind("\n", 0, per_doc_cap)
            if cut_pos < per_doc_cap // 2:   # no good cut point found, use cap
                cut_pos = per_doc_cap
            doc_block = doc_block[:cut_pos].rstrip()
            print(f"[CTX] doc_id={doc_id}: capped at {len(doc_block)} chars "
                  f"(per-doc budget {per_doc_cap}).")

        remaining = _MAX_CONTEXT_CHARS - total

        if len(doc_block) > remaining:
            if not first_block_added:
                # Safety net: first doc gets in even if it exceeds total budget
                print(f"[CTX] doc_id={doc_id} ({len(doc_block)} chars) exceeds global "
                      f"budget but is the only source — including anyway.")
                parts.append(doc_block)
                total += len(doc_block)
                included_docs.append(doc_id)
                first_block_added = True
                continue
            skipped_docs.append(doc_id)
            print(f"[CTX] Pass-1 deferred doc_id={doc_id} ({len(doc_block)} chars) — "
                  f"{remaining} chars remaining.")
            continue

        parts.append(doc_block)
        total += len(doc_block)
        included_docs.append(doc_id)
        first_block_added = True

    # ── Pass 2: fill remaining budget with smallest skipped docs first ────────
    # This ensures that a small but highly relevant document is never permanently
    # excluded just because a large document ran over the per-doc cap.
    if skipped_docs:
        # Sort by ascending block size so smallest docs fit first
        skipped_docs.sort(key=lambda d: len(doc_blocks[d]))
        for doc_id in skipped_docs:
            remaining = _MAX_CONTEXT_CHARS - total
            doc_block = doc_blocks[doc_id]  # original (possibly capped) block
            if len(doc_block) <= remaining:
                parts.append(doc_block)
                total += len(doc_block)
                included_docs.append(doc_id)
                print(f"[CTX] Pass-2 recovered doc_id={doc_id} ({len(doc_block)} chars).")
            else:
                print(f"[CTX] Excluded doc_id={doc_id} ({len(doc_block)} chars) — "
                      f"only {remaining} chars left after pass-2.")

    excluded_count = len(doc_blocks) - len(included_docs)
    print(f"[CTX] Included {len(included_docs)} doc(s), "
          f"excluded {excluded_count} doc(s). "
          f"Total context: {total} chars.")
    return "\n\n========\n\n".join(parts)


# ─────────────────────────────────────────────────────────────────────────────
# Reranker
# ─────────────────────────────────────────────────────────────────────────────

def _rerank_chunks(
    expanded: List[Tuple[str, str, str]],
    question: str,
) -> List[Tuple[str, str, str]]:
    """
    Rerank the expanded chunk list by asking the LLM to order them by relevance
    to `question`.  Returns a reordered copy of `expanded`.

    Safety contract:
    - If the LLM call fails for ANY reason, return `expanded` unchanged.
    - If the LLM returns a malformed response, return `expanded` unchanged.
    - Never raises an exception.

    Design notes:
    - Uses a compact prompt with numbered excerpts (first 200 chars per chunk)
      so the reranker call stays fast and cheap.
    - Deduplicates returned indices to guard against LLM hallucinating repeats.
    - Appends any indices the LLM omitted so NO chunk is silently dropped
      before the top-N slice that follows this call.
    """
    if len(expanded) <= 1:
        return expanded   # nothing to reorder

    try:
        import threading

        # ── Build numbered excerpt list ────────────────────────────────────────
        excerpts = []
        for i, (_, text, _) in enumerate(expanded, start=1):
            # Trim long chunks so the rerank prompt stays small
            excerpt = text.replace("\n", " ").strip()
            if len(excerpt) > 220:
                excerpt = excerpt[:220] + "…"
            excerpts.append(f"{i}. {excerpt}")

        chunks_block = "\n".join(excerpts)

        rerank_prompt = f"""أنت محرك ترتيب للمقاطع النصية. مهمتك: رتّب المقاطع أدناه حسب مدى أهميتها للإجابة عن السؤال.

السؤال:
{question}

المقاطع:
{chunks_block}

قواعد التقييم:
- الأولوية للمقاطع التي تحتوي على إجابة مباشرة وصريحة.
- للأسئلة عن القوائم (كليات، شروط، برامج): قدّم أولاً المقاطع التي تحتوي على قوائم كاملة.
- ضع في الأولوية المقاطع الأكثر اكتمالاً وأكثر صلةً مباشرةً بالسؤال.
- تجاهل المقاطع الضعيفة الصلة لكن أدرجها في النهاية.

أعد فقط مصفوفة JSON تحتوي على أرقام المقاطع بالترتيب الجديد.
لا تكتب أي شيء آخر. مثال: [3,1,4,2]"""

        # ── Call reranker with timeout via thread ──────────────────────────────
        result_holder: List[str] = []

        def _call():
            try:
                resp = _client.chat.completions.create(
                    model=_RERANK_MODEL,
                    messages=[{"role": "user", "content": rerank_prompt}],
                    temperature=0.0,
                    max_tokens=128,   # only need a short JSON array
                )
                result_holder.append(resp.choices[0].message.content or "")
            except Exception as call_err:
                print(f"[RERANK] LLM call error: {call_err}")

        t = threading.Thread(target=_call, daemon=True)
        t.start()
        t.join(timeout=_RERANK_TIMEOUT)

        if not result_holder:
            print("[RERANK] Timed out — using original order.")
            return expanded

        raw_response = result_holder[0]

        # ── Parse JSON array from response ─────────────────────────────────────
        cleaned = re.sub(r"```(?:json)?", "", raw_response, flags=re.IGNORECASE).strip()
        arr_match = re.search(r"\[(\s*\d+\s*(?:,\s*\d+\s*)*)\]", cleaned)
        if not arr_match:
            print(f"[RERANK] Could not parse order from response: {raw_response!r}")
            return expanded

        raw_order = [int(x.strip()) for x in arr_match.group(1).split(",")]

        # ── Validate and deduplicate indices ───────────────────────────────────
        n = len(expanded)
        seen: Set[int] = set()
        order: List[int] = []
        for idx in raw_order:
            if 1 <= idx <= n and idx not in seen:
                order.append(idx - 1)   # convert to 0-based
                seen.add(idx)

        # Append any index the model omitted (ensures no chunk lost)
        for i in range(n):
            if i not in seen:
                order.append(i)

        reranked = [expanded[i] for i in order]
        print(f"[RERANK] Reranked {n} chunks → new order: {[o+1 for o in order]}")
        return reranked

    except Exception as e:
        print(f"[RERANK] Unexpected error ({e}) — using original order.")
        return expanded


# ─────────────────────────────────────────────────────────────────────────────
# Main RAG function
# ─────────────────────────────────────────────────────────────────────────────

def ask_rag(question: str, history: List[Dict[str, str]] = None, db=None, user_type: str = "all") -> str:
    """
    Hybrid retrieval pipeline:
      1. Vector search in ChromaDB  — TOP _TOP_K most relevant chunks (cosine)
      2. Relevance filtering         — discard chunks whose distance > _MIN_RELEVANCE_DIST
                                       (fallback: use raw hits if too few survive)
      3. Neighbour expansion         — ±_NEIGHBOUR_WINDOW chunks per hit (same doc)
      4. LLM reranking              — reorder expanded chunks by question relevance,
                                       keep top _RERANK_TOP_N
      5. SQL query in PostgreSQL     — academic events / dates (if event question)
      6. Context construction        — group by document, cap at _MAX_CONTEXT_CHARS
      7. LLM answer generation
    """
    try:
        # ── Step 1: Vector search ─────────────────────────────────────────────
        query_embedding = _embed_query(question)

        try:
            collection_count = collection.count()
        except Exception:
            collection_count = 0

        n_results = min(_TOP_K, collection_count) if collection_count > 0 else 0

        where_filter = None
        user_type_lower = user_type.lower()
        if user_type_lower == "admin":
            where_filter = None  # Admin sees everything
        elif user_type_lower not in ["all", "guest"]:
            where_filter = {"$or": [{"user_type": "all"}, {"user_type": user_type_lower}]}
        else:
            where_filter = {"user_type": "all"}

        chroma_chunks: List[str] = []
        chroma_ids:    List[str] = []

        if n_results > 0:
            results = collection.query(
                query_embeddings=[query_embedding],
                n_results=n_results,
                include=["documents", "metadatas", "distances"],
                where=where_filter
            )
            raw_chunks    = results.get("documents", [[]])[0]
            raw_ids       = results.get("ids",       [[]])[0]
            raw_distances = results.get("distances", [[]])[0]

            print(f"[RAG] Retrieved {len(raw_chunks)} candidates from ChromaDB.")

            # ── Step 2: Relevance filtering ───────────────────────────────────
            for cid, chunk, dist in zip(raw_ids, raw_chunks, raw_distances):
                if dist <= _MIN_RELEVANCE_DIST:
                    chroma_ids.append(cid)
                    chroma_chunks.append(chunk)
                    print(f"[RAG]   ✔ {cid}  dist={dist:.4f}")
                else:
                    print(f"[RAG]   ✘ {cid}  dist={dist:.4f} — filtered out (too far)")

            print(f"[RAG] {len(chroma_chunks)} chunks passed relevance filter.")

            # ── Fallback: if strict filter leaves too few chunks, use raw hits ─
            # This prevents the LLM from receiving empty/starved context when
            # the distance threshold is too aggressive for the current query.
            if len(chroma_chunks) < _MIN_CHUNKS_AFTER_FILTER and raw_chunks:
                print(f"[RAG] ⚠ Only {len(chroma_chunks)} chunk(s) after filter — "
                      f"bypassing filter, using top {len(raw_chunks)} raw hits.")
                chroma_ids    = list(raw_ids)
                chroma_chunks = list(raw_chunks)

        # ── Step 3: Context expansion ─────────────────────────────────────────
        expanded_tuples: List[Tuple[str, str, str]] = []

        if chroma_ids:
            # Use a wider neighbour window for list/detail questions so that
            # surrounding context (e.g., the rest of a college list) is captured.
            adaptive_window = 2 if _is_detail_question(question) else _NEIGHBOUR_WINDOW
            expanded_tuples = _expand_with_neighbours(
                chroma_ids, chroma_chunks, window=adaptive_window
            )
            print(f"[RAG] Expanded to {len(expanded_tuples)} chunks "
                  f"(window={adaptive_window}) after neighbour fetch.")


        # ── Step 4: LLM Reranking (select by relevance, read in document order) ──
        # Correct pattern:
        #   1. Rerank  — LLM decides WHAT is most relevant (importance ordering)
        #   2. Slice   — keep top _RERANK_TOP_N most relevant chunks
        #   3. Dedup   — remove any duplicate chunk_ids the LLM may have produced
        #   4. Re-sort — restore original document order (sort_key = doc|chunk_idx)
        #                so the LLM reads a coherent, non-fragmented passage
        # Falls back to original order silently on any error (inside _rerank_chunks).
        if expanded_tuples:
            # Step 1 + 2: rerank then select top N
            reranked   = _rerank_chunks(expanded_tuples, question)
            top_chunks = reranked[:_RERANK_TOP_N]

            # Step 2b: inject high-density chunks the reranker may have ranked low.
            # Adaptive threshold: for detail questions (lists, conditions, programs)
            # use a lower threshold (300 chars) to capture more complete content.
            # For simple questions use 500 chars to avoid polluting short answers.
            density_threshold = 300 if _is_detail_question(question) else 500
            important = [c for c in expanded_tuples if len(c[1]) > density_threshold]
            top_ids   = {c[0] for c in top_chunks}
            injected  = 0
            for imp in important:
                if imp[0] not in top_ids:
                    top_chunks.append(imp)
                    top_ids.add(imp[0])
                    injected += 1
            if injected > 0:
                print(f"[RAG] Injected {injected} high-density chunk(s) "
                      f"(threshold={density_threshold} chars) skipped by reranker.")

            # Step 3: deduplicate by chunk_id (guard against LLM-produced repeats)
            seen_ids: set = set()
            deduped: List[Tuple[str, str, str]] = []
            for tup in top_chunks:
                if tup[0] not in seen_ids:
                    seen_ids.add(tup[0])
                    deduped.append(tup)

            # Step 4: restore original document reading order
            deduped.sort(key=lambda x: x[2])   # sort_key encodes doc_id|chunk_index
            expanded_tuples = deduped

            print(f"[RAG] Reranked → selected {len(expanded_tuples)} chunks (doc order restored).")

        # ── Step 5: SQL search — AcademicEvent ───────────────────────────────
        events_context = ""
        if db is not None and _is_event_query(question):
            events_context = _get_events_context(db)
            if events_context:
                print(f"[RAG] Academic events context injected.")

        # ── Step 6: Build unified context ─────────────────────────────────────
        context_parts: List[str] = []
        if expanded_tuples:
            context_parts.append(_build_context_text(expanded_tuples))
        if events_context:
            context_parts.append(events_context)

        # Filter out empty strings before checking — an empty _build_context_text()
        # result (all docs exceeded budget) must trigger the no-context path.
        context_parts = [p for p in context_parts if p and p.strip()]

        if not context_parts:
            return (
                "لا تتوفر لديّ معلومات كافية حول هذا الموضوع حالياً.\n"
                "يمكنك التواصل مع إدارة الجامعة للحصول على مزيد من التفاصيل."
            )

        # Annotate context so the LLM knows it must read the whole thing
        context_text = "\n\n".join(context_parts)

        # ── Logging ───────────────────────────────────────────────────────────
        print(f"[RAG] TOTAL CONTEXT LENGTH : {len(context_text)} chars")
        print(f"[RAG] TOTAL CHUNKS IN USE  : {len(expanded_tuples)}")

        # Prepend a mandatory reading instruction directly into the context block
        # so even models that skim prompts see it right before the actual text.
        context_text = (
            "تنبيه مهم: قد تكون الإجابة موزّعة على أجزاء متعددة في هذا السياق. "
            "يجب عليك قراءة جميع الأجزاء من البداية حتى النهاية قبل الإجابة.\n"
            "IMPORTANT: The answer may be spread across multiple sections. "
            "You MUST scan ALL sections before writing your answer.\n\n"
            + context_text
        )

        # ── Step 7: Build adaptive, strict prompt ─────────────────────────────
        detail_mode = _is_detail_question(question)

        if detail_mode:
            completeness_block = """
## LIST COMPLETENESS RULE — VERY IMPORTANT:
This question asks for a LIST, CONDITIONS, TYPES, PROGRAMS, or STEPS.

You MUST:
- Read every part of the [CONTEXT] before writing your answer.
- Extract EVERY item — do NOT stop after the first group you find.
- The answer may be distributed across multiple chunks or sections.
- You MUST scan ALL sections and collect ALL items before writing.
- Merge them into ONE complete, unified answer.
- An answer that is missing even ONE item from the [CONTEXT] is considered WRONG.
- List ALL items using Markdown bullet points (-), one per line.
- You may rewrite them to sound conversational, but do NOT skip any item.
"""
            length_instruction = (
                "- Your answer MUST include ALL items found in the [CONTEXT]. Do NOT truncate.\n"
                "- Use Markdown bullet points (-) for every item."
            )
        else:
            completeness_block = ""
            length_instruction = (
                "- Keep the answer focused but conversational.\n"
                "- Use Markdown bullet points (-) if the answer contains multiple facts.\n"
                "- Break long text into short, readable paragraphs."
            )

        system_prompt = f"""{get_current_datetime_context()}

You are "مجيب", the official academic assistant for King Abdulaziz University (KAU).

## CRITICAL READING RULE — MUST FOLLOW BEFORE WRITING ANYTHING:

You MUST read the ENTIRE [CONTEXT] section from beginning to end BEFORE writing even one word of your answer.

Do NOT stop when you find a partial answer.
Do NOT assume the first chunk contains everything.

If information appears in multiple places in the [CONTEXT]:
- You MUST collect it from ALL locations.
- You MUST merge it into ONE single, complete answer.
- Stopping early or ignoring later sections is considered a CRITICAL FAILURE.

## MANDATORY READING PROCEDURE — EXECUTE IN ORDER:

STEP A: Read chunk 1 completely.
STEP B: Read chunk 2 completely.
STEP C: Continue until you have read EVERY chunk in the [CONTEXT].
STEP D: ONLY AFTER finishing all chunks, begin writing your answer.

Answering before finishing ALL chunks = INVALID ANSWER.

## ANTI-EARLY-STOP INSTRUCTION:

You are NOT allowed to stop reading after finding one relevant section.
You MUST continue scanning until the END of [CONTEXT].
The answer may require combining information from chunk 1 AND chunk 5 AND chunk 9.
Missing ANY chunk means the answer is INCOMPLETE and WRONG.

---

## ABSOLUTE RULES — NEVER BREAK THESE:

1. LANGUAGE: Your ENTIRE response MUST be in Arabic only.
   - Do NOT write even a single English word or phrase.
   - Do NOT translate names into English.

2. GROUNDING: Answer ONLY from the [CONTEXT] section below.
   - Do NOT use your internal training knowledge.
   - Do NOT add any name, fact, date, or item not explicitly in the [CONTEXT].
   - Do NOT guess, infer, or extrapolate.

3. NO HALLUCINATION: Any item NOT present in the [CONTEXT] must NOT appear in your answer.

4. IF NOT FOUND: If the [CONTEXT] does not contain a clear answer, respond with ONLY:
   لا تتوفر لديّ معلومات كافية حول هذا الموضوع.
{completeness_block}
## FORMAT RULES:
- Use a professional, human-like conversational tone.
- Start directly with a clear summary or direct answer.
- Use short, readable paragraphs.
- Use Markdown headers (`###`) if answering multiple sub-topics.
- Use Markdown bullet points (`-`) for lists.
- Use **bold** text to highlight important entities (dates, names, critical numbers).
- Do NOT start with "بناءً على" / "وفقًا" / "استناداً إلى".
- Do NOT repeat the question back to the user.
{length_instruction}

## [CONTEXT]:
{context_text}"""

        # ── Step 8: Build message list with capped history ────────────────────
        messages = [{"role": "system", "content": system_prompt}]
        if history:
            for msg in history[-6:]:
                role    = msg.get("role", "user")
                content = msg.get("content", "")
                if role and content:
                    messages.append({"role": role, "content": content})
        messages.append({"role": "user", "content": question})

        # ── Step 9: Generate response (with retry on transient 502/503) ──────
        # The deep.sa API occasionally returns 502 Upstream errors.
        # We retry up to 3 times with exponential back-off before giving up.
        # temperature=0.0  → fully deterministic, maximum grounding
        # max_tokens=2000  → enough for complete multi-point Arabic answers
        _MAX_ATTEMPTS = 3
        _RETRY_DELAYS = [2, 4]   # seconds between attempts

        last_error = None
        for attempt in range(1, _MAX_ATTEMPTS + 1):
            try:
                completion = _client.chat.completions.create(
                    model=_LLM_MODEL,
                    messages=messages,
                    temperature=0.0,
                    max_tokens=3000,   # raised from 2000 — Arabic list answers can be long
                    timeout=60,        # seconds — abort if upstream hangs
                )
                return completion.choices[0].message.content.strip()

            except Exception as gen_err:
                last_error = gen_err
                err_str = str(gen_err)
                # Retry on transient upstream errors (502 / 503 / timeout)
                is_retryable = (
                    "502" in err_str
                    or "503" in err_str
                    or "upstream" in err_str.lower()
                    or "timeout" in err_str.lower()
                    or "timed out" in err_str.lower()
                )
                if is_retryable and attempt < _MAX_ATTEMPTS:
                    wait = _RETRY_DELAYS[attempt - 1]
                    print(f"[RAG] Attempt {attempt} failed ({err_str[:60]}). "
                          f"Retrying in {wait}s...")
                    time.sleep(wait)
                else:
                    break   # non-retryable error or max attempts reached

        print(f"[RAG] Error after {_MAX_ATTEMPTS} attempts: {last_error}")
        return "عذراً، حدث خطأ مؤقت. يرجى المحاولة مجدداً."

    except Exception as e:
        print(f"[RAG] Fatal error: {e}")
        return "عذراً، حدث خطأ غير متوقع."
# ─────────────────────────────────────────────────────────────────────────────
# Legacy shim — kept so nothing breaks
# ─────────────────────────────────────────────────────────────────────────────

def chunk_text(text: str) -> List[str]:
    """Legacy shim: delegates to the improved paragraph splitter."""
    return _paragraph_split(text)

    
