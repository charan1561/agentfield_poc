import re
from typing import Optional


def extract_first_code_block(text: str) -> str:
    """
    Extract the first fenced code block from an LLM response.
    Prefers ```python ... ``` but falls back to the first triple-backtick block.
    If none found, returns the original text.
    """
    if not text:
        return text

    # Prefer ```python ... ```
    m = re.search(r"```(?:python|py)\s*(.*?)```", text, flags=re.DOTALL | re.IGNORECASE)
    if m:
        return m.group(1).strip()

    # Fallback: any code fence
    m = re.search(r"```\s*(.*?)```", text, flags=re.DOTALL)
    if m:
        return m.group(1).strip()

    return text.strip()


def parse_yes_no(text: str) -> bool:
    """
    Parse 'Yes' or 'No' (case-insensitive). Defaults to False on ambiguity.
    """
    if not text:
        return False
    t = text.strip().lower()
    if "yes" == t or t.startswith("yes"):
        return True
    if "no" == t or t.startswith("no"):
        return False
    # Heuristic: look for standalone yes/no tokens
    if re.search(r"\byes\b", t):
        return True
    if re.search(r"\bno\b", t):
        return False
    return False


def parse_router_decision(text: str) -> Optional[str]:
    """
    Expect 'Add Step', 'Step i', 'Change Strategy', 'Rerun Analysis',
    or 'Retrieve Files'.
    Returns:
      - 'add' for Add Step
      - 'step:<i>' for Step i (1-based)
      - 'change_strategy' for Change Strategy
      - 'rerun_analysis' for Rerun Analysis
      - 'retrieve_files' for Retrieve Files
      - None if cannot parse
    """
    if not text:
        return None
    t = text.strip().lower()
    if "add step" in t:
        return "add"
    m = re.search(r"step\s+(\d+)", t)
    if m:
        try:
            idx = int(m.group(1))
            if idx >= 1:
                return f"step:{idx}"
        except Exception:
            pass
    if "change strategy" in t:
        return "change_strategy"
    if "rerun analysis" in t or "re-run analysis" in t:
        return "rerun_analysis"
    if "retrieve files" in t or "retrieve more files" in t:
        return "retrieve_files"
    return None


def truncate_text(text: str, max_chars: int = 4000) -> str:
    """
    Safely truncate long strings for prompt/context usage.
    """
    if text is None:
        return ""
    if len(text) <= max_chars:
        return text
    head = int(max_chars * 0.7)
    tail = max_chars - head - 20
    return f"{text[:head]}\n...\n{len(text) - head - tail} chars omitted\n...\n{text[-tail:]}"
