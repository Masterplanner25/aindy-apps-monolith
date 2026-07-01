import { createContext, useCallback, useContext, useMemo, useState } from "react";

/**
 * Shares the freshest MasterPlan ETA projection across app surfaces.
 *
 * Task completion (`/tasks/complete`) returns a recomputed, cascade-aware
 * projection under `orchestration.masterplan_projection` (MASTERPLAN_SAAS
 * Step 3). The task surface and the MasterPlan surface are separate, lazily
 * loaded routes that never mount together, so that fresh projection would
 * otherwise be discarded until the MasterPlan panel refetched on its own.
 *
 * This context is mounted above the app shell (persisting across route
 * changes): the task surface publishes the projection on completion, and the
 * MasterPlan ETA panel adopts it reactively — showing post-completion data
 * instantly instead of waiting for its next fetch.
 *
 * The default value is a safe no-op so components using the hook render fine
 * without a provider (e.g. in isolation tests).
 */
const MasterplanProjectionContext = createContext({
  projections: {},
  publishProjection: () => {},
});

export function MasterplanProjectionProvider({ children }) {
  const [projections, setProjections] = useState({});

  const publishProjection = useCallback((planId, projection) => {
    if (planId === null || planId === undefined || !projection) return;
    setProjections((prev) => ({ ...prev, [planId]: projection }));
  }, []);

  const value = useMemo(
    () => ({ projections, publishProjection }),
    [projections, publishProjection],
  );

  return (
    <MasterplanProjectionContext.Provider value={value}>
      {children}
    </MasterplanProjectionContext.Provider>
  );
}

export function useMasterplanProjection() {
  return useContext(MasterplanProjectionContext);
}

/**
 * Pull the recomputed MasterPlan projection out of a `/tasks/complete`
 * response. Tolerant of envelope-unwrapping variations: the projection lives
 * under `orchestration` (the `task_completion` flow's result extractor), but we
 * also accept a top-level or `data`-nested shape defensively. Returns
 * `{ planId, projection }` or `null` when no active-plan reprojection is present.
 */
export function extractReprojection(res) {
  const o = res?.orchestration ?? res?.data?.orchestration ?? res ?? {};
  const projection = o?.masterplan_projection ?? null;
  const planId = o?.masterplan_id ?? null;
  if (projection && planId !== null && planId !== undefined) {
    return { planId, projection };
  }
  return null;
}
