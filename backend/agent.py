"""
agent.py — Mujeeb KAU Agentic AI Layer
=======================================
ReAct-pattern agent with structured tool calling.
Sits on top of the existing RAG pipeline — does NOT replace it.

Flow per request:
  1. LLM receives system prompt + question
  2. LLM decides: call a tool OR give final answer
  3. If tool called → execute → inject observation → repeat (max MAX_ITERATIONS)
  4. Final answer returned to caller

Tools:
  • get_academic_events(query)   → PostgreSQL AcademicEvent table
  • search_knowledge_chunks(query) → ChromaDB vector search (existing RAG)
  • calculate_gpa(data)          → simple weighted GPA calculation
"""

import json
import re
import time
import os
from typing import List, Dict, Optional, Any
from dotenv import load_dotenv
from openai import OpenAI
from datetime_context import get_current_datetime_context

# This file is the agent layer.
# It receives a user question, decides which tool is needed,
# executes the tool, then asks the LLM to produce the final answer.

# ── Load env ──────────────────────────────────────────────────────────────────
# Get the backend directory path so the .env file can be loaded reliably
# even if the server is started from a different working directory.
BASE_DIR = os.path.dirname(os.path.abspath(__file__))

# Load environment variables such as OPENAI_API_KEY from the backend .env file.
load_dotenv(os.path.join(BASE_DIR, ".env"))

# API key and model configuration for the external OpenAI-compatible provider.
_DEEPSA_API_KEY  = os.getenv("OPENAI_API_KEY", "")
_DEEPSA_BASE_URL = "https://alapi.deep.sa/v1"
_LLM_MODEL       = "google/gemini-3-flash"

# Alternative model kept as a commented option for quick switching during testing.
#_LLM_MODEL       = "deep-sa/alLLM"


# Shared LLM client used by the agent for reasoning and final answer generation.
_client = OpenAI(base_url=_DEEPSA_BASE_URL, api_key=_DEEPSA_API_KEY)

# Safety limits
# MAX_ITERATIONS controls how many reasoning/tool-use rounds the agent can perform.
# MAX_TOOL_CALLS controls the total number of tool calls across the whole request.
# These limits prevent infinite tool loops and keep responses predictable.
MAX_ITERATIONS   = 5   # max tool-call rounds per request
MAX_TOOL_CALLS   = 8   # total tool calls across all iterations

# ─────────────────────────────────────────────────────────────────────────────
# TOOL DEFINITIONS
# ─────────────────────────────────────────────────────────────────────────────

# Tool schema passed to the LLM.
# The model reads these definitions to know which tools exist,
# when to call them, and what arguments each tool expects.
TOOLS_SCHEMA = [
    {
        "type": "function",
        "function": {
            "name": "get_academic_events",
            "description": (
                "Fetch academic events, schedules, registration windows, "
                "and calendar information from the university database. "
                "Use this for any question about WHEN something happens: exams, registration, "
                "semester start/end, deadlines, holidays, or any date-related query."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "The search query describing what events to look for (in Arabic or English)"
                    }
                },
                "required": ["query"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "search_knowledge_chunks",
            "description": (
                "Search the university knowledge base for rules, regulations, admission requirements, "
                "specialization conditions, academic policies, procedures, and general university information. "
                "Use this for any question about HOW something works, WHAT are the conditions/requirements, "
                "or any policy/regulation question."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "The search query in Arabic or English"
                    }
                },
                "required": ["query"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "calculate_gpa",
            "description": (
                "Calculate GPA (cumulative grade point average) given a list of courses with grades and credit hours. "
                "Use this ONLY when the user explicitly asks to calculate their GPA or average."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "courses": {
                        "type": "array",
                        "description": "List of courses with grade and credit hours",
                        "items": {
                            "type": "object",
                            "properties": {
                                "name":    {"type": "string",  "description": "Course name (optional)"},
                                "grade":   {"type": "string",  "description": "Letter grade: A+, A, B+, B, C+, C, D+, D, F"},
                                "credits": {"type": "number",  "description": "Credit hours for the course"}
                            },
                            "required": ["grade", "credits"]
                        }
                    }
                },
                "required": ["courses"]
            }
        }
    }
]

# ─────────────────────────────────────────────────────────────────────────────
# TOOL IMPLEMENTATIONS
# ─────────────────────────────────────────────────────────────────────────────

