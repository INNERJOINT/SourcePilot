import { useState } from "react";
import type { BackendName } from "../api/indexing";
import ConfirmDialog from "./ConfirmDialog";

interface DenseTriggerGuardProps {
  repoPath: string;
  backend: BackendName;
  onConfirmed: () => void;
  children: (trigger: () => void) => React.ReactNode;
}

export default function DenseTriggerGuard({
  repoPath,
  backend,
  onConfirmed,
  children,
}: DenseTriggerGuardProps) {
  const [open, setOpen] = useState(false);

  function trigger() {
    if (backend === "dense") {
      setOpen(true);
    } else {
      onConfirmed();
    }
  }

  function handleConfirm() {
    setOpen(false);
    onConfirmed();
  }

  return (
    <>
      {children(trigger)}
      <ConfirmDialog
        open={open}
        title="Confirm Rebuild Dense Index"
        message={`This will rebuild the dense index and may overwrite the existing Qdrant collection. Repository path: ${repoPath}. Confirm?`}
        onConfirm={handleConfirm}
        onCancel={() => setOpen(false)}
      />
    </>
  );
}
