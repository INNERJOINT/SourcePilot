import { render, screen, act } from "@testing-library/react";
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import LogViewer from "../components/LogViewer";

describe("LogViewer", () => {
  beforeEach(() => {
    vi.useFakeTimers();
  });

  afterEach(() => {
    vi.useRealTimers();
    vi.restoreAllMocks();
  });

  it("starts polling on mount", async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      json: async () => ({ content: "line1\n", offset: 0, next_offset: 6, eof: false }),
      text: async () => "",
    });
    vi.stubGlobal("fetch", fetchMock);

    await act(async () => {
      render(<LogViewer jobId={42} />);
    });

    expect(fetchMock).toHaveBeenCalledTimes(1);
    expect(fetchMock.mock.calls[0][0]).toContain("/api/indexing/jobs/42/log");

    // Advance timer to trigger second poll
    await act(async () => {
      vi.advanceTimersByTime(2500);
    });
    expect(fetchMock).toHaveBeenCalledTimes(2);

    vi.unstubAllGlobals();
  });

  it("stops polling on eof:true", async () => {
    let callCount = 0;
    const fetchMock = vi.fn().mockImplementation(() => {
      callCount++;
      const eof = callCount >= 2;
      return Promise.resolve({
        ok: true,
        json: async () => ({ content: `line${callCount}\n`, offset: (callCount - 1) * 6, next_offset: callCount * 6, eof }),
        text: async () => "",
      });
    });
    vi.stubGlobal("fetch", fetchMock);

    await act(async () => {
      render(<LogViewer jobId={10} />);
    });
    // 1st poll
    await act(async () => {
      vi.advanceTimersByTime(2500);
    });
    // 2nd poll → eof:true → interval cleared
    const countAfterEof = fetchMock.mock.calls.length;

    await act(async () => {
      vi.advanceTimersByTime(10000);
    });
    // No more calls after eof
    expect(fetchMock.mock.calls.length).toBe(countAfterEof);
    expect(screen.getByText(/Finished/)).toBeInTheDocument();

    vi.unstubAllGlobals();
  });

  it("stops polling on unmount", async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      json: async () => ({ content: "", offset: 0, next_offset: 0, eof: false }),
      text: async () => "",
    });
    vi.stubGlobal("fetch", fetchMock);

    let unmount: () => void;
    await act(async () => {
      const result = render(<LogViewer jobId={99} />);
      unmount = result.unmount;
    });

    const callsAtUnmount = fetchMock.mock.calls.length;
    unmount!();

    await act(async () => {
      vi.advanceTimersByTime(10000);
    });

    // No new fetches after unmount
    expect(fetchMock.mock.calls.length).toBe(callsAtUnmount);

    vi.unstubAllGlobals();
  });

  it("appends lines to pre element", async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      json: async () => ({ content: "hello\nworld\n", offset: 0, next_offset: 12, eof: false }),
      text: async () => "",
    });
    vi.stubGlobal("fetch", fetchMock);

    await act(async () => {
      render(<LogViewer jobId={5} />);
    });

    const pre = screen.getByTestId("log-pre");
    expect(pre.textContent).toContain("hello");
    expect(pre.textContent).toContain("world");

    vi.unstubAllGlobals();
  });

  it("stops polling on fetch error", async () => {
    let callCount = 0;
    const fetchMock = vi.fn().mockImplementation(() => {
      callCount++;
      if (callCount === 1) {
        return Promise.resolve({
          ok: true,
          json: async () => ({ content: "ok\n", offset: 0, next_offset: 3, eof: false }),
          text: async () => "",
        });
      }
      return Promise.reject(new Error("network failure"));
    });
    vi.stubGlobal("fetch", fetchMock);

    await act(async () => {
      render(<LogViewer jobId={7} />);
    });

    // 1st poll succeeds; advance to trigger 2nd poll which errors
    await act(async () => {
      vi.advanceTimersByTime(2500);
    });

    const callsAfterError = fetchMock.mock.calls.length;

    // Advance more — no further polls should happen
    await act(async () => {
      vi.advanceTimersByTime(10000);
    });

    expect(fetchMock.mock.calls.length).toBe(callsAfterError);
    expect(screen.getByText(/network failure/)).toBeInTheDocument();

    vi.unstubAllGlobals();
  });
});
