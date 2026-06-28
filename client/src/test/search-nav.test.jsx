import { fireEvent, render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";

import Sidebar from "../components/shared/Sidebar";

vi.mock("../context/AuthContext", async (importOriginal) => {
  const actual = await importOriginal();
  return {
    ...actual,
    useAuth: () => ({
      token: null,
      user: { is_admin: false },
      isAdmin: false,
      isAuthenticated: true,
      login: vi.fn(),
      register: vi.fn(),
      logout: vi.fn(),
      setToken: vi.fn(),
    }),
  };
});

vi.mock("../api/agent.js", async (importOriginal) => {
  const actual = await importOriginal();
  return {
    ...actual,
    getAgentRuns: vi.fn().mockResolvedValue([]),
  };
});

describe("Intelligence nav links point at real /search routes", () => {
  function openIntelligence() {
    render(
      <MemoryRouter>
        <Sidebar />
      </MemoryRouter>,
    );
    fireEvent.click(screen.getByRole("button", { name: /intelligence/i }));
  }

  it("links Research Engine to /search/research", () => {
    openIntelligence();
    expect(screen.getByRole("link", { name: /research engine/i })).toHaveAttribute(
      "href",
      "/search/research",
    );
  });

  it("links SEO Tool to /search/seo (previously orphaned)", () => {
    openIntelligence();
    expect(screen.getByRole("link", { name: /seo tool/i })).toHaveAttribute(
      "href",
      "/search/seo",
    );
  });

  it("links LeadGen to /search/leadgen", () => {
    openIntelligence();
    expect(screen.getByRole("link", { name: /leadgen/i })).toHaveAttribute(
      "href",
      "/search/leadgen",
    );
  });
});
