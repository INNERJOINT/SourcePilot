import { render, screen } from "@testing-library/react";
import { describe, it, expect, vi, afterEach } from "vitest";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import RepoDetail from "../pages/RepoDetail";

describe("RepoDetail", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
    vi.restoreAllMocks();
  });

  it("shows error for non-numeric route id", () => {
    render(
      <MemoryRouter initialEntries={["/repos/abc"]}>
        <Routes>
          <Route path="/repos/:id" element={<RepoDetail />} />
        </Routes>
      </MemoryRouter>
    );
    expect(screen.getByText("Invalid repository ID")).toBeInTheDocument();
  });

  it("fetches repo detail for valid numeric id", async () => {
    const mockDetail = {
      repo: { id: 1, repo_path: "/test", backend: "zoekt", last_finished_at: null, last_duration_s: null, last_status: null, entity_count: null },
      jobs: [],
    };
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      json: async () => mockDetail,
      text: async () => "",
    });
    vi.stubGlobal("fetch", fetchMock);

    render(
      <MemoryRouter initialEntries={["/repos/1"]}>
        <Routes>
          <Route path="/repos/:id" element={<RepoDetail />} />
        </Routes>
      </MemoryRouter>
    );

    expect(fetchMock).toHaveBeenCalled();
    expect(fetchMock.mock.calls[0][0]).toContain("/repos/1");
  });
});
