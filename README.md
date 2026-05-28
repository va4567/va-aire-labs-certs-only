# va-aire-labs-certs-only

**Cluster:** k3d `abox` · k3s v1.31.x · GitHub Codespace `va4567/va-aire-labs-certs-only`
**Stack:** agentgateway v1.2.1 · kagent v0.9.4 · Flux · FastMCP · A2A (FastAPI)

---

## Lab 0 — Cluster Setup

- k3d cluster `abox` (1 server + 1 agent node) with Gateway API CRDs
- Deployed via OCI Helm charts: `agentgateway`, `kagent-crds` + `kagent`, `flux install`
- Namespaces: `agentgateway-system`, `agentgateway`, `kagent`, `flux-system`
- Configured: `AgentgatewayBackend` (OpenAI gpt-4o-mini) + `HTTPRoute` routing all traffic via Gateway API
- Secrets: `openai-secret` (agentgateway-system), `llm-credentials` (agentgateway), `kagent-openai` (kagent) — all from Codespace secret `$LLM_API_KEY`

---

## Lab 2 — LLM Model + MCP Server + Declarative Agent

**Branch:** `LAB-2-cert`

| Resource | File | Details |
|---|---|---|
| `ModelConfig` | `infrastructure/kagent/model-configs/default-llm.yaml` | kagent.dev/v1alpha2, OpenAI gpt-4o-mini, secret: kagent-openai |
| `ConfigMap` + `Deployment` + `Service` | `infrastructure/kagent/tools/mcp-server.yaml` | FastMCP server, python:3.11-slim + initContainer, 4 tools |
| `RemoteMCPServer` | `infrastructure/kagent/tools/mcp-tool.yaml` | STREAMABLE_HTTP, timeout 30s, sseReadTimeout 5m, 4 tools auto-discovered |
| `Agent` | `infrastructure/kagent/agents/my-agent.yaml` | Declarative, python runtime, stream: true, 4 McpServer tool refs |

**MCP tools:** `get_current_time`, `roll_dice`, `calculate`, `cluster_info`

**Verified:** `kubectl get remotemcpserver cert-mcp-server -n kagent -o jsonpath='{.status.discoveredTools[*].name}'` returns all 4 tools. Agent `READY: True`, `ACCEPTED: True`. Kagent UI chat confirms tool calls are executed.

---

## Lab 4 — A2A Agent · Inventory · MCPG · qdrant

**Branch:** `LAB-4-cert`

### Task 1 — A2A Spec Research
Summary in `docs/research/a2a-conscept.md`. Key concepts: Agent Card at `/.well-known/agent.json`, task lifecycle (`POST /tasks` → artifact), skill declaration with input/output modes.

### Task 2 — A2A Agent Implementation
- **Framework:** FastAPI + uvicorn (`agents/a2a/src/main.py`)
- **Endpoints:** `GET /.well-known/agent.json` (Agent Card), `POST /tasks` (returns artifact), `GET /health` (readiness)
- **Image:** `ghcr.io/va4567/a2a-agent:v1` — built from `agents/a2a/Dockerfile`, pushed to GHCR (PAT with `write:packages`), made public for cluster pull
- **Deployment:** `agents/a2a/k8s/deployment.yaml` in `kagent` namespace, `AGENT_URL` env var, readinessProbe on `/health`
- **Verified:** `curl /.well-known/agent.json` returns valid JSON; `POST /tasks` returns completed artifact with `status.state: completed`

### Task 3 — Inventory
Snapshot of all AI resources in the cluster saved to `docs/research/ai-resources-snapshot.txt`:
```
kubectl get agents,remotemcpservers,modelconfigs -A
```
**Live counts:** 11 agents (9 Helm-managed + `my-agent` + `cert-lab-k8s-agent`), 3 RemoteMCPServers (`cert-mcp-server`, `kagent-grafana-mcp`, `kagent-tool-server`), 2 ModelConfigs (`default-llm` gpt-4o-mini, `default-model-config` gpt-4.1-mini)

### Task 4 — MCPG (MCP Gateway)
- **Implementation:** FastMCP `Client`-based proxy — `mcpg-code` ConfigMap + `python:3.11-slim` Deployment + Service in `kagent` namespace
- **Pattern:** ConfigMap + initContainer (`pip install fastmcp`), no image build required
- **Upstream:** proxies `cert-mcp-server` via `http://mcp-server.kagent.svc.cluster.local:8080/mcp`
- **Tools exposed:** `get_current_time`, `roll_dice`, `list_aggregated_servers`
- **Deployment:** revision 5, 1/1 Running; verified via two-step FastMCP session protocol (POST `initialize` → `mcp-session-id` → POST `tools/list`)

### Task 5 — qdrant
- Deployed via `qdrant/qdrant-helm` Helm chart in dedicated namespace
- Verified: `curl /healthz` returns HTTP 200

---

## Lab 7 — Vin's 15 Questions

**Branch:** `LAB-7-cert`

**Method:** ran `kubectl explain`, `kubectl get crd`, `kubectl get agents/remotemcpservers/modelconfigs -A --show-labels`, deployment YAML inspection against the running cluster. 
**Topics covered:** agent timeout/stuck handling, circuit breakers, model failover, provider response normalization, agent versioning, blue/green deployment, FastMCP architecture, FinOps controls, vLLM prefix caching, llm-d session-aware scheduling.

---

## Done Criteria Status

| Lab | Criterion | Status |
|---|---|---|
| Lab 0 | `kubectl get pods -n agentgateway-system` all Running | ✓ |
| Lab 0 | `kubectl get pods -n kagent` all Running | ✓ |
| Lab 0 | `flux check` all controllers ready | ✓ |
| Lab 2 | `kubectl get agent -n kagent` shows `my-agent` READY | ✓ |
| Lab 2 | Kagent UI chat returns MCP tool response | ✓ |
| Lab 4 | `curl /.well-known/agent.json` returns valid Agent Card JSON | ✓ |
| Lab 4 | qdrant `/healthz` returns 200 | ✓ |
| Lab 7 | All 15 questions answered, ≥5 with code/YAML snippets | ✓ |
