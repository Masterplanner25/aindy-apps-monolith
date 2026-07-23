import { authRequest, unwrapEnvelope } from "./_core.js";
import { ROUTES } from "./_routes.js";

// Several /apps/agent read routes wrap their payload as `{data: [...]}`. Verified live:
// runs, tools and suggestions all do; trust returns a bare object and /apps/memory/agents
// returns `{agents, total}`. `unwrapEnvelope` only unwraps when a `data` key is present,
// so it is applied to the wrapped reads and left off the ones that are already flat.
// Without it AgentConsole did `setRuns({data: []})` and then `runs.filter(...)`, which
// threw and blanked the whole console.

export function getAgents() {
  return authRequest(ROUTES.MEMORY.AGENTS, { method: "GET" });
}

export function recallFromAgent(namespace, query = "", limit = 5) {
  return authRequest(
    `${ROUTES.MEMORY.AGENT_RECALL(namespace)}?query=${encodeURIComponent(query)}&limit=${limit}`,
    { method: "GET" }
  );
}

export function getFederatedMemory(query, namespaces = null, limit = 5) {
  return authRequest(ROUTES.MEMORY.FEDERATED_RECALL, {
    method: "POST",
    body: JSON.stringify({ query, agent_namespaces: namespaces, limit }),
  });
}

export function createAgentRun(payload) {
  return authRequest(ROUTES.AGENT.CREATE_RUN, {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export function getAgentRuns(status = null, limit = 20) {
  const params = new URLSearchParams({ limit });
  if (status) params.append("status", status);
  return authRequest(`${ROUTES.AGENT.RUNS}?${params.toString()}`, { method: "GET" }).then(unwrapEnvelope);
}

export function getAgentRun(runId) {
  return authRequest(ROUTES.AGENT.RUN(runId), { method: "GET" }).then(unwrapEnvelope);
}

export function approveAgentRun(runId) {
  return authRequest(ROUTES.AGENT.APPROVE(runId), { method: "POST" });
}

export function rejectAgentRun(runId) {
  return authRequest(ROUTES.AGENT.REJECT(runId), { method: "POST" });
}

export function getAgentRunSteps(runId) {
  return authRequest(ROUTES.AGENT.STEPS(runId), { method: "GET" }).then(unwrapEnvelope);
}

export function getAgentTools() {
  return authRequest(ROUTES.AGENT.TOOLS, { method: "GET" }).then(unwrapEnvelope);
}

export function getAgentTrust() {
  return authRequest(ROUTES.AGENT.TRUST, { method: "GET" });
}

export function updateAgentTrust(payload) {
  return authRequest(ROUTES.AGENT.TRUST, {
    method: "PUT",
    body: JSON.stringify(payload),
  });
}

export function getAgentSuggestions() {
  return authRequest(ROUTES.AGENT.SUGGESTIONS, { method: "GET" }).then(unwrapEnvelope);
}

export async function fetchRunEvents(runId) {
  return authRequest(ROUTES.AGENT.EVENTS(runId));
}
