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
        title="确认重建 Dense 索引"
        message={`将重建 dense 索引,可能覆盖现有 Qdrant collection。仓库路径: ${repoPath}。确认继续?`}
        onConfirm={handleConfirm}
        onCancel={() => setOpen(false)}
      />
    </>
  );
}
