import { useEffect, useRef, useState } from "react";
import { indexingApi } from "../api/indexing";

interface LogViewerProps {
  jobId: number;
}

export default function LogViewer({ jobId }: LogViewerProps) {
  const [lines, setLines] = useState<string[]>([]);
  const [finished, setFinished] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const cursorRef = useRef(0);
  const intervalRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const mountedRef = useRef(true);
  const preRef = useRef<HTMLPreElement>(null);

  useEffect(() => {
    mountedRef.current = true;
    cursorRef.current = 0;

    async function poll() {
      try {
        const page = await indexingApi.getJobLog(jobId, cursorRef.current);
        if (!mountedRef.current) return;
        if (page.content.length > 0) {
          const newLines = page.content.split("\n").filter(l => l.length > 0);
          if (newLines.length > 0) {
            setLines((prev) => [...prev, ...newLines]);
          }
          cursorRef.current = page.next_offset;
        }
        if (page.eof) {
          setFinished(true);
          if (intervalRef.current !== null) {
            clearInterval(intervalRef.current);
            intervalRef.current = null;
          }
        }
      } catch (e) {
        if (mountedRef.current) {
          setError(String(e));
          if (intervalRef.current !== null) {
            clearInterval(intervalRef.current);
            intervalRef.current = null;
          }
        }
      }
    }

    poll();
    intervalRef.current = setInterval(poll, 2500);

    return () => {
      mountedRef.current = false;
      if (intervalRef.current !== null) {
        clearInterval(intervalRef.current);
        intervalRef.current = null;
      }
    };
  }, [jobId]);

  // Auto-scroll to bottom
  useEffect(() => {
    if (preRef.current) {
      preRef.current.scrollTop = preRef.current.scrollHeight;
    }
  }, [lines]);

  return (
    <div className="space-y-2">
      {error && <div className="p-2 bg-red-100 text-red-700 rounded text-sm">{error}</div>}
      <pre
        ref={preRef}
        data-testid="log-pre"
        className="bg-slate-900 text-green-300 text-xs p-4 rounded overflow-auto max-h-96 whitespace-pre-wrap"
      >
        {lines.join("\n")}
        {lines.length === 0 && !finished && !error && (
          <span className="text-slate-500">Loading...</span>
        )}
        {lines.length === 0 && finished && (
          <span className="text-slate-500">No log output</span>
        )}
      </pre>
      {finished && (
        <div className="text-sm text-slate-500 text-right">✓ Finished</div>
      )}
    </div>
  );
}
