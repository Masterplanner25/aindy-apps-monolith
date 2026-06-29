import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";

import { AppProviders } from "./utils";

// Admin gate: RippleTraceViewer renders <AdminAccessRequired/> unless isAdmin.
vi.mock("../context/AuthContext", async (importOriginal) => {
  const actual = await importOriginal();
  return { ...actual, useAuth: () => ({ isAdmin: true }) };
});

const {
  mockGetRippleTraceGraph,
  mockGetCausalChain,
  mockGetDropPointNarrative,
  mockGetDropPointPrediction,
  mockGetDropPointRecommendation,
  mockGetLearningStats,
} = vi.hoisted(() => ({
  mockGetRippleTraceGraph: vi.fn(),
  mockGetCausalChain: vi.fn(),
  mockGetDropPointNarrative: vi.fn(),
  mockGetDropPointPrediction: vi.fn(),
  mockGetDropPointRecommendation: vi.fn(),
  mockGetLearningStats: vi.fn(),
}));

vi.mock("../api/rippletrace.js", () => ({
  getRippleTraceGraph: mockGetRippleTraceGraph,
  getCausalChain: mockGetCausalChain,
  getDropPointNarrative: mockGetDropPointNarrative,
  getDropPointPrediction: mockGetDropPointPrediction,
  getDropPointRecommendation: mockGetDropPointRecommendation,
  getLearningStats: mockGetLearningStats,
}));

import RippleTraceViewer from "../components/platform/RippleTraceViewer";

// An execution trace mixing system events, a memory-node target, and an async branch.
const EXECUTION_GRAPH = {
  nodes: [
    { id: "e1", node_kind: "system_event", type: "flow.run", source: "flow", timestamp: "2026-01-01T12:00:00Z", payload: { drop_point_id: "drop-1" } },
    { id: "e2", node_kind: "system_event", type: "memory.read", source: "memory", timestamp: "2026-01-01T12:00:01Z", payload: {} },
    { id: "e3", node_kind: "system_event", type: "llm.call", source: "agent", timestamp: "2026-01-01T12:00:02Z", payload: {} },
    { id: "e4", node_kind: "system_event", type: "execution.completed", source: "flow", timestamp: "2026-01-01T12:00:03Z", payload: {} },
    { id: "m1", node_kind: "memory_node", type: "outcome", source: "memory", timestamp: "2026-01-01T12:00:04Z", payload: { content: "captured outcome" } },
  ],
  edges: [
    { id: "x1", source: "e1", target: "e2", target_kind: "system_event", relationship_type: "related_to", weight: 1 },
    { id: "x2", source: "e1", target: "e3", target_kind: "system_event", relationship_type: "async_child", weight: 1 },
    { id: "x3", source: "e3", target: "e4", target_kind: "system_event", relationship_type: "derived", weight: 1 },
    { id: "x4", source: "e2", target: "m1", target_kind: "memory_node", relationship_type: "stored_as_memory", weight: 1 },
  ],
  root_event: { id: "e1", node_kind: "system_event", type: "flow.run" },
  terminal_events: [{ id: "e4", node_kind: "system_event", type: "execution.completed" }],
  ripple_span: { node_count: 5, edge_count: 4, depth: 2, terminal_count: 1 },
  insights: {
    summary: "Root: flow.run. 1 terminal effects.",
    root_cause: { type: "flow.run" },
    dominant_path: [{ type: "flow.run" }, { type: "llm.call" }, { type: "execution.completed" }],
    failure_clusters: [],
    recommendations: ["Monitor the dominant path and terminal events for the next run."],
  },
};

async function loadGraph(graph) {
  mockGetRippleTraceGraph.mockResolvedValue(graph);
  render(
    <AppProviders>
      <RippleTraceViewer />
    </AppProviders>,
  );
  fireEvent.change(screen.getByPlaceholderText(/enter trace_id/i), {
    target: { value: "trace-123" },
  });
  fireEvent.click(screen.getByRole("button", { name: /load trace/i }));
  await waitFor(() => expect(mockGetRippleTraceGraph).toHaveBeenCalledWith("trace-123"));
}

describe("RippleTraceViewer", () => {
  beforeEach(() => {
    window.localStorage.clear();
    [
      mockGetRippleTraceGraph,
      mockGetCausalChain,
      mockGetDropPointNarrative,
      mockGetDropPointPrediction,
      mockGetDropPointRecommendation,
      mockGetLearningStats,
    ].forEach((fn) => fn.mockReset());
    mockGetLearningStats.mockResolvedValue({});
  });

  it("shows the empty state before a trace is loaded", () => {
    render(
      <AppProviders>
        <RippleTraceViewer />
      </AppProviders>,
    );
    expect(screen.getByText(/no trace loaded/i)).toBeInTheDocument();
    expect(screen.getByPlaceholderText(/enter trace_id/i)).toBeInTheDocument();
  });

  it("renders the execution graph including a memory-node target", async () => {
    await loadGraph(EXECUTION_GRAPH);

    // The memory artifact is reconstructed as a node in the graph.
    expect(await screen.findByText("outcome")).toBeInTheDocument();
    expect(screen.getAllByText("memory_node").length).toBeGreaterThan(0);
    // The event -> memory causal edge is rendered.
    expect(screen.getByText("stored_as_memory")).toBeInTheDocument();
    // System-event nodes are present too.
    expect(screen.getAllByText("flow.run").length).toBeGreaterThan(0);
  });

  it("renders the async branch edge", async () => {
    await loadGraph(EXECUTION_GRAPH);
    expect(await screen.findByText("async_child")).toBeInTheDocument();
    expect(screen.getByText("derived")).toBeInTheDocument();
  });

  it("summarizes span, root, and terminal events from the execution graph", async () => {
    await loadGraph(EXECUTION_GRAPH);

    // Trace summary reflects the ripple_span metrics.
    const nodesCard = (await screen.findByText("Nodes")).parentElement;
    expect(within(nodesCard).getByText("5")).toBeInTheDocument();
    expect(screen.getByText("Edges")).toBeInTheDocument();
    expect(screen.getByText("Terminal Events")).toBeInTheDocument();

    // Root and terminal badges come from the reconstructed graph.
    expect(screen.getAllByText(/Root: flow\.run/).length).toBeGreaterThan(0);
    expect(screen.getAllByText(/Terminal: execution\.completed/).length).toBeGreaterThan(0);
  });

  it("surfaces a load error", async () => {
    mockGetRippleTraceGraph.mockRejectedValue(new Error("Trace unavailable"));
    render(
      <AppProviders>
        <RippleTraceViewer />
      </AppProviders>,
    );
    fireEvent.change(screen.getByPlaceholderText(/enter trace_id/i), {
      target: { value: "bad-trace" },
    });
    fireEvent.click(screen.getByRole("button", { name: /load trace/i }));
    expect(await screen.findByText("Trace unavailable")).toBeInTheDocument();
  });
});
