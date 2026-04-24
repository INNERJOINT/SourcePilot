import { render, waitFor } from "@testing-library/react";
import { describe, it, expect, vi, afterEach } from "vitest";
import { MemoryRouter } from "react-router-dom";
import EventList from "../pages/EventList";

afterEach(() => {
  vi.restoreAllMocks();
});

describe("EventList", () => {
  it("converts slow=true to 1 in the API call", async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      json: async () => ({ total: 0, items: [] }),
      text: async () => "",
    });
    vi.stubGlobal("fetch", fetchMock);

    render(
      <MemoryRouter initialEntries={["/events?slow=true"]}>
        <EventList />
      </MemoryRouter>
    );

    await waitFor(() => {
      expect(fetchMock).toHaveBeenCalled();
    });

    const url = fetchMock.mock.calls[0][0] as string;
    expect(url).toContain("slow=1");
    expect(url).not.toContain("slow=true");
  });
});
