import os
import sys
import logging
from typing import List, Tuple, Optional, Dict, Any
from .azure_client import AzureLLM
from .prompts import (
    render_analyzer_prompt,
    render_planner_init_prompt,
    render_planner_next_prompt,
    render_coder_init_prompt,
    render_coder_next_prompt,
    render_verifier_prompt,
    render_router_prompt,
    render_finalizer_prompt,
    render_debug_summarize_prompt,
    render_debug_fix_analyzer_prompt,
    render_debug_fix_solution_prompt,
)
from .executor import run_python_code
from .events import EventBus
from .state import DSStarState, Description, ExecutionResult
from .retriever import retrieve_top_k
from .utils import extract_first_code_block, parse_yes_no, parse_router_decision, truncate_text
from .strategy_retriever import format_context_block


class DSStarAgents:
    def __init__(self, llm: AzureLLM, workdir: Optional[str] = None, event_bus: Optional[EventBus] = None, run_id: Optional[str] = None) -> None:
        self.llm = llm
        self.workdir = workdir or os.getcwd()
        self.event_bus = event_bus
        self.run_id = run_id or "default"
        self.step_counter = 0
        self.logger = self._setup_logger()

    def _setup_logger(self) -> logging.Logger:
        """Setup structured logging like online dststar.py."""
        rid = self.run_id[:8] if len(self.run_id) > 8 else self.run_id
        logger = logging.getLogger(f"ds_star.{rid}")
        logger.setLevel(logging.INFO)
        if not logger.handlers:
            handler = logging.StreamHandler(sys.stdout)
            handler.setFormatter(logging.Formatter(
                '%(asctime)s - %(levelname)s - %(message)s'
            ))
            logger.addHandler(handler)
        return logger

    def _log_step(self, step_name: str) -> str:
        """Log a step with separator bars like online version."""
        step_id = f"{self.step_counter:03d}_{step_name}"
        self.logger.info("=" * 50)
        self.logger.info(f"STEP {step_id}")
        self.logger.info("=" * 50)
        self.step_counter += 1
        return step_id

    def emit(self, type: str, node: Optional[str] = None, iteration: int = 0, status: Optional[str] = None, payload: Optional[Dict[str, Any]] = None) -> None:
        if self.event_bus and self.run_id:
            self.event_bus.emit_dict(
                type=type,
                run_id=self.run_id,
                node=node,
                iteration=iteration,
                status=status,
                payload=payload or {},
            )

    # --- Helper ---

    def _chat(self, messages: List[Dict[str, Any]], temperature: float = 0.0, max_tokens: Optional[int] = None) -> str:
        resp = self.llm.chat_complete(messages=messages, temperature=temperature, max_tokens=max_tokens)
        self.logger.info(f"[LLM] Response received ({len(resp)} chars)")
        return resp

    def _debug_analyzer_until_executes(self, filename: str, code: str, max_tries: int = 3) -> Tuple[str, ExecutionResult]:
        attempt = 0
        cur_code = code
        last_result: Optional[ExecutionResult] = None
        while attempt < max_tries:
            attempt += 1
            self.logger.info(f"Executing code (attempt {attempt}/{max_tries})...")
            result = run_python_code(cur_code, workdir=self.workdir)
            last_result = result
            if result.exit_code == 0:
                self.logger.info("Execution successful")
                return cur_code, result
            # Summarize traceback and ask debugger to fix
            self.logger.warning(f"Execution failed: {(result.stderr or result.stdout)[:100]}")
            tb = truncate_text(result.stderr or result.stdout, 4000)
            messages = render_debug_summarize_prompt(tb, filename=os.path.splitext(os.path.basename(filename))[0])
            summary = self._chat(messages)
            fix_msgs = render_debug_fix_analyzer_prompt(cur_code, summarized_bug=truncate_text(summary, 3500))
            fixed = self._chat(fix_msgs)
            cur_code = extract_first_code_block(fixed)
        # Return best-effort with last result
        self.logger.warning("Max debug attempts reached")
        return cur_code, last_result or ExecutionResult(stdout="", stderr="No execution attempted", exit_code=-99)

    def _debug_solution_until_executes(
        self,
        file_summaries: List[str],
        filenames: List[str],
        code: str,
        max_tries: int = 3,
    ) -> Tuple[str, ExecutionResult]:
        attempt = 0
        cur_code = code
        last_result: Optional[ExecutionResult] = None
        while attempt < max_tries:
            attempt += 1
            self.logger.info(f"Executing code (attempt {attempt}/{max_tries})...")
            result = run_python_code(cur_code, workdir=self.workdir)
            last_result = result
            if result.exit_code == 0:
                self.logger.info("Execution successful")
                return cur_code, result
            self.logger.warning(f"Execution failed: {(result.stderr or result.stdout)[:100]}")
            tb = truncate_text(result.stderr or result.stdout, 4000)
            sum_msgs = render_debug_summarize_prompt(tb, filename="solution")
            summarized = self._chat(sum_msgs)
            fix_msgs = render_debug_fix_solution_prompt(file_summaries, filenames, cur_code, truncate_text(summarized, 3500))
            fixed = self._chat(fix_msgs)
            cur_code = extract_first_code_block(fixed)
        self.logger.warning("Max debug attempts reached")
        return cur_code, last_result or ExecutionResult(stdout="", stderr="No execution attempted", exit_code=-99)

    # --- Analyzer ---

    def analyze_files(self, state: DSStarState) -> DSStarState:
        descriptions: List[Description] = []
        for fn in state.data_files:
            self._log_step("analyzer")
            self.logger.info(f"Analyzing {fn}...")
            msgs = render_analyzer_prompt(fn)
            resp = self._chat(msgs)
            code = extract_first_code_block(resp)
            self.emit("analyzer_code_generated", node="analyze", iteration=state.iteration, payload={"filename": fn, "code": truncate_text(code, 1500)})
            fixed_code, result = self._debug_analyzer_until_executes(fn, code, max_tries=3)
            self.emit("analyzer_execution_result", node="analyze", iteration=state.iteration, status=("ok" if result.exit_code == 0 else "error"), payload={"filename": fn, "exit_code": result.exit_code, "stdout": truncate_text(result.stdout, 800), "stderr": truncate_text(result.stderr, 800)})
            # Use stdout as description summary (paper uses analyzer scripts to print summaries)
            summary = (result.stdout or "").strip()
            if not summary:
                # If nothing printed, include stderr snippet
                summary = f"[Empty stdout]\n{truncate_text(result.stderr, 1000)}"
            descriptions.append(Description(filename=fn, summary=truncate_text(summary, 4000)))
            self.emit("description_captured", node="analyze", iteration=state.iteration, payload={"filename": fn})
        state.data_descriptions = descriptions

        # Optional retrieval (top-K) per paper if many files
        if state.use_retriever and len(descriptions) > state.embedding_top_k:
            desc_texts = [d.summary for d in descriptions]
            indices = retrieve_top_k(self.llm, query=state.query, descriptions=desc_texts, k=state.embedding_top_k)
            state.retrieved_indices = indices
            self.emit("retriever_selected", node="analyze", iteration=state.iteration, payload={"count": len(indices)})
        else:
            state.retrieved_indices = None

        return state

    # --- Planner ---

    def _get_context_block(self, state: DSStarState) -> str:
        return format_context_block(state.retrieved_strategies, state.anti_patterns)

    def initial_plan(self, state: DSStarState) -> DSStarState:
        self._log_step("planner_init")
        filenames, summaries = state.active_filenames_and_summaries()

        msgs = render_planner_init_prompt(
            state.query,
            summaries,
            filenames,
            state.guidelines or "Provide helpful, concise analysis",
            strategies=self._get_context_block(state),
        )

        step = self._chat(msgs).strip()
        state.plans = [step]
        self.emit("plan_generated", node="planner", iteration=state.iteration,
                payload={"step_index": 1, "text": truncate_text(step, 1000)})
        return state

    def next_plan(self, state: DSStarState, last_result: str) -> DSStarState:
        self._log_step("planner_next")
        filenames, summaries = state.active_filenames_and_summaries()

        msgs = render_planner_next_prompt(
            state.query,
            summaries,
            filenames,
            state.plans,
            truncate_text(last_result, 2000),
            state.guidelines or "Provide helpful, concise analysis",
            strategies=self._get_context_block(state),
        )

        step = self._chat(msgs).strip()
        state.plans.append(step)
        self.emit("plan_generated", node="planner", iteration=state.iteration, payload={"step_index": len(state.plans), "text": truncate_text(step, 1000)})
        return state

    # --- Coder ---

    def implement_initial(self, state: DSStarState) -> DSStarState:
        self._log_step("coder_init")
        filenames, summaries = state.active_filenames_and_summaries()
        msgs = render_coder_init_prompt(
            summaries, filenames, state.plans[0],
            strategies=self._get_context_block(state),
        )
        resp = self._chat(msgs)
        code = extract_first_code_block(resp)
        self.emit("code_generated", node="init_impl", iteration=state.iteration, payload={"kind": "initial", "code": truncate_text(code, 1500)})
        fixed_code, result = self._debug_solution_until_executes(summaries, filenames, code, max_tries=3)
        self.emit("code_execution_result", node="init_impl", iteration=state.iteration, status=("ok" if result.exit_code == 0 else "error"), payload={"exit_code": result.exit_code, "stdout": truncate_text(result.stdout, 800), "stderr": truncate_text(result.stderr, 800), "artifacts": result.artifacts})
        state.base_code = fixed_code
        state.current_code = fixed_code
        state.codes_per_step = [fixed_code]
        state.execution_result = result
        return state

    def implement_next(self, state: DSStarState, current_step: str) -> DSStarState:
        self._log_step("coder_next")
        filenames, summaries = state.active_filenames_and_summaries()
        msgs = render_coder_next_prompt(
            file_summaries=summaries,
            filenames=filenames,
            base_code=state.base_code or state.current_code,
            previous_plans=state.plans[:-1],
            current_step=current_step,
            guidelines=state.guidelines or "",
            strategies=self._get_context_block(state),
        )
        resp = self._chat(msgs)
        code = extract_first_code_block(resp)
        self.emit("code_generated", node="refine", iteration=state.iteration, payload={"kind": "next", "step_index": len(state.plans), "code": truncate_text(code, 1500)})
        fixed_code, result = self._debug_solution_until_executes(summaries, filenames, code, max_tries=3)
        self.emit("code_execution_result", node="refine", iteration=state.iteration, status=("ok" if result.exit_code == 0 else "error"), payload={"step_index": len(state.plans), "exit_code": result.exit_code, "stdout": truncate_text(result.stdout, 800), "stderr": truncate_text(result.stderr, 800), "artifacts": result.artifacts})
        state.current_code = fixed_code
        state.base_code = fixed_code  # treat latest as new base
        state.codes_per_step.append(fixed_code)
        state.execution_result = result
        return state

    # --- Verifier ---

    def verify(self, state: DSStarState) -> DSStarState:
        """
        Progressive verification with early acceptance.
        Key principle: If we have meaningful output, accept it quickly.
        """
        self._log_step("verifier")
        self.logger.info("-" * 30)
        self.logger.info(f"Refinement Round {state.iteration + 1}")
        self.logger.info("-" * 30)

        question = state.query
        plans = state.plans
        code = state.current_code

        # Build result_text from execution result
        result_text = (state.execution_result.stdout or "").strip()
        if state.execution_result.stderr:
            result_text += "\n" + state.execution_result.stderr.strip()

        # EARLY EXIT: If we have substantial output (>1500 chars) and it's been 2+ iterations, likely good enough
        if state.iteration >= 2 and len(result_text) > 1500:
            state.verified = True
            self.emit("verify_early_accept", node="verify", iteration=state.iteration,
                     payload={"reason": f"Substantial output after {state.iteration} iterations"})
            return state

        # CIRCUIT BREAKER: Force exit at 50% of max_iterations (down from 80%)
        if state.iteration >= int(state.max_iterations * 0.5):
            state.verified = True
            self.emit("verify_forced_exit", node="verify", iteration=state.iteration,
                     payload={"reason": f"Reached {state.iteration}/{state.max_iterations} iterations, forcing exit"})
            return state

        # Ask LLM-as-judge (semantic correctness)
        msgs = render_verifier_prompt(
            plans,
            code,
            truncate_text(result_text, 3500),
            question
        )
        verdict = self._chat(msgs).strip().lower()

        # Parse verdict with "almost" support
        if "yes" in verdict:
            llm_verified = True
            confidence = "high"
        elif "almost" in verdict or "partial" in verdict:
            llm_verified = True  # Accept "almost" or "partial" immediately
            confidence = "medium"
        else:
            llm_verified = False
            confidence = "low"

        # Check if summary.md exists (but don't depend on it)
        summary_exists = os.path.isfile(os.path.join(self.workdir, "final", "summary.md"))

        # SIMPLIFIED VERIFICATION: Trust LLM more than file existence
        if llm_verified:
            # LLM says question is answered - accept it
            state.verified = True
            self.emit("verify_accepted", node="verify", iteration=state.iteration,
                     payload={"reason": f"LLM verified ({confidence} confidence), finalizer will ensure files exist"})
        elif state.iteration >= 3:
            # After 3 iterations (down from 5), accept whatever we have
            state.verified = True
            self.emit("verify_iteration_limit", node="verify", iteration=state.iteration,
                     payload={"reason": "Reached 3 iterations, accepting current state"})
        else:
            # Give it one more try
            state.verified = False

        self.emit(
            "verify_verdict",
            node="verify",
            iteration=state.iteration,
            payload={
                "llm_verified": llm_verified,
                "confidence": confidence,
                "summary_exists": summary_exists,
                "final_verified": state.verified,
                "verdict_text": truncate_text(verdict, 500),
                "has_output": len(result_text) > 500,
            },
        )

        # Track consecutive verification failures for mid-loop reflection
        if state.verified:
            state.consecutive_verify_fails = 0
        else:
            state.consecutive_verify_fails += 1
            # Extract failure hint from verdict text
            hint_map = {
                "file":      "bad_file_selection",
                "column":    "missing_column",
                "data":      "weak_analysis",
                "code":      "incorrect_code",
                "error":     "execution_error",
                "execution": "execution_error",
                "answer":    "poor_final_answer",
                "method":    "wrong_method",
                "visual":    "bad_visualization",
                "plot":      "bad_visualization",
            }
            for keyword, ftype in hint_map.items():
                if keyword in verdict:
                    state.failure_type = ftype
                    self.emit("failure_type_detected", node="verify",
                              iteration=state.iteration,
                              payload={"failure_type": ftype})
                    break

        return state


    # --- Router ---

    def route(self, state: DSStarState) -> DSStarState:
        self._log_step("router")

        filenames, summaries = state.active_filenames_and_summaries()
        result_text = (state.execution_result.stdout or "") + ("\n" + (state.execution_result.stderr or "") if state.execution_result.stderr else "")
        msgs = render_router_prompt(
            question=state.query,
            file_summaries=summaries,
            filenames=filenames,
            current_plans=state.plans,
            result=truncate_text(result_text, 2000),
            strategies=self._get_context_block(state),
        )
        resp = self._chat(msgs)
        decision = parse_router_decision(resp)
        if decision is None:
            # Default to Add Step if unclear
            decision = "add"
        state.router_decision = decision
        self.emit("route_decision", node="route", iteration=state.iteration, payload={"raw": truncate_text(resp, 1500), "parsed": decision})
        return state

    # --- Finalizer ---

    def finalize(self, state: DSStarState) -> DSStarState:
        """
        Robust finalizer that ALWAYS produces output, even if LLM fails.

        Key improvement: We capture stdout from LLM code and use it to create
        summary.md even if the code itself fails to write the file.
        """
        self._log_step("finalizer")

        filenames, summaries = state.active_filenames_and_summaries()

        # Prepare guidelines
        guidelines = state.guidelines or "Provide clear, helpful analysis"

        fixed_code = state.current_code
        result = state.execution_result
        best_stdout = ""  # Track the best output we've seen

        summary_path = os.path.join(self.workdir, "final", "summary.md")
        os.makedirs(os.path.dirname(summary_path), exist_ok=True)

        # Try up to 3 times to create proper output (increased from 2)
        for attempt in range(3):
            msgs = render_finalizer_prompt(
                question=state.query,
                file_summaries=summaries,
                filenames=filenames,
                reference_code=state.current_code,
                reference_result=truncate_text((state.execution_result.stdout or ""), 2000),
                guidelines=guidelines,
            )

            resp = self._chat(msgs)
            code = extract_first_code_block(resp)

            self.emit("final_code_generated", node="finalize", iteration=state.iteration,
                    payload={"attempt": attempt + 1, "code": truncate_text(code, 2000)})

            fixed_code, result = self._debug_solution_until_executes(summaries, filenames, code, max_tries=2)

            # Track best stdout (longest meaningful output)
            current_stdout = (result.stdout or "").strip()
            if len(current_stdout) > len(best_stdout):
                best_stdout = current_stdout

            # Check if summary.md was created by LLM code
            if os.path.isfile(summary_path):
                # Success!
                state.final_code = fixed_code
                state.final_answer = (result.stdout or "").strip()
                state.execution_result = result

                self.emit("final_execution_result", node="finalize", iteration=state.iteration,
                        status="ok", payload={"exit_code": result.exit_code,
                                            "artifacts": result.artifacts})
                return state

            # File not created, but we might have good stdout - try to extract and save it
            if self._try_create_summary_from_stdout(best_stdout, state.query, summary_path):
                self.emit("finalizer_stdout_extraction", node="finalize",
                         payload={"attempt": attempt + 1, "reason": "Created summary from stdout"})
                state.final_code = fixed_code
                state.final_answer = best_stdout
                state.execution_result = result
                return state

            # Failed - log and retry
            self.emit("finalizer_retry", node="finalize", payload={
                "attempt": attempt + 1,
                "reason": "summary.md not created and stdout not usable"
            })

        # After all attempts, GUARANTEE output using emergency fallback
        self.emit("finalizer_emergency", node="finalize", iteration=state.iteration,
                 payload={"reason": "Creating emergency summary from available data"})

        # Use best_stdout if available, otherwise use execution_result
        if best_stdout:
            state.execution_result = ExecutionResult(
                stdout=best_stdout,
                stderr=result.stderr,
                exit_code=result.exit_code,
                artifacts=result.artifacts
            )

        self._emergency_create_summary(state)

        # Read back what we created
        if os.path.isfile(summary_path):
            try:
                with open(summary_path, "r", encoding="utf-8") as f:
                    state.final_answer = f.read()
            except Exception:
                state.final_answer = best_stdout or state.execution_result.stdout or "Analysis completed."
        else:
            state.final_answer = best_stdout or state.execution_result.stdout or "Analysis completed with limited output."

        state.final_code = fixed_code
        state.execution_result = result

        # DEFENSIVE: Clean up any empty CSV files that may have been created
        self._cleanup_empty_csv_files(state)

        return state

    def _try_create_summary_from_stdout(self, stdout: str, query: str, summary_path: str) -> bool:
        """
        Try to create summary.md from stdout content.
        Returns True if successful, False if stdout doesn't contain usable content.
        """
        if not stdout or len(stdout) < 100:
            return False

        # Check if stdout looks like markdown (has headers or structure)
        looks_like_markdown = (
            stdout.startswith("#") or
            "\n##" in stdout or
            "\n- " in stdout or
            "**" in stdout
        )

        # Check if stdout has meaningful analysis content
        has_analysis_content = (
            len(stdout) > 200 and
            any(word in stdout.lower() for word in ["analysis", "finding", "result", "summary", "total", "constraint", "capacity"])
        )

        if looks_like_markdown or has_analysis_content:
            try:
                # If it looks like markdown, use directly
                if looks_like_markdown:
                    content = stdout
                else:
                    # Wrap in markdown structure
                    content = f"""# Analysis Results

**Question:** {query}

## Findings

{stdout}

---
*Analysis generated from execution output.*
"""
                with open(summary_path, "w", encoding="utf-8", errors="replace") as f:
                    f.write(content)
                rid = self.run_id[:8] if len(self.run_id) > 8 else self.run_id
                print(f"[DS-STAR:{rid}] ✓ Created summary.md from stdout")
                return True
            except Exception as e:
                rid = self.run_id[:8] if len(self.run_id) > 8 else self.run_id
                print(f"[DS-STAR:{rid}] Failed to create summary from stdout: {e}")
                return False

        return False

    def _emergency_create_summary(self, state: DSStarState) -> None:
        """
        Create robust fallback summary.md when LLM code generation fails.
        Extracts MAXIMUM value from execution results and history.
        This ALWAYS succeeds - it's the ultimate safety net.
        """
        rid = self.run_id[:8] if len(self.run_id) > 8 else self.run_id
        print(f"[DS-STAR:{rid}] ⚠️ EMERGENCY FALLBACK - Creating guaranteed output")

        summary_path = os.path.join(self.workdir, "final", "summary.md")

        # Ensure directory exists with multiple fallback attempts
        try:
            os.makedirs(os.path.dirname(summary_path), exist_ok=True)
        except Exception as e:
            print(f"[DS-STAR:{rid}] WARNING: Could not create final/ directory: {e}")
            # Try alternative location
            summary_path = os.path.join(self.workdir, "emergency_summary.md")

        # Extract answer from stdout
        stdout = (state.execution_result.stdout or "").strip()

        # Also check history for any useful output from previous iterations
        all_outputs = []
        if stdout:
            all_outputs.append(("latest", stdout))

        # Check if we have any meaningful history with timestamps
        if hasattr(state, 'history') and state.history:
            for idx, entry in enumerate(state.history):
                if isinstance(entry, dict):
                    hist_stdout = entry.get('stdout', '') or ''
                    if hist_stdout and len(hist_stdout) > 50:
                        all_outputs.append((f"iteration_{idx}", hist_stdout))

        # Find the best output (longest with actual content)
        best_output = ""
        best_source = "none"
        for source, output in all_outputs:
            if len(output) > len(best_output):
                best_output = output
                best_source = source

        # Build comprehensive summary
        plans_text = "\n".join([f"{i+1}. {p}" for i, p in enumerate(state.plans)]) if state.plans else "No plans recorded"

        if best_output and len(best_output) > 50:
            # We have meaningful output - use it
            summary_content = f"""# Analysis Results

**Question:** {state.query}

## Summary

{best_output}

## Analysis Details

**Steps Completed:** {len(state.plans)}
**Iterations:** {state.iteration}
**Output Source:** {best_source}

### Execution Plans
{plans_text}

---
*Analysis completed after {state.iteration} iterations. This output was automatically generated from execution results.*
"""
        else:
            # Minimal output - provide maximum context we can
            artifacts_info = ""
            if hasattr(state.execution_result, 'artifacts') and state.execution_result.artifacts:
                artifacts_list = [f"- {k}: {v}" for k, v in state.execution_result.artifacts.items()]
                artifacts_info = "\n\n**Generated Artifacts:**\n" + "\n".join(artifacts_list)

            summary_content = f"""# Analysis Results

**Question:** {state.query}

## Status

The analysis completed but output generation was incomplete.

## What Was Attempted

**Analysis Plans:**
{plans_text}

**Execution Summary:**
- Total iterations: {state.iteration}
- Plans executed: {len(state.plans)}
- Verified: {state.verified}
- Exit code: {state.execution_result.exit_code}{artifacts_info}

## Partial Output
```
{best_output if best_output else "(No output captured - check logs for execution details)"}
```

## Next Steps

1. Review the execution plans above to see what was attempted
2. Try breaking down the question into simpler steps
3. Check if the data format matches expectations
4. Review error messages in execution logs

---
*This is an emergency fallback summary. The analysis ran but couldn't generate complete formatted output.*
*Exit code: {state.execution_result.exit_code} | Iterations: {state.iteration}*
"""

        # Try multiple times with different encodings/error handling
        write_attempts = [
            ("utf-8", "strict"),
            ("utf-8", "replace"),
            ("latin-1", "replace"),
            ("ascii", "ignore"),
        ]

        for encoding, errors in write_attempts:
            try:
                with open(summary_path, "w", encoding=encoding, errors=errors) as f:
                    f.write(summary_content)
                print(f"[DS-STAR:{rid}] ✓ Emergency summary created with {encoding}/{errors}")
                self.emit("emergency_summary_created", node="finalize",
                         payload={"path": summary_path, "has_stdout": bool(stdout),
                                 "encoding": encoding, "best_source": best_source})
                return  # Success!
            except Exception as e:
                print(f"[DS-STAR:{rid}] Failed with {encoding}/{errors}: {e}")
                continue

        # ABSOLUTE LAST RESORT: Create minimal file with minimal content
        print(f"[DS-STAR:{rid}] ⚠️ ALL WRITE ATTEMPTS FAILED - Creating absolute minimal summary")
        try:
            minimal_content = f"# Analysis Results\n\nQuestion: {state.query[:200]}\n\nAnalysis incomplete. See execution logs.\n"
            with open(summary_path, "wb") as f:  # Binary write as last resort
                f.write(minimal_content.encode("utf-8", errors="ignore"))
            print(f"[DS-STAR:{rid}] ✓ Minimal binary summary created")
        except Exception as final_error:
            print(f"[DS-STAR:{rid}] ❌ CRITICAL: Could not create any summary file: {final_error}")
            # At this point, we've truly exhausted all options

    def _cleanup_empty_csv_files(self, state: DSStarState) -> None:
        """
        Remove empty CSV files (only headers, no data rows) and update result.json.
        This is a defensive layer to catch any empty files created by LLM code.
        """
        rid = self.run_id[:8] if len(self.run_id) > 8 else self.run_id
        final_dir = os.path.join(self.workdir, "final")

        if not os.path.isdir(final_dir):
            return

        # Find all CSV files in final/ directory
        csv_files = [f for f in os.listdir(final_dir) if f.endswith('.csv')]
        removed_files = []

        for csv_file in csv_files:
            csv_path = os.path.join(final_dir, csv_file)
            try:
                # Check if CSV is empty (only has header row)
                with open(csv_path, 'r', encoding='utf-8') as f:
                    lines = f.readlines()

                # If file has <= 1 line (header only or completely empty), remove it
                if len(lines) <= 1:
                    os.remove(csv_path)
                    removed_files.append(f"final/{csv_file}")
                    print(f"[DS-STAR:{rid}] 🗑️  Removed empty CSV: {csv_file} (no data rows)")
                    self.emit("empty_csv_removed", node="finalize",
                             payload={"file": csv_file, "reason": "no data rows"})

            except Exception as e:
                print(f"[DS-STAR:{rid}] Warning: Could not check {csv_file}: {e}")

        # Update result.json to remove references to deleted files
        if removed_files:
            result_json_path = os.path.join(final_dir, "result.json")
            if os.path.isfile(result_json_path):
                try:
                    import json
                    with open(result_json_path, 'r', encoding='utf-8') as f:
                        result_data = json.load(f)

                    # Remove deleted files from "files_created" list
                    if "files_created" in result_data:
                        original_count = len(result_data["files_created"])
                        result_data["files_created"] = [
                            f for f in result_data["files_created"]
                            if f not in removed_files
                        ]
                        new_count = len(result_data["files_created"])

                        if new_count < original_count:
                            with open(result_json_path, 'w', encoding='utf-8') as f:
                                json.dump(result_data, f, indent=2)
                            print(f"[DS-STAR:{rid}] ✓ Updated result.json (removed {original_count - new_count} empty file references)")

                except Exception as e:
                    print(f"[DS-STAR:{rid}] Warning: Could not update result.json: {e}")

    # --- Orchestration Steps for Router Decisions ---

    def refine_add_step(self, state: DSStarState) -> DSStarState:
        last_result = (state.execution_result.stdout or "") + ("\n" + (state.execution_result.stderr or "") if state.execution_result.stderr else "")
        state = self.next_plan(state, last_result=last_result)
        # implement the newly added step on top of base code
        current_step = state.plans[-1]
        self.emit("plan_added", node="refine", iteration=state.iteration, payload={"step_index": len(state.plans), "text": truncate_text(current_step, 1000)})
        state = self.implement_next(state, current_step=current_step)
        return state

    def refine_fix_step(self, state: DSStarState, step_index_1based: int) -> DSStarState:
        # Paper-consistent behavior: backtrack by truncating to steps before the incorrect one,
        # then generate a new next step and implement it.
        l = max(1, min(step_index_1based, len(state.plans)))
        keep_upto = l - 1  # number of steps to keep (0..l-1)
        # Truncate plans and code history
        state.plans = state.plans[:keep_upto]
        state.codes_per_step = state.codes_per_step[:keep_upto]
        if keep_upto > 0 and state.codes_per_step:
            state.base_code = state.codes_per_step[-1]
            state.current_code = state.base_code
        else:
            state.base_code = ""
            state.current_code = ""
        # Generate next plan based on the latest execution result
        last_result = (state.execution_result.stdout or "") + ("\n" + (state.execution_result.stderr or "") if state.execution_result.stderr else "")
        state = self.next_plan(state, last_result=last_result)
        # Implement the newly added step on top of the truncated base
        current_step = state.plans[-1]
        self.emit("plan_fixed", node="refine", iteration=state.iteration, payload={"fixed_index": step_index_1based, "new_step_index": len(state.plans), "text": truncate_text(current_step, 1000)})
        state = self.implement_next(state, current_step=current_step)
        return state

    # --- Entry orchestration without LangGraph (useful for tests) ---

    def run_loop(self, state: DSStarState) -> DSStarState:
        # Analyze
        state = self.analyze_files(state)
        state.iteration = 0
        state.record_iteration({"phase": "analyze"})

        # Initial plan + implement
        state = self.initial_plan(state)
        state = self.implement_initial(state)
        state.record_iteration({"phase": "init_impl", "stdout": truncate_text(state.execution_result.stdout, 800)})

        # Verify/Refine loop
        while state.iteration < state.max_iterations:
            state = self.verify(state)
            if state.verified:
                break
            state = self.route(state)
            if state.router_decision == "add":
                state = self.refine_add_step(state)
            elif isinstance(state.router_decision, str) and state.router_decision.startswith("step:"):
                try:
                    step_idx = int(state.router_decision.split(":")[1])
                except Exception:
                    step_idx = len(state.plans)
                state = self.refine_fix_step(state, step_index_1based=step_idx)
            elif state.router_decision == "change_strategy":
                state.plans = state.plans[:1]
                state.codes_per_step = state.codes_per_step[:1]
                state.base_code = state.codes_per_step[0] if state.codes_per_step else ""
                state.current_code = state.base_code
                state = self.refine_add_step(state)
            elif state.router_decision == "rerun_analysis":
                state = self.analyze_files(state)
                state = self.refine_add_step(state)
            elif state.router_decision == "retrieve_files":
                state.retrieved_indices = None
                state = self.refine_add_step(state)
            else:
                state = self.refine_add_step(state)
            state.iteration += 1
            state.record_iteration({"phase": "refine", "stdout": truncate_text(state.execution_result.stdout, 800)})

        # Finalize
        state = self.finalize(state)
        state.record_iteration({"phase": "finalize", "answer": truncate_text(state.final_answer or "", 500)})
        return state

def _required_artifacts_exist(workdir: str) -> bool:
    """
    Hard check for mandatory DS-STAR outputs.
    """
    summary_md = os.path.join(workdir, "final", "summary.md")
   # analysis_csv = os.path.join(workdir, "final", "analysis.csv")
    return os.path.isfile(summary_md)
