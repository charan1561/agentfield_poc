#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/../../.." && pwd)"
CP_DIR="${REPO_ROOT}/control-plane"
BUILD_DIR="${TMPDIR:-/tmp}/agentfield-ds-star"

CP_PORT="${AGENTFIELD_PORT:-8080}"
AGENT_PORT="${PORT:-8001}"

CP_PID=""
AGENT_PID=""

cleanup() {
  echo ""
  echo "[run] Shutting down..."
  [[ -n "$AGENT_PID" ]] && kill "$AGENT_PID" 2>/dev/null
  [[ -n "$CP_PID" ]] && kill "$CP_PID" 2>/dev/null
  wait 2>/dev/null
  echo "[run] Stopped."
}
trap cleanup EXIT INT TERM

# --- load .env ---
if [[ -f "${SCRIPT_DIR}/.env" ]]; then
  set -a
  source "${SCRIPT_DIR}/.env"
  set +a
fi

# --- port check ---
port_in_use() {
  if command -v ss >/dev/null 2>&1; then
    ss -tlnp 2>/dev/null | grep -q ":$1 "
  elif command -v lsof >/dev/null 2>&1; then
    lsof -iTCP:"$1" -sTCP:LISTEN >/dev/null 2>&1
  else
    return 1
  fi
}

if port_in_use "$CP_PORT"; then
  echo "[run] ERROR: Port $CP_PORT already in use (control plane). Stop the existing process first."
  exit 1
fi
if port_in_use "$AGENT_PORT"; then
  echo "[run] ERROR: Port $AGENT_PORT already in use (ds-star agent). Stop the existing process first."
  exit 1
fi

# --- ensure workdir ---
DS_STAR_WORKDIR="${DS_STAR_WORKDIR:-/tmp/ds_star}"
mkdir -p "${DS_STAR_WORKDIR}/data" "${DS_STAR_WORKDIR}/final"

# --- build UI if needed ---
UI_DIR="${CP_DIR}/web/client"
if [[ ! -f "${UI_DIR}/dist/index.html" ]]; then
  echo "[build] Building UI (first time only)..."
  (cd "${UI_DIR}" && npm install --silent && npm run build)
fi

# --- build control plane ---
mkdir -p "${BUILD_DIR}"
echo "[build] Compiling control plane..."
(cd "${CP_DIR}" && go build -tags "embedded sqlite_fts5" -o "${BUILD_DIR}/agentfield-server" ./cmd/agentfield-server)
echo "[build] Done."

# --- start control plane ---
echo "[cp] Starting on port ${CP_PORT}..."
"${BUILD_DIR}/agentfield-server" server --port "${CP_PORT}" 2>&1 | sed -u 's/^/[cp] /' &
CP_PID=$!

# --- health check ---
echo "[cp] Waiting for health..."
for i in $(seq 1 60); do
  if curl -sf --max-time 2 "http://127.0.0.1:${CP_PORT}/api/v1/health" >/dev/null 2>&1; then
    echo "[cp] Healthy."
    break
  fi
  if ! kill -0 "$CP_PID" 2>/dev/null; then
    echo "[cp] ERROR: Control plane exited unexpectedly."
    exit 1
  fi
  sleep 1
done
if ! curl -sf --max-time 2 "http://127.0.0.1:${CP_PORT}/api/v1/health" >/dev/null 2>&1; then
  echo "[cp] ERROR: Control plane did not become healthy in 60s."
  exit 1
fi

# --- start ds-star agent ---
echo "[ds] Starting DS_star agent on port ${AGENT_PORT}..."
(cd "${SCRIPT_DIR}" && python main.py) 2>&1 | sed -u 's/^/[ds] /' &
AGENT_PID=$!

# --- wait for registration ---
echo "[ds] Waiting for agent registration..."
for i in $(seq 1 15); do
  if curl -sf --max-time 2 "http://127.0.0.1:${CP_PORT}/api/v1/agents/ds-star" >/dev/null 2>&1; then
    echo "[ds] Registered."
    break
  fi
  sleep 1
done

# --- ready ---
echo ""
echo "========================================="
echo "  AgentField + DS_star ready"
echo "  UI:   http://localhost:${CP_PORT}/ui/"
echo "  Stop: Ctrl+C"
echo ""
echo "  Test:"
echo "  curl -X POST http://localhost:${CP_PORT}/api/v1/reasoners/ds-star.orchestration_run_pipeline \\"
echo "    -H 'Content-Type: application/json' \\"
echo "    -d '{\"input\": {\"query\": \"Describe the data\", \"data_files\": [\"FIFA2018Statistics.csv\"], \"max_iterations\": 3}}'"
echo "========================================="
echo ""

wait
