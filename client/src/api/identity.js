import { authRequest, unwrapEnvelope } from "./_core.js";
import { ROUTES } from "./_routes.js";

// Every /apps/identity route runs through `execute_with_pipeline` and returns the
// `{status, data, ...}` envelope. Without unwrapping, IdentityDashboard reads
// `profile?.["communication" | "tools" | "decision_making" | "learning"]` off the
// envelope — all undefined — so the page renders with four blank dimension cards and
// an evolution panel stuck at 0 observations / 0 changes.
//
// Note: the /apps/memory routes are NOT enveloped (they return `{nodes, ...}` and
// `{results, ...}` directly), which is why `memory.js` correctly has no unwrap.

export function getIdentityProfile() {
  return authRequest(ROUTES.IDENTITY.PROFILE, { method: "GET" }).then(unwrapEnvelope);
}

export function updateIdentityProfile(updates) {
  return authRequest(ROUTES.IDENTITY.PROFILE, {
    method: "PUT",
    body: JSON.stringify(updates),
  }).then(unwrapEnvelope);
}

export function getIdentityEvolution() {
  return authRequest(ROUTES.IDENTITY.EVOLUTION, { method: "GET" }).then(unwrapEnvelope);
}

export function getIdentityContext() {
  return authRequest(ROUTES.IDENTITY.CONTEXT, { method: "GET" }).then(unwrapEnvelope);
}
