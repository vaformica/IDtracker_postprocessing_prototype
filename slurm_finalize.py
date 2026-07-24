#!/usr/bin/env python3
"""Validate and atomically promote one completed SLURM processing batch."""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path


def write_json_atomic(destination: Path, payload: dict) -> None:
    temporary = destination.with_name(
        destination.name + f".partial.{os.getpid()}"
    )
    temporary.write_text(
        json.dumps(payload, indent=2, sort_keys=True),
        encoding="utf-8",
    )
    temporary.replace(destination)


def validate_worker_outputs(manifest: dict) -> None:
    status_folder = Path(manifest["status_folder"])
    statuses = []
    for index, item in enumerate(manifest["items"]):
        status_path = status_folder / f"{index:05d}.json"
        if not status_path.is_file():
            raise RuntimeError(f"missing worker status: {status_path}")
        status = json.loads(status_path.read_text(encoding="utf-8"))
        statuses.append(status)
        if status.get("status") != "SUCCESS":
            raise RuntimeError(
                f"worker {index} did not succeed: {status.get('error', status)}"
            )
        if status.get("qc_record_id") != item["qc_record_id"]:
            raise RuntimeError(f"worker {index} QC identity mismatch")
        if (
            not Path(item["source_result_file"]).is_file()
            or Path(item["source_result_file"]).stat().st_size == 0
        ):
            raise RuntimeError(f"worker {index} CSV is missing")
        if (
            not Path(item["plot_output"]).is_file()
            or Path(item["plot_output"]).stat().st_size == 0
        ):
            raise RuntimeError(f"worker {index} PDF is missing")


def promote_outputs(manifest: dict) -> None:
    plot_stage = Path(manifest["plot_stage"])
    plot_folder = Path(manifest["plot_folder"])
    plot_previous = Path(manifest["plot_previous"])
    combined_stage = Path(manifest["combined_stage"])
    combined_destination = Path(manifest["combined_destination"])
    if len(list(plot_stage.glob("*.pdf"))) != len(manifest["items"]):
        raise RuntimeError("staged PDF count does not match manifest item count")
    if not combined_stage.is_file():
        raise RuntimeError("staged combined CSV is missing")

    if plot_previous.exists():
        shutil.rmtree(plot_previous)
    moved_previous = False
    if plot_folder.exists():
        plot_folder.replace(plot_previous)
        moved_previous = True
    try:
        plot_stage.replace(plot_folder)
        combined_stage.replace(combined_destination)
    except Exception:
        if plot_folder.exists():
            shutil.rmtree(plot_folder)
        if moved_previous and plot_previous.exists():
            plot_previous.replace(plot_folder)
        raise
    if plot_previous.exists():
        shutil.rmtree(plot_previous)


def main() -> None:
    if len(sys.argv) != 2:
        raise SystemExit("Usage: slurm_finalize.py MANIFEST.json")
    manifest_path = Path(sys.argv[1])
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    validate_worker_outputs(manifest)
    combine_request = {
        "items": [
            {
                key: value
                for key, value in item.items()
                if key
                in {
                    "source_result_file",
                    "qc_record_id",
                    "video",
                    "cell_label",
                    "analysis_type",
                    "camera",
                    "camera_id",
                    "video_year",
                    "recording_date",
                    "recording_time",
                    "act",
                    "processing_batch_id",
                    "processing_created_at",
                    "processing_execution_mode",
                }
            }
            for item in manifest["items"]
        ],
        "destination": manifest["combined_stage"],
        "overwrite": True,
    }
    result = subprocess.run(
        [manifest["remote_python"], manifest["combine_script"]],
        input=json.dumps(combine_request),
        text=True,
        capture_output=True,
        check=False,
    )
    if result.stdout:
        print(result.stdout, end="")
    if result.stderr:
        print(result.stderr, end="", file=sys.stderr)
    if result.returncode:
        raise RuntimeError(
            f"combine step exited with status {result.returncode}"
        )
    promote_outputs(manifest)
    write_json_atomic(
        Path(manifest["completion_marker"]),
        {
            "status": "SUCCESS",
            "completed_at_utc": datetime.now(timezone.utc).isoformat(),
            "processed_sessions": len(manifest["items"]),
            "combined_output": manifest["combined_destination"],
            "pdf_folder": manifest["plot_folder"],
            "script_version": manifest["script_version"],
        },
    )


if __name__ == "__main__":
    main()
