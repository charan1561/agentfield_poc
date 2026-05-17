#!/bin/bash
set -e

echo "=== AgentField Dev Container ==="

# Populate web client node_modules from image cache if the volume is empty
if [ -d /workspace/control-plane/web/client ] && \
   [ ! -d /workspace/control-plane/web/client/node_modules/.pnpm ]; then
    echo "[init] Populating web client node_modules from cache..."
    cp -r /tmp/nodecache/web-client/node_modules /workspace/control-plane/web/client/ 2>/dev/null || true
fi

# Populate TS SDK node_modules from image cache if the volume is empty
if [ -d /workspace/sdk/typescript ] && \
   [ ! -d /workspace/sdk/typescript/node_modules/.package-lock.json ]; then
    echo "[init] Populating TS SDK node_modules from cache..."
    cp -r /tmp/nodecache/ts-sdk/node_modules /workspace/sdk/typescript/ 2>/dev/null || true
fi

# Re-install Python SDK in editable mode (fast no-op if already installed)
if [ -d /workspace/sdk/python ]; then
    pip install --break-system-packages -e /workspace/sdk/python --quiet 2>/dev/null || true
fi

echo "[ready] Go $(go version | awk '{print $3}') | $(python3 --version 2>&1) | Node $(node --version) | pnpm $(pnpm --version)"
echo "[ready] GOFLAGS=${GOFLAGS}"
echo "[ready] Working directory: $(pwd)"

exec "$@"
