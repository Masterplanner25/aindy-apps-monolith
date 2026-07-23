import { beforeEach, describe, expect, it, vi } from "vitest";

import { getAgentRuns, getAgentTools, getAgentSuggestions, getAgentTrust } from "../api/agent.js";

function makeToken(payload) {
  const encoded = btoa(JSON.stringify(payload)).replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/g, "");
  return `header.${encoded}.signature`;
}

function stubResponse(body) {
  vi.stubGlobal(
    "fetch",
    vi.fn().mockResolvedValue({
      ok: true,
      status: 200,
      text: () => Promise.resolve(JSON.stringify(body)),
    })
  );
}

// /apps/agent/runs, /tools and /suggestions wrap their payload as `{data: [...]}`.
// Without unwrapping, AgentConsole did `setRuns({data: []})` and then `runs.filter(...)`,
// which threw and blanked the console.
describe("agent api unwraps the wrapped reads", () => {
  beforeEach(() => {
    window.localStorage.clear();
    vi.unstubAllGlobals();
    window.localStorage.setItem("token", makeToken({ sub: "u-1" }));
  });

  it("getAgentRuns returns the run array", async () => {
    stubResponse({ data: [{ id: "r1", status: "pending_approval" }] });
    const runs = await getAgentRuns();
    expect(Array.isArray(runs)).toBe(true);
    expect(runs[0].status).toBe("pending_approval");
  });

  it("getAgentTools returns the tool array", async () => {
    stubResponse({ data: [{ name: "arm.analyze" }] });
    await expect(getAgentTools()).resolves.toHaveLength(1);
  });

  it("getAgentSuggestions returns the suggestion array", async () => {
    stubResponse({ data: [] });
    await expect(getAgentSuggestions()).resolves.toEqual([]);
  });

  // /apps/agent/trust returns a bare object with no `data` key. unwrapEnvelope is not
  // applied there, and would be a no-op anyway — this pins that it stays flat.
  it("getAgentTrust returns the settings object unchanged", async () => {
    stubResponse({ user_id: "u-1", auto_execute_low: true, allowed_auto_grant_tools: [] });
    const trust = await getAgentTrust();
    expect(trust.auto_execute_low).toBe(true);
    expect(trust.user_id).toBe("u-1");
  });
});
