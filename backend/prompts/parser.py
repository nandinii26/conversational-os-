import re

# ── Keyword sets for intent detection ────────────────────────────────────────

_SEARCH_PREFIXES  = ("search ", "find ", "look for ", "locate ")
_SEARCH_PHRASES   = ("search for", "find me", "look for", "locate file", "where is")

_PPT_KEYWORDS     = (
    "generate ppt", "create ppt", "make ppt", "build ppt",
    "generate presentation", "create presentation", "make presentation",
    "build presentation", "make slides", "create slides", "generate slides",
    "ppt on", "presentation on", "slides on",
)

_SUMMARIZE_KEYWORDS = (
    "summarize", "summarise", "summary", "brief", "abstract",
    "in short", "give me a summary", "tldr", "tl;dr", "sum up", "condense",
)

_EMAIL_KEYWORDS = (
    "draft email", "compose email", "write email", "send email",
    "email to", "email about", "write a mail", "draft a mail",
)

# File extensions the user might name in the query
_FILE_EXT_RE = re.compile(
    r"[\w\-. ]+\.(pdf|txt|csv|doc|docx|xlsx|xls|ppt|pptx|md|json)",
    re.IGNORECASE,
)

# "on/about/for/regarding <topic>" extractor
_TOPIC_RE = re.compile(r"(?:on|about|for|regarding)\s+(.+)", re.IGNORECASE)

# Filename substring after common search verbs
_SEARCH_FILE_RE = re.compile(
    r"(?:search for|find|locate|look for)\s+([\w\-_.]+)", re.IGNORECASE
)


def _extract_file(command: str) -> str:
    m = _FILE_EXT_RE.search(command)
    if m:
        return m.group(0).strip()
    m = _SEARCH_FILE_RE.search(command)
    if m:
        return m.group(1).strip()
    return ""


def _extract_topic(command: str) -> str:
    m = _TOPIC_RE.search(command)
    return m.group(1).strip() if m else ""


def parse_command(command: str) -> dict:
    """
    Fast, fully rule-based intent classifier — no LLM round-trip needed.

    Returns a dict with keys:
        action       : 'search' | 'generate_ppt' | 'summarize' | 'email' | 'chat'
        file         : filename/substring to search for (may be empty)
        topic        : topic for PPT generation (may be empty)
        folder       : always '' (reserved for future use)
        raw_response : the original command string
    """
    cmd_lower = command.lower().strip()

    # ── 1. Search / Find ─────────────────────────────────────────────────────
    is_search = (
        any(cmd_lower.startswith(p) for p in _SEARCH_PREFIXES)
        or any(p in cmd_lower for p in _SEARCH_PHRASES)
    )
    if is_search:
        return {
            "action": "search",
            "folder": "",
            "file": _extract_file(command),
            "topic": "",
            "raw_response": command,
        }

    # ── 2. Generate PPT ───────────────────────────────────────────────────────
    if any(kw in cmd_lower for kw in _PPT_KEYWORDS):
        file_name = _extract_file(command)
        topic = _extract_topic(command) if not file_name else ""
        return {
            "action": "generate_ppt",
            "folder": "",
            "file": file_name,
            "topic": topic,
            "raw_response": command,
        }

    # ── 3. Summarize ──────────────────────────────────────────────────────────
    if any(kw in cmd_lower for kw in _SUMMARIZE_KEYWORDS):
        return {
            "action": "summarize",
            "folder": "",
            "file": _extract_file(command),
            "topic": "",
            "raw_response": command,
        }

    # ── 4. Email ──────────────────────────────────────────────────────────────
    if any(kw in cmd_lower for kw in _EMAIL_KEYWORDS):
        return {
            "action": "email",
            "folder": "",
            "file": "",
            "topic": "",
            "raw_response": command,
        }

    # ── 5. Default: general chat / Q&A ────────────────────────────────────────
    return {
        "action": "chat",
        "folder": "",
        "file": "",
        "topic": "",
        "raw_response": command,
    }