def _tool_get_academic_events(query: str, db=None, user_type: str = "all") -> Dict[str, Any]:
    """
    Benefit:
        Retrieves academic calendar events from PostgreSQL for date-related questions.

    What it does:
        Reads AcademicEvent records from the database, filters events based on the
        current user type, optionally narrows the result using query keywords, and
        returns the events as structured JSON for the agent.

    Why it is useful:
        The agent should not invent dates. This tool grounds answers about exams,
        registration periods, deadlines, holidays, and semester events in database data.
    """
    # The tool requires a live database session from the FastAPI endpoint.
    if db is None:
        return {"success": False, "error": "Database not available", "events": []}

    try:
        # Import inside the function to avoid circular imports during app startup.
        from models import AcademicEvent
        from sqlalchemy import or_
        
        # Start with all academic events, then apply audience filtering.
        query_db = db.query(AcademicEvent)

        if user_type.lower() not in ["all", "guest"]:
            query_db = query_db.filter(or_(AcademicEvent.UserType == "all", AcademicEvent.UserType.is_(None), AcademicEvent.UserType == user_type.lower()))
        else:
            # Guests and general users only see public events.
            query_db = query_db.filter(or_(AcademicEvent.UserType == "all", AcademicEvent.UserType.is_(None)))
            
        # Order events by start date so the final answer can present them chronologically.
        events = query_db.order_by(AcademicEvent.StartDate).all()

        if not events:
            return {"success": True, "count": 0, "events": [], "message": "No academic events found in the database."}

        # Convert SQLAlchemy objects into plain dictionaries that can be serialized as JSON.
        events_list = []
        for ev in events:
            events_list.append({
                "title":      ev.Title or "",
                "start_date": str(ev.StartDate)  if ev.StartDate  else None,
                "end_date":   str(ev.EndDate)    if ev.EndDate    else None,
                "hi_start":   str(ev.HStartDate) if ev.HStartDate else None,
                "hi_end":     str(ev.HEndDate)   if ev.HEndDate   else None,
                "user_type":  ev.UserType or "all",
            })

        # Keyword-filter if query is specific.
        # Short words are ignored because they usually add noise in Arabic and English.
        keywords = [w for w in query.split() if len(w) > 2]
        if keywords:
            filtered = [
                e for e in events_list
                if any(kw in e["title"] for kw in keywords)
            ]
            # Fall back to all events if filter returns nothing.
            # This avoids hiding valid calendar data when the keyword match is too strict.
            if filtered:
                events_list = filtered

        return {
            "success": True,
            "count":   len(events_list),
            "events":  events_list
        }

    except Exception as e:
        print(f"[AGENT][get_academic_events] Error: {e}")
        return {"success": False, "error": str(e), "events": []}


