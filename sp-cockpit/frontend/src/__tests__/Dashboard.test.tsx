import { render, screen, waitFor } from "@testing-library/react";
import { describe, it, expect, vi, afterEach, beforeEach } from "vitest";
import { MemoryRouter } from "react-router-dom";
import Dashboard from "../pages/Dashboard";

beforeEach(() => {
  vi.stubGlobal("ResizeObserver", class { observe() {} unobserve() {} disconnect() {} });
});

afterEach(() => {
  vi.restoreAllMocks();
});

describe("Dashboard", () => {
  it("renders without crashing when stats have null numeric fields", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue({
        ok: true,
        json: async () => ({
          total_events: null,
          qps: null,
          p50_ms: null,
          p95_ms: null,
          error_rate: null,
          buckets: [],
        }),
        text: async () => "",
      })
    );

    render(
      <MemoryRouter>
        <Dashboard />
      </MemoryRouter>
    );

    await waitFor(() => {
      expect(screen.getByText("QPS")).toBeInTheDocument();
    });

    // Verify null fields rendered as zero without crashing
    expect(screen.getByText("0.00%")).toBeInTheDocument();
  });
});
