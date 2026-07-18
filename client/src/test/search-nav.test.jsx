import { render, screen } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";

import AppShell from "../components/shared/AppShell";
import { SystemProvider } from "../context/SystemContext";

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

// Guards against the previously-orphaned search nav links regressing. Targets the
// LIVE nav (AppShell) — the app renders AppShell's own <nav>, not the (deleted) Sidebar.
describe("Search nav links point at real /search routes (live AppShell nav)", () => {
  function renderShell() {
    render(
      <SystemProvider>
        <MemoryRouter initialEntries={["/dashboard"]}>
          <Routes>
            <Route element={<AppShell />}>
              <Route path="/dashboard" element={<div>Dashboard content</div>} />
            </Route>
          </Routes>
        </MemoryRouter>
      </SystemProvider>,
    );
  }

  it("links Research to /search/research", () => {
    renderShell();
    expect(screen.getByRole("link", { name: /^research$/i })).toHaveAttribute(
      "href",
      "/search/research",
    );
  });

  it("links AI SEO to /search/seo", () => {
    renderShell();
    expect(screen.getByRole("link", { name: /^ai seo$/i })).toHaveAttribute(
      "href",
      "/search/seo",
    );
  });

  it("links Lead Gen to /search/leadgen", () => {
    renderShell();
    expect(screen.getByRole("link", { name: /^lead gen$/i })).toHaveAttribute(
      "href",
      "/search/leadgen",
    );
  });
});
