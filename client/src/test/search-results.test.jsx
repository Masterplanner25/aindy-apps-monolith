import { render, screen } from "@testing-library/react";

import SearchResults from "../components/app/SearchResults";

const SAMPLE = [
  {
    title: "Cloud Security Inc",
    url: "https://sec.io",
    snippet: "cloud security platform",
    score: 0.76,
    metadata: { relevance: 1.0, quality_score: 0.4 },
  },
  {
    title: "Generic Co",
    url: null,
    snippet: "general services",
    score: 0.36,
    metadata: { relevance: 0.0, quality_score: 0.9 },
  },
];

describe("SearchResults", () => {
  it("renders nothing when there are no results", () => {
    const { container } = render(<SearchResults results={[]} />);
    expect(container.firstChild).toBeNull();
  });

  it("renders ranked items with titles and percentage scores", () => {
    render(<SearchResults results={SAMPLE} searchScore={0.76} title="Ranked Sources" />);

    expect(screen.getByText("Ranked Sources")).toBeInTheDocument();
    expect(screen.getByText("Cloud Security Inc")).toBeInTheDocument();
    expect(screen.getByText("Generic Co")).toBeInTheDocument();

    // 0.76 -> 76 rank badge, 0.36 -> 36
    expect(screen.getByText(/rank 76/i)).toBeInTheDocument();
    expect(screen.getByText(/rank 36/i)).toBeInTheDocument();
    // overall search score badge
    expect(screen.getByText(/overall 76/i)).toBeInTheDocument();
  });

  it("renders a link only when an item has a url", () => {
    render(<SearchResults results={SAMPLE} />);
    const link = screen.getByRole("link", { name: "Cloud Security Inc" });
    expect(link).toHaveAttribute("href", "https://sec.io");
    // the url-less item is text, not a link
    expect(screen.queryByRole("link", { name: "Generic Co" })).toBeNull();
  });
});
