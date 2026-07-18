import { describe, it, expect } from "vitest";

import { ROUTES, APP_OWNED_ROUTE_CORRECTIONS } from "../_routes.js";

// Guards the app-owned route corrections (UIKIT-ROUTE-DRIFT-1): @aindy/ui-kit's ROUTES
// bake in this monolith's analytics `/compute/*` and SEO `/seo/*` paths without their
// backend router prefix. `_routes.js` corrects them app-side (the ownership boundary).
// This test fails if a correction regresses (e.g. a bad ui-kit bump slips a bare path
// through).
describe("app-owned route corrections", () => {
  it("analytics compute routes carry the /compute prefix", () => {
    for (const key of APP_OWNED_ROUTE_CORRECTIONS.COMPUTE_KEYS) {
      expect(ROUTES.ANALYTICS[key], key).toMatch(/^\/compute\//);
    }
  });

  it("SEO routes carry the /seo prefix", () => {
    for (const key of APP_OWNED_ROUTE_CORRECTIONS.SEO_KEYS) {
      expect(ROUTES.SEARCH[key], key).toMatch(/^\/seo\//);
    }
  });

  it("leaves non-app-domain routes untouched", () => {
    // These already resolve correctly (no intermediate router prefix) and must not be
    // rewritten by the override.
    expect(ROUTES.TASKS.LIST).toBe("/tasks/list");
    expect(ROUTES.AGENT.CREATE_RUN).toBe("/agent/run");
    expect(ROUTES.SEARCH.LEAD_GEN).toBe("/leadgen/");
  });

  it("is idempotent — does not double-prefix", () => {
    for (const key of APP_OWNED_ROUTE_CORRECTIONS.COMPUTE_KEYS) {
      expect(ROUTES.ANALYTICS[key]).not.toMatch(/\/compute\/compute\//);
    }
    for (const key of APP_OWNED_ROUTE_CORRECTIONS.SEO_KEYS) {
      expect(ROUTES.SEARCH[key]).not.toMatch(/\/seo\/seo\//);
    }
  });
});
