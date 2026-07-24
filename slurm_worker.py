#!/usr/bin/env python3
"""Run one manifest item from an IDtracker post-processing SLURM array."""
from __future__ import annotations

import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path


def write_json_atomic(destination: Path, payload: dict) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_name(
        destination.name + f".partial.{os.getpid()}"
    )
    temporary.write_text(
        json.dumps(payload, indent=2, sort_keys=True),
        encoding="utf-8",
    )
    temporary.replace(destination)


def main() -> None:
    if len(sys.argv) != 2:
        raise SystemExit("Usage: slurm_worker.py MANIFEST.json")
    manifest_path = Path(sys.argv[1])
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    task_index = int(os.environ["SLURM_ARRAY_TASK_ID"])
    item = manifest["items"][task_index]
    status_path = Path(manifest["status_folder"]) / f"{task_index:05d}.json"
    started_at = datetime.now(timezone.utc).isoformat()
    command = [
        manifest["remote_python"],
        manifest["processor_path"],
        *item["processor_args"],
    ]
    environment = os.environ.copy()
    matplotlib_cache = (
        Path(manifest["matplotlib_cache"]) / f"task_{task_index:05d}"
    )
    matplotlib_cache.mkdir(parents=True, exist_ok=True)
    environment["MPLCONFIGDIR"] = str(matplotlib_cache)
    try:
        result = subprocess.run(
            command,
            text=True,
            capture_output=True,
            env=environment,
            check=False,
        )
        if result.stdout:
            print(result.stdout, end="")
        if result.stderr:
            print(result.stderr, end="", file=sys.stderr)
        if result.returncode:
            raise RuntimeError(
                f"processor exited with status {result.returncode}"
            )
        if (
            not Path(item["source_result_file"]).is_file()
            or Path(item["source_result_file"]).stat().st_size == 0
        ):
            raise RuntimeError("processor did not create the expected CSV")
        if (
            not Path(item["plot_output"]).is_file()
            or Path(item["plot_output"]).stat().st_size == 0
        ):
            raise RuntimeError("processor did not create the expected PDF")
        write_json_atomic(
            status_path,
            {
                "status": "SUCCESS",
                "task_index": task_index,
                "qc_record_id": item["qc_record_id"],
                "started_at_utc": started_at,
                "finished_at_utc": datetime.now(timezone.utc).isoformat(),
                "source_result_file": item["source_result_file"],
                "plot_output": item["plot_output"],
            },
        )
    except Exception as exc:
        write_json_atomic(
            status_path,
            {
                "status": "FAILED",
                "task_index": task_index,
                "qc_record_id": item.get("qc_record_id", ""),
                "started_at_utc": started_at,
                "finished_at_utc": datetime.now(timezone.utc).isoformat(),
                "error": str(exc),
            },
        )
        raise


if __name__ == "__main__":
    main()
