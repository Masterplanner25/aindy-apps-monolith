import { describe, it, expect } from "vitest";

import { ROUTES as UIKIT_ROUTES } from "@aindy/ui-kit";
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

  it("leaves non-app-domain routes as ui-kit defines them (passthrough)", () => {
    // The override only corrects the app-domain /compute + /seo paths; everything else
    // passes through unchanged from ui-kit (robust to ui-kit route revisions).
    expect(ROUTES.TASKS.LIST).toBe(UIKIT_ROUTES.TASKS.LIST);
    expect(ROUTES.AGENT.CREATE_RUN).toBe(UIKIT_ROUTES.AGENT.CREATE_RUN);
    expect(ROUTES.SEARCH.LEAD_GEN).toBe(UIKIT_ROUTES.SEARCH.LEAD_GEN);
    expect(ROUTES.OPERATOR.FLOW_STRATEGIES).toBe(UIKIT_ROUTES.OPERATOR.FLOW_STRATEGIES);
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
