import { describe, it, expect } from "vitest";

import { ROUTES as UIKIT_ROUTES } from "@aindy/ui-kit";
import { ROUTES, APP_OWNED_ROUTE_CORRECTIONS } from "../_routes.js";

// Guards the app-owned route corrections (UIKIT-ROUTE-DRIFT-1). @aindy/ui-kit's ROUTES
// build this monolith's app-domain paths without the prefixes the backend mounts them under:
//   - the sub-router prefixes /compute and /seo are omitted entirely
//   - the /apps mount prefix is missing from EVERY app-domain route (ui-kit's app prefix is
//     the empty string), which left 90 of 101 app routes 404ing
// `_routes.js` corrects both app-side (the ownership boundary). These tests fail if a
// correction regresses — e.g. a bad ui-kit bump slips bare paths through again.
describe("app-owned route corrections", () => {
  it("analytics compute routes carry the /apps/compute prefix", () => {
    for (const key of APP_OWNED_ROUTE_CORRECTIONS.COMPUTE_KEYS) {
      expect(ROUTES.ANALYTICS[key], key).toMatch(/^\/apps\/compute\//);
    }
  });

  it("SEO routes carry the /apps/seo prefix", () => {
    for (const key of APP_OWNED_ROUTE_CORRECTIONS.SEO_KEYS) {
      expect(ROUTES.SEARCH[key], key).toMatch(/^\/apps\/seo\//);
    }
  });

  it("mounts app-domain routes under /apps", () => {
    // These are app-domain and MUST be corrected — ui-kit emits them bare, which 404s.
    expect(ROUTES.TASKS.LIST).toBe("/apps/tasks/list");
    expect(ROUTES.MASTERPLAN.GENESIS_SESSION).toBe("/apps/genesis/session");
    expect(ROUTES.FREELANCE.ORDERS).toBe("/apps/freelance/orders");
    expect(ROUTES.SEARCH.LEAD_GEN).toBe(`/apps${UIKIT_ROUTES.SEARCH.LEAD_GEN}`);
  });

  it("leaves runtime-owned namespaces exactly as ui-kit defines them", () => {
    expect(ROUTES.OPERATOR.FLOW_STRATEGIES).toBe(UIKIT_ROUTES.OPERATOR.FLOW_STRATEGIES);
    expect(ROUTES.AUTH.LOGIN).toBe(UIKIT_ROUTES.AUTH.LOGIN);
    expect(ROUTES.PLATFORM.VERSION).toBe(UIKIT_ROUTES.PLATFORM.VERSION);
    expect(ROUTES.PLATFORM.HEALTH_DETAILS).toBe(UIKIT_ROUTES.PLATFORM.HEALTH_DETAILS);
    // Runtime client-telemetry sink, mounted at the root.
    expect(ROUTES.OPERATOR.CLIENT_ERROR).toBe("/client/error");
  });

  it("does not double-prefix routes ui-kit already mounts under /apps", () => {
    expect(ROUTES.AGENT.CREATE_RUN).toBe(UIKIT_ROUTES.AGENT.CREATE_RUN);
    for (const group of Object.values(ROUTES)) {
      for (const value of Object.values(group)) {
        if (typeof value === "string") {
          expect(value).not.toMatch(/\/apps\/apps\//);
        }
      }
    }
  });

  it("is idempotent — does not double-prefix sub-routers", () => {
    for (const key of APP_OWNED_ROUTE_CORRECTIONS.COMPUTE_KEYS) {
      expect(ROUTES.ANALYTICS[key]).not.toMatch(/\/compute\/compute\//);
    }
    for (const key of APP_OWNED_ROUTE_CORRECTIONS.SEO_KEYS) {
      expect(ROUTES.SEARCH[key]).not.toMatch(/\/seo\/seo\//);
    }
  });

  it("corrects path-building functions too, not just strings", () => {
    expect(ROUTES.MASTERPLAN.PLAN_ANCHOR("p1")).toBe("/apps/masterplans/p1/anchor");
    expect(ROUTES.RIPPLETRACE.CAUSAL_CHAIN("d1")).toBe("/apps/rippletrace/causal/chain/d1");
    // ...while leaving runtime-owned builders alone.
    expect(ROUTES.OPERATOR.FLOW_RUN("r1")).toBe("/platform/flows/runs/r1");
  });
});
