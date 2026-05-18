"""
HyperAgent Meta Controller — Run analysis, failure classification, strategy generation.

Responsibilities:
  classify_failure()              — rich failure type from run trace
  generate_strategy()             — what went wrong + how to fix next time
  generate_alternative_strategies — 2-3 alternative approaches for mid-loop reflection
"""

import json
import logging
from typing import Any, Dict, List, Optional

from .azure_client import AzureLLM
from .state import DSStarState
from .utils import truncate_text

logger = logging.getLogger("ds_star.meta_controller")

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
#  Failure classification                                             #
# ------------------------------------------------------------------ #

_CLASSIFY_PROMPT = """You are analyzing a data-science agent run that {outcome}.

QUERY: {query}
PLANS EXECUTED: {plans}
EXIT CODE: {exit_code}
STDOUT (snippet): {stdout}
STDERR (snippet): {stderr}
FINAL ANSWER (snippet): {answer}

Classify the primary failure into exactly ONE of:
{failure_list}

Respond with ONLY valid JSON:
{{"failure_type": "<type>", "reason": "<one sentence>"}}"""


def classify_failure(
    state: DSStarState, llm: AzureLLM
) -> Dict[str, str]:
    """
    Analyze the run trace and return the primary failure type.
    Returns {failure_type, reason}.
    """
    outcome = "succeeded" if state.verified else "did not fully succeed"
    plans_text = "\n".join(
        f"  {i+1}. {p}" for i, p in enumerate(state.plans)
    ) or "(none)"

    prompt = _CLASSIFY_PROMPT.format(
        outcome=outcome,
        query=state.query,
        plans=plans_text,
        exit_code=state.execution_result.exit_code,
        stdout=truncate_text(state.execution_result.stdout or "", 1200),
        stderr=truncate_text(state.execution_result.stderr or "", 800),
        answer=truncate_text(state.final_answer or "(none)", 1000),
        failure_list="\n".join(f"  - {ft}" for ft in FAILURE_TYPES),
    )

    try:
        raw = llm.chat_complete(
            [{"role": "user", "content": prompt}],
            temperature=0.0, max_tokens=200,
        )
        start, end = raw.find("{"), raw.rfind("}") + 1
        if start >= 0 and end > start:
            parsed = json.loads(raw[start:end])
        else:
            parsed = {}

        ft = parsed.get("failure_type", "none")
        if ft not in FAILURE_TYPES:
            ft = "none"
        return {
            "failure_type": ft,
            "reason": parsed.get("reason", ""),
        }
    except Exception as exc:
        logger.warning("classify_failure failed: %s", exc)
        return {"failure_type": "none", "reason": str(exc)}


# ------------------------------------------------------------------ #
#  Strategy generation                                                #
# ------------------------------------------------------------------ #

_STRATEGY_PROMPT = """A data-science agent just ran with this outcome:

QUERY: {query}
FAILURE TYPE: {failure_type}
REASON: {reason}
PLANS: {plans}
EXIT CODE: {exit_code}
STDOUT (snippet): {stdout}

Generate a concise strategy (2-3 sentences) that would help a future
agent avoid this failure type and produce a better answer.

Focus on:
  - What went wrong
  - What to do differently next time

Respond with ONLY the strategy text, no JSON."""


def generate_strategy(
    state: DSStarState,
    failure_type: str,
    llm: AzureLLM,
    reason: str = "",
) -> Optional[str]:
    """Generate a reusable strategy from a completed run."""
    if failure_type == "none" and state.verified:
        plans_text = "\n".join(
            f"  {i+1}. {p}" for i, p in enumerate(state.plans)
        )
        success_prompt = (
            f"A data-science agent successfully answered this query:\n\n"
            f"QUERY: {state.query}\n"
            f"PLANS: {plans_text}\n\n"
            f"Summarize in 2-3 sentences the approach that worked, "
            f"so it can be reused for similar future queries.\n"
            f"Respond with ONLY the strategy text."
        )
        try:
            return llm.chat_complete(
                [{"role": "user", "content": success_prompt}],
                temperature=0.0, max_tokens=200,
            ).strip()
        except Exception as exc:
            logger.warning("generate_strategy (success) failed: %s", exc)
            return None

    plans_text = "\n".join(
        f"  {i+1}. {p}" for i, p in enumerate(state.plans)
    ) or "(none)"

    prompt = _STRATEGY_PROMPT.format(
        query=state.query,
        failure_type=failure_type,
        reason=reason,
        plans=plans_text,
        exit_code=state.execution_result.exit_code,
        stdout=truncate_text(state.execution_result.stdout or "", 1000),
    )

    try:
        return llm.chat_complete(
            [{"role": "user", "content": prompt}],
            temperature=0.0, max_tokens=250,
        ).strip()
    except Exception as exc:
        logger.warning("generate_strategy failed: %s", exc)
        return None


# ------------------------------------------------------------------ #
#  Alternative strategies (mid-loop reflection)                       #
# ------------------------------------------------------------------ #

_ALTERNATIVES_PROMPT = """A data-science agent is stuck while answering this query:

QUERY: {query}
CURRENT PLANS: {plans}
ITERATION: {iteration}
LAST EXIT CODE: {exit_code}
LAST STDOUT (snippet): {stdout}
LAST STDERR (snippet): {stderr}

The current approach is not working. Suggest 2-3 ALTERNATIVE strategies
the agent could try. Each strategy should be a short paragraph.

Respond with ONLY valid JSON:
{{"strategies": ["strategy 1 text", "strategy 2 text", "strategy 3 text"]}}"""


def generate_alternative_strategies(
    state: DSStarState, llm: AzureLLM
) -> List[str]:
    """Generate 2-3 alternative approaches when the agent is stuck."""
    plans_text = "\n".join(
        f"  {i+1}. {p}" for i, p in enumerate(state.plans)
    ) or "(none)"

    prompt = _ALTERNATIVES_PROMPT.format(
        query=state.query,
        plans=plans_text,
        iteration=state.iteration,
        exit_code=state.execution_result.exit_code,
        stdout=truncate_text(state.execution_result.stdout or "", 800),
        stderr=truncate_text(state.execution_result.stderr or "", 600),
    )

    try:
        raw = llm.chat_complete(
            [{"role": "user", "content": prompt}],
            temperature=0.3, max_tokens=500,
        )
        start, end = raw.find("{"), raw.rfind("}") + 1
        if start >= 0 and end > start:
            parsed = json.loads(raw[start:end])
            strategies = parsed.get("strategies", [])
            if isinstance(strategies, list):
                return [s for s in strategies if isinstance(s, str) and s.strip()]
        return []
    except Exception as exc:
        logger.warning("generate_alternative_strategies failed: %s", exc)
        return []


# ------------------------------------------------------------------ #
#  Full meta-analysis pipeline                                        #
# ------------------------------------------------------------------ #

def analyze_run(
    state: DSStarState, llm: AzureLLM
) -> Dict[str, Any]:
    """
    Complete meta-analysis: classify failure, then generate strategy.
    Returns {failure_type, reason, strategy}.
    """
    classification = classify_failure(state, llm)
    ft = classification["failure_type"]
    reason = classification["reason"]

    strategy = generate_strategy(state, ft, llm, reason=reason)

    return {
        "failure_type": ft,
        "reason":       reason,
        "strategy":     strategy,
    }
