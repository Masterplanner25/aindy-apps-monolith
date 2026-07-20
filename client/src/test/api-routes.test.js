import { describe, expect, it } from "vitest";

import { ROUTES } from "../api/_routes.js";

describe("API route registry", () => {
  it("freezes the top-level registry and nested domain maps", () => {
    expect(Object.isFrozen(ROUTES)).toBe(true);

    for (const paths of Object.values(ROUTES)) {
      expect(Object.isFrozen(paths)).toBe(true);
    }

    expect(() => {
      ROUTES.AUTH = {};
    }).toThrow(TypeError);
  });

  it("uses only strings or functions for route entries", () => {
    for (const [domain, paths] of Object.entries(ROUTES)) {
      for (const [key, value] of Object.entries(paths)) {
        expect(
          typeof value === "string" || typeof value === "function",
          `ROUTES.${domain}.${key} must be string or function`,
        ).toBe(true);
      }
    }
  });

  it("builds representative static and dynamic paths correctly", () => {
    // App-domain routes carry the backend's /apps mount. ui-kit emits them unprefixed
    // (its app prefix is ""), which made them 404; _routes.js corrects them.
    expect(ROUTES.ARM.ANALYZE).toBe("/apps/arm/analyze");
    expect(ROUTES.MASTERPLAN.GENESIS_SESSION).toBe("/apps/genesis/session");
    expect(ROUTES.MASTERPLAN.PLAN_ANCHOR("plan-9")).toBe("/apps/masterplans/plan-9/anchor");
    expect(ROUTES.RIPPLETRACE.CAUSAL_CHAIN("drop 1")).toBe(
      "/apps/rippletrace/causal/chain/drop%201",
    );
    expect(ROUTES.FREELANCE.ORDERS).toBe("/apps/freelance/orders");
    expect(ROUTES.TASKS.LIST).toBe("/apps/tasks/list");

    // Already-correct app routes must not double-prefix.
    expect(ROUTES.AGENT.EVENTS("run-7")).toBe("/apps/agent/runs/run-7/events");

    // Runtime-owned namespaces are left alone.
    expect(ROUTES.OPERATOR.FLOW_RUN("abc-123")).toBe("/platform/flows/runs/abc-123");
    expect(ROUTES.PLATFORM.VERSION).toBe("/api/version");
    expect(ROUTES.PLATFORM.HEALTH_DETAILS).toBe("/health/details");
    expect(ROUTES.AUTH.LOGIN).toBe("/auth/login");
    expect(ROUTES.OPERATOR.CLIENT_ERROR).toBe("/client/error");

    // PLATFORM is mixed: an app path and a runtime path in the same domain map,
    // which is why the correction is path-based rather than per-domain.
    expect(ROUTES.PLATFORM.DASHBOARD_OVERVIEW).toBe("/apps/dashboard/overview");
  });

  it("composes sub-router and /apps corrections", () => {
    // /calculate_twr -> /compute/calculate_twr -> /apps/compute/calculate_twr
    expect(ROUTES.ANALYTICS.CALCULATE_TWR).toBe("/apps/compute/calculate_twr");
    expect(ROUTES.SEARCH.ANALYZE_SEO).toBe("/apps/seo/analyze_seo/");
  });

  it("imports every API module without error", async () => {
    const modules = await Promise.all([
      import("../api/auth.js"),
      import("../api/tasks.js"),
      import("../api/agent.js"),
      import("../api/analytics.js"),
      import("../api/arm.js"),
      import("../api/freelance.js"),
      import("../api/identity.js"),
      import("../api/masterplan.js"),
      import("../api/memory.js"),
      import("../api/search.js"),
      import("../api/social.js"),
      import("../api/rippletrace.js"),
      import("../api/operator.js"),
      import("../api/product.js"),
      import("../api/platform.js"),
    ]);

    modules.forEach((moduleExports) => {
      expect(moduleExports).toBeDefined();
    });
  });
});
