# AgentField Dev Environment Setup

Docker-based development workflow that bypasses corporate proxy restrictions for Go module downloads.

**How it works:** Build a Docker image with all dependencies on the personal laptop (unrestricted internet), push to Docker Hub, pull on the office laptop, and develop using bind mounts.

---

## Prerequisites

| Machine | Required Software |
|---------|-------------------|
| Personal laptop | Git, Go 1.25+, Docker (native Linux) |
| Office laptop | Git, Docker Desktop with WSL2 |

---

## PERSONAL LAPTOP (unrestricted internet)

Run these commands once during initial setup, and again whenever dependencies change (go.mod, pyproject.toml, package.json updates).

### Step 1: Clone and branch

```bash
# Clone the repo (skip if already cloned)
git clone <your-repo-url> agentfield_poc
cd agentfield_poc

# Create a dedicated dev branch for vendored dependencies
git checkout -b dev/docker-dev
```

### Step 2: Vendor all Go modules

This downloads every Go dependency and stores it locally in `vendor/` directories. These travel with git, so the office laptop never needs to download them.

```bash
(cd sdk/go && go mod vendor)
(cd control-plane && go mod vendor)
(cd examples/go_agent_nodes && go mod vendor)
(cd examples/go_harness_demo && go mod vendor)
(cd examples/benchmarks/100k-scale/go-bench && go mod vendor)
(cd tests/functional/go_agents && go mod vendor)
```

### Step 3: Validate the vendor directories work

```bash
(cd control-plane && go build -mod=vendor -tags "sqlite_fts5" ./...)
(cd sdk/go && go build -mod=vendor ./...)
```

Both commands should complete with no errors and no network calls.

### Step 4: Commit vendored dependencies

```bash
git add -A
git commit -m "chore: vendor Go modules for offline dev"
```

### Step 5: Build the Docker dev image

```bash
docker build -f deployments/docker/Dockerfile.dev -t agentfield-dev:latest .
```

This takes 5-15 minutes on first build (downloads Go tools, Python packages, Node packages). Subsequent rebuilds are fast due to Docker layer caching.

### Step 6: Smoke test the image

```bash
docker run --rm agentfield-dev:latest bash -c \
  "go version && python3 --version && node --version && pnpm --version"
```

Expected output (versions may vary):
```
go1.25
Python 3.11.x
v20.x.x
9.x.x
```

### Step 7: Push image to Docker Hub

Replace `yourusername` with your Docker Hub username.

```bash
# Tag with both latest and date stamp for rollback
docker tag agentfield-dev:latest yourusername/agentfield-dev:latest
docker tag agentfield-dev:latest yourusername/agentfield-dev:$(date +%Y%m%d)

# Push both tags
docker push yourusername/agentfield-dev:latest
docker push yourusername/agentfield-dev:$(date +%Y%m%d)
```

### Step 8: Push the branch to GitHub

```bash
git push origin dev/docker-dev
```

### Done (personal laptop)

The image is on Docker Hub. The vendored branch is on GitHub. Switch to the office laptop.

---

## OFFICE LAPTOP (corporate proxy, has Claude Code)

### First-time setup

Run these once.

#### 1. Pull the Docker image

```bash
docker pull yourusername/agentfield-dev:latest
```

#### 2. Update docker-compose.dev.yml with your Docker Hub username

Open `deployments/docker/docker-compose.dev.yml` and replace `agentfield-dev:latest` with `yourusername/agentfield-dev:latest` on the `image:` line.

#### 3. Switch to the dev branch with vendored dependencies

```bash
cd C:\charan\research\agentfield_poc
git checkout dev/docker-dev
git pull origin dev/docker-dev
```

#### 4. Start the dev environment

```bash
docker compose -f deployments/docker/docker-compose.dev.yml up -d
```

This starts two containers:
- `agentfield-dev` -- your development shell (Go + Python + Node + all deps)
- `agentfield-dev-postgres` -- PostgreSQL 16 with pgvector

Wait for both to be healthy:

```bash
docker compose -f deployments/docker/docker-compose.dev.yml ps
```

#### 5. Enter the dev container

```bash
docker compose -f deployments/docker/docker-compose.dev.yml exec dev bash
```

You are now inside the container at `/workspace` (your repo, bind-mounted).

---

### Daily workflow

#### Start the environment (if stopped)

```bash
docker compose -f deployments/docker/docker-compose.dev.yml start
```

#### Enter the container

```bash
docker compose -f deployments/docker/docker-compose.dev.yml exec dev bash
```

