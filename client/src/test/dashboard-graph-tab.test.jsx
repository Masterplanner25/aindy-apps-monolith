/**
 * The Dashboard Graph tab must show the graph, not bounce to Overview.
 *
 * Reported: clicking Graph landed back on Overview. Cause: no /dashboard/graph route was
 * registered, so navigating there matched nothing, hit the catch-all redirect, and returned
 * to /dashboard (Overview). The Dashboard component already keys its active tab off
 * pathname === "/dashboard/graph"; these tests lock that wiring so the route + tab stay in sync.
 */
import { render, screen, waitFor } from "@testing-library/react";

import { AppProviders } from "./utils";

const { mockGetDashboardOverview, mockGetMyScore, mockRecalculateScore, mockGetScoreHistory } =
  vi.hoisted(() => ({
    mockGetDashboardOverview: vi.fn(),
    mockGetMyScore: vi.fn(),
    mockRecalculateScore: vi.fn(),
    mockGetScoreHistory: vi.fn(),
  }));

const { mockGetCausalGraph, mockGetInfluenceGraph, mockGetDropPointNarrative } = vi.hoisted(() => ({
  mockGetCausalGraph: vi.fn(),
  mockGetInfluenceGraph: vi.fn(),
  mockGetDropPointNarrative: vi.fn(),
}));

vi.mock("../api/platform.js", () => ({
  getDashboardOverview: mockGetDashboardOverview,
}));

// GraphView pulls its graph data from the CANONICAL, user-authable rippletrace routes — not
// platform.js's legacy api-key-gated getInfluenceGraph/getCausalGraph, which 401 a normal user
// and trip the global session-expired logout. Mocking rippletrace.js here also guards that
// GraphView keeps importing from the canonical module.
vi.mock("../api/rippletrace.js", () => ({
  getCausalGraph: mockGetCausalGraph,
  getInfluenceGraph: mockGetInfluenceGraph,
  getDropPointNarrative: mockGetDropPointNarrative,
}));

vi.mock("../api/product.js", () => ({
  getMyScore: mockGetMyScore,
  recalculateScore: mockRecalculateScore,
  getScoreHistory: mockGetScoreHistory,
}));

const OVERVIEW = {
  status: "success",
  data: { status: "ok", overview: { system_timestamp: "t", author_count: 0, recent_authors: [], recent_ripples: [] } },
};

let Dashboard;

beforeAll(async () => {
  Dashboard = (await import("../components/app/Dashboard.jsx")).default;
});

beforeEach(() => {
  vi.clearAllMocks();
  mockGetDashboardOverview.mockResolvedValue(OVERVIEW);
  mockGetMyScore.mockResolvedValue({ master_score: 0, kpis: {} });
  mockGetScoreHistory.mockResolvedValue({ history: [] });
  mockGetInfluenceGraph.mockResolvedValue({ nodes: [], edges: [] });
  mockGetCausalGraph.mockResolvedValue({ causal_edges: [] });
});

function renderAt(path) {
  // AppProviders wraps a BrowserRouter, which reads window.location — set the path there
  // rather than nesting a second Router (React Router forbids that).
  window.history.pushState({}, "", path);
  return render(
    <AppProviders>
      <Dashboard />
    </AppProviders>,
  );
}

describe("Dashboard Graph tab routing", () => {
  it("renders the Graph view at /dashboard/graph, not Overview", async () => {
    renderAt("/dashboard/graph");
    // GraphView is the graph tab; its mode selector labels are stable.
    await waitFor(() => expect(screen.getByText(/Influence View/i)).toBeInTheDocument());
    // The overview payload must NOT be showing — that would be the reported bounce.
    expect(screen.queryByText(/Total Authors/i)).not.toBeInTheDocument();
  });

  it("loads graph data from the canonical user-authable routes, not the 401 legacy ones", async () => {
    renderAt("/dashboard/graph");
    // Both must be the rippletrace.js (canonical) mocks — if GraphView regressed to platform.js
    // these would never be called and the real 401-then-logout path would run in the browser.
    await waitFor(() => expect(mockGetInfluenceGraph).toHaveBeenCalled());
    expect(mockGetCausalGraph).toHaveBeenCalled();
  });

  it("renders Overview at /dashboard", async () => {
    renderAt("/dashboard");
    await waitFor(() => expect(screen.getByText(/Total Authors/i)).toBeInTheDocument());
    expect(screen.queryByText(/Influence View/i)).not.toBeInTheDocument();
  });
});
