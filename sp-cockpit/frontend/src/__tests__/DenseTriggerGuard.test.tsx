import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { describe, it, expect, vi, beforeEach } from "vitest";
import DenseTriggerGuard from "../components/DenseTriggerGuard";

describe("DenseTriggerGuard", () => {
  it("calls onConfirmed immediately for non-dense backends", () => {
    const onConfirmed = vi.fn();
    render(
      <DenseTriggerGuard repoPath="/repo" backend="zoekt" onConfirmed={onConfirmed}>
        {(trigger) => <button onClick={trigger}>Trigger</button>}
      </DenseTriggerGuard>
    );
    fireEvent.click(screen.getByText("Trigger"));
    expect(onConfirmed).toHaveBeenCalledTimes(1);
  });

  it("shows dialog when triggering dense — no POST fired yet", async () => {
    const fetchMock = vi.fn();
    vi.stubGlobal("fetch", fetchMock);

    const onConfirmed = vi.fn();
    render(
      <DenseTriggerGuard repoPath="/my/repo" backend="dense" onConfirmed={onConfirmed}>
        {(trigger) => <button onClick={trigger} data-testid="trigger-btn">Trigger</button>}
      </DenseTriggerGuard>
    );

    fireEvent.click(screen.getByTestId("trigger-btn"));

    // Dialog should be visible
    expect(screen.getByText(/This will rebuild the dense index/)).toBeInTheDocument();
    expect(screen.getByText(/\/my\/repo/)).toBeInTheDocument();

    // onConfirmed NOT called yet
    expect(onConfirmed).not.toHaveBeenCalled();
    // fetch NOT called
    expect(fetchMock).not.toHaveBeenCalled();

    vi.unstubAllGlobals();
  });

  it("fires onConfirmed after clicking Confirm in dialog", async () => {
    const fetchMock = vi.fn();
    vi.stubGlobal("fetch", fetchMock);

    const onConfirmed = vi.fn();
    render(
      <DenseTriggerGuard repoPath="/my/repo" backend="dense" onConfirmed={onConfirmed}>
        {(trigger) => <button onClick={trigger}>Trigger</button>}
      </DenseTriggerGuard>
    );

    fireEvent.click(screen.getByText("Trigger"));
    expect(screen.getByText(/This will rebuild the dense index/)).toBeInTheDocument();

    fireEvent.click(screen.getByText("Confirm"));

    await waitFor(() => expect(onConfirmed).toHaveBeenCalledTimes(1));
    // Dialog dismissed
    expect(screen.queryByText(/This will rebuild the dense index/)).not.toBeInTheDocument();

    vi.unstubAllGlobals();
  });

  it("cancels dialog without calling onConfirmed", () => {
    const onConfirmed = vi.fn();
    render(
      <DenseTriggerGuard repoPath="/my/repo" backend="dense" onConfirmed={onConfirmed}>
        {(trigger) => <button onClick={trigger}>Trigger</button>}
      </DenseTriggerGuard>
    );

    fireEvent.click(screen.getByText("Trigger"));
    fireEvent.click(screen.getByText("Cancel"));

    expect(onConfirmed).not.toHaveBeenCalled();
    expect(screen.queryByText(/This will rebuild the dense index/)).not.toBeInTheDocument();
  });
});
