// App-owned route map.
//
// The shared @aindy/ui-kit exports `ROUTES`, but it bakes in a few *app-domain*
// paths (this monolith's analytics `/compute/*` and SEO `/seo/*` endpoints) without
// their backend router prefix — so they resolve to paths the backend never registers
// (e.g. the AI SEO tool would 404). Per the runtime/app split applied at the frontend
// layer, the shared kit owns runtime/platform routes and each app owns its own app
// routes. This module is that ownership boundary: it re-exports ui-kit's `ROUTES` and
// corrects the app-domain paths that belong to this monolith.
//
// Self-healing: each override only prepends the missing prefix when ui-kit's value is
// present and not already prefixed — so if a future ui-kit removes these app routes (the
// correct upstream end-state) or fixes them, this becomes a no-op rather than breaking.
//
// The one genuinely runtime-owned route in the same finding — `/platform/flows/strategies`
// — is NOT corrected here; it is fixed upstream in @aindy/ui-kit (every consumer benefits).
// See docs/handoffs/UIKIT_ROUTE_FIXES.md and TECH_DEBT UIKIT-ROUTE-DRIFT-1.

import { ROUTES as UIKIT_ROUTES } from "@aindy/ui-kit";

// Analytics KPI compute endpoints live under the backend `/compute` router.
const COMPUTE_KEYS = [
  "CALCULATE_TWR",
  "CALCULATE_ENGAGEMENT",
  "CALCULATE_AI_EFFICIENCY",
  "CALCULATE_IMPACT_SCORE",
  "CALCULATE_AI_PRODUCTIVITY_BOOST",
  "CALCULATE_ATTENTION_VALUE",
  "CALCULATE_BUSINESS_GROWTH",
  "CALCULATE_DECISION_EFFICIENCY",
  "CALCULATE_ENGAGEMENT_RATE",
  "CALCULATE_EXECUTION_SPEED",
  "CALCULATE_INCOME_EFFICIENCY",
  "CALCULATE_LOST_POTENTIAL",
  "CALCULATE_MONETIZATION_EFFICIENCY",
  "CALCULATE_REVENUE_SCALING",
];

// SEO endpoints live under the backend `/seo` router.
const SEO_KEYS = ["ANALYZE_SEO", "GENERATE_META", "SUGGEST_IMPROVEMENTS"];

function withPrefix(group, keys, prefix) {
  const corrected = { ...group };
  for (const key of keys) {
    const value = group?.[key];
    if (typeof value === "string" && !value.startsWith(prefix)) {
      corrected[key] = `${prefix}${value}`;
    }
  }
  // Preserve ui-kit's frozen-domain-map contract (see api-routes.test.js).
  return Object.freeze(corrected);
}

export const ROUTES = Object.freeze({
  ...UIKIT_ROUTES,
  ANALYTICS: withPrefix(UIKIT_ROUTES.ANALYTICS, COMPUTE_KEYS, "/compute"),
  SEARCH: withPrefix(UIKIT_ROUTES.SEARCH, SEO_KEYS, "/seo"),
});

// Exposed for the route-map guard test.
export const APP_OWNED_ROUTE_CORRECTIONS = { COMPUTE_KEYS, SEO_KEYS };
