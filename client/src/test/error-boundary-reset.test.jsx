/**
 * A tripped route boundary must not follow the user to the next page.
 *
 * Regression: ErrorBoundary had no reset path. Every route renders the same
 * RouteErrorBoundary component type at the same position in the tree, so React reuses the
 * instance across navigation — once hasError was true it stayed true, and the NEXT page
 * rendered "…encountered an error." too. The only escape offered was a full page reload,
 * which is exactly what users hit: one broken page appeared to break the whole app.
 */
import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import ErrorBoundary from "../components/shared/ErrorBoundary.jsx";

function Boom() {
  throw new Error("boom");
}

function Fine() {
  return <div>healthy page</div>;
}

describe("ErrorBoundary resetKey", () => {
  it("shows the fallback when a child throws", () => {
    render(
      <ErrorBoundary resetKey="/a" fallback={<div>fallback shown</div>}>
        <Boom />
      </ErrorBoundary>,
    );
    expect(screen.getByText("fallback shown")).toBeInTheDocument();
  });

  it("clears the error when resetKey changes (navigation)", () => {
    const { rerender } = render(
      <ErrorBoundary resetKey="/a" fallback={<div>fallback shown</div>}>
        <Boom />
      </ErrorBoundary>,
    );
    expect(screen.getByText("fallback shown")).toBeInTheDocument();

    // Navigate: same boundary instance, new route, healthy child.
    rerender(
      <ErrorBoundary resetKey="/b" fallback={<div>fallback shown</div>}>
        <Fine />
      </ErrorBoundary>,
    );

    expect(screen.getByText("healthy page")).toBeInTheDocument();
    expect(screen.queryByText("fallback shown")).not.toBeInTheDocument();
  });

  it("keeps the fallback while resetKey is unchanged", () => {
    const { rerender } = render(
      <ErrorBoundary resetKey="/a" fallback={<div>fallback shown</div>}>
        <Boom />
      </ErrorBoundary>,
    );
    rerender(
      <ErrorBoundary resetKey="/a" fallback={<div>fallback shown</div>}>
        <Fine />
      </ErrorBoundary>,
    );
    expect(screen.getByText("fallback shown")).toBeInTheDocument();
  });
});