def _tool_search_knowledge_chunks(query: str, db=None, user_type: str = "all") -> Dict[str, Any]:
    """
    Benefit:
        Searches the existing ChromaDB knowledge base for policy and document answers.

    What it does:
        Uses the same RAG retrieval helpers already defined in rag.py: embeds the query,
        searches ChromaDB, filters weak matches, expands neighboring chunks, reranks the
        results, and builds a context string for the agent.

    Why it is useful:
        This keeps the agent connected to the project knowledge base without duplicating
        the full RAG logic. The tool retrieves context only; the agent still writes the
        final answer.
    """
    try:
        # Import existing RAG internals.
        # Keeping these imports here reduces startup coupling and reuses the tested pipeline.
        from rag import (
            _embed_query,
            _expand_with_neighbours,
            _rerank_chunks,
            _build_context_text,
            _is_detail_question,
            collection,
            _TOP_K,
            _MIN_RELEVANCE_DIST,
            _MIN_CHUNKS_AFTER_FILTER,
            _NEIGHBOUR_WINDOW,
            _RERANK_TOP_N,
        )

        # Convert the user query into an embedding before searching ChromaDB.
        query_embedding = _embed_query(query)

        # Check how many vectors exist before querying.
        # If ChromaDB count fails, treat it as empty instead of crashing the agent.
        try:
            collection_count = collection.count()
        except Exception:
            collection_count = 0

        if collection_count == 0:
            return {"success": True, "context": "", "chunk_count": 0,
                    "message": "Knowledge base is empty."}

        # Never request more results than the collection actually contains.
        n_results = min(_TOP_K, collection_count)

        # Build metadata filtering based on the current user role.
        where_filter = None
        user_type_lower = user_type.lower()
        if user_type_lower == "admin":
            # Admin sees everything, so no metadata filter is applied.
            where_filter = None  # Admin sees everything
        elif user_type_lower not in ["all", "guest"]:
            # Logged-in user types see public chunks plus chunks assigned to their category.
            where_filter = {"$or": [{"user_type": "all"}, {"user_type": user_type_lower}]}
        else:
            # Guests and general users only see public chunks.
            where_filter = {"user_type": "all"}

        # Query ChromaDB for the most relevant document chunks.
        results = collection.query(
            query_embeddings=[query_embedding],
            n_results=n_results,
            include=["documents", "metadatas", "distances"],
            where=where_filter
        )

        raw_chunks    = results.get("documents", [[]])[0]
        raw_ids       = results.get("ids",       [[]])[0]
        raw_distances = results.get("distances", [[]])[0]

        # Relevance filter.
        # Keep only chunks with acceptable vector distance.
        chroma_ids, chroma_chunks = [], []
        for cid, chunk, dist in zip(raw_ids, raw_chunks, raw_distances):
            if dist <= _MIN_RELEVANCE_DIST:
                chroma_ids.append(cid)
                chroma_chunks.append(chunk)

        # If strict filtering leaves too few chunks, fall back to the raw search results.
        # This protects recall for broad or wording-sensitive questions.
        if len(chroma_chunks) < _MIN_CHUNKS_AFTER_FILTER and raw_chunks:
            chroma_ids    = list(raw_ids)
            chroma_chunks = list(raw_chunks)

        if not chroma_ids:
            return {"success": True, "context": "", "chunk_count": 0,
                    "message": "No relevant content found for this query."}

        # Neighbour expansion.
        # Detail questions get a smaller window to stay focused; broad questions use the default.
        adaptive_window = 2 if _is_detail_question(query) else _NEIGHBOUR_WINDOW
        expanded = _expand_with_neighbours(chroma_ids, chroma_chunks, window=adaptive_window)

        # Rerank + slice.
        # Reranking improves the order of retrieved chunks before the final context is built.
        if expanded:
            reranked   = _rerank_chunks(expanded, query)
            top_chunks = reranked[:_RERANK_TOP_N]

            # Preserve long, information-dense chunks even if they were not in the top reranked set.
            density_threshold = 300 if _is_detail_question(query) else 500
            important = [c for c in expanded if len(c[1]) > density_threshold]
            top_ids   = {c[0] for c in top_chunks}
            for imp in important:
                if imp[0] not in top_ids:
                    top_chunks.append(imp)
                    top_ids.add(imp[0])

            # Dedup and restore doc order.
            # This removes repeated chunks while keeping the original document sequence.
            seen_ids: set = set()
            deduped = []
            for tup in top_chunks:
                if tup[0] not in seen_ids:
                    seen_ids.add(tup[0])
                    deduped.append(tup)
            deduped.sort(key=lambda x: x[2])
            expanded = deduped

        # Build the final text context that will be passed back to the agent.
        context = _build_context_text(expanded)
        return {
            "success":     True,
            "context":     context,
            "chunk_count": len(expanded),
        }

    except Exception as e:
        print(f"[AGENT][search_knowledge_chunks] Error: {e}")
        return {"success": False, "error": str(e), "context": ""}


# GPA grade-point mapping (KAU scale).
# The GPA tool uses this dictionary to convert letter grades into numeric points.
_GRADE_POINTS = {
    "A+": 4.0, "A": 4.0, "A-": 3.75,
    "B+": 3.5, "B": 3.0, "B-": 2.75,
    "C+": 2.5, "C": 2.0, "C-": 1.75,
    "D+": 1.5, "D": 1.0, "D-": 0.75,
    "F":  0.0,
}


