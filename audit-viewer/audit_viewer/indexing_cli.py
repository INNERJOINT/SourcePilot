"""CLI callback for indexing job lifecycle management.

Usage:
    python -m audit_viewer.indexing_cli start --repo-path /path/to/repo --backend dense [--log-path /path/to.log]
    python -m audit_viewer.indexing_cli finish --job-id 42 --status success --exit-code 0

Environment variables:
    INDEXING_INTERNAL_TOKEN  — Bearer token for X-Indexing-Internal-Token header
    INDEXING_API_URL         — Override API URL (default http://localhost:9100)
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path


# ---------------------------------------------------------------------------
# HTTP helpers (uses httpx)
# ---------------------------------------------------------------------------

def _make_headers() -> dict[str, str]:
    token = os.getenv("INDEXING_INTERNAL_TOKEN", "")
    headers: dict[str, str] = {}
    if token:
        headers["X-Indexing-Internal-Token"] = token
    return headers


def _post_with_retry(url: str, payload: dict, timeout: float = 30.0, retries: int = 3):
    """POST JSON with exponential backoff retries. Returns (response, None) or (None, exc)."""
    import httpx

    headers = _make_headers()
    last_exc: Exception | None = None
    for attempt in range(retries):
        if attempt > 0:
            time.sleep(2 ** (attempt - 1))  # 1s, 2s, …
        try:
            resp = httpx.post(url, json=payload, headers=headers, timeout=timeout)
            return resp, None
        except Exception as exc:  # noqa: BLE001
            last_exc = exc
    return None, last_exc


# ---------------------------------------------------------------------------
# Subcommands
# ---------------------------------------------------------------------------

def cmd_start(args: argparse.Namespace) -> int:
    """POST to /api/indexing/jobs/internal-start, print JOB_ID=<id>."""
    url = f"{args.api_url.rstrip('/')}/api/indexing/jobs/internal-start"
    payload: dict = {
        "repo_path": args.repo_path,
        "backend": args.backend,
    }
    if args.log_path:
        payload["log_path"] = args.log_path

    resp, exc = _post_with_retry(url, payload)
    if exc is not None:
        print(f"ERROR: network failure contacting {url}: {exc}", file=sys.stderr)
        return 1

    if resp.status_code == 409:
        # Already running — print existing job id and exit 2
        try:
            data = resp.json()
            existing_id = data.get("job_id") or data.get("id")
            print(f"JOB_ID={existing_id}")
        except Exception:
            print(f"JOB_ID=", file=sys.stderr)
        return 2

    if not resp.is_success:
        print(f"ERROR: unexpected status {resp.status_code}: {resp.text}", file=sys.stderr)
        return 1

    try:
        data = resp.json()
        job_id = data.get("job_id") or data.get("id")
        print(f"JOB_ID={job_id}")
    except Exception as exc:
        print(f"ERROR: failed to parse response: {exc}", file=sys.stderr)
        return 1

    return 0


def cmd_finish(args: argparse.Namespace) -> int:
    """POST to /api/indexing/jobs/{id}/finish. On network failure write fallback JSON."""
    url = f"{args.api_url.rstrip('/')}/api/indexing/jobs/{args.job_id}/finish"
    payload: dict = {
        "status": args.status,
        "exit_code": args.exit_code,
    }

    resp, exc = _post_with_retry(url, payload)
    if exc is not None or (resp is not None and not resp.is_success):
        error_detail = str(exc) if exc else f"status {resp.status_code}"
        print(f"WARN: finish POST failed ({error_detail}), writing fallback", file=sys.stderr)
        _write_fallback(args.job_id, payload)
        return 0  # non-fatal — reaper will pick it up

    return 0


def _write_fallback(job_id: int | str, payload: dict) -> None:
    fallback_dir = Path(".omc") / "indexing-fallback"
    fallback_dir.mkdir(parents=True, exist_ok=True)
    fallback_file = fallback_dir / f"{job_id}.json"
    fallback_data = {"job_id": job_id, **payload, "fallback_ts": int(time.time())}
    fallback_file.write_text(json.dumps(fallback_data, indent=2))
    print(f"WARN: fallback written to {fallback_file}", file=sys.stderr)


# ---------------------------------------------------------------------------
# Argument parser
# ---------------------------------------------------------------------------

def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m audit_viewer.indexing_cli",
        description="Indexing job lifecycle CLI",
    )
    parser.add_argument(
        "--api-url",
        default=os.getenv("INDEXING_API_URL", "http://localhost:9100"),
        help="Base URL of audit-viewer API (default: http://localhost:9100)",
    )

    sub = parser.add_subparsers(dest="command", required=True)

    # start
    p_start = sub.add_parser("start", help="Register the start of an indexing job")
    p_start.add_argument("--repo-path", required=True, help="Absolute path to the repository")
    p_start.add_argument(
        "--backend", required=True, choices=["zoekt", "dense", "graph"],
        help="Indexing backend",
    )
    p_start.add_argument("--log-path", default=None, help="Path to the log file for this job")

    # finish
    p_finish = sub.add_parser("finish", help="Report completion of an indexing job")
    p_finish.add_argument("--job-id", required=True, help="Job ID returned by start")
    p_finish.add_argument(
        "--status", required=True, choices=["success", "fail", "warn"],
        help="Terminal status",
    )
    p_finish.add_argument("--exit-code", type=int, default=0, help="Process exit code")

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.command == "start":
        return cmd_start(args)
    if args.command == "finish":
        return cmd_finish(args)
    parser.print_help()
    return 1


if __name__ == "__main__":
    sys.exit(main())
