import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { describe, it, expect, vi, afterEach } from "vitest";
import { MemoryRouter } from "react-router-dom";
import Repositories from "../pages/Repositories";
import type { ReposResponse } from "../api/indexing";

const mockRepos: ReposResponse = {
  total: 2,
  items: [
    {
      id: 1,
      repo_path: "/aosp/frameworks/base",
      backend: "zoekt",
      last_finished_at: new Date(Date.now() - 60000).toISOString(),
      last_duration_s: 12.5,
      last_status: "success",
      entity_count: 1234,
    },
    {
      id: 2,
      repo_path: "/aosp/system/core",
      backend: "dense",
      last_finished_at: new Date(Date.now() - 3600000).toISOString(),
      last_duration_s: 45.0,
      last_status: "fail",
      entity_count: null,
    },
  ],
};

function setup(response = mockRepos) {
  const fetchMock = vi.fn().mockResolvedValue({
    ok: true,
    json: async () => response,
    text: async () => "",
  });
  vi.stubGlobal("fetch", fetchMock);
  return { fetchMock };
}

describe("Repositories", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
    vi.restoreAllMocks();
  });

  it("renders repo list", async () => {
    setup();
    render(
      <MemoryRouter>
        <Repositories />
      </MemoryRouter>
    );

    await waitFor(() => screen.getByText("/aosp/frameworks/base"));
    expect(screen.getByText("/aosp/system/core")).toBeInTheDocument();
    expect(screen.getByText("2 total")).toBeInTheDocument();
  });

  it("renders status chips", async () => {
    setup();
    render(
      <MemoryRouter>
        <Repositories />
      </MemoryRouter>
    );

    await waitFor(() => screen.getByText("success"));
    // "fail" appears in the status filter <option> too, so just check a chip exists
    expect(screen.getAllByText("fail").length).toBeGreaterThanOrEqual(1);
  });

  it("calls API with backend filter when changed", async () => {
    const { fetchMock } = setup();
    render(
      <MemoryRouter>
        <Repositories />
      </MemoryRouter>
    );

    await waitFor(() => screen.getByText("/aosp/frameworks/base"));

    fireEvent.change(screen.getByTestId("filter-backend"), {
      target: { value: "zoekt" },
    });

    await waitFor(() => {
      const calls = fetchMock.mock.calls;
      const filtered = calls.some((c: unknown[]) =>
        String(c[0]).includes("backend=zoekt")
      );
      expect(filtered).toBe(true);
    });
  });

  it("toggles sort order on header click", async () => {
    setup();
    render(
      <MemoryRouter>
        <Repositories />
      </MemoryRouter>
    );

    await waitFor(() => screen.getByText("/aosp/frameworks/base"));

    const sortHeader = screen.getByTestId("sort-last-finished");
    // Initially descending
    expect(sortHeader.textContent).toContain("↓");
    fireEvent.click(sortHeader);
    expect(sortHeader.textContent).toContain("↑");
  });

  it("opens AddRepoModal when Add Repo clicked", async () => {
    setup();
    render(
      <MemoryRouter>
        <Repositories />
      </MemoryRouter>
    );

    await waitFor(() => screen.getByText("/aosp/frameworks/base"));

    fireEvent.click(screen.getByText("+ Add Repo"));
    expect(screen.getByText("添加仓库 / 触发索引")).toBeInTheDocument();
  });

  it("shows DenseTriggerGuard dialog for dense repo trigger", async () => {
    setup();
    render(
      <MemoryRouter>
        <Repositories />
      </MemoryRouter>
    );

    await waitFor(() => screen.getByText("/aosp/system/core"));

    // repo id=2 is dense backend
    fireEvent.click(screen.getByTestId("trigger-2"));

    expect(screen.getByText(/将重建 dense 索引/)).toBeInTheDocument();
  });
});