def _tool_calculate_gpa(courses: List[Dict]) -> Dict[str, Any]:
    """
    Benefit:
        Calculates a student's GPA from grades and credit hours.

    What it does:
        Validates the submitted courses, converts each letter grade into grade points,
        multiplies grade points by credit hours, totals all points and credits, then
        returns the final weighted GPA with a standing label.

    Why it is useful:
        GPA calculation is deterministic and should be handled by code, not guessed by
        the LLM. This keeps the answer accurate and explainable.
    """
    try:
        if not courses:
            return {"success": False, "error": "No courses provided."}

        # Running totals used for weighted GPA calculation.
        total_points  = 0.0
        total_credits = 0.0

        # Stores per-course calculation details for transparent output.
        course_details = []

        # Validate and calculate points for each submitted course.
        for course in courses:
            grade   = str(course.get("grade", "")).strip().upper()
            credits = float(course.get("credits", 0))
            name    = course.get("name", "")

            # Reject unknown grades so incorrect values do not produce misleading GPA results.
            if grade not in _GRADE_POINTS:
                return {
                    "success": False,
                    "error": f"Unknown grade '{grade}'. Valid grades: {list(_GRADE_POINTS.keys())}"
                }
            # Credit hours must be positive for weighted GPA calculation.
            if credits <= 0:
                return {"success": False, "error": f"Invalid credits ({credits}) for course '{name}'."}

            # Weighted course points = grade points × credit hours.
            points = _GRADE_POINTS[grade] * credits
            total_points  += points
            total_credits += credits
            course_details.append({
                "name":    name,
                "grade":   grade,
                "credits": credits,
                "points":  round(points, 2)
            })

        if total_credits == 0:
            return {"success": False, "error": "Total credit hours is zero."}

        # Final GPA is total weighted points divided by total credit hours.
        gpa = round(total_points / total_credits, 2)

        # Classify GPA.
        # This label helps the final response explain the numeric result clearly.
        if gpa >= 3.75:
            standing = "ممتاز (Excellent)"
        elif gpa >= 3.0:
            standing = "جيد جداً (Very Good)"
        elif gpa >= 2.0:
            standing = "جيد (Good)"
        elif gpa >= 1.0:
            standing = "مقبول (Pass)"
        else:
            standing = "راسب (Fail)"

        return {
            "success":        True,
            "gpa":            gpa,
            "standing":       standing,
            "total_credits":  total_credits,
            "total_points":   round(total_points, 2),
            "course_details": course_details,
        }

    except Exception as e:
        print(f"[AGENT][calculate_gpa] Error: {e}")
        return {"success": False, "error": str(e)}


# ─────────────────────────────────────────────────────────────────────────────
# TOOL DISPATCHER
# ─────────────────────────────────────────────────────────────────────────────

def _dispatch_tool(name: str, arguments: Dict, db=None, user_type: str = "all") -> str:
    """
    Benefit:
        Centralizes tool execution for the agent.

    What it does:
        Receives a tool name and arguments from the LLM, calls the matching Python
        tool function, and returns the result as a JSON string that can be injected
        back into the conversation as a tool observation.

    Why it is useful:
        Keeping tool routing in one place makes the ReAct loop cleaner and makes it
        easier to add, remove, or debug tools later.
    """
    try:
        # Route the tool call to the correct implementation based on its name.
        if name == "get_academic_events":
            result = _tool_get_academic_events(arguments.get("query", ""), db=db, user_type=user_type)
        elif name == "search_knowledge_chunks":
            result = _tool_search_knowledge_chunks(arguments.get("query", ""), db=db, user_type=user_type)
        elif name == "calculate_gpa":
            result = _tool_calculate_gpa(arguments.get("courses", []))
        else:
            result = {"success": False, "error": f"Unknown tool: {name}"}

        # Return JSON with Arabic preserved for better readability in the LLM observation.
        return json.dumps(result, ensure_ascii=False, indent=2)

    except Exception as e:
        return json.dumps({"success": False, "error": str(e)}, ensure_ascii=False)


# ─────────────────────────────────────────────────────────────────────────────
# SYSTEM PROMPT
# ─────────────────────────────────────────────────────────────────────────────

