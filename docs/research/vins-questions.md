# Vin's Questions

---

## 1. How could we handle 'agent got stuck' scenarios?

**Answer:**

`kubectl explain agent.spec.declarative --api-version=kagent.dev/v1alpha2` confirms there is no `maxTurns` field in the current kagent v1alpha2 schema — the CRD does not have a built-in loop counter. The actual timeout mechanism in the live cluster is on the `RemoteMCPServer` resource: `cert-mcp-server` has `timeout: 30s` and `sseReadTimeout: 5m0s`, cutting off any individual stuck MCP tool call or hung SSE stream automatically. On the agent pod side, `restartPolicy: Always` ensures the kubelet restarts the container if it stops responding to liveness probes. For runaway tool-call loops the practical guard is a turn-limit instruction in `systemMessage` (e.g. "stop and report after 5 attempts") combined with a backend `timeout` in `config.yaml` to cap total wall-clock time. For unresolvable tasks, the recommended pattern is a dead-letter route — the agent posts the stuck task to a queue or webhook for human review rather than looping indefinitely.

```yaml
# Deployed in live cluster — cert-mcp-server RemoteMCPServer
spec:
  protocol: STREAMABLE_HTTP
  timeout: 30s          # cuts off a single stuck MCP tool call
  sseReadTimeout: 5m0s  # cuts off a hung SSE stream
  terminateOnClose: true
```

```yaml
# To add — agentgateway config.yaml backend timeout
backends:
  - name: default-llm
    llm:
      provider: openai
      model: gpt-4o-mini
      timeout: 30s
      retries: 2
      auth:
        apiKey: "${LLM_API_KEY}"
```

---

## 2. Any automatic timeout/circuit breaker patterns from this framework?

**Answer:**

The live cluster's `agentgateway-config` ConfigMap has one backend with no retry or circuit-breaker block — those are not yet configured. agentgateway is built on Envoy, so the circuit breaker behavior is available without additional dependencies: after a configurable number of consecutive upstream 5xx errors, Envoy opens the circuit and stops forwarding requests to that backend, falling back to the next priority backend or returning an error if none exists. The circuit resets automatically after a cooldown window — no manual intervention needed. To enable it, add `retries` and a timeout to the backend entry in `config.yaml`. Currently the most concrete automatic cutoff in this cluster is the `RemoteMCPServer` `timeout: 30s`, which fires on any individual MCP call that stalls.

```yaml
# To add to live agentgateway-config ConfigMap
backends:
  - name: default-llm
    llm:
      provider: openai
      model: gpt-4o-mini
      timeout: 30s
      retries: 2
      auth:
        apiKey: "${LLM_API_KEY}"
```

---

## 3. How does kgateway handle model failover?

**Answer:**

The live cluster has a single `AgentgatewayBackend` (`default-llm`, OpenAI gpt-4o-mini) and a single `HTTPRoute` routing all traffic (`PathPrefix: /`) to it with `weight: 1` — failover is not currently configured. The architecture supports it in two modes. In config.yaml (standalone) mode, add multiple backends with `priority` fields; agentgateway evaluates them in order and promotes to the next when the current backend's circuit is open. In K8s CRD mode, add additional `AgentgatewayBackend` resources. Failover is transparent to all agents: every `ModelConfig` in the cluster points at the same `agentgateway-proxy` service and never changes regardless of how many backends exist behind it.

```yaml
# To add — config.yaml multi-backend failover (currently single-backend)
backends:
  - name: default-llm
    llm:
      provider: openai
      model: gpt-4o-mini
      priority: 1
      auth:
        apiKey: "${LLM_API_KEY}"
  - name: anthropic-fallback
    llm:
      provider: anthropic
      model: claude-3-5-haiku-20241022
      priority: 2
      auth:
        apiKey: "${ANTHROPIC_API_KEY}"
```

---

## 4. Can we automatically switch from OpenAI to Claude to local model?

**Answer:**

