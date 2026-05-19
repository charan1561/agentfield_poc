"""DS_star Data Science Multi-Agent System integrated with AgentField."""

from __future__ import annotations

import os
import sys
from pathlib import Path

from fastapi import UploadFile, File
from fastapi.responses import JSONResponse
from agentfield import AIConfig, Agent

if __package__ in (None, ""):
    current_dir = Path(__file__).resolve().parent
    if str(current_dir) not in sys.path:
        sys.path.insert(0, str(current_dir))

from routers import (
    analysis_router,
    planning_router,
    coding_router,
    verification_router,
    orchestration_router,
    meta_router,
)

app = Agent(
    node_id="ds-star",
    agentfield_server=os.getenv("AGENTFIELD_SERVER", "http://localhost:8080"),
    ai_config=AIConfig(
        model=os.getenv("AI_MODEL", "azure/gpt-5-chat"),
    ),
)

app.include_router(analysis_router)
app.include_router(planning_router)
app.include_router(coding_router)
app.include_router(verification_router)
app.include_router(orchestration_router)
app.include_router(meta_router)


@app.server.post("/upload")
async def upload_data_file(file: UploadFile = File(...)):
    workdir = os.getenv("DS_STAR_WORKDIR", "/tmp/ds_star")
    data_dir = os.path.join(workdir, "data")
    os.makedirs(data_dir, exist_ok=True)
    dest = os.path.join(data_dir, file.filename)
    content = await file.read()
    with open(dest, "wb") as f:
        f.write(content)
    return JSONResponse({"filename": file.filename, "size": len(content)})


@app.server.get("/files")
async def list_data_files():
    workdir = os.getenv("DS_STAR_WORKDIR", "/tmp/ds_star")
    data_dir = os.path.join(workdir, "data")
    if not os.path.isdir(data_dir):
        return JSONResponse({"files": []})
    files = []
    for name in os.listdir(data_dir):
        full = os.path.join(data_dir, name)
        if os.path.isfile(full):
            files.append({"name": name, "size": os.path.getsize(full)})
    return JSONResponse({"files": files})


if __name__ == "__main__":
    print("DS_star Data Science Agent")
    print(f"  Node ID: ds-star")
    print(f"  Control Plane: {app.agentfield_server}")
    print(f"  Workdir: {os.getenv('DS_STAR_WORKDIR', '/tmp/ds_star')}")
    print()
    print("Routers:")
    print("  analysis/     - File analysis and description")
    print("  planning/     - Step-by-step analysis planning")
    print("  coding/       - Python code generation and execution")
    print("  verification/ - Result verification and routing")
    print("  orchestration/ - Full pipeline and finalization")
    print("  meta/         - Cross-run learning and strategy retrieval")

    port_env = os.getenv("PORT")
    if port_env is None:
        app.run(auto_port=True, host="0.0.0.0")
    else:
        app.run(port=int(port_env), host="0.0.0.0")
