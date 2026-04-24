import { render, screen } from "@testing-library/react";
import { vi, describe, it, expect, beforeEach } from "vitest";
import ProjectSelector, { ProjectProvider } from "../components/ProjectSelector";
import { api } from "../api/client";

vi.mock("../api/client", () => ({
  api: {
    projects: vi.fn(),
  },
}));

describe("ProjectSelector", () => {
  beforeEach(() => {
    localStorage.clear();
  });

  it("renders nothing when only 1 project", async () => {
    (api.projects as ReturnType<typeof vi.fn>).mockResolvedValue([
      { name: "ace", source_root: "/mnt/ace", repo_path: "/mnt/ace/.repo", zoekt_url: "http://localhost:6070" },
    ]);

    const { container } = render(
      <ProjectProvider>
        <ProjectSelector />
      </ProjectProvider>
    );

    // Wait for async fetch
    await screen.findByRole && await new Promise((r) => setTimeout(r, 50));
    expect(container.querySelector("select")).toBeNull();
  });

  it("renders dropdown when multiple projects", async () => {
    (api.projects as ReturnType<typeof vi.fn>).mockResolvedValue([
      { name: "ace", source_root: "/mnt/ace", repo_path: "/mnt/ace/.repo", zoekt_url: "http://localhost:6070" },
      { name: "beta", source_root: "/mnt/beta", repo_path: "/mnt/beta/.repo", zoekt_url: "http://localhost:6071" },
    ]);

    render(
      <ProjectProvider>
        <ProjectSelector />
      </ProjectProvider>
    );

    const select = await screen.findByRole("combobox");
    expect(select).toBeTruthy();
    expect(screen.getByText("ace")).toBeTruthy();
    expect(screen.getByText("beta")).toBeTruthy();
  });
});
