#!/usr/bin/env python3
"""Combine one reviewed processing batch without altering source CSV files."""
import csv
import json
import os
import sys
from pathlib import Path


def main():
    request = json.load(sys.stdin)
    items = request["items"]
    destination = Path(request["destination"])
    overwrite = bool(request.get("overwrite", False))
    leading_fields = [
        "cell_label",
        "video",
        "analysis_type",
        "video_year",
    ]
    trailing_fields = [
        "qc_record_id",
        "camera",
        "camera_id",
        "recording_date",
        "recording_time",
        "act",
        "processing_batch_id",
        "processing_created_at",
        "source_result_file",
    ]
    rows = []
    base_fields = None
    for item in items:
        source = Path(item["source_result_file"])
        with source.open(newline="", encoding="utf-8-sig") as stream:
            reader = csv.DictReader(stream)
            fields = reader.fieldnames or []
            if base_fields is None:
                base_fields = fields
            elif fields != base_fields:
                raise ValueError(
                    "Result schemas differ; refusing to combine " + str(source)
                )
            for row in reader:
                row.update(
                    {
                        "qc_record_id": item["qc_record_id"],
                        "video": item["video"],
                        "cell_label": item["cell_label"],
                        "analysis_type": item["analysis_type"],
                        "camera": item.get("camera", ""),
                        "camera_id": item.get("camera_id", ""),
                        "video_year": item.get("video_year", ""),
                        "recording_date": item.get("recording_date", ""),
                        "recording_time": item.get("recording_time", ""),
                        "act": item.get("act", ""),
                        "processing_batch_id": item.get(
                            "processing_batch_id", ""
                        ),
                        "processing_created_at": item.get(
                            "processing_created_at", ""
                        ),
                        "source_result_file": str(source),
                    }
                )
                rows.append(row)

    if not rows or base_fields is None:
        raise ValueError("No result rows were available to combine")
    destination.parent.mkdir(parents=True, exist_ok=True)
    if destination.exists() and not overwrite:
        raise FileExistsError(
            f"Refusing to overwrite existing combined output: {destination}"
        )
    temporary = destination.with_name(
        destination.name + f".partial.{os.getpid()}"
    )
    try:
        with temporary.open("x", newline="", encoding="utf-8") as stream:
            writer = csv.DictWriter(
                stream,
                fieldnames=leading_fields + base_fields + trailing_fields,
            )
            writer.writeheader()
            writer.writerows(rows)
            stream.flush()
            os.fsync(stream.fileno())
        temporary.replace(destination)
    except Exception:
        if temporary.exists():
            temporary.unlink()
        raise
    print(
        json.dumps(
            {
                "status": "OK",
                "combined_output": str(destination),
                "rows": len(rows),
                "source_files": len(items),
            }
        )
    )


if __name__ == "__main__":
    main()
