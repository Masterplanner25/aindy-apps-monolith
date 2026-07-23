import { beforeEach, describe, expect, it, vi } from "vitest";

import { createTask } from "../api/tasks.js";

function makeToken(payload) {
  const encoded = btoa(JSON.stringify(payload)).replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/g, "");
  return `header.${encoded}.signature`;
}

function stubOk() {
  const fetchSpy = vi.fn().mockResolvedValue({
    ok: true,
    status: 200,
    text: () => Promise.resolve(JSON.stringify({ status: "success", data: { task_id: "1" } })),
  });
  vi.stubGlobal("fetch", fetchSpy);
  return fetchSpy;
}

function sentBody(fetchSpy) {
  const [, opts] = fetchSpy.mock.calls[0];
  return JSON.parse(opts.body);
}

// The dashboard sent only {name, priority} out of the 13 fields TaskCreate accepts.
// Two of the omitted ones are load-bearing: estimated_hours lands in Task.duration
// (the MasterPlan ETA effort term and the Infinity Volume input), and masterplan_id
// drives ETA/WCU recalculation plus the completion cascade.
describe("createTask payload", () => {
  beforeEach(() => {
    window.localStorage.clear();
    vi.unstubAllGlobals();
    window.localStorage.setItem("token", makeToken({ sub: "u-1" }));
  });

  it("carries estimated_hours and masterplan_id when supplied", async () => {
    const fetchSpy = stubOk();
    await createTask({
      name: "Ship the thing",
      priority: "medium",
      estimated_hours: 2.5,
      masterplan_id: 7,
    });
    expect(sentBody(fetchSpy)).toEqual({
      name: "Ship the thing",
      priority: "medium",
      estimated_hours: 2.5,
      masterplan_id: 7,
    });
  });

  // Both fields are Optional server-side; omitting them is not the same as sending null,
  // so the form must leave them out rather than send empty values.
  it("omits the optional fields entirely when not supplied", async () => {
    const fetchSpy = stubOk();
    await createTask({ name: "Bare task", priority: "medium" });
    const body = sentBody(fetchSpy);
    expect(body).toEqual({ name: "Bare task", priority: "medium" });
    expect("estimated_hours" in body).toBe(false);
    expect("masterplan_id" in body).toBe(false);
  });
});