# Main system prompt that controls the agent behavior.
# It defines the assistant identity, when to call tools, language handling,
# grounding rules, completeness rules, and final answer formatting.
AGENT_SYSTEM_PROMPT = """ <role>
أنت "مجيب"، المساعد الأكاديمي الذكي لجامعة الملك عبدالعزيز (KAU).
You are "Mujeeb", the intelligent academic assistant for King Abdulaziz University (KAU). </role>

<goal>
Provide accurate, complete, and grounded academic answers using ONLY available data sources.
Never answer from general knowledge when tools are available.
</goal>

<tools>
You have three tools available. ALWAYS use them before answering:

1. get_academic_events(query)
   → Use for: schedules, exam dates, registration periods, semester start/end, deadlines, holidays
   → Trigger words: متى، موعد، تاريخ، تسجيل، اختبار، نهائي، بداية، نهاية، تقويم، فصل

2. search_knowledge_chunks(query)
   → Use for: rules, regulations, admission requirements, GPA conditions, specialization policies, procedures
   → Trigger words: شروط، متطلبات، كيف، ما هي، لوائح، نظام، قبول، تخصص، مواد، ساعات

3. calculate_gpa(courses)
   → Use ONLY when: user explicitly provides grades and credits and asks to calculate GPA/معدل
   → Never call this unless the user provides actual course data

   </tools>

<decision_rules>

* If question contains time/date keywords → call get_academic_events FIRST
* If question asks about rules/regulations/requirements → call search_knowledge_chunks FIRST
* If question asks to calculate معدل/GPA with actual data → call calculate_gpa
* You MAY call multiple tools if the question requires multiple types of information
* You MUST call at least one tool before giving a final answer (unless it is a pure greeting)
  </decision_rules>

<language_handling>

* Always detect the input language first (Arabic or English)
* If the input is English:

  1. Translate the question into Arabic
  2. Use the Arabic version when calling tools
  3. Generate the final answer in English
* If the input is Arabic:

  1. Use the question as-is
  2. Answer in Arabic
     </language_handling>

<constraints>
- NEVER hallucinate facts, names, dates, or requirements.
- NEVER answer from training knowledge if a tool can provide the data.
- ALWAYS prefer tool results over assumptions.
- If tool returns no data → say clearly: "لا تتوفر لديّ معلومات كافية حول هذا الموضوع حالياً."
- NEVER repeat the user's question in your answer.
- Do NOT start with "بناءً على" or "وفقًا" — start directly with the content.
- The response language MUST match the user's question language.
- The conversation includes previous messages (history).
- You MUST use previous messages to understand the current question context.

* If the user asks a follow-up question:
  • You MUST link it to previous messages.
  • Do NOT treat it as a new independent question.

* If the question is unclear or incomplete:
  • Use previous conversation context to infer meaning.
  • Do NOT ignore earlier messages.

* NEVER compress or merge official academic rights, rules, conditions, requirements, procedures, or regulations into fewer points.

* If the retrieved content contains multiple items, preserve ALL items completely.

  </constraints>

<format>
- Detect the language of the user question (Arabic or English).
- If the question is in English:
  • Translate it internally to Arabic for tool usage.
  • Respond in English with a professional, human-like tone.
- If the question is in Arabic:
  • Respond in professional Arabic.
- **IMPORTANT**: Provide answers in a natural, conversational style, similar to a human assistant (like ChatGPT).
- **Structure**:
  • Start directly with a clear summary or direct answer.
  • Use short, readable paragraphs (avoid huge text blocks).
  • Use Markdown headers (`###`) if the answer contains distinct topics.
  • Use Markdown bullet points (`-` or `*`) for lists and requirements.
  • Use **bold** text to highlight important entities (dates, GPA numbers, critical conditions).
  • End naturally without sounding robotic.

* **CRITICAL COMPLETENESS RULE**:
  • If the retrieved content contains rights, conditions, rules, requirements, procedures, regulations, policies, or official lists:

  * You MUST include ALL items completely.
  * You MUST NOT omit, merge, compress, or summarize list items.
  * Preserve the full meaning of every item.
  * You may improve formatting and readability ONLY without removing content.
  * Exhaustiveness is more important than brevity.

* For GPA calculations: Show a clean, well-spaced breakdown using bullet points and highlight the final GPA.

  </format>

<examples>
Q: "متى اختبار الفاينل؟"
→ THOUGHT: This is a date question. Call get_academic_events.
→ ACTION: get_academic_events(query="اختبار نهائي فاينل")
→ Use the returned dates in the answer.

Q: "ما شروط القبول؟"
→ THOUGHT: This is about regulations. Call search_knowledge_chunks.
→ ACTION: search_knowledge_chunks(query="شروط القبول")
→ Answer from the returned context.

Q: "احسب معدلي: A+ 3 ساعات، B 4 ساعات"
→ THOUGHT: User wants GPA calculation with actual data.
→ ACTION: calculate_gpa(courses=[{"grade":"A+","credits":3},{"grade":"B","credits":4}])
→ Return the computed GPA and standing. </examples>
"""


