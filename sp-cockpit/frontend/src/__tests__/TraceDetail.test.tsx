import { render, screen, waitFor } from "@testing-library/react";
import { describe, it, expect, vi, afterEach } from "vitest";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import TraceDetail from "../pages/TraceDetail";

afterEach(() => {
  vi.restoreAllMocks();
});

describe("TraceDetail", () => {
  it("clamps waterfall offset to non-negative values", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue({
        ok: true,
        json: async () => ({
          trace_id: "abc",
          event_count: 1,
          total_ms: 100,
          has_error: false,
          started_ms: 5000,
          events: [
            {
              id: 1,
              ts_ms: 4900, // before started_ms → would produce negative offset
              duration_ms: 10,
              event: "tool_call",
              tool: "zoekt",
              stage: null,
              status: "ok",
              slow: false,
              payload_json: "{}",
              trace_id: "abc",
            },
          ],
        }),
        text: async () => "",
      })
    );

    render(
      <MemoryRouter initialEntries={["/trace/abc"]}>
        <Routes>
          <Route path="/trace/:traceId" element={<TraceDetail />} />
        </Routes>
      </MemoryRouter>
    );

    await waitFor(() => {
      expect(screen.getByTestId("waterfall")).toBeInTheDocument();
    });

    const bar = screen.getByTestId("waterfall").querySelector(".bg-blue-400");
    expect(bar).toBeTruthy();
    const left = parseFloat((bar as HTMLElement).style.left);
    expect(left).toBeGreaterThanOrEqual(0);
  });
});
