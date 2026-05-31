"""
datetime_context.py — Dynamic Datetime Context Helper
======================================================
Provides a single reusable function: get_current_datetime_context()

Returns a formatted string with:
  • Current Date  (YYYY-MM-DD)
  • Current Day   (e.g. Wednesday / الأربعاء)
  • Current Time  (HH:MM, 24-hour)
  • Timezone      (Asia/Riyadh)

This string is injected at the TOP of every LLM system prompt so the
model always has accurate, real-time temporal awareness — critical for:
  - Academic calendar / deadline questions
  - Countdown calculations (days until event)
  - Time-sensitive scheduling queries
  - Any "today / now / current" phrasing

Usage:
    from datetime_context import get_current_datetime_context
    dt_block = get_current_datetime_context()
    system_prompt = dt_block + "\\n\\n" + BASE_SYSTEM_PROMPT
"""

from datetime import datetime
import pytz

# ── Constants ─────────────────────────────────────────────────────────────────

_TIMEZONE = "Asia/Riyadh"

# Arabic day names (Monday = 0 … Sunday = 6, matching datetime.weekday())
_ARABIC_DAYS = {
    0: "الاثنين",
    1: "الثلاثاء",
    2: "الأربعاء",
    3: "الخميس",
    4: "الجمعة",
    5: "السبت",
    6: "الأحد",
}

# English day names (same index mapping)
_ENGLISH_DAYS = {
    0: "Monday",
    1: "Tuesday",
    2: "Wednesday",
    3: "Thursday",
    4: "Friday",
    5: "Saturday",
    6: "Sunday",
}


# ── Public API ────────────────────────────────────────────────────────────────

def get_current_datetime_context() -> str:
    """
    Return a formatted datetime context block for injection into LLM prompts.

    The block is always computed fresh at call time — no caching — so every
    request receives the correct real-time values.

    Returns:
        str: Multi-line datetime context ready to prepend to any system prompt.

    Example output:
        --- Temporal Context (injected automatically) ---
        Current date: 2026-05-06
        Current day:  Wednesday (الأربعاء)
        Current time: 14:35
        Timezone:     Asia/Riyadh
        -------------------------------------------------
    """
    tz = pytz.timezone(_TIMEZONE)
    now: datetime = datetime.now(tz)

    date_str     = now.strftime("%Y-%m-%d")
    time_str     = now.strftime("%H:%M")
    weekday_idx  = now.weekday()
    day_en       = _ENGLISH_DAYS[weekday_idx]
    day_ar       = _ARABIC_DAYS[weekday_idx]

    return (
        "--- Temporal Context (injected automatically) ---\n"
        f"Current date: {date_str}\n"
        f"Current day:  {day_en} ({day_ar})\n"
        f"Current time: {time_str}\n"
        f"Timezone:     {_TIMEZONE}\n"
        "-------------------------------------------------"
    )