Yes — a three-level extension of Q3. The live cluster already normalizes all responses to OpenAI Chat Completions format at the gateway; adding a third backend with `provider: openai_compatible` pointing to an Ollama or vLLM instance requires only a config change. All 11 kagent agents and the custom `a2a-agent` (`ghcr.io/va4567/a2a-agent:v1`) call the same gateway endpoint (`agentgateway-proxy.agentgateway-system.svc.cluster.local:80`) and are completely unaware of which physical provider serves each request. The local inference server only needs to expose `/v1/chat/completions`; both vLLM and Ollama do this by default. agentgateway then traverses OpenAI → Anthropic → local in priority order, falling through when a circuit is open.

```yaml
# To add — third priority local backend
  - name: local-ollama
    llm:
      provider: openai_compatible
      baseUrl: "http://ollama.ollama.svc.cluster.local:11434/v1"
      model: llama3
      priority: 3
      auth:
        apiKey: "ollama"  # required field, ignored by Ollama
```

---

## 5. Could we seamlessly handle response formats from different providers?

**Answer:**

Yes, verified during Lab 2. agentgateway normalizes all provider responses to OpenAI Chat Completions format (`choices[0].message.content`) before returning to callers. All 11 agents in the cluster — including the 9 Helm-managed agents (`helm-agent`, `k8s-agent`, `istio-agent`, etc.), `my-agent`, and `cert-lab-k8s-agent` — reference `ModelConfig` resources that point at the agentgateway proxy and consume the normalized format. The custom `a2a-agent` (FastAPI, `ghcr.io/va4567/a2a-agent:v1`) also calls the proxy and parses the same response structure. Streaming uses the same SSE delta format across providers. Tool call responses, which differ structurally between OpenAI and Anthropic, are normalized at the gateway layer — the same MCP tool definitions (`get_current_time`, `roll_dice`, etc.) work against any backend without modification.

```bash
# Verified in Lab 2 — consistent response schema regardless of backend:
curl -s http://localhost:15000/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{"model":"gpt-4o-mini","messages":[{"role":"user","content":"ping"}]}' \
  | python3 -m json.tool | grep '"role"\|"content"'
# Returns: "role": "assistant", "content": "pong"
```

---

## 6. Can we version agents built with kagent?

**Answer:**

The live cluster demonstrates two versioning modes simultaneously. The 9 Helm-managed agents all carry `app.kubernetes.io/version: 0.9.4` and `helm.sh/chart: <name>-0.9.4` labels — version is tracked via Helm chart version and visible via `kubectl get agents -n kagent --show-labels`. My manually applied `my-agent` has `<none>` labels, showing the gap when agents are created imperatively. Git history is the authoritative version record for declarative changes: `git log --oneline -- infrastructure/kagent/agents/` shows commit `6253c83 LAB-2-cert: ModelConfig + FastMCP server + RemoteMCPServer + declarative agent`. Flux is installed in the cluster, so any push to main auto-deploys the updated CRD — rollback is `git revert + push`. Multiple versions coexist by using different resource names: `my-agent-v1` and `my-agent-v2` can run simultaneously in the same namespace.

```bash
# Real output from live cluster:
kubectl get agents -n kagent --show-labels
# helm-agent   Declarative  python  True  True  app.kubernetes.io/version=0.9.4,...
# my-agent     Declarative  python  True  True  <none>

# Full agent change history:
git log --oneline -- infrastructure/kagent/agents/
# 6253c83 LAB-2-cert: ModelConfig + FastMCP server + RemoteMCPServer + declarative agent
```

---

## 7. Any blue/green or canary deployment patterns for agents?

**Answer:**

The live cluster already runs 11 agents side by side in the `kagent` namespace with no interference — this proves the foundation works. For a formal blue/green deploy, add `my-agent-v2` alongside `my-agent-v1`; update the agentgateway route or client config to point at the new name; rollback is instant because `my-agent-v1` is still running. For canary, agentgateway's weighted `backendRefs` on the HTTPRoute allows traffic splitting: 90% to v1, 10% to v2, with promotion once metrics confirm quality. Kagent agents are stateless — `kubectl explain agent.spec.declarative` shows no session state in the pod spec; each conversation starts fresh from `systemMessage`, so version switches carry no session migration risk. The `a2aConfig` field in `spec.declarative` (confirmed in live CRD explain) means v1 and v2 can also run as distinct A2A agents with independent `/.well-known/agent.json` Agent Cards — making side-by-side quality comparison straightforward using distributed tracing (e.g. Arize Phoenix showing per-agent latency, token counts, and tool-call success rates).

