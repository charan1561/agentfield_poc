from __future__ import annotations
from typing import List, Optional, Dict, Any, Union
from pydantic import BaseModel, Field


class ExecutionResult(BaseModel):
    stdout: str = ""
    stderr: str = ""
    exit_code: int = 0
    # Optionally record output artifacts (e.g., paths under final/)
    artifacts: Dict[str, Any] = Field(default_factory=dict)


class Description(BaseModel):
    filename: str
    summary: str  # textual description captured from analyzer script execution output


class DSStarState(BaseModel):
    # Inputs
    query: str
    data_dir: str = "data"
    data_files: List[str] = Field(default_factory=list)
    guidelines: Optional[str] = None

    # Analyzer outputs
    data_descriptions: List[Description] = Field(default_factory=list)
    retrieved_indices: Optional[List[int]] = None  # indices into data_descriptions (top-K)

    # Planning and implementation
    plans: List[str] = Field(default_factory=list)  # cumulative steps p0..pk
    base_code: str = ""     # code implementing plans up to previous step
    current_code: str = ""  # code implementing current cumulative plan
    codes_per_step: List[str] = Field(default_factory=list)  # snapshot of code implementing up to each step

    # Execution
    execution_result: ExecutionResult = Field(default_factory=ExecutionResult)
    last_traceback: Optional[str] = None

    # Control / verification
    verified: bool = False
    router_decision: Optional[Union[str, int]] = None  # "Add Step" or index (1-based in prompt, we normalize to 0-based int)
    iteration: int = 0
    max_iterations: int = 20

    # Finalization
    final_answer: Optional[str] = None
    final_code: Optional[str] = None

    # LLM/Embedding config (optional if set via env)
    embedding_top_k: int = 100  # per paper Section 3.3
    use_retriever: bool = True  # enable retrieval if N > K

    # HyperAgent fields
    retrieved_strategies: List[str] = Field(default_factory=list)
    anti_patterns: List[Dict[str, Any]] = Field(default_factory=list)
    similar_runs: List[Dict[str, Any]] = Field(default_factory=list)
    run_score: Optional[Dict[str, Any]] = None
    failure_type: Optional[str] = None
    consecutive_verify_fails: int = 0

    # Observability
    history: List[Dict[str, Any]] = Field(default_factory=list)

    def active_filenames_and_summaries(self) -> tuple[List[str], List[str]]:
        """
        Returns (filenames, summaries) either full set or retrieved top-K subset
        depending on retrieved_indices.
        """
        if self.retrieved_indices is None:
            fns = [d.filename for d in self.data_descriptions]
            sums = [d.summary for d in self.data_descriptions]
            return fns, sums
        fns = [self.data_descriptions[i].filename for i in self.retrieved_indices]
        sums = [self.data_descriptions[i].summary for i in self.retrieved_indices]
        return fns, sums

    def record_iteration(self, extra: Optional[Dict[str, Any]] = None) -> None:
        rec = {
            "iteration": self.iteration,
            "plans": list(self.plans),
            "verified": self.verified,
            "router_decision": self.router_decision,
            "exit_code": self.execution_result.exit_code,
        }
        if extra:
            rec.update(extra)
        self.history.append(rec)