#### Build the control plane

```bash
cd /workspace/control-plane
go build -tags "sqlite_fts5" ./...
```

#### Run Go tests

```bash
cd /workspace/control-plane
go test ./internal/services/... -count=1

cd /workspace/sdk/go
go test ./...
```

#### Run the control plane server (local mode, SQLite)

```bash
cd /workspace/control-plane
go run -tags "sqlite_fts5" ./cmd/af dev
```

Server starts at http://localhost:8080 (accessible from your host browser).

#### Run the web UI dev server (separate terminal)

Open a second terminal on the host:

```bash
docker compose -f deployments/docker/docker-compose.dev.yml exec dev bash
```

Inside the container:

```bash
cd /workspace/control-plane/web/client
pnpm run dev --host 0.0.0.0
```

UI dev server at http://localhost:5173 (hot-reloads on file changes).

#### Run Python SDK tests

```bash
cd /workspace/sdk/python
pytest
```

#### Edit source code

Edit files normally on the host using **VS Code + Claude Code**. Changes are instantly visible inside the container via the bind mount. No copy or sync step needed.

#### Git operations

Run git commands on the **host** (not inside the container):

```bash
git add -A
git commit -m "feat: your change"
git push origin dev/docker-dev
```

---

### Stop and restart

```bash
# Stop containers (preserves all volumes and state)
docker compose -f deployments/docker/docker-compose.dev.yml stop

# Start again later
docker compose -f deployments/docker/docker-compose.dev.yml start

# Full teardown (keeps named volumes)
docker compose -f deployments/docker/docker-compose.dev.yml down

# DANGER: Full teardown AND delete volumes (Go cache, node_modules, postgres data)
docker compose -f deployments/docker/docker-compose.dev.yml down -v
```

---

## Updating dependencies

When `go.mod`, `pyproject.toml`, or `package.json` changes on main:

### On personal laptop

```bash
cd agentfield_poc
git checkout dev/docker-dev
git merge main

# Re-vendor Go modules
(cd sdk/go && go mod vendor)
(cd control-plane && go mod vendor)
(cd examples/go_agent_nodes && go mod vendor)
(cd examples/go_harness_demo && go mod vendor)
(cd examples/benchmarks/100k-scale/go-bench && go mod vendor)
(cd tests/functional/go_agents && go mod vendor)

# Rebuild and push image (only needed if Python/Node deps changed)
docker build -f deployments/docker/Dockerfile.dev -t agentfield-dev:latest .
docker tag agentfield-dev:latest yourusername/agentfield-dev:latest
docker push yourusername/agentfield-dev:latest

# Push updated branch
git add -A
git commit -m "chore: update vendored dependencies"
git push origin dev/docker-dev
```

### On office laptop

```bash
# Pull updated vendor directories
git pull origin dev/docker-dev

# Pull updated image (only if Python/Node deps changed)
docker pull yourusername/agentfield-dev:latest

# Recreate containers with new image
docker compose -f deployments/docker/docker-compose.dev.yml up -d
```

---

## Ports reference

| Port | Service | URL |
|------|---------|-----|
| 8080 | Control plane API + UI | http://localhost:8080 |
| 5173 | Vite dev server (web UI) | http://localhost:5173 |
| 5433 | PostgreSQL | `postgres://agentfield:agentfield@localhost:5433/agentfield` |
| 8001 | Agent port | http://localhost:8001 |

---

## Troubleshooting

**"go: module lookup disabled by GOPROXY=off"**
This means `GOFLAGS=-mod=vendor` is set but the vendor/ directory is missing for that module. Pull the latest `dev/docker-dev` branch to get vendor/ directories.

**Vite dev server not accessible from host browser**
Make sure to pass `--host 0.0.0.0`: `pnpm run dev --host 0.0.0.0`

**Permission errors on bind-mounted files**
Docker Desktop WSL2 usually handles this transparently. If not, add `user: "1000:1000"` under the `dev` service in `docker-compose.dev.yml`.

**node_modules empty after container recreation**
The entrypoint script auto-populates from cache on first start. If it fails, run manually inside the container:
```bash
cd /workspace/control-plane/web/client && pnpm install --frozen-lockfile
cd /workspace/sdk/typescript && npm ci
```

**Slow first Go build**
Expected -- WSL2 bind mounts from Windows are slower than native Linux. The Go build cache (named volume) makes subsequent builds fast. First build may take 2-3 minutes; incremental builds take seconds.