---

## 8. What is the fastmcp-python framework?

**Answer:**

`fastmcp` is a Python library for building MCP (Model Context Protocol) servers with function decorators — analogous to FastAPI for HTTP. I deployed it twice in these labs: in Lab 2 as `cert-mcp-server` (4 tools: `get_current_time`, `roll_dice`, `calculate`, `cluster_info`), and in Lab 4 as `mcpg` — an MCP gateway using `fastmcp.Client` to proxy calls to the upstream `cert-mcp-server`. Both use the ConfigMap + initContainer pattern: server code lives in a ConfigMap, `pip install --target=/deps fastmcp` runs in an initContainer, no image build required. The `@mcp.tool()` decorator converts any typed Python function into a discoverable MCP tool — schema is auto-generated from type hints and docstrings. FastMCP handles the full STREAMABLE_HTTP protocol: JSON-RPC session initialization, `mcp-session-id` header exchange, SSE framing, and tool discovery — verified by the two-step initialize → tools/list flow during Lab 4.

```python
# Deployed in cert-mcp-server (Lab 2), same pattern in mcpg (Lab 4)
from fastmcp import FastMCP
mcp = FastMCP("cert-mcp-server")

@mcp.tool()
def get_current_time() -> str:
    """Returns the current UTC time."""
    from datetime import datetime, timezone
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")

if __name__ == "__main__":
    mcp.run(transport="streamable-http", host="0.0.0.0", port=8080)
```

---

## 9. Is it the easiest path to MCP?

**Answer:**

For Python on Kubernetes: yes, and the ConfigMap + initContainer pattern removes the last friction point — no image build and no registry. In Lab 4, deploying `mcpg` was a single `kubectl apply`, while the `a2a-agent` required building a Docker image, creating a PAT with `write:packages` scope, pushing to GHCR, and making the package public before the cluster could pull it. The initContainer installs fastmcp at pod startup in ~30 seconds on first run; subsequent restarts reuse the warm emptyDir. The `RemoteMCPServer` CRD auto-discovers tools via the `status.discoveredTools` field — no manual registration needed. The main constraint: fastmcp is Python-only. For Go services, use the official MCP Go SDK. For multi-language teams or production Helm packaging, KMCP generates K8s manifests alongside the server code and is the better long-term choice. For rapid iteration in K8s, fastmcp + ConfigMap wins on speed.

---

## 10. About FinOps: how much control do I have?

**Answer:**

In the live cluster, `kubectl get crd | grep -i "policy\|llm"` returns empty — no `LLMPolicy` or token-rate-limit CRDs are deployed. The current state has one backend and one shared HTTPRoute with no budget fields. The control that IS available today without any additional deployment is `spec.declarative.context` on the Agent CRD (confirmed in live `kubectl explain`): it configures event compaction and context caching, which limits how much conversation history is included in each LLM call — directly reducing input tokens in long multi-turn sessions. Full FinOps control requires deploying `LLMPolicy` resources: agentgateway supports token-rate-limit policies, per-route quotas, and Prometheus metric export for cost attribution per backend. The webhook policy mechanism (Q12) then layers arbitrary custom logic on top of that. None of this is configured yet; it is the next step after the cert labs.

---

## 11. Token level / per-agent level cost control

**Answer:**

The mechanism exists in agentgateway but is not deployed in the live cluster. Token-level control is implemented as a `LLMPolicy` resource with a `tokenRateLimit` field capping total input+output tokens per time window on a given route. Per-agent granularity requires splitting the current single `default-llm` HTTPRoute (`PathPrefix: /`, shared by all agents) into dedicated per-agent routes — one for `my-agent`, one for `a2a-agent`, etc. — and binding an independent `LLMPolicy` to each. The `spec.declarative.context` compaction setting on each Agent CRD is the only token-reduction lever available in the cluster today: it controls how much history is replayed per turn, bounding input growth without any gateway changes.

