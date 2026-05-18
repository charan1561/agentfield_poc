"""
HyperAgent Evaluator — Hybrid heuristic + LLM scoring for completed runs.

Returns a structured evaluation:
  score        : 0.0–1.0 composite
  quality      : "high" | "medium" | "low"
  failure_type : classified failure or "none"
"""

import json
import logging
from typing import Any, Dict, List, Optional

from .state import DSStarState
from .azure_client import AzureLLM
from .utils import truncate_text

logger = logging.getLogger("ds_star.evaluator")

FAILURE_TYPES = [
    "bad_file_selection",
    "weak_analysis",
    "incorrect_code",
    "execution_error",
    "poor_final_answer",
    "missing_column",
    "wrong_method",
    "bad_visualization",
    "none",
]


# ------------------------------------------------------------------ #
#  Heuristic scoring                                                  #
# ------------------------------------------------------------------ #

def _heuristic_score(state: DSStarState) -> Dict[str, Any]:
    """Fast, deterministic scoring based on run artifacts."""
    score = 0.0
    details: Dict[str, Any] = {}

    code_ok = state.execution_result.exit_code == 0
    details["code_success"] = code_ok
    if code_ok:
        score += 0.25

    has_answer = bool(state.final_answer and len(state.final_answer) > 50)
    details["has_answer"] = has_answer
    if has_answer:
        score += 0.20

    stdout_len = len(state.execution_result.stdout or "")
    details["stdout_length"] = stdout_len
    if stdout_len > 1000:
        score += 0.10

    has_artifacts = len(state.execution_result.artifacts) > 0
    details["has_artifacts"] = has_artifacts
    if has_artifacts:
        score += 0.10

    if state.verified:
        score += 0.10

    iteration_penalty = min(state.iteration * 0.03, 0.25)
    details["iteration_penalty"] = iteration_penalty
    score -= iteration_penalty

    if not code_ok:
        score -= 0.10

    score = max(0.0, min(1.0, score))
    details["heuristic_score"] = round(score, 3)
    return details


# ------------------------------------------------------------------ #
#  LLM evaluation                                                     #
# ------------------------------------------------------------------ #

_EVAL_PROMPT = """You are evaluating a data-science agent run.

QUERY: {query}

FILES USED: {files}

FINAL ANSWER (first 2000 chars):
{answer}

CODE EXIT CODE: {exit_code}
ITERATIONS: {iterations}
STDOUT SNIPPET: {stdout}

Rate this run on three dimensions. Respond ONLY with valid JSON:
{{
  "answered_query": true/false,
  "correct_files": true/false,
  "reasoning_sound": true/false,
  "failure_type": "<one of: {failure_types}>"
}}"""


def _llm_evaluate(
    state: DSStarState, llm: AzureLLM
) -> Dict[str, Any]:
    """LLM-as-judge evaluation of the run."""
    filenames, _ = state.active_filenames_and_summaries()
    prompt = _EVAL_PROMPT.format(
        query=state.query,
        files=", ".join(filenames),
        answer=truncate_text(state.final_answer or "(none)", 2000),
        exit_code=state.execution_result.exit_code,
        iterations=state.iteration,
        stdout=truncate_text(state.execution_result.stdout or "", 1000),
        failure_types=", ".join(FAILURE_TYPES),
    )
    msgs = [{"role": "user", "content": prompt}]

    try:
        raw = llm.chat_complete(msgs, temperature=0.0, max_tokens=300)
        start = raw.find("{")
        end = raw.rfind("}") + 1
        if start >= 0 and end > start:
            parsed = json.loads(raw[start:end])
        else:
            parsed = {}
    except Exception as exc:
        logger.warning("LLM evaluation failed: %s", exc)
        parsed = {}

    return {
        "answered_query":  parsed.get("answered_query", False),
        "correct_files":   parsed.get("correct_files", True),
        "reasoning_sound": parsed.get("reasoning_sound", False),
        "failure_type":    parsed.get("failure_type", "none"),
    }


# ------------------------------------------------------------------ #
#  Combined evaluation                                                #
# ------------------------------------------------------------------ #

def evaluate_run(
    state: DSStarState,
    llm: Optional[AzureLLM] = None,
) -> Dict[str, Any]:
    """
    Hybrid evaluation combining heuristics and (optionally) LLM judgment.

    Returns:
      score        : 0.0–1.0
      quality      : "high" | "medium" | "low"
      failure_type : str
      details      : dict of sub-scores
    """
    h = _heuristic_score(state)
    h_score = h["heuristic_score"]

    llm_result: Dict[str, Any] = {}
    llm_score = 0.0

    if llm is not None:
        try:
            llm_result = _llm_evaluate(state, llm)
            dims = [
                llm_result.get("answered_query", False),
                llm_result.get("correct_files", False),
                llm_result.get("reasoning_sound", False),
            ]
            llm_score = sum(0.20 for d in dims if d)
        except Exception as exc:
            logger.warning("LLM eval error (non-fatal): %s", exc)

    # weighted blend: 40% heuristic, 60% LLM (if available)
    if llm is not None:
        final_score = 0.4 * h_score + 0.6 * (h_score + llm_score)
    else:
        final_score = h_score

    final_score = round(max(0.0, min(1.0, final_score)), 3)

    if final_score >= 0.7:
        quality = "high"
    elif final_score >= 0.4:
        quality = "medium"
    else:
        quality = "low"

    failure_type = llm_result.get("failure_type", "none")
    if failure_type not in FAILURE_TYPES:
        failure_type = "none"
    if final_score >= 0.7:
        failure_type = "none"

    return {
        "score":        final_score,
        "quality":      quality,
        "failure_type": failure_type,
        "details": {
            "heuristic": h,
            "llm":       llm_result,
        },
    }