# ─────────────────────────────────────────────────────────────────────────────
# AGENT STEP LOG (optional, for debugging)
# ─────────────────────────────────────────────────────────────────────────────

class AgentStep:
    """
    Benefit:
        Stores a compact record of each tool call made by the agent.

    What it does:
        Saves the iteration number, tool name, tool arguments, and a shortened version
        of the tool observation for debugging logs.

    Why it is useful:
        During development, this makes it easier to understand which tools the agent used
        and what information each tool returned.
    """

    def __init__(self, iteration: int, tool_name: str, tool_args: Dict, observation: str):
        self.iteration   = iteration
        self.tool_name   = tool_name
        self.tool_args   = tool_args
        # Store only a shortened observation to keep debug logs readable.
        self.observation = observation[:500] + "..." if len(observation) > 500 else observation

    def __repr__(self):
        return (
            f"[Step {self.iteration}] Tool={self.tool_name} "
            f"Args={self.tool_args} → Obs={self.observation[:80]}..."
        )


# ─────────────────────────────────────────────────────────────────────────────
# MAIN AGENT FUNCTION  (ReAct loop)
# ─────────────────────────────────────────────────────────────────────────────

def run_agent(
    question:   str,
    history:    List[Dict[str, str]] = None,
    db=None,
    max_iterations: int = MAX_ITERATIONS,
    user_type: str = "all",
) -> str:
    """
    Benefit:
        Runs the main Agentic AI flow for one user question.

    What it does:
        Builds the message context, adds current date/time, includes recent chat history,
        lets the LLM decide whether to call tools, executes tool calls, feeds tool
        results back to the LLM, and returns the final grounded answer.

    Why it is useful:
        This function is the core ReAct loop. It allows Mujeeb to reason, retrieve
        official data, calculate when needed, and answer using project data instead
        of relying on unsupported assumptions.

    Args:
        question:       The user's query (Arabic or English).
        history:        Previous conversation turns [{role, content}].
        db:             SQLAlchemy session (passed from the endpoint).
        max_iterations: Safety cap on tool-call rounds.
        user_type:      Current user category used for filtering documents/events.

    Returns:
        Final answer string.
    """
    # Avoid using a mutable default value for history.
    if history is None:
        history = []

    # ── Build initial message list ─────────────────────────────────────────
    # Prepend a fresh datetime block so the LLM always knows the real
    # current date / time / timezone on every single request.
    _dt_context = get_current_datetime_context()
    _system_with_dt = _dt_context + "\n\n" + AGENT_SYSTEM_PROMPT
    messages: List[Dict] = [{"role": "system", "content": _system_with_dt}]

    # Include last 6 turns of history for short-term memory.
    # This helps the agent understand follow-up questions without loading the full chat.
    for msg in history[-6:]:
        role    = msg.get("role", "user")
        content = msg.get("content", "")
        if role in ("user", "assistant") and content:
            messages.append({"role": role, "content": content})

    # Add the current user question as the latest message.
    messages.append({"role": "user", "content": question})

    # Track tool calls for debugging and enforce the maximum tool-call limit.
    steps:           List[AgentStep] = []
    total_tool_calls: int            = 0

    # ── ReAct Loop ────────────────────────────────────────────────────────
    for iteration in range(1, max_iterations + 1):
        print(f"[AGENT] Iteration {iteration}/{max_iterations}")

        try:
            # Ask the LLM to either answer or request one of the registered tools.
            response = _client.chat.completions.create(
                model=_LLM_MODEL,
                messages=messages,
                tools=TOOLS_SCHEMA,
                tool_choice="auto",
                temperature=0.0,
                max_tokens=4000,
                timeout=90,
            )
        except Exception as llm_err:
            # If the agent LLM call fails, use the classic RAG pipeline instead of failing the user.
            print(f"[AGENT] LLM call failed: {llm_err}")
            return _fallback_rag(question, history, db, user_type)

        choice  = response.choices[0]
        message = choice.message

        # ── Final answer (no tool call) ────────────────────────────────
        # If the model did not request a tool, treat the message as the final answer.
        if not message.tool_calls:
            answer = (message.content or "").strip()
            if answer:
                print(f"[AGENT] Final answer after {iteration} iteration(s). Steps: {len(steps)}")
                return answer
            # LLM returned empty — fall back to avoid returning a blank response.
            print("[AGENT] Empty response from LLM, falling back to RAG.")
            return _fallback_rag(question, history, db, user_type)

        # ── Process tool calls ─────────────────────────────────────────
        # Append the assistant message with tool_calls to the thread.
        # This is required so the later tool observations match the model's requested calls.
        messages.append(message)

        for tool_call in message.tool_calls:
            # Stop tool execution if the global safety limit has been reached.
            if total_tool_calls >= MAX_TOOL_CALLS:
                print(f"[AGENT] MAX_TOOL_CALLS ({MAX_TOOL_CALLS}) reached — stopping tool calls.")
                break

            tool_name = tool_call.function.name

            # Tool arguments arrive as a JSON string from the LLM.
            # If parsing fails, use an empty dictionary so the dispatcher can handle it safely.
            try:
                tool_args = json.loads(tool_call.function.arguments or "{}")
            except json.JSONDecodeError:
                tool_args = {}

            print(f"[AGENT]  → Tool: {tool_name}({tool_args})")

            # Execute the requested tool and receive its JSON observation.
            observation = _dispatch_tool(tool_name, tool_args, db=db, user_type=user_type)
            total_tool_calls += 1

            # Store a compact debug record of this tool call.
            step = AgentStep(iteration, tool_name, tool_args, observation)
            steps.append(step)
            print(f"[AGENT]  ← Observation ({len(observation)} chars)")

            # Inject tool result back into the message thread.
            # The LLM uses this observation in the next iteration to continue reasoning or answer.
            messages.append({
                "role":         "tool",
                "tool_call_id": tool_call.id,
                "name":         tool_name,
                "content":      observation,
            })

    # ── Exceeded max iterations — do one final synthesis call ──────────
    # If the loop ends before a final answer, ask the LLM to synthesize an answer
    # from all collected tool observations.
    print(f"[AGENT] Max iterations reached. Synthesizing final answer.")
    try:
        synthesis = _client.chat.completions.create(
            model=_LLM_MODEL,
            messages=messages + [{
                "role": "user",
                "content": (
                    "بناءً على المعلومات التي جمعتها من الأدوات، "
                    "أجب الآن على السؤال الأصلي بشكل كامل ومنظم بأسلوب محادثة طبيعي، "
                    "مع استخدام تنسيق Markdown (عناوين، نقاط، خط عريض) ليكون الرد واضحاً واحترافياً."
                )
            }],
            temperature=0.0,
            max_tokens=3000,
            timeout=60,
        )
        answer = (synthesis.choices[0].message.content or "").strip()
        if answer:
            return answer
    except Exception as e:
        print(f"[AGENT] Synthesis call failed: {e}")

    return _fallback_rag(question, history, db, user_type)


# ─────────────────────────────────────────────────────────────────────────────
# FALLBACK — delegates to classic ask_rag if agent fails
# ─────────────────────────────────────────────────────────────────────────────

def _fallback_rag(question: str, history: List[Dict], db=None, user_type: str = "all") -> str:
    """
    Benefit:
        Provides a backup answer path if the agent flow fails.

    What it does:
        Calls the original ask_rag pipeline using the same question, history, database
        session, and user type. If that also fails, it returns a simple Arabic error
        message to the user.

    Why it is useful:
        The system remains usable even if the agent LLM call, tool loop, or synthesis
        step fails temporarily.
    """
    try:
        # Import here to avoid startup dependency issues and only load RAG when needed.
        from rag import ask_rag
        print("[AGENT] Falling back to classic ask_rag.")
        return ask_rag(question, history, db=db, user_type=user_type)
    except Exception as e:
        print(f"[AGENT] Fallback RAG also failed: {e}")
        return "عذراً، حدث خطأ مؤقت. يرجى المحاولة مجدداً."

