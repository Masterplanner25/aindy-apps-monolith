import { authRequest, unwrapEnvelope } from "./_core.js";
import { ROUTES } from "./_routes.js";

// Every /apps/social route runs through `execute_with_pipeline_sync` and returns the
// standard `{status, data, result, events, ...}` envelope, so each call must unwrap.
// Without this the feed hands an object to `safeMap` (renders nothing, and never shows
// the empty state either, since an object has no `.length`) and the analytics panel
// reads `analytics.overview` off the envelope and shows all zeros.

export function getProfile(username) {
  return authRequest(ROUTES.SOCIAL.PROFILE_BY_USERNAME(username), { method: "GET" }).then(
    unwrapEnvelope
  );
}

export function upsertProfile(profileData) {
  return authRequest(ROUTES.SOCIAL.PROFILE, {
    method: "POST",
    body: JSON.stringify(profileData),
  }).then(unwrapEnvelope);
}

export function getFeed(limit = 20, trustFilter = null) {
  let path = `${ROUTES.SOCIAL.FEED}?limit=${limit}`;
  if (trustFilter) {
    path += `&trust_filter=${trustFilter}`;
  }
  return authRequest(path, { method: "GET" }).then(unwrapEnvelope);
}

export function createPost(postData) {
  return authRequest(ROUTES.SOCIAL.POST, {
    method: "POST",
    body: JSON.stringify(postData),
  }).then(unwrapEnvelope);
}

export function getSocialAnalytics() {
  return authRequest(ROUTES.SOCIAL.ANALYTICS, { method: "GET" }).then(unwrapEnvelope);
}

export function recordSocialInteraction(postId, action, amount = 1) {
  return authRequest(ROUTES.SOCIAL.INTERACT(postId), {
    method: "POST",
    body: JSON.stringify({ action, amount }),
  }).then(unwrapEnvelope);
}
