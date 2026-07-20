/**
 * Dashboard must render against the shapes the API actually returns.
 *
 * Reported: "the Dashboard is encountering an error and won't reload" — a deterministic
 * render failure, so reloading reproduces it. Every backend call succeeds (verified live:
 * /apps/dashboard/overview, /apps/scores/me and /apps/scores/me/history all 200), so the
 * failure is client-side handling of those payloads.
 *
 * The fixtures below are copied from real live responses on a fresh account, including the
 * envelope nesting, so this reproduces the user's exact conditions.
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

vi.mock("../api/platform.js", () => ({
  getDashboardOverview: mockGetDashboardOverview,
}));

vi.mock("../api/product.js", () => ({
  getMyScore: mockGetMyScore,
  recalculateScore: mockRecalculateScore,
  getScoreHistory: mockGetScoreHistory,
}));

// Real /apps/dashboard/overview response — note `overview` is nested under `data`.
const LIVE_OVERVIEW = {
  status: "success",
  data: {
    status: "ok",
    overview: {
      system_timestamp: "2026-07-20T12:30:04.179171+00:00",
      author_count: 0,
      recent_authors: [],
      recent_ripples: [],
    },
  },
};

const LIVE_SCORE = {
  user_id: "aa4dcf66-14dd-422f-8d2d-d849fc9c6dfd",
  master_score: 0.0,
  kpis: {
    execution_speed: 0.0,
    decision_efficiency: 0.0,
    ai_productivity_boost: 0.0,
    focus_quality: 0.0,
    masterplan_progress: 0.0,
  },
};

const LIVE_HISTORY = { user_id: "aa4dcf66-14dd-422f-8d2d-d849fc9c6dfd", history: [] };

let Dashboard;

beforeAll(async () => {
  Dashboard = (await import("../components/app/Dashboard.jsx")).default;
});

beforeEach(() => {
  vi.clearAllMocks();
  mockGetDashboardOverview.mockResolvedValue(LIVE_OVERVIEW);
  mockGetMyScore.mockResolvedValue(LIVE_SCORE);
  mockGetScoreHistory.mockResolvedValue(LIVE_HISTORY);
});

describe("Dashboard against live API shapes", () => {
  it("renders without throwing on a fresh account", async () => {
    render(
      <AppProviders>
        <Dashboard />
      </AppProviders>,
    );
    await waitFor(() => expect(mockGetDashboardOverview).toHaveBeenCalled());
    expect(screen.getByText(/Infinity Score/i)).toBeInTheDocument();
  });

  it("shows the overview payload rather than a permanent loading state", async () => {
    render(
      <AppProviders>
        <Dashboard />
      </AppProviders>,
    );
    // `overview` is nested under `data` — reading it off the top level silently yields
    // undefined and pins OverviewTab on "Loading dashboard..." forever.
    await waitFor(() =>
      expect(screen.queryByText(/Loading dashboard/i)).not.toBeInTheDocument(),
    );
    expect(screen.getByText(/Total Authors/i)).toBeInTheDocument();
  });

  it("surfaces a failed overview request instead of hanging on Loading", async () => {
    // Previously uncaught: the rejection escaped as an unhandled promise rejection and the
    // tab sat on "Loading dashboard..." indefinitely, which reads as a hang, not a failure.
    mockGetDashboardOverview.mockRejectedValue(new Error("boom"));
    render(
      <AppProviders>
        <Dashboard />
      </AppProviders>,
    );
    await waitFor(() =>
      expect(screen.getByText(/Could not load the dashboard overview/i)).toBeInTheDocument(),
    );
    expect(screen.queryByText(/Loading dashboard/i)).not.toBeInTheDocument();
    // The rest of the page must still render — one failed panel is not a dead page.
    expect(screen.getByText(/Infinity Score/i)).toBeInTheDocument();
  });
});
