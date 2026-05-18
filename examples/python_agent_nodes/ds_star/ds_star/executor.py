import os
import sys
import subprocess
import tempfile
import shutil
import time
from typing import Tuple, Dict, Any, Optional, List
from .state import ExecutionResult


def _collect_final_artifacts(workdir: str, final_dir: str = "final", since_timestamp: Optional[float] = None) -> Dict[str, Any]:
    """
    Collects paths of files produced under final/. Returns a dict of artifact_name -> path.
    If since_timestamp is provided, uses lenient timestamp check (allows 5 second buffer).
    """
    artifacts: Dict[str, Any] = {}
    final_path = os.path.join(workdir, final_dir)

    if not os.path.isdir(final_path):
        return artifacts

    for root, _, files in os.walk(final_path):
        for f in files:
            full_path = os.path.join(root, f)
            try:
                # LENIENT timestamp check: allow 5 second buffer before script start
                # This handles clock skew and file system latency
                if since_timestamp is not None:
                    mtime = os.path.getmtime(full_path)
                    if mtime < (since_timestamp - 5.0):
                        continue

                rel_path = os.path.relpath(full_path, workdir)
                # Normalize path separators for cross-platform compatibility
                rel_path = rel_path.replace("\\", "/")

                artifacts[rel_path] = {
                    "path": rel_path,
                    "size": os.path.getsize(full_path),
                    "mtime": os.path.getmtime(full_path)
                }
            except Exception as e:
                # Log but skip files we cannot stat
                print(f"[DS-STAR-DEBUG] Could not collect artifact {full_path}: {e}")
                continue

    return artifacts



def run_python_code(
    code: str,
    workdir: Optional[str] = None,
    timeout_sec: int = 120,
    python_exe: Optional[str] = None,
    env: Optional[Dict[str, str]] = None,
) -> ExecutionResult:
    """
    Executes the provided Python code in a temporary file within workdir.
    Captures stdout/stderr/exit code and collects final/ artifacts.
    On Windows, uses the default 'python' in PATH unless python_exe is provided.

    Note:
    - Code is expected to read inputs from 'data/' and write outputs to 'final/' per DS-STAR paper.
    - No network access is enforced by environment setup (caller responsibility).
    """
    workdir = workdir or os.getcwd()
    os.makedirs(workdir, exist_ok=True)

    tmp_dir = tempfile.mkdtemp(prefix="dsstar_", dir=workdir)
    script_path = os.path.join(tmp_dir, "run.py")

    with open(script_path, "w", encoding="utf-8") as f:
        f.write(code)

    # Choose python executable
    python_exe = python_exe or "python"

    # Prepare subprocess environment
    proc_env = os.environ.copy()
    proc_env["MPLBACKEND"] = "Agg"
    if env:
        proc_env.update(env)

    # Ensure final directory exists to collect artifacts (code may also create it)
    final_dir = os.path.join(workdir, "final")
    os.makedirs(final_dir, exist_ok=True)

    # Run the script
    try:
        start = time.time()
        proc = subprocess.run(
            [python_exe, "-u", script_path],
            cwd=workdir,
            capture_output=True,
            text=True,
            timeout=timeout_sec,
            env=proc_env,
        )
        duration = time.time() - start
        stdout = proc.stdout or ""
        stderr = proc.stderr or ""
        exit_code = proc.returncode
    except subprocess.TimeoutExpired as e:
        stdout = e.stdout or ""
        stderr = (e.stderr or "") + f"\n[TimeoutExpired] Execution exceeded {timeout_sec} seconds."
        exit_code = -1
    except Exception as e:
        stdout = ""
        stderr = f"[ExecutorError] {type(e).__name__}: {e}"
        exit_code = -2

    artifacts = _collect_final_artifacts(workdir, since_timestamp=start)

    # --- IMPROVED ARTIFACT VERIFICATION ---
    summary_exists = any(k.endswith("summary.md") for k in artifacts.keys())

    if not summary_exists:
        # Do one more check directly in case artifact collection missed it
        direct_check_path = os.path.join(workdir, "final", "summary.md")
        if os.path.isfile(direct_check_path):
            rel_path = "final/summary.md"
            artifacts[rel_path] = {
                "path": rel_path,
                "size": os.path.getsize(direct_check_path),
                "mtime": os.path.getmtime(direct_check_path)
            }
            summary_exists = True

    # Only log when summary.md is collected (finalize step)
    if summary_exists:
        print(f"[DS-STAR] ✓ Final artifacts: {list(artifacts.keys())}")

    # Cleanup temp directory
    try:
        shutil.rmtree(tmp_dir, ignore_errors=True)
    except Exception:
        # Non-critical
        pass

    return ExecutionResult(stdout=stdout, stderr=stderr, exit_code=exit_code, artifacts=artifacts)
