#!/usr/bin/env python3
"""Read-only video-level audit for impossible IDtracker coordinate jumps."""
from __future__ import annotations

import csv
import json
import math
import sys
from collections import defaultdict
from pathlib import Path

import numpy as np


AUDIT_VERSION = "1.0"
RETURN_HORIZON_FRAMES = 120
SYNCHRONY_TOLERANCE_FRAMES = 2


def load_trajectories(path: Path) -> np.ndarray:
    suffix = path.suffix.lower()
    if suffix == ".npy":
        loaded = np.load(path, allow_pickle=True)
        if isinstance(loaded, np.ndarray) and loaded.shape == ():
            loaded = loaded.item()
        if isinstance(loaded, dict):
            loaded = loaded.get("trajectories", loaded)
        arr = np.asarray(loaded, dtype=float)
    elif suffix in {".h5", ".hdf5"}:
        import h5py

        with h5py.File(path, "r") as handle:
            candidates = []

            def collect(_name, obj):
                if isinstance(obj, h5py.Dataset) and obj.ndim in (2, 3):
                    candidates.append(np.asarray(obj, dtype=float))

            handle.visititems(collect)
        if len(candidates) != 1:
            raise ValueError(
                f"Expected one trajectory dataset in {path}; found "
                f"{len(candidates)}"
            )
        arr = candidates[0]
    elif suffix == ".csv":
        with path.open(newline="", encoding="utf-8-sig") as handle:
            numeric = [
                [float(value) for value in row]
                for row in csv.reader(handle)
                if row
            ]
        arr = np.asarray(numeric, dtype=float)
    else:
        raise ValueError(f"Unsupported trajectory file: {path}")

    if arr.ndim == 2 and arr.shape[1] == 2:
        arr = arr[:, None, :]
    if arr.ndim != 3:
        raise ValueError(f"Unexpected trajectory shape {arr.shape} in {path}")
    if arr.shape[-1] == 2:
        return arr
    axes_of_two = [axis for axis, size in enumerate(arr.shape) if size == 2]
    if len(axes_of_two) != 1:
        raise ValueError(f"Ambiguous trajectory axes {arr.shape} in {path}")
    return np.moveaxis(arr, axes_of_two[0], -1)


def audit_track(
    xy: np.ndarray,
    global_start: int,
    threshold_px: float,
    return_horizon_frames: int = RETURN_HORIZON_FRAMES,
) -> dict:
    xy = np.asarray(xy, dtype=float)
    valid = np.isfinite(xy).all(axis=1)
    steps = np.linalg.norm(np.diff(xy, axis=0), axis=1)
    edges = np.flatnonzero(
        valid[:-1] & valid[1:] & (steps > threshold_px)
    )
    excluded = np.zeros(len(xy), dtype=bool)
    events = []
    for edge in edges:
        if excluded[edge]:
            continue
        pre = xy[edge]
        return_offset = None
        stop = min(len(xy), edge + 2 + return_horizon_frames)
        for candidate in range(edge + 2, stop):
            if (
                valid[candidate]
                and np.linalg.norm(xy[candidate] - pre) <= threshold_px
            ):
                return_offset = candidate
                break
        if return_offset is None:
            excluded[edge + 1 :] = True
            event_end = len(xy) - 1
            status = "PERSISTENT_NO_RETURN_WITHIN_HORIZON"
        else:
            excluded[edge + 1 : return_offset] = True
            event_end = return_offset - 1
            status = "RETURNED_TO_PRE_JUMP_LOCATION"
        events.append(
            {
                "jump_pre_frame": int(global_start + edge),
                "jump_destination_frame": int(global_start + edge + 1),
                "excluded_start_frame": int(global_start + edge + 1),
                "excluded_end_frame": int(global_start + event_end),
                "return_frame": (
                    int(global_start + return_offset)
                    if return_offset is not None
                    else None
                ),
                "step_px": float(steps[edge]),
                "status": status,
            }
        )
        if return_offset is None:
            break
    return {
        "events": events,
        "jump_events": len(events),
        "persistent_events": sum(
            event["return_frame"] is None for event in events
        ),
        "excluded_coordinate_frames": int(excluded.sum()),
    }


