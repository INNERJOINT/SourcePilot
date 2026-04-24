import { render, screen } from "@testing-library/react";
import { describe, it, expect, vi, afterEach } from "vitest";
import { MemoryRouter } from "react-router-dom";
import App from "../App";

afterEach(() => {
  vi.restoreAllMocks();
});

describe("App", () => {
  it("shows 404 for unknown routes", () => {
    // Stub fetch to prevent actual API calls from child pages
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue({
      ok: true,
      json: async () => ({}),
      text: async () => "",
    }));

    render(
      <MemoryRouter initialEntries={["/unknown-page"]}>
        <App />
      </MemoryRouter>
    );

    expect(screen.getByText("Page not found")).toBeInTheDocument();
    expect(screen.getByText("Back to Dashboard")).toBeInTheDocument();
  });
});
