import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { describe, it, expect, vi, afterEach } from "vitest";
import AddRepoModal from "../components/AddRepoModal";

function mockFetch(response: unknown) {
  return vi.fn().mockResolvedValue({
    ok: true,
    json: async () => response,
    text: async () => "",
  });
}

describe("AddRepoModal", () => {
  it("renders nothing when closed", () => {
    render(<AddRepoModal open={false} onClose={vi.fn()} onAdded={vi.fn()} />);
    expect(screen.queryByText("添加仓库 / 触发索引")).not.toBeInTheDocument();
  });

  it("renders modal when open", () => {
    render(<AddRepoModal open={true} onClose={vi.fn()} onAdded={vi.fn()} />);
    expect(screen.getByText("添加仓库 / 触发索引")).toBeInTheDocument();
  });

  it("submits one POST per checked backend", async () => {
    const fetchMock = mockFetch({ id: 1, status: "queued" });
    vi.stubGlobal("fetch", fetchMock);

    const onAdded = vi.fn();
    render(<AddRepoModal open={true} onClose={vi.fn()} onAdded={onAdded} />);

    // Fill in repo path
    fireEvent.change(screen.getByPlaceholderText("/path/to/repo"), {
      target: { value: "/test/repo" },
    });

    // zoekt is pre-checked; also check dense
    fireEvent.click(screen.getByTestId("checkbox-dense"));

    fireEvent.click(screen.getByText("提交"));

    await waitFor(() => expect(onAdded).toHaveBeenCalledTimes(1));

    // Should have posted once for zoekt, once for dense
    const postCalls = fetchMock.mock.calls.filter(
      (c: unknown[]) => typeof c[1] === "object" && (c[1] as RequestInit).method === "POST"
    );
    expect(postCalls.length).toBe(2);

    const bodies = postCalls.map((c: unknown[]) => JSON.parse((c[1] as RequestInit).body as string));
    const backends = bodies.map((b: { backend: string }) => b.backend).sort();
    expect(backends).toEqual(["dense", "zoekt"]);

    vi.unstubAllGlobals();
  });

  it("submits only checked backends", async () => {
    const fetchMock = mockFetch({ id: 2, status: "queued" });
    vi.stubGlobal("fetch", fetchMock);

    const onAdded = vi.fn();
    render(<AddRepoModal open={true} onClose={vi.fn()} onAdded={onAdded} />);

    fireEvent.change(screen.getByPlaceholderText("/path/to/repo"), {
      target: { value: "/test/repo2" },
    });

    // Uncheck zoekt, check structural only
    fireEvent.click(screen.getByTestId("checkbox-zoekt"));
    fireEvent.click(screen.getByTestId("checkbox-structural"));

    fireEvent.click(screen.getByText("提交"));

    await waitFor(() => expect(onAdded).toHaveBeenCalledTimes(1));

    const postCalls = fetchMock.mock.calls.filter(
      (c: unknown[]) => typeof c[1] === "object" && (c[1] as RequestInit).method === "POST"
    );
    expect(postCalls.length).toBe(1);
    const body = JSON.parse((postCalls[0][1] as RequestInit).body as string);
    expect(body.backend).toBe("structural");

    vi.unstubAllGlobals();
  });

  it("does NOT call onAdded when all jobs fail", async () => {
    const fetchMock = vi.fn().mockRejectedValue(new Error("HTTP 500"));
    vi.stubGlobal("fetch", fetchMock);

    const onAdded = vi.fn();
    render(<AddRepoModal open={true} onClose={vi.fn()} onAdded={onAdded} />);

    fireEvent.change(screen.getByPlaceholderText("/path/to/repo"), {
      target: { value: "/test/repo" },
    });
    fireEvent.click(screen.getByText("提交"));

    await waitFor(() => expect(screen.getByText(/✗ zoekt/)).toBeInTheDocument());
    expect(onAdded).not.toHaveBeenCalled();

    vi.unstubAllGlobals();
  });
});