def _synchronized_clusters(track_rows: list[dict]) -> list[dict]:
    points = sorted(
        (
            event["jump_destination_frame"],
            row["qc_record_id"],
            row["track_key"],
        )
        for row in track_rows
        for event in row["events"]
    )
    if not points:
        return []
    groups = [[points[0]]]
    for point in points[1:]:
        if (
            point[0] - groups[-1][-1][0]
            <= 2 * SYNCHRONY_TOLERANCE_FRAMES
        ):
            groups[-1].append(point)
        else:
            groups.append([point])
    return [
        {
            "start_frame": int(group[0][0]),
            "end_frame": int(group[-1][0]),
            "representative_frame": int(
                round(float(np.median([point[0] for point in group])))
            ),
            "affected_records": len({point[1] for point in group}),
            "affected_tracks": len({point[2] for point in group}),
        }
        for group in groups
    ]


def audit_manifest(manifest: dict) -> dict:
    threshold_px = float(manifest.get("jump_threshold_px", 50.0))
    window = int(manifest.get("window_frames", 7200))
    records = list(manifest.get("records") or [])
    tracks = []
    record_capacity = {}
    for record in records:
        path = Path(record["trajectory"])
        arr = load_trajectories(path)
        start = int(record["start"])
        end = start + window
        if end >= len(arr):
            tracks.append(
                {
                    **record,
                    "track_key": record["qc_record_id"] + ":ERROR",
                    "animal_id": "",
                    "events": [],
                    "jump_events": "",
                    "persistent_events": "",
                    "excluded_coordinate_frames": "",
                    "audit_error": (
                        f"window {start}-{end} exceeds final frame {len(arr)-1}"
                    ),
                }
            )
            continue
        record_capacity[record["qc_record_id"]] = len(arr) - 1 - window
        for animal in range(arr.shape[1]):
            result = audit_track(
                arr[start : end + 1, animal, :],
                global_start=start,
                threshold_px=threshold_px,
            )
            tracks.append(
                {
                    **record,
                    "track_key": f"{record['qc_record_id']}:{animal}",
                    "animal_id": animal,
                    **result,
                    "audit_error": "",
                }
            )

    summaries = []
    grouped = defaultdict(list)
    for track in tracks:
        grouped[track["video"]].append(track)
    for video, video_tracks in sorted(grouped.items()):
        usable = [track for track in video_tracks if not track["audit_error"]]
        record_ids = {track["qc_record_id"] for track in usable}
        clusters = _synchronized_clusters(usable)
        minimum_records = max(3, math.ceil(0.5 * len(record_ids)))
        camera_wide = [
            cluster
            for cluster in clusters
            if cluster["affected_records"] >= minimum_records
        ]
        persistent_tracks = sum(
            bool(track["persistent_events"]) for track in usable
        )
        tracks_with_jumps = sum(
            bool(track["jump_events"]) for track in usable
        )
        suggested = ""
        last_disturbance = ""
        suggestion_fits = ""
        if camera_wide:
            last_disturbance = max(
                cluster["end_frame"] for cluster in camera_wide
            )
            suggested = int(
                math.ceil((last_disturbance + 1) / 50.0) * 50
            )
            latest_start = min(
                record_capacity[record_id] for record_id in record_ids
            )
            suggestion_fits = suggested <= latest_start
            status = (
                "VIDEO_WIDE_DISTURBANCE_START_RECOMMENDED"
                if suggestion_fits
                else "VIDEO_WIDE_DISTURBANCE_NO_FULL_WINDOW_AFTER"
            )
        elif persistent_tracks:
            status = "CELL_OR_ANIMAL_SPECIFIC_PERSISTENT_JUMPS"
        elif tracks_with_jumps:
            status = "CELL_OR_ANIMAL_SPECIFIC_RETURNING_JUMPS"
        else:
            status = "PASS_NO_JUMPS_OVER_THRESHOLD"
        summaries.append(
            {
                "video": video,
                "analysis_type": usable[0]["analysis"] if usable else "",
                "current_starts": ";".join(
                    str(value)
                    for value in sorted(
                        {int(track["start"]) for track in usable}
                    )
                ),
                "approved_records": len(record_ids),
                "animal_tracks": len(usable),
                "tracks_with_jumps": tracks_with_jumps,
                "persistent_jump_tracks": persistent_tracks,
                "synchronized_disturbance_clusters": len(camera_wide),
                "last_synchronized_disturbance_frame": last_disturbance,
                "suggested_start_global_frame": suggested,
                "suggested_full_window_fits": suggestion_fits,
                "audit_status": status,
                "jump_threshold_px": threshold_px,
                "return_horizon_frames": RETURN_HORIZON_FRAMES,
                "synchrony_tolerance_frames": SYNCHRONY_TOLERANCE_FRAMES,
                "audit_version": AUDIT_VERSION,
            }
        )
    return {"summaries": summaries, "tracks": tracks}


def main() -> int:
    result = audit_manifest(json.load(sys.stdin))
    json.dump(result, sys.stdout)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
