/**
 * SearchHistory must refetch when its refreshToken changes.
 *
 * Regression: the "Recent SEO Analyses" panel fetched once on mount and never again, so a
 * freshly-run analysis (saved server-side) didn't appear until a full page reload — it read
 * "No saved searches yet" even though the row existed. The parent now bumps refreshToken after
 * a successful analyze; this pins that the panel refetches on that bump.
 */
import { render, screen, waitFor } from "@testing-library/react";

const { mockGetSearchHistory, mockDeleteSearchHistoryItem } = vi.hoisted(() => ({
  mockGetSearchHistory: vi.fn(),
  mockDeleteSearchHistoryItem: vi.fn(),
}));

vi.mock("../api/search.js", () => ({
  getSearchHistory: mockGetSearchHistory,
  deleteSearchHistoryItem: mockDeleteSearchHistoryItem,
}));

let SearchHistory;

beforeAll(async () => {
  SearchHistory = (await import("../components/app/SearchHistory.jsx")).default;
});

beforeEach(() => {
  vi.clearAllMocks();
  mockGetSearchHistory.mockResolvedValue({ items: [] });
});

describe("SearchHistory refreshToken", () => {
  it("refetches when refreshToken changes", async () => {
    const { rerender } = render(
      <SearchHistory searchType="seo_analysis" refreshToken={0} />,
    );
    await waitFor(() => expect(mockGetSearchHistory).toHaveBeenCalledTimes(1));

    // A new analysis was saved — parent bumps the token.
    mockGetSearchHistory.mockResolvedValue({
      items: [{ id: "h1", query: "my article" }],
    });
    rerender(<SearchHistory searchType="seo_analysis" refreshToken={1} />);

    await waitFor(() => expect(mockGetSearchHistory).toHaveBeenCalledTimes(2));
    expect(await screen.findByText(/my article/i)).toBeInTheDocument();
    expect(screen.queryByText(/No saved searches yet/i)).not.toBeInTheDocument();
  });

  it("does not refetch when refreshToken is unchanged across re-renders", async () => {
    const { rerender } = render(
      <SearchHistory searchType="seo_analysis" refreshToken={5} title="A" />,
    );
    await waitFor(() => expect(mockGetSearchHistory).toHaveBeenCalledTimes(1));
    // A cosmetic prop change with the same token must not trigger a refetch.
    rerender(<SearchHistory searchType="seo_analysis" refreshToken={5} title="B" />);
    expect(mockGetSearchHistory).toHaveBeenCalledTimes(1);
  });
});
