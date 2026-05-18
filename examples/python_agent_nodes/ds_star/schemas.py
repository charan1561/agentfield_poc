"""Pydantic request/response models for DS_star AgentField reasoners."""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


class FileDescription(BaseModel):
    filename: str
    summary: str


class AnalyzeResponse(BaseModel):
    descriptions: List[FileDescription] = Field(description="File descriptions from analysis")


class PlanResponse(BaseModel):
    plans: List[str] = Field(description="Step-by-step analysis plans")


class CodeResponse(BaseModel):
    code: str = Field(description="Generated Python code")
    stdout: str = Field(default="", description="Execution stdout")
    stderr: str = Field(default="", description="Execution stderr")
    exit_code: int = Field(default=0, description="Process exit code")
    artifacts: Dict[str, Any] = Field(default_factory=dict, description="Output artifacts")


class VerifyResponse(BaseModel):
    verified: bool = Field(description="Whether the analysis answers the query")
    failure_type: Optional[str] = Field(default=None, description="Failure category if not verified")
    consecutive_fails: int = Field(default=0)


class RouteResponse(BaseModel):
    decision: str = Field(description="Refinement action: add, step:<i>, change_strategy, rerun_analysis, retrieve_files")


class PipelineResponse(BaseModel):
    final_answer: Optional[str] = Field(default=None, description="Final analysis summary")
    final_code: Optional[str] = Field(default=None, description="Final generated code")
    iterations: int = Field(default=0, description="Total iterations executed")
    verified: bool = Field(default=False, description="Whether verification passed")
    plans: List[str] = Field(default_factory=list, description="All generated plans")
    run_score: Optional[Dict[str, Any]] = Field(default=None, description="Evaluation score")
    failure_type: Optional[str] = Field(default=None)


class MetaLearnResponse(BaseModel):
    strategy_stored: bool = Field(default=False)
    failure_classified: bool = Field(default=False)
    failure_type: Optional[str] = Field(default=None)
    score: Optional[Dict[str, Any]] = Field(default=None)


class StrategyResponse(BaseModel):
    strategies: List[Dict[str, Any]] = Field(default_factory=list)


class AntiPatternResponse(BaseModel):
    anti_patterns: List[Dict[str, Any]] = Field(default_factory=list)