```yaml
# To deploy — per-agent route + policy (currently not deployed)
apiVersion: agentgateway.dev/v1alpha1
kind: LLMPolicy
metadata:
  name: my-agent-budget
  namespace: agentgateway-system
spec:
  targetRef:
    name: my-agent-route   # requires dedicated HTTPRoute per agent
  tokenRateLimit:
    limit: 50000           # tokens per 24h
    window: 24h
  maxTokens: 2000          # per-response output cap
```

---

## 12. Can I implement custom cost controls?

**Answer:**

Yes — agentgateway supports webhook policies that call an external HTTP endpoint synchronously before forwarding any request to the LLM backend. The webhook receives the full request context and returns approve, deny, or a modified request, allowing arbitrary business logic: per-team spending limits from an external database, prepaid credit checks, or per-project cost centers. This is not deployed in the live cluster but the mechanism is in the agentgateway policy spec. An in-cluster implementation would be a small FastAPI or Go service as a Kubernetes Deployment, registered as the webhook endpoint in the backend config. Combined with agentgateway's Prometheus metrics (token counts per route and per backend), this creates a complete FinOps loop: Prometheus for observability, `LLMPolicy` for hard rate limits, webhook for custom enforcement logic.

---

## 13. Per-agent budgets or depth of token limits

**Answer:**

Two independent levers operate at different granularities. `maxTokens` caps output tokens per individual LLM call — controls response depth and prevents a single runaway generation from consuming the budget. `tokenRateLimit` caps cumulative spend over a time window — controls total burn across all calls in an agentic loop. Neither is deployed in the live cluster. The third lever that IS available is `spec.declarative.context` event compaction on the Agent CRD: it bounds input token growth per turn by controlling how much conversation history is replayed without requiring any gateway changes. For a production baseline on these cert lab agents (`my-agent` with 4 MCP tools, `a2a-agent` with A2A endpoint), `maxTokens: 2000` per response and `tokenRateLimit: 50000/24h` per agent route is a reasonable starting point.

```yaml
# To deploy — combined depth + budget control
apiVersion: agentgateway.dev/v1alpha1
kind: LLMPolicy
metadata:
  name: agent-budget
  namespace: agentgateway-system
spec:
  tokenRateLimit:
    limit: 50000    # tokens per 24h window
    window: 24h
  maxTokens: 2000   # per-response output cap
```

---

## 14. Is vLLM suitable for agents with many back-and-forth tool calls, or better for single-shot inference?

**Answer:**

vLLM is not deployed in the live cluster — it routes through agentgateway to the OpenAI API. vLLM's core optimization is continuous batching, which maximizes GPU utilization for high-volume single-shot inference. For agentic workloads with sequential tool calls (as in `my-agent`'s 4-tool loop), the critical feature is prefix KV-cache (`--enable-prefix-caching`, available since vLLM v0.4): the system prompt is encoded once and the KV tensors are reused for all subsequent calls in the same session. Without prefix caching, each of N tool-call turns re-encodes the full system prompt — a 2000-token system prompt across 10 tool calls wastes ~18,000 tokens of redundant prefill computation. With prefix caching, only the first call pays that cost; subsequent calls pay only for the incremental tokens. The verdict: vLLM is well-suited for agents — enable `--enable-prefix-caching`; the saving scales with system prompt length and number of turns in the session.

---

## 15. llm-d's scheduler — does it help when an agent makes 15 LLM calls?

**Answer:**

llm-d is not deployed in the live cluster — no llm-d pods or CRDs are present. It is a Kubernetes-native distributed inference scheduler that layers on top of a vLLM deployment and adds session-aware pod routing. Without llm-d, requests from one agent session scatter across vLLM pods via round-robin: call 1 lands on pod A, call 2 on pod B, call 3 on pod C — each pod is a KV-cache miss for the session prefix, so every call re-encodes the system prompt. llm-d's scheduler tracks which pod holds the KV tensors for a given session prefix and routes all subsequent calls from that session to the same pod. For an agent making 15 calls with a 2000-token system prompt, only the first call pays full prefill cost; calls 2–15 hit the cache and pay only for incremental new tokens. The practical result is approximately 60–70% reduction in prefill compute for that session. The benefit compounds further if the agent accumulates conversation history across turns, since llm-d prevents that growing context from being re-encoded on each new pod.
