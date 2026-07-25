#!/usr/bin/env python3
"""Auditable, analysis-window-only IDtracker.ai post-processing.

Coordinates are never interpolated. All time-like outputs use global frames.
"""
from __future__ import annotations

import argparse
import ast
import csv
import json
import math
import os
import re
import textwrap
from pathlib import Path

import numpy as np


SCRIPT_VERSION = "0.7.1"
POST_WAKE_FIXED_INTERVALS = 3600

IDTRACKER_TRAJECTORY_SOURCES = {
    "validated.npy": "IDTRACKER_VALIDATED",
    "without_gaps.npy": "IDTRACKER_WITHOUT_GAPS",
    "trajectories_wo_gaps.npy": "IDTRACKER_LEGACY_WO_GAPS",
    "trajectories_without_gaps.npy": "IDTRACKER_LEGACY_WITHOUT_GAPS",
    "trajectories.npy": "IDTRACKER_RAW_NPY",
    "trajectories.h5": "IDTRACKER_RAW_H5",
    "trajectories.csv": "IDTRACKER_RAW_CSV",
}

OUTPUT_COLUMNS = [
    "script_version",
    "analysis_start_frame",
    "analysis_timespan_frames",
    "analysis_end_frame_inclusive",
    "analysis_frame_observations_inclusive",
    "movement_threshold_px",
    "idtracker_animal_id",
    "starting_side",
    "threshold_crossing_global_frame",
    "latency_to_threshold_frames",
    "total_distance_px_in_analysis_window",
    "one_frame_jump_threshold_px",
    "one_frame_jumps_excluded",
    "jump_threshold_px",
    "jump_artifact_coordinate_frames_excluded",
    "jump_qc_status",
    "post_wake_analysis_status",
    "post_wake_wall_analysis_status",
    "post_wake_fungus_analysis_status",
    "post_wake_open_off_fungus_analysis_status",
    "post_wake_valid_coordinate_frames",
    "post_wake_valid_movement_steps",
    "post_wake_missing_coordinate_frames",
    "post_wake_jump_excluded_steps",
    "post_wake_total_distance_px",
    "post_wake_distance_px_per_valid_step",
    "post_wake_frames_inside_wall_buffer",
    "post_wake_frames_outside_wall_buffer",
    "post_wake_open_area_proportion",
    "post_wake_distance_px_inside_wall_buffer",
    "post_wake_distance_px_outside_wall_buffer",
    "post_wake_steps_inside_wall_buffer",
    "post_wake_steps_outside_wall_buffer",
    "post_wake_open_distance_px_per_available_step",
    "post_wake_speed_px_per_open_step",
    "post_wake_frames_on_fungus",
    "post_wake_frames_off_fungus",
    "post_wake_distance_px_on_fungus",
    "post_wake_distance_px_off_fungus",
    "post_wake_steps_on_fungus",
    "post_wake_steps_off_fungus",
    "post_wake_off_fungus_proportion",
    "post_wake_off_fungus_distance_px_per_available_step",
    "post_wake_speed_px_per_off_fungus_step",
    "post_wake_frames_open_and_off_fungus",
    "post_wake_distance_px_open_and_off_fungus",
    "post_wake_steps_open_and_off_fungus",
    "post_wake_open_off_fungus_proportion",
    "post_wake_open_off_fungus_distance_px_per_available_step",
    "post_wake_speed_px_per_open_off_fungus_step",
    "post_wake_3600_analysis_status",
    "post_wake_3600_anchor_rule",
    "post_wake_3600_start_global_frame",
    "post_wake_3600_end_global_frame_inclusive",
    "post_wake_3600_frame_intervals",
    "post_wake_3600_frame_observations_inclusive",
    "post_wake_3600_wall_analysis_status",
    "post_wake_3600_fungus_analysis_status",
    "post_wake_3600_open_off_fungus_analysis_status",
    "post_wake_3600_valid_coordinate_frames",
    "post_wake_3600_valid_movement_steps",
    "post_wake_3600_missing_coordinate_frames",
    "post_wake_3600_jump_excluded_steps",
    "post_wake_3600_total_distance_px",
    "post_wake_3600_distance_px_per_valid_step",
    "post_wake_3600_frames_inside_wall_buffer",
    "post_wake_3600_frames_outside_wall_buffer",
    "post_wake_3600_open_area_proportion",
    "post_wake_3600_distance_px_inside_wall_buffer",
    "post_wake_3600_distance_px_outside_wall_buffer",
    "post_wake_3600_steps_inside_wall_buffer",
    "post_wake_3600_steps_outside_wall_buffer",
    "post_wake_3600_open_distance_px_per_available_step",
    "post_wake_3600_speed_px_per_open_step",
    "post_wake_3600_frames_on_fungus",
    "post_wake_3600_frames_off_fungus",
    "post_wake_3600_frames_in_fungus_edge_buffer",
    "post_wake_3600_frames_in_fungus_interior",
    "post_wake_3600_distance_px_on_fungus",
    "post_wake_3600_distance_px_off_fungus",
    "post_wake_3600_distance_px_in_fungus_edge_buffer",
    "post_wake_3600_distance_px_in_fungus_interior",
    "post_wake_3600_steps_on_fungus",
    "post_wake_3600_steps_off_fungus",
    "post_wake_3600_off_fungus_proportion",
    "post_wake_3600_off_fungus_distance_px_per_available_step",
    "post_wake_3600_speed_px_per_off_fungus_step",
    "post_wake_3600_frames_open_and_off_fungus",
    "post_wake_3600_distance_px_open_and_off_fungus",
    "post_wake_3600_steps_open_and_off_fungus",
    "post_wake_3600_open_off_fungus_proportion",
    "post_wake_3600_open_off_fungus_distance_px_per_available_step",
    "post_wake_3600_speed_px_per_open_off_fungus_step",
    "post_wake_3600_social_analysis_status",
    "post_wake_3600_frames_within_social_distance",
    "post_wake_3600_distance_moved_px_while_within_social_distance",
    "post_wake_3600_social_disappearance_frames",
    "post_wake_3600_social_return_interaction_events",
    "post_wake_3600_social_disappearance_imputed_frames",
    "post_wake_3600_remaining_missing_coordinate_frames_after_social_substitution",
    "post_wake_3600_coordinate_frames_used_in_distance_and_location_calculations",
    "post_wake_3600_turtling_candidate_frames",
    "post_wake_3600_turtling_candidate_proportion_of_detected_frames",
    "post_wake_3600_turtling_candidate_events",
    "post_wake_3600_turtling_detector_status",
    "wall_buffer_px",
    "frames_inside_wall_buffer",
    "frames_outside_wall_buffer",
    "distance_px_inside_wall_buffer",
    "distance_px_outside_wall_buffer",
    "spatial_partition_status",
    "fungus_buffer_px",
    "frames_on_fungus",
    "frames_in_fungus_edge_buffer",
    "frames_in_fungus_interior",
    "distance_px_on_fungus",
    "distance_px_in_fungus_edge_buffer",
    "distance_px_in_fungus_interior",
    "fungus_partition_status",
    "social_distance_threshold_px",
    "frames_within_social_distance",
    "distance_moved_px_while_within_social_distance",
    "social_disappearance_frames",
    "social_return_interaction_events",
    "social_analysis_status",
    "use_social_disappearance_in_calculations",
    "social_disappearance_imputed_frames",
    "remaining_missing_coordinate_frames_after_social_substitution",
    "coordinate_frames_used_in_distance_and_location_calculations",
    "turtling_candidate_frames",
    "turtling_candidate_proportion_of_detected_frames",
    "turtling_candidate_events",
    "turtling_detector_status",
    "turtling_window_frames",
    "turtling_min_path_px",
    "turtling_max_radius90_px",
    "turtling_min_turn_rotations",
    "turtling_max_straightness",
    "turtling_max_step_px",
    "baseline_x_px",
    "baseline_y_px",
    "valid_coordinate_frames_in_window",
    "missing_coordinate_frames_in_window",
    "result_status",
    "warning",
    "trajectory_source_kind",
    "session_folder",
    "trajectory_file",
    "archived_original_start_frame",
    "start_frame_decision_source",
    "start_frame_decision_provenance",
]


def load_rois(session_folder: Path) -> list[np.ndarray]:
    session_json = session_folder / "session.json"
    if not session_json.is_file():
        matches = list(session_folder.rglob("session.json"))
        if len(matches) != 1:
            raise ValueError(
                "Expected exactly one session.json for ROI geometry; "
                f"found {len(matches)} under {session_folder}"
            )
        session_json = matches[0]
    data = json.loads(session_json.read_text(encoding="utf-8"))
    raw_rois = data.get("roi_list") or []
    if isinstance(raw_rois, dict):
        values = list(raw_rois.values())
    else:
        values = list(raw_rois)
    if not values:
        raise ValueError("session.json contains no ROI geometry in roi_list")
    polygons = []
    for index, raw_roi in enumerate(values):
        if isinstance(raw_roi, dict):
            raw_roi = (
                raw_roi.get("polygon")
                or raw_roi.get("points")
                or raw_roi.get("roi")
            )
        if isinstance(raw_roi, str):
            match = re.search(r"(\[\s*\[.*\]\s*\])", raw_roi)
            if not match:
                raise ValueError(f"Could not parse ROI polygon string at index {index}")
            raw_roi = ast.literal_eval(match.group(1))
        polygon = np.asarray(raw_roi, dtype=float)
        if (
            polygon.ndim != 2
            or polygon.shape[1] != 2
            or len(polygon) < 3
            or not np.isfinite(polygon).all()
        ):
            raise ValueError(f"Invalid ROI polygon shape at index {index}: {polygon.shape}")
        polygons.append(polygon)
    return polygons


def load_primary_roi(session_folder: Path) -> np.ndarray:
    """Compatibility helper: the primary arena is always roi_list[0]."""
    return load_rois(session_folder)[0]


def distance_to_polygon_boundary(points: np.ndarray, polygon: np.ndarray) -> np.ndarray:
    points = np.asarray(points, dtype=float)
    distances = []
    for index in range(len(polygon)):
        a = polygon[index]
        b = polygon[(index + 1) % len(polygon)]
        ab = b - a
        denominator = float(np.dot(ab, ab))
        if denominator <= 0:
            distance = np.sqrt(np.sum((points - a) ** 2, axis=1))
        else:
            projection = np.clip(
                np.sum((points - a) * ab, axis=1) / denominator,
                0.0,
                1.0,
            )
            nearest = a + projection[:, None] * ab
            distance = np.sqrt(np.sum((points - nearest) ** 2, axis=1))
        distances.append(distance)
    return np.min(np.vstack(distances), axis=0)


def points_inside_polygon(points: np.ndarray, polygon: np.ndarray) -> np.ndarray:
    points = np.asarray(points, dtype=float)
    x = points[:, 0]
    y = points[:, 1]
    inside = np.zeros(len(points), dtype=bool)
    previous = len(polygon) - 1
    for current in range(len(polygon)):
        xi, yi = polygon[current]
        xj, yj = polygon[previous]
        crosses = ((yi > y) != (yj > y)) & (
            x < (xj - xi) * (y - yi) / ((yj - yi) + np.finfo(float).eps) + xi
        )
        inside ^= crosses
        previous = current
    on_boundary = distance_to_polygon_boundary(points, polygon) <= 1e-9
    return inside | on_boundary


def _normalize(arr: np.ndarray) -> np.ndarray:
    arr = np.asarray(arr, dtype=float)
    arr = np.squeeze(arr)
    if arr.ndim == 2:
        if arr.shape[1] % 2:
            raise ValueError(f"2-D trajectory shape is not x/y pairs: {arr.shape}")
        return arr.reshape(arr.shape[0], arr.shape[1] // 2, 2)
    if arr.ndim != 3 or arr.shape[-1] != 2:
        raise ValueError(
            "Trajectory array must have shape (frames, individuals, 2); "
            f"observed {arr.shape}"
        )
    if arr.shape[0] < arr.shape[1] and arr.shape[0] <= 100:
        arr = np.transpose(arr, (1, 0, 2))
    if arr.shape[0] < arr.shape[1]:
        raise ValueError(f"Ambiguous trajectory axes after normalization: {arr.shape}")
    return arr


def load_trajectories(path: Path) -> np.ndarray:
    suffix = path.suffix.lower()
    if suffix == ".npy":
        raw = np.load(path, allow_pickle=True)
        if raw.dtype == object and raw.shape == ():
            item = raw.item()
            if not isinstance(item, dict) or "trajectories" not in item:
                raise ValueError("Object NPY does not contain a 'trajectories' array")
            raw = item["trajectories"]
        return _normalize(raw)
    if suffix in {".h5", ".hdf5"}:
        try:
            import h5py
        except ImportError as exc:
            raise RuntimeError("h5py is required to read HDF5 trajectories") from exc
        with h5py.File(path, "r") as handle:
            candidates = []

            def visit(name, obj):
                if hasattr(obj, "shape") and len(obj.shape) in {2, 3}:
                    if "trajector" in name.lower():
                        candidates.append(name)

            handle.visititems(visit)
            if len(candidates) != 1:
                raise ValueError(
                    "Expected exactly one trajectory-named HDF5 dataset; "
                    f"found {candidates}"
                )
            return _normalize(handle[candidates[0]][...])
    if suffix == ".csv":
        with path.open(newline="", encoding="utf-8-sig") as stream:
            reader = csv.DictReader(stream)
            fields = reader.fieldnames or []
            ids = sorted(
                {
                    int(match.group(1))
                    for field in fields
                    if (match := re.fullmatch(r"x(\d+)", field))
                    and f"y{match.group(1)}" in fields
                }
            )
            if not ids:
                raise ValueError("CSV must contain explicit xN and yN column pairs")
            rows = list(reader)
        arr = np.full((len(rows), len(ids), 2), np.nan)
        for frame, row in enumerate(rows):
            for column, identity in enumerate(ids):
                for axis, prefix in enumerate(("x", "y")):
                    value = row[f"{prefix}{identity}"].strip()
                    if value:
                        arr[frame, column, axis] = float(value)
        return arr
    raise ValueError(f"Unsupported trajectory format: {suffix}")


def validate_trajectory_source(path: Path) -> str:
    source_kind = IDTRACKER_TRAJECTORY_SOURCES.get(path.name)
    if source_kind is None:
        raise ValueError(
            "UNRECOGNIZED_TRAJECTORY_SOURCE: expected an IDtracker validated, "
            "without-gaps, or raw trajectories file with a recognized name."
        )
    return source_kind


# Compatibility name retained for older imports; raw IDtracker sources are now
# intentionally accepted under the user-approved fallback policy.
validate_interpolated_trajectory_source = validate_trajectory_source


def compute_social_candidates(
    window_arr: np.ndarray,
    social_distance_threshold_px: float = 60.0,
    eligible_missing_mask: np.ndarray | None = None,
) -> dict:
    """Return auditable fight-only social-distance and disappearance masks.

    A within-range frame has two valid animals separated by at most the single
    social distance threshold. A disappearance run is counted only when one
    specific animal is missing, the immediately preceding frame is within
    range, and the missing animal reappears before the inclusive window ends.

    A return interaction event requires within range, then at least one frame
    where both animals are visibly farther apart than the threshold, then
    within range again. A missing-only gap is not evidence of separation.
    """
    frame_count = int(window_arr.shape[0])
    empty = np.zeros(frame_count, dtype=bool)
    if window_arr.shape[1] != 2:
        return {
            "status": "NOT_CALCULATED_EXPECTED_TWO_ANIMALS",
            "distance": np.full(frame_count, np.nan),
            "within_mask": empty.copy(),
            "disappearance_mask": empty.copy(),
            "disappearance_masks_by_animal": np.zeros(
                (frame_count, window_arr.shape[1]), dtype=bool
            ),
            "disappearance_events": [],
            "return_events": 0,
        }

    valid = np.isfinite(window_arr).all(axis=2)
    if eligible_missing_mask is None:
        eligible_missing_mask = ~valid
    else:
        eligible_missing_mask = np.asarray(
            eligible_missing_mask, dtype=bool
        )
        if eligible_missing_mask.shape != valid.shape:
            raise ValueError(
                "eligible_missing_mask must match the trajectory frame/animal "
                f"shape {valid.shape}; received {eligible_missing_mask.shape}"
            )
    both_valid = valid[:, 0] & valid[:, 1]
    distance = np.full(frame_count, np.nan)
    difference = window_arr[:, 0, :] - window_arr[:, 1, :]
    distance[both_valid] = np.sqrt(
        np.sum(difference[both_valid] ** 2, axis=1)
    )
    within_mask = both_valid & (distance <= social_distance_threshold_px)
    disappearance_mask = empty.copy()
    disappearance_masks_by_animal = np.zeros((frame_count, 2), dtype=bool)
    disappearance_events = []

    for missing_animal in (0, 1):
        run_mask = (
            (~valid[:, missing_animal])
            & eligible_missing_mask[:, missing_animal]
            & valid[:, 1 - missing_animal]
        )
        changes = np.diff(
            np.concatenate(([False], run_mask, [False])).astype(np.int8)
        )
        starts = np.flatnonzero(changes == 1)
        stops = np.flatnonzero(changes == -1)
        for run_start, run_stop_exclusive in zip(starts, stops):
            if run_start == 0 or run_stop_exclusive >= frame_count:
                continue
            if not within_mask[run_start - 1]:
                continue
            if not valid[run_stop_exclusive, missing_animal]:
                continue
            if not both_valid[run_stop_exclusive]:
                continue
            disappearance_mask[run_start:run_stop_exclusive] = True
            disappearance_masks_by_animal[
                run_start:run_stop_exclusive, missing_animal
            ] = True
            disappearance_events.append(
                {
                    "missing_animal": missing_animal,
                    "start_offset": int(run_start),
                    "end_offset": int(run_stop_exclusive - 1),
                }
            )

    return_events = 0
    not_within = ~within_mask
    changes = np.diff(
        np.concatenate(([False], not_within, [False])).astype(np.int8)
    )
    starts = np.flatnonzero(changes == 1)
    stops = np.flatnonzero(changes == -1)
    visibly_separate = (
        both_valid & (distance > social_distance_threshold_px)
    )
    for run_start, run_stop_exclusive in zip(starts, stops):
        if run_start == 0 or run_stop_exclusive >= frame_count:
            continue
        if not within_mask[run_start - 1]:
            continue
        if not within_mask[run_stop_exclusive]:
            continue
        if visibly_separate[run_start:run_stop_exclusive].any():
            return_events += 1

    return {
        "status": "CALCULATED_FIGHT_TWO_ANIMALS",
        "distance": distance,
        "within_mask": within_mask,
        "disappearance_mask": disappearance_mask,
        "disappearance_masks_by_animal": disappearance_masks_by_animal,
        "disappearance_events": disappearance_events,
        "return_events": return_events,
    }


def filter_jump_artifact_coordinates(
    xy: np.ndarray,
    threshold_px: float = 200.0,
    return_horizon_frames: int = 120,
) -> dict:
    """Identify rejected adjacent movement steps without deleting coordinates.

    A one-frame jump is a finite adjacent step strictly greater than
    ``threshold_px``. That step is excluded from distance, latency chains, and
    plotted paths. Both endpoint coordinates remain available for per-frame
    wall/fungus location counts. The deprecated ``return_horizon_frames``
    argument is retained only for call compatibility; the separate Jump Audit
    still performs its documented return/persistence classification.
    """
    xy = np.asarray(xy, dtype=float)
    if xy.ndim != 2 or xy.shape[1] != 2:
        raise ValueError("Jump QC expects a frames-by-2 coordinate array")
    if threshold_px <= 0 or return_horizon_frames < 1:
        raise ValueError(
            "Jump threshold and return horizon must both be positive"
        )

    valid = np.isfinite(xy).all(axis=1)
    step_distance = np.linalg.norm(np.diff(xy, axis=0), axis=1)
    rejected_step_mask = (
        valid[:-1] & valid[1:] & (step_distance > threshold_px)
    )
    jump_edges = np.flatnonzero(rejected_step_mask)
    excluded = np.zeros(len(xy), dtype=bool)
    events = [
        {
            "jump_edge_offset": int(edge),
            "jump_destination_offset": int(edge + 1),
            "step_px": float(step_distance[edge]),
            "status": "ONE_FRAME_STEP_EXCLUDED",
        }
        for edge in jump_edges
    ]
    status = (
        "ONE_FRAME_JUMP_STEPS_EXCLUDED"
        if events
        else "PASS_NO_JUMPS_OVER_THRESHOLD"
    )
    return {
        "cleaned_xy": xy.copy(),
        "excluded_mask": excluded,
        "rejected_step_mask": rejected_step_mask,
        "step_distance_px": step_distance,
        "events": events,
        "persistent_events": 0,
        "status": status,
    }


def _events_from_mask(mask: np.ndarray) -> list[dict]:
    """Return contiguous inclusive event runs for one Boolean frame mask."""
    changes = np.diff(
        np.concatenate(([False], mask, [False])).astype(np.int8)
    )
    starts = np.flatnonzero(changes == 1)
    stops = np.flatnonzero(changes == -1)
    return [
        {
            "start_offset": int(event_start),
            "end_offset": int(event_stop - 1),
            "frames": int(event_stop - event_start),
        }
        for event_start, event_stop in zip(starts, stops)
    ]


def exclude_turtling_candidates_on_fungus(
    result: dict,
    xy: np.ndarray,
    fungus_roi: np.ndarray | None,
) -> dict:
    """Remove fight turtling candidates whose centroid is on the fungus ROI.

    This changes only the turtling candidate mask and its contiguous events.
    It does not alter coordinates or any distance, wall, fungus, or social
    calculation.
    """
    adjusted = dict(result)
    mask = np.asarray(result["mask"], dtype=bool).copy()
    excluded = np.zeros(len(mask), dtype=bool)
    if fungus_roi is not None and mask.any():
        xy = np.asarray(xy, dtype=float)
        valid = np.isfinite(xy).all(axis=1)
        on_fungus = np.zeros(len(mask), dtype=bool)
        on_fungus[valid] = points_inside_polygon(xy[valid], fungus_roi)
        excluded = mask & on_fungus
        mask[excluded] = False
    adjusted["mask"] = mask
    adjusted["events"] = _events_from_mask(mask)
    adjusted["fungus_excluded_mask"] = excluded
    return adjusted


def continuous_path_segments(
    xy: np.ndarray,
    maximum_step_px: float,
) -> list[tuple[np.ndarray, np.ndarray]]:
    """Return contiguous plotted path segments without missing or large steps.

    Each tuple contains the original frame offsets and their coordinates.
    Rejected transitions are not drawn, and no coordinates are interpolated.
    """
    xy = np.asarray(xy, dtype=float)
    valid = np.isfinite(xy).all(axis=1)
    if len(xy) < 2:
        return []
    step_lengths = np.linalg.norm(np.diff(xy, axis=0), axis=1)
    accepted_edges = (
        valid[:-1] & valid[1:] & (step_lengths <= maximum_step_px)
    )
    segments = []
    run_start = None
    for edge_index, accepted in enumerate(accepted_edges):
        if accepted and run_start is None:
            run_start = edge_index
        if run_start is not None and (
            not accepted or edge_index == len(accepted_edges) - 1
        ):
            run_stop = (
                edge_index + 1
                if accepted and edge_index == len(accepted_edges) - 1
                else edge_index
            )
            offsets = np.arange(run_start, run_stop + 1)
            segments.append((offsets, xy[offsets]))
            run_start = None
    return segments


POST_WAKE_NUMERIC_COLUMNS = (
    "post_wake_valid_coordinate_frames",
    "post_wake_valid_movement_steps",
    "post_wake_missing_coordinate_frames",
    "post_wake_jump_excluded_steps",
    "post_wake_total_distance_px",
    "post_wake_distance_px_per_valid_step",
    "post_wake_frames_inside_wall_buffer",
    "post_wake_frames_outside_wall_buffer",
    "post_wake_open_area_proportion",
    "post_wake_distance_px_inside_wall_buffer",
    "post_wake_distance_px_outside_wall_buffer",
    "post_wake_steps_inside_wall_buffer",
    "post_wake_steps_outside_wall_buffer",
    "post_wake_open_distance_px_per_available_step",
    "post_wake_speed_px_per_open_step",
    "post_wake_frames_on_fungus",
    "post_wake_frames_off_fungus",
    "post_wake_distance_px_on_fungus",
    "post_wake_distance_px_off_fungus",
    "post_wake_steps_on_fungus",
    "post_wake_steps_off_fungus",
    "post_wake_off_fungus_proportion",
    "post_wake_off_fungus_distance_px_per_available_step",
    "post_wake_speed_px_per_off_fungus_step",
    "post_wake_frames_open_and_off_fungus",
    "post_wake_distance_px_open_and_off_fungus",
    "post_wake_steps_open_and_off_fungus",
    "post_wake_open_off_fungus_proportion",
    "post_wake_open_off_fungus_distance_px_per_available_step",
    "post_wake_speed_px_per_open_off_fungus_step",
)

POST_WAKE_3600_CORE_NUMERIC_COLUMNS = tuple(
    column.replace("post_wake_", "post_wake_3600_", 1)
    for column in POST_WAKE_NUMERIC_COLUMNS
)
POST_WAKE_3600_EXTRA_NUMERIC_COLUMNS = (
    "post_wake_3600_start_global_frame",
    "post_wake_3600_end_global_frame_inclusive",
    "post_wake_3600_frame_intervals",
    "post_wake_3600_frame_observations_inclusive",
    "post_wake_3600_frames_in_fungus_edge_buffer",
    "post_wake_3600_frames_in_fungus_interior",
    "post_wake_3600_distance_px_in_fungus_edge_buffer",
    "post_wake_3600_distance_px_in_fungus_interior",
    "post_wake_3600_frames_within_social_distance",
    "post_wake_3600_distance_moved_px_while_within_social_distance",
    "post_wake_3600_social_disappearance_frames",
    "post_wake_3600_social_return_interaction_events",
    "post_wake_3600_social_disappearance_imputed_frames",
    "post_wake_3600_remaining_missing_coordinate_frames_after_social_substitution",
    "post_wake_3600_coordinate_frames_used_in_distance_and_location_calculations",
    "post_wake_3600_turtling_candidate_frames",
    "post_wake_3600_turtling_candidate_proportion_of_detected_frames",
    "post_wake_3600_turtling_candidate_events",
)


def blank_post_wake_metrics(status: str, is_fight: bool) -> dict:
    """Return explicit missing post-wake outputs for an unavailable wake frame."""
    output = {column: "" for column in POST_WAKE_NUMERIC_COLUMNS}
    output.update(
        {
            "post_wake_analysis_status": status,
            "post_wake_wall_analysis_status": (
                "NOT_CALCULATED_NO_WAKE_FRAME"
            ),
            "post_wake_fungus_analysis_status": (
                "NOT_CALCULATED_NO_WAKE_FRAME"
                if is_fight
                else "NOT_APPLICABLE_NOT_FIGHT"
            ),
            "post_wake_open_off_fungus_analysis_status": (
                "NOT_CALCULATED_NO_WAKE_FRAME"
                if is_fight
                else "NOT_APPLICABLE_NOT_FIGHT"
            ),
        }
    )
    return output


def blank_post_wake_3600_metrics(
    status: str,
    *,
    is_fight: bool,
    anchor_rule: str,
) -> dict:
    """Return explicit blanks when the complete fixed window is unavailable."""
    output = {
        column: ""
        for column in (
            POST_WAKE_3600_CORE_NUMERIC_COLUMNS
            + POST_WAKE_3600_EXTRA_NUMERIC_COLUMNS
        )
    }
    output.update(
        {
            "post_wake_3600_analysis_status": status,
            "post_wake_3600_anchor_rule": anchor_rule,
            "post_wake_3600_wall_analysis_status": status,
            "post_wake_3600_fungus_analysis_status": (
                status if is_fight else "NOT_APPLICABLE_NOT_FIGHT"
            ),
            "post_wake_3600_open_off_fungus_analysis_status": (
                status if is_fight else "NOT_APPLICABLE_NOT_FIGHT"
            ),
            "post_wake_3600_social_analysis_status": (
                status if is_fight else "NOT_APPLICABLE_NOT_FIGHT"
            ),
            "post_wake_3600_turtling_detector_status": status,
        }
    )
    return output


def compute_post_wake_metrics(
    *,
    effective_xy: np.ndarray,
    raw_xy: np.ndarray,
    wake_offset: int,
    step_distances: np.ndarray,
    accepted_steps: np.ndarray,
    rejected_jump_steps: np.ndarray,
    primary_roi: np.ndarray | None,
    secondary_roi: np.ndarray | None,
    wall_buffer_px: float,
    is_fight: bool,
) -> dict:
    """Calculate wake-through-inclusive-end metrics with valid-step denominators.

    ``wake_offset`` is the already-established latency offset. Movement steps
    begin at that frame and end at the next frame. Missing and rejected jump
    steps are never bridged. Jump QC changes step eligibility only; it does not
    remove either endpoint from per-frame location counts.
    """
    effective_xy = np.asarray(effective_xy, dtype=float)
    raw_xy = np.asarray(raw_xy, dtype=float)
    frame_count = len(effective_xy)
    if not 0 <= wake_offset < frame_count:
        raise ValueError("wake_offset is outside the analysis window")
    valid = np.isfinite(effective_xy).all(axis=1)
    raw_valid = np.isfinite(raw_xy).all(axis=1)
    post_frames = np.arange(frame_count) >= wake_offset
    post_steps = np.arange(max(frame_count - 1, 0)) >= wake_offset
    post_accepted = accepted_steps & post_steps
    post_rejected = rejected_jump_steps & post_steps
    valid_frames = int((valid & post_frames).sum())
    valid_step_count = int(post_accepted.sum())
    missing_frames = int((~raw_valid & post_frames).sum())
    jump_step_count = int(post_rejected.sum())

    output = {column: "" for column in POST_WAKE_NUMERIC_COLUMNS}
    output.update(
        {
            "post_wake_analysis_status": (
                "CALCULATED"
                if valid_step_count
                else "NOT_CALCULATED_NO_VALID_MOVEMENT_STEPS"
            ),
            "post_wake_wall_analysis_status": "NOT_CALCULATED",
            "post_wake_fungus_analysis_status": (
                "NOT_CALCULATED"
                if is_fight
                else "NOT_APPLICABLE_NOT_FIGHT"
            ),
            "post_wake_open_off_fungus_analysis_status": (
                "NOT_CALCULATED"
                if is_fight
                else "NOT_APPLICABLE_NOT_FIGHT"
            ),
            "post_wake_valid_coordinate_frames": valid_frames,
            "post_wake_valid_movement_steps": valid_step_count,
            "post_wake_missing_coordinate_frames": missing_frames,
            "post_wake_jump_excluded_steps": jump_step_count,
        }
    )
    total_distance = ""
    if valid_step_count:
        total_distance = float(step_distances[post_accepted].sum())
        output["post_wake_total_distance_px"] = total_distance
        output["post_wake_distance_px_per_valid_step"] = (
            total_distance / valid_step_count
        )

    inside_primary = np.zeros(frame_count, dtype=bool)
    distance_to_wall = np.full(frame_count, np.nan)
    midpoint_in_primary = np.zeros(frame_count - 1, dtype=bool)
    midpoint_distance_to_wall = np.full(frame_count - 1, np.nan)
    in_wall = np.zeros(frame_count, dtype=bool)
    open_area = np.zeros(frame_count, dtype=bool)
    steps_in_wall = np.zeros(frame_count - 1, dtype=bool)
    steps_open = np.zeros(frame_count - 1, dtype=bool)
    wall_pass = False
    if primary_roi is None:
        output["post_wake_wall_analysis_status"] = (
            "NOT_CALCULATED_NO_PRIMARY_ROI"
        )
    else:
        if valid.any():
            inside_primary[valid] = points_inside_polygon(
                effective_xy[valid], primary_roi
            )
            distance_to_wall[valid] = distance_to_polygon_boundary(
                effective_xy[valid], primary_roi
            )
        in_wall = (
            valid
            & inside_primary
            & (distance_to_wall <= wall_buffer_px)
            & post_frames
        )
        open_area = (
            valid
            & inside_primary
            & (distance_to_wall > wall_buffer_px)
            & post_frames
        )
        if post_accepted.any():
            midpoints = (effective_xy[:-1] + effective_xy[1:]) / 2.0
            midpoint_in_primary[post_accepted] = points_inside_polygon(
                midpoints[post_accepted], primary_roi
            )
            midpoint_distance_to_wall[post_accepted] = (
                distance_to_polygon_boundary(
                    midpoints[post_accepted], primary_roi
                )
            )
        steps_in_wall = (
            post_accepted
            & midpoint_in_primary
            & (midpoint_distance_to_wall <= wall_buffer_px)
        )
        steps_open = (
            post_accepted
            & midpoint_in_primary
            & (midpoint_distance_to_wall > wall_buffer_px)
        )
        frames_in = int(in_wall.sum())
        frames_out = int(open_area.sum())
        count_steps_in = int(steps_in_wall.sum())
        count_steps_out = int(steps_open.sum())
        output["post_wake_frames_inside_wall_buffer"] = frames_in
        output["post_wake_frames_outside_wall_buffer"] = frames_out
        output["post_wake_steps_inside_wall_buffer"] = count_steps_in
        output["post_wake_steps_outside_wall_buffer"] = count_steps_out
        distance_in = ""
        distance_out = ""
        if valid_step_count:
            distance_in = float(step_distances[steps_in_wall].sum())
            distance_out = float(step_distances[steps_open].sum())
            output["post_wake_distance_px_inside_wall_buffer"] = distance_in
            output["post_wake_distance_px_outside_wall_buffer"] = distance_out
        frames_outside_roi = int(
            (valid & post_frames & ~inside_primary).sum()
        )
        steps_outside_roi = int(
            (post_accepted & ~midpoint_in_primary).sum()
        )
        wall_pass = (
            frames_outside_roi == 0
            and steps_outside_roi == 0
            and frames_in + frames_out == valid_frames
            and count_steps_in + count_steps_out == valid_step_count
            and (
                not valid_step_count
                or math.isclose(
                    float(distance_in) + float(distance_out),
                    float(total_distance),
                    rel_tol=1e-10,
                    abs_tol=1e-8,
                )
            )
        )
        output["post_wake_wall_analysis_status"] = (
            "PASS" if wall_pass else "FAIL_OUTSIDE_PRIMARY_ROI"
        )
        if wall_pass:
            if valid_frames:
                output["post_wake_open_area_proportion"] = (
                    frames_out / valid_frames
                )
            if valid_step_count:
                output[
                    "post_wake_open_distance_px_per_available_step"
                ] = float(distance_out) / valid_step_count
                if count_steps_out:
                    output["post_wake_speed_px_per_open_step"] = (
                        float(distance_out) / count_steps_out
                    )
            assert frames_in + frames_out == valid_frames
            assert count_steps_in + count_steps_out == valid_step_count

    on_fungus = np.zeros(frame_count, dtype=bool)
    off_fungus = np.zeros(frame_count, dtype=bool)
    steps_on_fungus = np.zeros(frame_count - 1, dtype=bool)
    steps_off_fungus = np.zeros(frame_count - 1, dtype=bool)
    fungus_pass = False
    if is_fight:
        if secondary_roi is None:
            output["post_wake_fungus_analysis_status"] = (
                "NOT_CALCULATED_NO_SECONDARY_ROI"
            )
        else:
            if valid.any():
                on_fungus[valid] = points_inside_polygon(
                    effective_xy[valid], secondary_roi
                )
            on_fungus &= post_frames
            off_fungus = valid & post_frames & ~on_fungus
            midpoint_on_fungus = np.zeros(frame_count - 1, dtype=bool)
            if post_accepted.any():
                midpoints = (effective_xy[:-1] + effective_xy[1:]) / 2.0
                midpoint_on_fungus[post_accepted] = points_inside_polygon(
                    midpoints[post_accepted], secondary_roi
                )
            steps_on_fungus = post_accepted & midpoint_on_fungus
            steps_off_fungus = post_accepted & ~midpoint_on_fungus
            frames_on = int(on_fungus.sum())
            frames_off = int(off_fungus.sum())
            count_steps_on = int(steps_on_fungus.sum())
            count_steps_off = int(steps_off_fungus.sum())
            output["post_wake_frames_on_fungus"] = frames_on
            output["post_wake_frames_off_fungus"] = frames_off
            output["post_wake_steps_on_fungus"] = count_steps_on
            output["post_wake_steps_off_fungus"] = count_steps_off
            distance_on = ""
            distance_off = ""
            if valid_step_count:
                distance_on = float(
                    step_distances[steps_on_fungus].sum()
                )
                distance_off = float(
                    step_distances[steps_off_fungus].sum()
                )
                output["post_wake_distance_px_on_fungus"] = distance_on
                output["post_wake_distance_px_off_fungus"] = distance_off
            fungus_pass = (
                frames_on + frames_off == valid_frames
                and count_steps_on + count_steps_off == valid_step_count
                and (
                    not valid_step_count
                    or math.isclose(
                        float(distance_on) + float(distance_off),
                        float(total_distance),
                        rel_tol=1e-10,
                        abs_tol=1e-8,
                    )
                )
            )
            if not fungus_pass:
                raise AssertionError(
                    "Post-wake fungus on/off partition failed"
                )
            output["post_wake_fungus_analysis_status"] = "PASS"
            if valid_frames:
                output["post_wake_off_fungus_proportion"] = (
                    frames_off / valid_frames
                )
            if valid_step_count:
                output[
                    "post_wake_off_fungus_distance_px_per_available_step"
                ] = float(distance_off) / valid_step_count
                if count_steps_off:
                    output["post_wake_speed_px_per_off_fungus_step"] = (
                        float(distance_off) / count_steps_off
                    )

    if is_fight:
        if wall_pass and fungus_pass:
            open_and_off = open_area & off_fungus
            steps_open_and_off = steps_open & steps_off_fungus
            joint_frames = int(open_and_off.sum())
            joint_steps = int(steps_open_and_off.sum())
            joint_distance = (
                float(step_distances[steps_open_and_off].sum())
                if valid_step_count
                else ""
            )
            output["post_wake_frames_open_and_off_fungus"] = joint_frames
            output["post_wake_steps_open_and_off_fungus"] = joint_steps
            output[
                "post_wake_distance_px_open_and_off_fungus"
            ] = joint_distance
            if valid_frames:
                output["post_wake_open_off_fungus_proportion"] = (
                    joint_frames / valid_frames
                )
            if valid_step_count:
                output[
                    "post_wake_open_off_fungus_distance_px_per_available_step"
                ] = float(joint_distance) / valid_step_count
                if joint_steps:
                    output[
                        "post_wake_speed_px_per_open_off_fungus_step"
                    ] = float(joint_distance) / joint_steps
            output[
                "post_wake_open_off_fungus_analysis_status"
            ] = "PASS"
            assert np.all(~open_and_off | open_area)
            assert np.all(~open_and_off | off_fungus)
            assert np.all(~steps_open_and_off | steps_open)
            assert np.all(~steps_open_and_off | steps_off_fungus)
        else:
            output[
                "post_wake_open_off_fungus_analysis_status"
            ] = "NOT_CALCULATED_WALL_OR_FUNGUS_PARTITION_UNAVAILABLE"
    return output


def compute_post_wake_3600_metrics(
    *,
    effective_xy: np.ndarray,
    raw_xy: np.ndarray,
    original_xy: np.ndarray,
    start_offset: int,
    analysis_start_global_frame: int,
    step_distances: np.ndarray,
    accepted_steps: np.ndarray,
    rejected_jump_steps: np.ndarray,
    primary_roi: np.ndarray | None,
    secondary_roi: np.ndarray | None,
    wall_buffer_px: float,
    fungus_buffer_px: float,
    is_fight: bool,
    anchor_rule: str,
    social: dict | None,
    social_all_xy: np.ndarray,
    social_all_missing_mask: np.ndarray,
    focal_social_disappearance_mask: np.ndarray,
    social_distance_threshold_px: float,
    imputed_mask: np.ndarray,
    turtling_result: dict,
) -> dict:
    """Calculate one complete 3600-interval window after the chosen wake anchor.

    The inclusive coordinate window contains 3601 frame observations. For BAs,
    ``start_offset`` is the focal animal's wake offset. For fights it is the
    later of the two wake offsets, so both output rows share exactly the same
    global start and end. All movement calculations retain the existing
    accepted-adjacent-step and midpoint rules.
    """
    stop_offset = start_offset + POST_WAKE_FIXED_INTERVALS
    if start_offset < 0 or stop_offset >= len(effective_xy):
        raise ValueError("A complete 3600-interval post-wake window is required")
    frame_slice = slice(start_offset, stop_offset + 1)
    step_slice = slice(start_offset, stop_offset)
    fixed_effective = np.asarray(effective_xy[frame_slice], dtype=float)
    fixed_raw = np.asarray(raw_xy[frame_slice], dtype=float)
    fixed_original = np.asarray(original_xy[frame_slice], dtype=float)
    fixed_step_distances = np.asarray(step_distances[step_slice], dtype=float)
    fixed_accepted_steps = np.asarray(accepted_steps[step_slice], dtype=bool)
    fixed_rejected_steps = np.asarray(
        rejected_jump_steps[step_slice], dtype=bool
    )

    core = compute_post_wake_metrics(
        effective_xy=fixed_effective,
        raw_xy=fixed_raw,
        wake_offset=0,
        step_distances=fixed_step_distances,
        accepted_steps=fixed_accepted_steps,
        rejected_jump_steps=fixed_rejected_steps,
        primary_roi=primary_roi,
        secondary_roi=secondary_roi,
        wall_buffer_px=wall_buffer_px,
        is_fight=is_fight,
    )
    output = {
        key.replace("post_wake_", "post_wake_3600_", 1): value
        for key, value in core.items()
    }
    output.update(
        {
            "post_wake_3600_anchor_rule": anchor_rule,
            "post_wake_3600_start_global_frame": (
                analysis_start_global_frame + start_offset
            ),
            "post_wake_3600_end_global_frame_inclusive": (
                analysis_start_global_frame + stop_offset
            ),
            "post_wake_3600_frame_intervals": POST_WAKE_FIXED_INTERVALS,
            "post_wake_3600_frame_observations_inclusive": (
                POST_WAKE_FIXED_INTERVALS + 1
            ),
        }
    )

    fixed_valid = np.isfinite(fixed_effective).all(axis=1)
    fixed_raw_valid = np.isfinite(fixed_raw).all(axis=1)
    fixed_original_valid = np.isfinite(fixed_original).all(axis=1)
    fixed_imputed = np.asarray(imputed_mask[frame_slice], dtype=bool)
    fixed_imputed_count = int((fixed_imputed & fixed_valid).sum())
    fixed_missing_count = int((~fixed_raw_valid).sum())
    remaining_missing = fixed_missing_count - fixed_imputed_count
    if remaining_missing < 0:
        raise AssertionError(
            "Fixed-window social substitutions exceeded original missing frames"
        )
    output[
        "post_wake_3600_social_disappearance_imputed_frames"
    ] = fixed_imputed_count if is_fight else ""
    output[
        "post_wake_3600_remaining_missing_coordinate_frames_after_social_substitution"
    ] = remaining_missing
    output[
        "post_wake_3600_coordinate_frames_used_in_distance_and_location_calculations"
    ] = int(fixed_valid.sum())
    output.update(
        {
            "post_wake_3600_frames_in_fungus_edge_buffer": "",
            "post_wake_3600_frames_in_fungus_interior": "",
            "post_wake_3600_distance_px_in_fungus_edge_buffer": "",
            "post_wake_3600_distance_px_in_fungus_interior": "",
        }
    )
    if is_fight and secondary_roi is not None:
        fixed_on_fungus = np.zeros(len(fixed_effective), dtype=bool)
        fixed_fungus_edge_distance = np.full(
            len(fixed_effective), np.nan
        )
        if fixed_valid.any():
            fixed_on_fungus[fixed_valid] = points_inside_polygon(
                fixed_effective[fixed_valid], secondary_roi
            )
            fixed_fungus_edge_distance[fixed_valid] = (
                distance_to_polygon_boundary(
                    fixed_effective[fixed_valid], secondary_roi
                )
            )
        fixed_in_fungus_buffer = (
            fixed_on_fungus
            & (fixed_fungus_edge_distance <= fungus_buffer_px)
        )
        fixed_in_fungus_interior = (
            fixed_on_fungus
            & (fixed_fungus_edge_distance > fungus_buffer_px)
        )
        fixed_midpoint_on_fungus = np.zeros(
            len(fixed_step_distances), dtype=bool
        )
        fixed_midpoint_fungus_edge_distance = np.full(
            len(fixed_step_distances), np.nan
        )
        if fixed_accepted_steps.any():
            fixed_midpoints = (
                fixed_effective[:-1] + fixed_effective[1:]
            ) / 2.0
            fixed_midpoint_on_fungus[fixed_accepted_steps] = (
                points_inside_polygon(
                    fixed_midpoints[fixed_accepted_steps],
                    secondary_roi,
                )
            )
            fixed_midpoint_fungus_edge_distance[fixed_accepted_steps] = (
                distance_to_polygon_boundary(
                    fixed_midpoints[fixed_accepted_steps],
                    secondary_roi,
                )
            )
        fixed_steps_in_fungus_buffer = (
            fixed_accepted_steps
            & fixed_midpoint_on_fungus
            & (
                fixed_midpoint_fungus_edge_distance
                <= fungus_buffer_px
            )
        )
        fixed_steps_in_fungus_interior = (
            fixed_accepted_steps
            & fixed_midpoint_on_fungus
            & (
                fixed_midpoint_fungus_edge_distance
                > fungus_buffer_px
            )
        )
        fixed_buffer_distance = ""
        fixed_interior_distance = ""
        if fixed_accepted_steps.any():
            fixed_buffer_distance = float(
                fixed_step_distances[fixed_steps_in_fungus_buffer].sum()
            )
            fixed_interior_distance = float(
                fixed_step_distances[fixed_steps_in_fungus_interior].sum()
            )
        output.update(
            {
                "post_wake_3600_frames_in_fungus_edge_buffer": int(
                    fixed_in_fungus_buffer.sum()
                ),
                "post_wake_3600_frames_in_fungus_interior": int(
                    fixed_in_fungus_interior.sum()
                ),
                "post_wake_3600_distance_px_in_fungus_edge_buffer": (
                    fixed_buffer_distance
                ),
                "post_wake_3600_distance_px_in_fungus_interior": (
                    fixed_interior_distance
                ),
            }
        )
        assert (
            output["post_wake_3600_frames_in_fungus_edge_buffer"]
            + output["post_wake_3600_frames_in_fungus_interior"]
            == output["post_wake_3600_frames_on_fungus"]
        )
        if output["post_wake_3600_distance_px_on_fungus"] != "":
            assert math.isclose(
                output["post_wake_3600_distance_px_in_fungus_edge_buffer"]
                + output["post_wake_3600_distance_px_in_fungus_interior"],
                output["post_wake_3600_distance_px_on_fungus"],
                rel_tol=1e-10,
                abs_tol=1e-8,
            )

    if not is_fight:
        output.update(
            {
                "post_wake_3600_social_analysis_status": (
                    "NOT_APPLICABLE_NOT_FIGHT"
                ),
                "post_wake_3600_frames_within_social_distance": "",
                "post_wake_3600_distance_moved_px_while_within_social_distance": "",
                "post_wake_3600_social_disappearance_frames": "",
                "post_wake_3600_social_return_interaction_events": "",
            }
        )
    elif social is None or social["status"] != "CALCULATED_FIGHT_TWO_ANIMALS":
        output.update(
            {
                "post_wake_3600_social_analysis_status": (
                    "NOT_CALCULATED_EXPECTED_TWO_ANIMALS"
                ),
                "post_wake_3600_frames_within_social_distance": "",
                "post_wake_3600_distance_moved_px_while_within_social_distance": "",
                "post_wake_3600_social_disappearance_frames": "",
                "post_wake_3600_social_return_interaction_events": "",
            }
        )
    else:
        fixed_within = np.asarray(
            social["within_mask"][frame_slice], dtype=bool
        )
        fixed_social_steps = (
            fixed_accepted_steps
            & fixed_within[:-1]
            & fixed_within[1:]
        )
        fixed_social = compute_social_candidates(
            social_all_xy[frame_slice],
            social_distance_threshold_px=social_distance_threshold_px,
            eligible_missing_mask=social_all_missing_mask[frame_slice],
        )
        output.update(
            {
                "post_wake_3600_social_analysis_status": (
                    "CALCULATED_FIGHT_TWO_ANIMALS"
                ),
                "post_wake_3600_frames_within_social_distance": int(
                    fixed_within.sum()
                ),
                "post_wake_3600_distance_moved_px_while_within_social_distance": (
                    float(fixed_step_distances[fixed_social_steps].sum())
                ),
                "post_wake_3600_social_disappearance_frames": int(
                    focal_social_disappearance_mask[frame_slice].sum()
                ),
                "post_wake_3600_social_return_interaction_events": int(
                    fixed_social["return_events"]
                ),
            }
        )

    fixed_turtling_mask = np.asarray(
        turtling_result["mask"][frame_slice], dtype=bool
    )
    fixed_turtling_frames = int(fixed_turtling_mask.sum())
    output.update(
        {
            "post_wake_3600_turtling_candidate_frames": (
                fixed_turtling_frames
            ),
            "post_wake_3600_turtling_candidate_proportion_of_detected_frames": (
                fixed_turtling_frames / int(fixed_original_valid.sum())
                if fixed_original_valid.any()
                else ""
            ),
            "post_wake_3600_turtling_candidate_events": len(
                _events_from_mask(fixed_turtling_mask)
            ),
            "post_wake_3600_turtling_detector_status": (
                turtling_result["status"]
            ),
        }
    )
    return output


def compute_turtling_candidates(
    xy: np.ndarray,
    window_frames: int = 120,
    min_path_px: float = 120.0,
    max_radius90_px: float = 35.0,
    min_turn_rotations: float = 3.0,
    max_straightness: float = 0.25,
    max_step_px: float = 20.0,
) -> dict:
    """Screen for sustained tight looping using original centroid coordinates.

    This is deliberately a trajectory candidate detector, not a posture
    classifier. It never uses social-disappearance substitutions.
    """
    xy = np.asarray(xy, dtype=float)
    frame_count = len(xy)
    candidate_mask = np.zeros(frame_count, dtype=bool)
    if frame_count < window_frames:
        return {
            "mask": candidate_mask,
            "events": [],
            "status": "NOT_CALCULATED_WINDOW_LONGER_THAN_ANALYSIS",
        }

    for start_offset in range(frame_count - window_frames + 1):
        stop_offset = start_offset + window_frames
        block = xy[start_offset:stop_offset]
        valid = np.isfinite(block).all(axis=1)

        # Up to 5% missing positions may occur, but missing gaps are never
        # bridged and missing frames are never labeled as candidates.
        if float(valid.mean()) < 0.95:
            continue

        step_vectors = np.diff(block, axis=0)
        valid_steps = valid[:-1] & valid[1:]
        step_lengths = np.linalg.norm(step_vectors, axis=1)
        if (
            valid_steps.any()
            and float(step_lengths[valid_steps].max()) > max_step_px
        ):
            continue

        # Sub-pixel centroid movement is excluded from path and turn evidence
        # so stationary tracking jitter cannot by itself create a candidate.
        moving_steps = valid_steps & (step_lengths >= 1.0)
        path_px = float(step_lengths[moving_steps].sum())
        if path_px < min_path_px:
            continue

        observed_points = block[valid]
        center = np.median(observed_points, axis=0)
        radii = np.linalg.norm(observed_points - center, axis=1)
        radius90_px = float(np.quantile(radii, 0.90))
        if not 5.0 <= radius90_px <= max_radius90_px:
            continue

        consecutive_moving_steps = moving_steps[:-1] & moving_steps[1:]
        if not consecutive_moving_steps.any():
            continue
        headings = np.arctan2(step_vectors[:, 1], step_vectors[:, 0])
        heading_changes = np.arctan2(
            np.sin(np.diff(headings)),
            np.cos(np.diff(headings)),
        )
        absolute_turn_rotations = float(
            np.abs(heading_changes[consecutive_moving_steps]).sum()
            / (2.0 * np.pi)
        )
        if absolute_turn_rotations < min_turn_rotations:
            continue

        observed_indices = np.flatnonzero(valid)
        net_displacement_px = float(
            np.linalg.norm(
                block[int(observed_indices[-1])]
                - block[int(observed_indices[0])]
            )
        )
        if net_displacement_px / path_px > max_straightness:
            continue

        candidate_mask[start_offset:stop_offset] |= valid

    return {
        "mask": candidate_mask,
        "events": _events_from_mask(candidate_mask),
        "status": "CALCULATED_PROVISIONAL_CENTROID_PATH_CANDIDATES",
    }


def compute_wake_threshold_result(
    observed_xy: np.ndarray,
    *,
    analysis_start_global_frame: int,
    movement_threshold_px: float,
    one_frame_jump_threshold_px: float,
) -> dict:
    """Apply the exact-start, continuous-chain wake threshold rule once."""
    observed_xy = np.asarray(observed_xy, dtype=float)
    valid = np.isfinite(observed_xy).all(axis=1)
    result = {
        "crossing": "",
        "latency": "",
        "baseline_x": "",
        "baseline_y": "",
        "status": "OK",
        "warning": "",
    }
    if not valid[0]:
        result.update(
            {
                "status": "NOT_CALCULATED",
                "warning": (
                    "The coordinate at the exact analysis-entry frame is "
                    "missing; no later frame was substituted and no latency "
                    "was calculated."
                ),
            }
        )
        return result

    differences = observed_xy[1:] - observed_xy[:-1]
    step_distances = np.sqrt(np.sum(differences ** 2, axis=1))
    valid_steps = valid[:-1] & valid[1:]
    accepted_steps = (
        valid_steps & (step_distances <= one_frame_jump_threshold_px)
    )
    reachable = np.zeros(len(observed_xy), dtype=bool)
    reachable[0] = True
    for frame_offset in range(1, len(observed_xy)):
        reachable[frame_offset] = (
            reachable[frame_offset - 1]
            and accepted_steps[frame_offset - 1]
        )

    baseline = observed_xy[0]
    result["baseline_x"] = float(baseline[0])
    result["baseline_y"] = float(baseline[1])
    displacement = np.full(len(observed_xy), np.nan)
    displacement[valid] = np.sqrt(
        np.sum((observed_xy[valid] - baseline) ** 2, axis=1)
    )
    hits = np.flatnonzero(
        (displacement >= movement_threshold_px) & reachable
    )
    if hits.size:
        latency = int(hits[0])
        result["latency"] = latency
        result["crossing"] = analysis_start_global_frame + latency
    else:
        result.update(
            {
                "status": "THRESHOLD_NOT_REACHED",
                "warning": (
                    "Threshold was not reached through a continuous sequence "
                    "of valid steps at or below the one-frame jump threshold."
                ),
            }
        )
    return result


def analyze(
    trajectory_file: Path,
    session_folder: Path,
    start: int,
    window: int,
    threshold: float,
    wall_buffer_px: float = 30.0,
    fungus_buffer_px: float = 30.0,
    analysis_type: str = "",
    social_distance_threshold_px: float = 60.0,
    use_social_disappearance_in_calculations: bool = False,
    one_frame_jump_threshold_px: float = 200.0,
    turtling_window_frames: int = 120,
    turtling_min_path_px: float = 120.0,
    turtling_max_radius90_px: float = 35.0,
    turtling_min_turn_rotations: float = 3.0,
    turtling_max_straightness: float = 0.25,
    turtling_max_step_px: float = 20.0,
    analysis_start_original_global_frame: int | None = None,
    analysis_start_source: str = "SOURCE_INTERVAL",
    analysis_start_adjustment_provenance: str = "",
) -> list[dict]:
    if start <= 0:
        raise ValueError("Analysis start must be greater than zero; zero is a data-entry flag")
    if window <= 0 or threshold <= 0:
        raise ValueError("Window frames and wake threshold must be positive")
    if wall_buffer_px < 0 or fungus_buffer_px < 0:
        raise ValueError("ROI-buffer widths cannot be negative")
    if social_distance_threshold_px <= 0:
        raise ValueError("The social-distance threshold must be positive")
    if one_frame_jump_threshold_px <= 0:
        raise ValueError("The one-frame jump threshold must be positive")
    if turtling_window_frames < 3:
        raise ValueError("The turtling window must contain at least 3 frames")
    if (
        turtling_min_path_px <= 0
        or turtling_max_radius90_px < 5
        or turtling_min_turn_rotations <= 0
        or not 0 <= turtling_max_straightness <= 1
        or turtling_max_step_px <= 0
    ):
        raise ValueError(
            "Invalid turtling settings: path, turns, and maximum step must be "
            "positive; radius90 must be at least 5 pixels; maximum "
            "straightness must be a proportion from 0 through 1"
        )

    trajectory_source_kind = validate_trajectory_source(
        trajectory_file
    )
    arr = load_trajectories(trajectory_file)
    try:
        rois = load_rois(session_folder)
        primary_roi = rois[0]
        roi_error = ""
    except Exception as exc:
        rois = []
        primary_roi = None
        roi_error = str(exc)
    is_fight = "fight" in analysis_type.strip().lower()
    secondary_roi = rois[1] if is_fight and len(rois) > 1 else None
    end_inclusive = start + window
    if end_inclusive >= arr.shape[0]:
        raise ValueError(
            "Requested global window is outside the trajectory array: "
            f"inclusive frames {start} through {end_inclusive} versus "
            f"global frames 0 through {arr.shape[0] - 1}. "
            "Processing stopped because the array may be interval-relative."
        )
    window_arr = arr[start : end_inclusive + 1]
    raw_missing_mask = ~np.isfinite(window_arr).all(axis=2)
    original_jump_qc = [
        filter_jump_artifact_coordinates(
            window_arr[:, animal, :],
            threshold_px=one_frame_jump_threshold_px,
        )
        for animal in range(window_arr.shape[1])
    ]
    jump_filtered_arr = np.stack(
        [result["cleaned_xy"] for result in original_jump_qc],
        axis=1,
    )
    social = (
        compute_social_candidates(
            jump_filtered_arr,
            social_distance_threshold_px=social_distance_threshold_px,
            eligible_missing_mask=raw_missing_mask,
        )
        if is_fight
        else None
    )
    calculation_arr = jump_filtered_arr.copy()
    imputed_frames_by_animal = np.zeros(
        window_arr.shape[1], dtype=int
    )
    if (
        use_social_disappearance_in_calculations
        and social is not None
        and social["status"] == "CALCULATED_FIGHT_TWO_ANIMALS"
    ):
        for missing_animal in (0, 1):
            impute_mask = social["disappearance_masks_by_animal"][
                :, missing_animal
            ]
            calculation_arr[impute_mask, missing_animal, :] = (
                jump_filtered_arr[impute_mask, 1 - missing_animal, :]
            )
    calculation_jump_qc = [
        filter_jump_artifact_coordinates(
            calculation_arr[:, animal, :],
            threshold_px=one_frame_jump_threshold_px,
        )
        for animal in range(window_arr.shape[1])
    ]
    calculation_arr = np.stack(
        [result["cleaned_xy"] for result in calculation_jump_qc],
        axis=1,
    )
    if (
        use_social_disappearance_in_calculations
        and social is not None
        and social["status"] == "CALCULATED_FIGHT_TWO_ANIMALS"
    ):
        calculation_valid = np.isfinite(calculation_arr).all(axis=2)
        for missing_animal in (0, 1):
            impute_mask = social["disappearance_masks_by_animal"][
                :, missing_animal
            ]
            imputed_frames_by_animal[missing_animal] = int(
                (impute_mask & calculation_valid[:, missing_animal]).sum()
            )
    turtling_by_animal = [
        exclude_turtling_candidates_on_fungus(
            compute_turtling_candidates(
                jump_filtered_arr[:, animal, :],
                window_frames=turtling_window_frames,
                min_path_px=turtling_min_path_px,
                max_radius90_px=turtling_max_radius90_px,
                min_turn_rotations=turtling_min_turn_rotations,
                max_straightness=turtling_max_straightness,
                max_step_px=turtling_max_step_px,
            ),
            jump_filtered_arr[:, animal, :],
            secondary_roi,
        )
        for animal in range(window_arr.shape[1])
    ]
    starting_sides = ["NOT_APPLICABLE_NOT_FIGHT"] * window_arr.shape[1]
    if is_fight:
        starting_sides = ["UNASSIGNED_EXPECTED_TWO_ANIMALS"] * window_arr.shape[1]
        if window_arr.shape[1] == 2:
            start_xy = jump_filtered_arr[0]
            if not np.isfinite(start_xy).all():
                starting_sides = ["UNASSIGNED_MISSING_START_COORDINATE"] * 2
            elif math.isclose(
                float(start_xy[0, 0]),
                float(start_xy[1, 0]),
                rel_tol=0.0,
                abs_tol=1e-9,
            ):
                starting_sides = ["UNASSIGNED_EQUAL_START_X"] * 2
            elif start_xy[0, 0] < start_xy[1, 0]:
                starting_sides = ["LEFT", "RIGHT"]
            else:
                starting_sides = ["RIGHT", "LEFT"]
    wake_results = [
        compute_wake_threshold_result(
            jump_filtered_arr[:, animal, :],
            analysis_start_global_frame=start,
            movement_threshold_px=threshold,
            one_frame_jump_threshold_px=one_frame_jump_threshold_px,
        )
        for animal in range(window_arr.shape[1])
    ]
    fight_fixed_anchor_offset = None
    fight_fixed_unavailable_status = ""
    if is_fight:
        if window_arr.shape[1] != 2:
            fight_fixed_unavailable_status = (
                "NOT_CALCULATED_FIGHT_REQUIRES_EXACTLY_TWO_ANIMALS"
            )
        elif any(result["latency"] == "" for result in wake_results):
            fight_fixed_unavailable_status = (
                "NOT_CALCULATED_ONE_OR_BOTH_ANIMALS_NO_WAKE_FRAME"
            )
        else:
            fight_fixed_anchor_offset = max(
                int(result["latency"]) for result in wake_results
            )
    output = []
    for individual in range(window_arr.shape[1]):
        raw_observed_xy = window_arr[:, individual, :]
        observed_xy = jump_filtered_arr[:, individual, :]
        raw_valid = np.isfinite(raw_observed_xy).all(axis=1)
        original_valid = np.isfinite(observed_xy).all(axis=1)
        xy = calculation_arr[:, individual, :]
        valid = np.isfinite(xy).all(axis=1)
        warning = ""
        wake_result = wake_results[individual]
        crossing = wake_result["crossing"]
        latency = wake_result["latency"]
        baseline_x = wake_result["baseline_x"]
        baseline_y = wake_result["baseline_y"]
        status = wake_result["status"]
        warnings = []
        if wake_result["warning"]:
            warnings.append(wake_result["warning"])
        if trajectory_source_kind.startswith("IDTRACKER_RAW_"):
            warnings.append(
                "RAW_IDTRACKER_INPUT: no validated/without-gaps trajectory "
                "was available. Original missing counts are preserved; "
                "remaining invalid distance steps are excluded without gap bridging."
            )

        differences = xy[1:] - xy[:-1]
        step_distances = np.sqrt(np.sum(differences ** 2, axis=1))
        valid_steps = valid[:-1] & valid[1:]
        accepted_steps = (
            valid_steps
            & (step_distances <= one_frame_jump_threshold_px)
        )
        jump_qc = calculation_jump_qc[individual]
        one_frame_jumps_excluded = int(
            jump_qc["rejected_step_mask"].sum()
        )
        # Deprecated compatibility field: jump QC is now step-only and does
        # not delete either endpoint coordinate.
        jump_artifact_frames = 0
        if valid_steps.any():
            total_distance = float(step_distances[accepted_steps].sum())
        else:
            total_distance = ""
            warnings.append(
                "No adjacent frame pair had valid coordinates at both endpoints "
                "and a step at or below the one-frame jump threshold; total "
                "distance was not calculated."
            )
        excluded_steps = int((~valid_steps).sum())
        missing_coordinate_frames = int((~raw_valid).sum())
        if missing_coordinate_frames:
            warnings.append(
                f"The selected IDtracker {trajectory_source_kind} file still "
                f"contains {missing_coordinate_frames} missing coordinate "
                "frame(s) inside this analysis window; they remain missing in "
                "the original-data counts."
            )
        imputed_frame_count = int(imputed_frames_by_animal[individual])
        remaining_missing_after_social_substitution = (
            missing_coordinate_frames - imputed_frame_count
        )
        if remaining_missing_after_social_substitution < 0:
            raise AssertionError(
                "Social-disappearance substitutions exceeded original "
                "missing-coordinate frames"
            )
        if imputed_frame_count:
            warnings.append(
                "SOCIAL_DISAPPEARANCE_IMPUTATION_USED: the visible partner's "
                f"centroid was copied into {imputed_frame_count} qualifying "
                "missing frame(s) for total distance and wall/fungus location "
                "calculations. Latency and original missing-data counts still "
                "use the unmodified IDtracker coordinates."
            )
        if excluded_steps:
            warnings.append(
                f"Distance excluded {excluded_steps} adjacent-frame pair(s) "
                "with a missing coordinate at one or both endpoints; remaining "
                "gaps were not bridged."
            )
        if one_frame_jumps_excluded:
            warnings.append(
                f"ANTI_JUMP_STEP_QC: excluded {one_frame_jumps_excluded} "
                f"adjacent movement step(s) strictly greater than "
                f"{one_frame_jump_threshold_px:g} pixels. Endpoint coordinates "
                "remain available for frame-based wall/fungus counts; rejected "
                "steps are excluded from latency chains, distance totals, ROI "
                "movement distances, social movement distance, and PDF path "
                "connections without interpolation."
            )
        turtling_result = turtling_by_animal[individual]
        turtling_candidate_frames = int(
            turtling_result["mask"].sum()
        )
        turtling_candidate_proportion = (
            float(turtling_candidate_frames / int(original_valid.sum()))
            if original_valid.any()
            else ""
        )
        turtling_candidate_events = len(turtling_result["events"])
        if turtling_candidate_frames:
            warnings.append(
                "TURTLING_CANDIDATE_ONLY: centroid-path geometry identified "
                f"{turtling_candidate_frames} candidate frame(s) in "
                f"{turtling_candidate_events} event(s). Coordinates alone "
                "cannot confirm that the beetle was physically upside down; "
                "review the dark-red PDF overlay."
            )

        frames_in_wall = ""
        frames_outside_wall = ""
        distance_in_wall = ""
        distance_outside_wall = ""
        spatial_status = "NOT_CALCULATED"
        if primary_roi is None:
            warnings.append(
                "Wall-buffer metrics were not calculated because the primary ROI "
                f"could not be loaded: {roi_error}"
            )
        else:
            inside_roi = np.zeros(len(xy), dtype=bool)
            distance_to_wall = np.full(len(xy), np.nan)
            if valid.any():
                inside_roi[valid] = points_inside_polygon(
                    xy[valid], primary_roi
                )
                distance_to_wall[valid] = distance_to_polygon_boundary(
                    xy[valid], primary_roi
                )
            in_wall = (
                valid
                & inside_roi
                & (distance_to_wall <= wall_buffer_px)
            )
            outside_wall = (
                valid
                & inside_roi
                & (distance_to_wall > wall_buffer_px)
            )
            frames_in_wall = int(in_wall.sum())
            frames_outside_wall = int(outside_wall.sum())

            midpoint_in_roi = np.zeros(len(step_distances), dtype=bool)
            midpoint_distance_to_wall = np.full(
                len(step_distances), np.nan
            )
            if accepted_steps.any():
                midpoints = (xy[:-1] + xy[1:]) / 2.0
                midpoint_in_roi[accepted_steps] = points_inside_polygon(
                    midpoints[accepted_steps], primary_roi
                )
                midpoint_distance_to_wall[accepted_steps] = (
                    distance_to_polygon_boundary(
                        midpoints[accepted_steps], primary_roi
                    )
                )
            step_in_wall = (
                accepted_steps
                & midpoint_in_roi
                & (midpoint_distance_to_wall <= wall_buffer_px)
            )
            step_outside_wall = (
                accepted_steps
                & midpoint_in_roi
                & (midpoint_distance_to_wall > wall_buffer_px)
            )
            distance_in_wall = float(step_distances[step_in_wall].sum())
            distance_outside_wall = float(
                step_distances[step_outside_wall].sum()
            )

            frames_outside_roi = int((valid & ~inside_roi).sum())
            distance_outside_roi = float(
                step_distances[accepted_steps & ~midpoint_in_roi].sum()
            )
            frame_ok = (
                frames_in_wall + frames_outside_wall
                == int(valid.sum())
            )
            distance_ok = math.isclose(
                distance_in_wall + distance_outside_wall,
                float(total_distance) if total_distance != "" else 0.0,
                rel_tol=1e-10,
                abs_tol=1e-8,
            )
            if frame_ok and distance_ok:
                spatial_status = "PASS"
            else:
                spatial_status = "FAIL_OUTSIDE_PRIMARY_ROI"
                warnings.append(
                    "Wall/interior additivity failed because primary-ROI QC found "
                    f"{frames_outside_roi} valid frame(s), "
                    f"{distance_outside_roi:.6g} px of midpoint-classified distance "
                    "outside the primary ROI."
                )

        frames_on_fungus = ""
        frames_in_fungus_buffer = ""
        frames_in_fungus_interior = ""
        distance_on_fungus = ""
        distance_in_fungus_buffer = ""
        distance_in_fungus_interior = ""
        fungus_status = "NOT_APPLICABLE_NOT_FIGHT"
        if is_fight:
            if secondary_roi is None:
                fungus_status = "NOT_CALCULATED_NO_SECONDARY_ROI"
                warnings.append(
                    "Fungus metrics were not calculated because this fight session "
                    "does not contain roi_list[1]."
                )
            else:
                on_fungus = np.zeros(len(xy), dtype=bool)
                distance_to_fungus_edge = np.full(len(xy), np.nan)
                if valid.any():
                    on_fungus[valid] = points_inside_polygon(
                        xy[valid], secondary_roi
                    )
                    distance_to_fungus_edge[valid] = (
                        distance_to_polygon_boundary(
                            xy[valid], secondary_roi
                        )
                    )
                in_fungus_buffer = (
                    on_fungus
                    & (distance_to_fungus_edge <= fungus_buffer_px)
                )
                in_fungus_interior = (
                    on_fungus
                    & (distance_to_fungus_edge > fungus_buffer_px)
                )
                frames_on_fungus = int(on_fungus.sum())
                frames_in_fungus_buffer = int(in_fungus_buffer.sum())
                frames_in_fungus_interior = int(in_fungus_interior.sum())

                segment_on_fungus = np.zeros(len(step_distances), dtype=bool)
                segment_distance_to_fungus_edge = np.full(
                    len(step_distances), np.nan
                )
                if accepted_steps.any():
                    midpoints = (xy[:-1] + xy[1:]) / 2.0
                    segment_on_fungus[accepted_steps] = points_inside_polygon(
                        midpoints[accepted_steps], secondary_roi
                    )
                    segment_distance_to_fungus_edge[accepted_steps] = (
                        distance_to_polygon_boundary(
                            midpoints[accepted_steps], secondary_roi
                        )
                    )
                segment_in_fungus_buffer = (
                    accepted_steps
                    & segment_on_fungus
                    & (
                        segment_distance_to_fungus_edge
                        <= fungus_buffer_px
                    )
                )
                segment_in_fungus_interior = (
                    accepted_steps
                    & segment_on_fungus
                    & (
                        segment_distance_to_fungus_edge
                        > fungus_buffer_px
                    )
                )
                distance_on_fungus = float(
                    step_distances[
                        accepted_steps & segment_on_fungus
                    ].sum()
                )
                distance_in_fungus_buffer = float(
                    step_distances[segment_in_fungus_buffer].sum()
                )
                distance_in_fungus_interior = float(
                    step_distances[segment_in_fungus_interior].sum()
                )
                fungus_frames_ok = (
                    frames_in_fungus_buffer + frames_in_fungus_interior
                    == frames_on_fungus
                )
                fungus_distance_ok = math.isclose(
                    distance_in_fungus_buffer
                    + distance_in_fungus_interior,
                    distance_on_fungus,
                    rel_tol=1e-10,
                    abs_tol=1e-8,
                )
                fungus_status = (
                    "PASS"
                    if fungus_frames_ok and fungus_distance_ok
                    else "FAIL_INTERNAL_PARTITION"
                )
                if fungus_status != "PASS":
                    warnings.append(
                        "Fungus edge-buffer/interior additivity failed; "
                        "this result requires review."
                    )
        if social is None:
            social_threshold = ""
            social_frames = ""
            social_distance_moved = ""
            social_disappearance_frames = ""
            social_return_events = ""
            social_status = "NOT_APPLICABLE_NOT_FIGHT"
        else:
            social_status = social["status"]
            social_threshold = social_distance_threshold_px
            if social_status == "CALCULATED_FIGHT_TWO_ANIMALS":
                social_frames = int(social["within_mask"].sum())
                social_steps = (
                    accepted_steps
                    & social["within_mask"][:-1]
                    & social["within_mask"][1:]
                )
                social_distance_moved = float(
                    step_distances[social_steps].sum()
                )
                social_disappearance_frames = int(
                    social["disappearance_masks_by_animal"][
                        :, individual
                    ].sum()
                )
                social_return_events = int(social["return_events"])
            else:
                social_frames = ""
                social_distance_moved = ""
                social_disappearance_frames = ""
                social_return_events = ""
                warnings.append(
                    "Social-distance metrics were not calculated "
                    "because exactly two IDtracker animals are required."
                )
        if crossing == "":
            post_wake = blank_post_wake_metrics(
                (
                    "NOT_CALCULATED_INVALID_BASELINE"
                    if not original_valid[0]
                    else "NOT_CALCULATED_THRESHOLD_NOT_REACHED"
                ),
                is_fight=is_fight,
            )
        else:
            post_wake = compute_post_wake_metrics(
                effective_xy=xy,
                raw_xy=raw_observed_xy,
                wake_offset=int(latency),
                step_distances=step_distances,
                accepted_steps=accepted_steps,
                rejected_jump_steps=jump_qc["rejected_step_mask"],
                primary_roi=primary_roi,
                secondary_roi=secondary_roi,
                wall_buffer_px=wall_buffer_px,
                is_fight=is_fight,
            )
        fixed_anchor_rule = (
            "BOTH_ANIMALS_WAKE_LATER_CROSSING"
            if is_fight
            else "INDIVIDUAL_WAKE_THRESHOLD_CROSSING"
        )
        if is_fight:
            fixed_anchor_offset = fight_fixed_anchor_offset
            fixed_unavailable_status = fight_fixed_unavailable_status
        else:
            fixed_anchor_offset = (
                int(latency) if latency != "" else None
            )
            fixed_unavailable_status = (
                "NOT_CALCULATED_INVALID_BASELINE"
                if not original_valid[0]
                else "NOT_CALCULATED_THRESHOLD_NOT_REACHED"
            )
        if fixed_anchor_offset is None:
            post_wake_3600 = blank_post_wake_3600_metrics(
                fixed_unavailable_status,
                is_fight=is_fight,
                anchor_rule=fixed_anchor_rule,
            )
        elif (
            fixed_anchor_offset + POST_WAKE_FIXED_INTERVALS
            >= len(window_arr)
        ):
            post_wake_3600 = blank_post_wake_3600_metrics(
                "NOT_CALCULATED_COMPLETE_3600_FRAME_WINDOW_DOES_NOT_FIT",
                is_fight=is_fight,
                anchor_rule=fixed_anchor_rule,
            )
        else:
            if (
                is_fight
                and social is not None
                and social["status"] == "CALCULATED_FIGHT_TWO_ANIMALS"
            ):
                focal_disappearance_mask = social[
                    "disappearance_masks_by_animal"
                ][:, individual]
            else:
                focal_disappearance_mask = np.zeros(
                    len(window_arr), dtype=bool
                )
            focal_imputed_mask = (
                focal_disappearance_mask
                if use_social_disappearance_in_calculations and is_fight
                else np.zeros(len(window_arr), dtype=bool)
            )
            post_wake_3600 = compute_post_wake_3600_metrics(
                effective_xy=xy,
                raw_xy=raw_observed_xy,
                original_xy=observed_xy,
                start_offset=int(fixed_anchor_offset),
                analysis_start_global_frame=start,
                step_distances=step_distances,
                accepted_steps=accepted_steps,
                rejected_jump_steps=jump_qc["rejected_step_mask"],
                primary_roi=primary_roi,
                secondary_roi=secondary_roi,
                wall_buffer_px=wall_buffer_px,
                fungus_buffer_px=fungus_buffer_px,
                is_fight=is_fight,
                anchor_rule=fixed_anchor_rule,
                social=social,
                social_all_xy=jump_filtered_arr,
                social_all_missing_mask=raw_missing_mask,
                focal_social_disappearance_mask=focal_disappearance_mask,
                social_distance_threshold_px=social_distance_threshold_px,
                imputed_mask=focal_imputed_mask,
                turtling_result=turtling_result,
            )
        warning = " ".join(warnings)

        output.append(
            {
                "script_version": SCRIPT_VERSION,
                "analysis_start_frame": start,
                "analysis_timespan_frames": window,
                "analysis_end_frame_inclusive": end_inclusive,
                "analysis_frame_observations_inclusive": window + 1,
                "movement_threshold_px": threshold,
                "idtracker_animal_id": individual,
                "starting_side": starting_sides[individual],
                "threshold_crossing_global_frame": crossing,
                "latency_to_threshold_frames": latency,
                "total_distance_px_in_analysis_window": total_distance,
                "one_frame_jump_threshold_px": (
                    one_frame_jump_threshold_px
                ),
                "one_frame_jumps_excluded": one_frame_jumps_excluded,
                "jump_threshold_px": one_frame_jump_threshold_px,
                "jump_artifact_coordinate_frames_excluded": (
                    jump_artifact_frames
                ),
                "jump_qc_status": jump_qc["status"],
                **post_wake,
                **post_wake_3600,
                "wall_buffer_px": wall_buffer_px,
                "frames_inside_wall_buffer": frames_in_wall,
                "frames_outside_wall_buffer": frames_outside_wall,
                "distance_px_inside_wall_buffer": distance_in_wall,
                "distance_px_outside_wall_buffer": distance_outside_wall,
                "spatial_partition_status": spatial_status,
                "fungus_buffer_px": fungus_buffer_px if is_fight else "",
                "frames_on_fungus": frames_on_fungus,
                "frames_in_fungus_edge_buffer": frames_in_fungus_buffer,
                "frames_in_fungus_interior": frames_in_fungus_interior,
                "distance_px_on_fungus": distance_on_fungus,
                "distance_px_in_fungus_edge_buffer": distance_in_fungus_buffer,
                "distance_px_in_fungus_interior": distance_in_fungus_interior,
                "fungus_partition_status": fungus_status,
                "social_distance_threshold_px": social_threshold,
                "frames_within_social_distance": social_frames,
                "distance_moved_px_while_within_social_distance": (
                    social_distance_moved
                ),
                "social_disappearance_frames": social_disappearance_frames,
                "social_return_interaction_events": social_return_events,
                "social_analysis_status": social_status,
                "use_social_disappearance_in_calculations": (
                    (
                        "YES"
                        if use_social_disappearance_in_calculations
                        else "NO"
                    )
                    if is_fight
                    else "NOT_APPLICABLE_NOT_FIGHT"
                ),
                "social_disappearance_imputed_frames": (
                    imputed_frame_count if is_fight else ""
                ),
                "remaining_missing_coordinate_frames_after_social_substitution": (
                    remaining_missing_after_social_substitution
                ),
                "coordinate_frames_used_in_distance_and_location_calculations": (
                    int(valid.sum())
                ),
                "turtling_candidate_frames": turtling_candidate_frames,
                "turtling_candidate_proportion_of_detected_frames": (
                    turtling_candidate_proportion
                ),
                "turtling_candidate_events": turtling_candidate_events,
                "turtling_detector_status": turtling_result["status"],
                "turtling_window_frames": turtling_window_frames,
                "turtling_min_path_px": turtling_min_path_px,
                "turtling_max_radius90_px": turtling_max_radius90_px,
                "turtling_min_turn_rotations": turtling_min_turn_rotations,
                "turtling_max_straightness": turtling_max_straightness,
                "turtling_max_step_px": turtling_max_step_px,
                "baseline_x_px": baseline_x,
                "baseline_y_px": baseline_y,
                "valid_coordinate_frames_in_window": int(
                    raw_valid.sum()
                ),
                "missing_coordinate_frames_in_window": int(
                    (~raw_valid).sum()
                ),
                "result_status": status,
                "warning": warning,
                "trajectory_source_kind": trajectory_source_kind,
                "session_folder": str(session_folder),
                "trajectory_file": str(trajectory_file),
                "archived_original_start_frame": (
                    start
                    if analysis_start_original_global_frame is None
                    else analysis_start_original_global_frame
                ),
                "start_frame_decision_source": analysis_start_source,
                "start_frame_decision_provenance": (
                    analysis_start_adjustment_provenance
                ),
            }
        )
    return output


def write_plot_pdf(
    destination: Path,
    trajectory_file: Path,
    session_folder: Path,
    rows: list[dict],
    analysis_type: str,
    video: str,
    cell_label: str,
    qc_record_id: str,
) -> None:
    """Write audit plots without interpolation, seconds, or derived smoothing."""
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        from matplotlib.backends.backend_pdf import PdfPages
        from matplotlib.patches import Patch
    except ImportError as exc:
        raise RuntimeError(
            "Matplotlib is required for PDF plots. Run the installer once to "
            "add it to idtracker_reprocess_v1."
        ) from exc

    arr = load_trajectories(trajectory_file)
    start = int(rows[0]["analysis_start_frame"])
    end = int(rows[0]["analysis_end_frame_inclusive"])
    raw_window_arr = arr[start : end + 1]
    one_frame_jump_threshold_px = float(
        rows[0].get(
            "one_frame_jump_threshold_px",
            rows[0]["jump_threshold_px"],
        )
    )
    plot_jump_qc = [
        filter_jump_artifact_coordinates(
            raw_window_arr[:, animal, :],
            threshold_px=one_frame_jump_threshold_px,
        )
        for animal in range(raw_window_arr.shape[1])
    ]
    window_arr = np.stack(
        [result["cleaned_xy"] for result in plot_jump_qc],
        axis=1,
    )
    global_frames = np.arange(start, end + 1)
    is_fight = "fight" in analysis_type.strip().lower()
    social = (
        compute_social_candidates(
            window_arr,
            social_distance_threshold_px=float(
                rows[0]["social_distance_threshold_px"]
            ),
            eligible_missing_mask=(
                ~np.isfinite(raw_window_arr).all(axis=2)
            ),
        )
        if is_fight
        else None
    )
    use_social_imputation = (
        str(rows[0].get("use_social_disappearance_in_calculations", "NO"))
        == "YES"
    )
    try:
        rois = load_rois(session_folder)
    except Exception:
        rois = []
    fungus_roi = rois[1] if is_fight and len(rois) > 1 else None
    turtling_by_animal = [
        exclude_turtling_candidates_on_fungus(
            compute_turtling_candidates(
                window_arr[:, animal, :],
                window_frames=int(rows[animal]["turtling_window_frames"]),
                min_path_px=float(rows[animal]["turtling_min_path_px"]),
                max_radius90_px=float(
                    rows[animal]["turtling_max_radius90_px"]
                ),
                min_turn_rotations=float(
                    rows[animal]["turtling_min_turn_rotations"]
                ),
                max_straightness=float(
                    rows[animal]["turtling_max_straightness"]
                ),
                max_step_px=float(rows[animal]["turtling_max_step_px"]),
            ),
            window_arr[:, animal, :],
            fungus_roi,
        )
        for animal in range(window_arr.shape[1])
    ]
    colors = ["#0072B2", "#D55E00", "#009E73", "#CC79A7"]
    video_name = Path(video).name
    page_video = f"Video: {video_name}"
    page_context = (
        f"Cell: {cell_label}    |    "
        f"Trajectory: {rows[0]['trajectory_source_kind']}    |    "
        f"Script: v{rows[0]['script_version']}"
    )
    if qc_record_id:
        page_context += f"    |    QC record: {qc_record_id}"
    identity_lines = (
        textwrap.wrap(
            page_video,
            width=92,
            break_long_words=True,
            break_on_hyphens=False,
        )
        + textwrap.wrap(
            page_context,
            width=104,
            break_long_words=True,
            break_on_hyphens=False,
        )
    )
    identity_top = 0.992
    identity_spacing = 0.018
    identity_bottom = (
        identity_top - identity_spacing * (len(identity_lines) - 1)
    )
    plot_content_top = min(0.93, identity_bottom - 0.018)

    def add_page_identity(fig):
        for line_number, line in enumerate(identity_lines):
            fig.text(
                0.5,
                identity_top - identity_spacing * line_number,
                line,
                ha="center",
                va="top",
                fontsize=9,
                fontweight="bold",
            )

    finite_sets = [
        xy[np.isfinite(xy).all(axis=1)] for xy in window_arr.transpose(1, 0, 2)
    ]
    finite_sets = [xy for xy in finite_sets if len(xy)]
    if rois:
        all_geometry = np.vstack(rois + finite_sets)
    elif finite_sets:
        all_geometry = np.vstack(finite_sets)
    else:
        all_geometry = np.asarray([[0.0, 0.0], [1.0, 1.0]])
    xy_min = np.nanmin(all_geometry, axis=0)
    xy_max = np.nanmax(all_geometry, axis=0)
    span = np.maximum(xy_max - xy_min, 1.0)
    pad = 0.05 * float(max(span))
    x_limits = (float(xy_min[0] - pad), float(xy_max[0] + pad))
    y_limits = (float(xy_max[1] + pad), float(xy_min[1] - pad))

    def draw_rois_2d(ax):
        for index, polygon in enumerate(rois[:2]):
            closed = np.vstack([polygon, polygon[0]])
            if index == 0:
                ax.plot(
                    closed[:, 0], closed[:, 1], color="#009E73",
                    linewidth=1.5, label="primary ROI",
                )
            else:
                ax.plot(
                    closed[:, 0], closed[:, 1], color="#CC79A7",
                    linewidth=1.5, linestyle="--", label="fungus ROI",
                )

    def style_2d(ax, title):
        ax.set_title(title)
        ax.set_xlabel("global x position (pixels)")
        ax.set_ylabel("global y position (pixels)")
        ax.set_xlim(*x_limits)
        ax.set_ylim(*y_limits)
        ax.set_aspect("equal", adjustable="box")
        ax.grid(True, alpha=0.18)
        handles, labels = ax.get_legend_handles_labels()
        unique = {}
        for handle, label in zip(handles, labels):
            unique.setdefault(label, handle)
        if unique:
            ax.legend(
                unique.values(), unique.keys(), frameon=False, fontsize=8,
                loc="upper center", bbox_to_anchor=(0.5, -0.12), ncol=2,
            )

    def draw_filtered_path_2d(ax, xy, **plot_kwargs):
        label = plot_kwargs.pop("label", None)
        segments = continuous_path_segments(
            xy, one_frame_jump_threshold_px
        )
        for segment_index, (_offsets, segment_xy) in enumerate(segments):
            ax.plot(
                segment_xy[:, 0],
                segment_xy[:, 1],
                label=label if segment_index == 0 else None,
                **plot_kwargs,
            )
        if not segments and label:
            ax.plot([], [], label=label, **plot_kwargs)

    def draw_jump_endpoints_2d(ax, xy, label):
        xy = np.asarray(xy, dtype=float)
        jump_qc = filter_jump_artifact_coordinates(
            xy, threshold_px=one_frame_jump_threshold_px
        )
        endpoints = np.flatnonzero(
            jump_qc["rejected_step_mask"]
        ) + 1
        if not endpoints.size:
            return
        ax.scatter(
            xy[endpoints, 0],
            xy[endpoints, 1],
            s=8,
            marker="x",
            color="#666666",
            linewidth=0.45,
            alpha=0.30,
            label=label,
            zorder=4,
        )

    def draw_turtling_overlay_2d(ax, animal, xy):
        candidate = xy.copy()
        candidate[~turtling_by_animal[animal]["mask"]] = np.nan
        ax.plot(
            candidate[:, 0],
            candidate[:, 1],
            color="#8B0000",
            linewidth=1.4,
            linestyle="--",
            alpha=0.78,
            label=f"animal {animal} potential turtling",
            zorder=7,
        )

    destination.parent.mkdir(parents=True, exist_ok=True)
    with PdfPages(destination) as pdf:
        fig, ax = plt.subplots(figsize=(8.5, 8.5))
        add_page_identity(fig)
        draw_rois_2d(ax)
        for animal, xy in enumerate(window_arr.transpose(1, 0, 2)):
            finite = np.isfinite(xy).all(axis=1)
            label = (
                f"IDtracker animal {animal} "
                f"({rows[animal]['starting_side']})"
            )
            draw_filtered_path_2d(
                ax,
                xy,
                color=colors[animal % len(colors)], linewidth=0.65,
                alpha=0.8, label=label,
            )
            draw_jump_endpoints_2d(
                ax,
                raw_window_arr[:, animal, :],
                label=(
                    f"animal {animal} destination after rejected "
                    f">{one_frame_jump_threshold_px:g} px step"
                ),
            )
            draw_turtling_overlay_2d(ax, animal, xy)
            if finite[0]:
                ax.scatter(
                    xy[0, 0], xy[0, 1], s=55, marker="o",
                    color=colors[animal % len(colors)], edgecolor="black",
                    linewidth=0.4, zorder=5, label=f"animal {animal} start",
                )
            crossing = rows[animal]["threshold_crossing_global_frame"]
            if crossing != "":
                offset = int(crossing) - start
                if 0 <= offset < len(xy) and finite[offset]:
                    ax.scatter(
                        xy[offset, 0], xy[offset, 1], s=95, marker="*",
                        color=colors[animal % len(colors)], edgecolor="black",
                        linewidth=0.4, zorder=6,
                        label=f"animal {animal} threshold crossing",
                    )
        style_2d(ax, "Both tracks within the inclusive analysis window")
        fig.tight_layout(rect=[0, 0.08, 1, plot_content_top])
        pdf.savefig(fig)
        plt.close(fig)

        for animal, xy in enumerate(window_arr.transpose(1, 0, 2)):
            fig, ax = plt.subplots(figsize=(8.5, 11))
            add_page_identity(fig)
            draw_rois_2d(ax)
            finite = np.isfinite(xy).all(axis=1)
            draw_filtered_path_2d(
                ax,
                xy,
                color=colors[animal % len(colors)], linewidth=0.7,
                alpha=0.85, label=f"IDtracker animal {animal} track",
            )
            draw_jump_endpoints_2d(
                ax,
                raw_window_arr[:, animal, :],
                label=(
                    f"destination after rejected "
                    f">{one_frame_jump_threshold_px:g} px step"
                ),
            )
            draw_turtling_overlay_2d(ax, animal, xy)
            if finite[0]:
                ax.scatter(
                    xy[0, 0], xy[0, 1], s=60, marker="o",
                    color=colors[animal % len(colors)], edgecolor="black",
                    linewidth=0.4, zorder=5, label="analysis start",
                )
            crossing = rows[animal]["threshold_crossing_global_frame"]
            if crossing != "":
                offset = int(crossing) - start
                if 0 <= offset < len(xy) and finite[offset]:
                    ax.scatter(
                        xy[offset, 0], xy[offset, 1], s=100, marker="*",
                        color=colors[animal % len(colors)], edgecolor="black",
                        linewidth=0.4, zorder=6, label="threshold crossing",
                    )
            style_2d(
                ax,
                f"IDtracker animal {animal}: {rows[animal]['starting_side']}",
            )
            fig.tight_layout(rect=[0, 0.08, 1, plot_content_top])
            pdf.savefig(fig)
            plt.close(fig)

        count = window_arr.shape[1]
        columns = min(count, 2)
        rows_of_plots = int(math.ceil(count / columns))
        fig = plt.figure(figsize=(11, 8.5))
        add_page_identity(fig)
        for animal, xy in enumerate(window_arr.transpose(1, 0, 2), 1):
            ax = fig.add_subplot(
                rows_of_plots, columns, animal, projection="3d"
            )
            finite = np.isfinite(xy).all(axis=1)
            for offsets, segment_xy in continuous_path_segments(
                xy, one_frame_jump_threshold_px
            ):
                ax.plot(
                    segment_xy[:, 0],
                    segment_xy[:, 1],
                    global_frames[offsets],
                    color=colors[(animal - 1) % len(colors)],
                    linewidth=0.7,
                    alpha=0.85,
                )
            candidate_mask = turtling_by_animal[animal - 1]["mask"]
            candidate = xy.copy()
            candidate[~candidate_mask] = np.nan
            ax.plot(
                candidate[:, 0],
                candidate[:, 1],
                global_frames,
                color="#8B0000",
                linewidth=1.4,
                linestyle="--",
                alpha=0.78,
            )
            for roi_index, polygon in enumerate(rois[:2]):
                closed = np.vstack([polygon, polygon[0]])
                ax.plot(
                    closed[:, 0], closed[:, 1],
                    np.full(len(closed), start),
                    color="#009E73" if roi_index == 0 else "#CC79A7",
                    linestyle="-" if roi_index == 0 else "--",
                    linewidth=1.2,
                )
            if finite[0]:
                ax.scatter(
                    xy[0, 0], xy[0, 1], start,
                    s=32, marker="o",
                    color=colors[(animal - 1) % len(colors)],
                    edgecolor="black", linewidth=0.35,
                    depthshade=False,
                )
            crossing = rows[animal - 1]["threshold_crossing_global_frame"]
            if crossing != "":
                offset = int(crossing) - start
                if 0 <= offset < len(xy) and finite[offset]:
                    ax.scatter(
                        xy[offset, 0], xy[offset, 1], int(crossing),
                        s=52, marker="*",
                        color=colors[(animal - 1) % len(colors)],
                        edgecolor="black", linewidth=0.35,
                        depthshade=False,
                    )
            ax.set_title(
                f"IDtracker animal {animal - 1}: "
                f"{rows[animal - 1]['starting_side']}"
            )
            ax.set_xlabel("global x (px)", labelpad=5)
            ax.set_ylabel("global y (px)", labelpad=5)
            ax.set_zlabel("global frame", labelpad=5)
            ax.set_xlim(*x_limits)
            ax.set_ylim(*y_limits)
            ax.set_zlim(start, end)
            ax.view_init(elev=24, azim=-58)
            try:
                ax.set_proj_type("ortho")
                ax.set_box_aspect((1.0, 1.0, 1.25))
            except (AttributeError, TypeError):
                pass
            ax.grid(True, alpha=0.2)
            ax.tick_params(labelsize=7, pad=1)
        fig.suptitle(
            "3D tracks through global frames - one panel per IDtracker animal",
            fontsize=14, y=min(0.91, plot_content_top - 0.01),
        )
        fig.tight_layout(rect=[0.02, 0.03, 0.98, 0.86], w_pad=2.5)
        pdf.savefig(fig)
        plt.close(fig)

        if (
            social is not None
            and social["status"]
            == "CALCULATED_FIGHT_TWO_ANIMALS"
        ):
            fig, ax = plt.subplots(figsize=(8.5, 11))
            draw_rois_2d(ax)
            for animal, xy in enumerate(window_arr.transpose(1, 0, 2)):
                finite = np.isfinite(xy).all(axis=1)
                draw_filtered_path_2d(
                    ax,
                    xy,
                    color="#A0A0A0",
                    linewidth=0.6, alpha=0.55,
                    label=f"animal {animal} full track",
                )
                within = xy.copy()
                within[~(finite & social["within_mask"])] = np.nan
                draw_filtered_path_2d(
                    ax,
                    within,
                    color="#E60049",
                    linewidth=2.6, alpha=0.95,
                    label="both visible and within social distance",
                )
                disappearance = xy.copy()
                disappearance[
                    ~(finite & social["disappearance_mask"])
                ] = np.nan
                draw_filtered_path_2d(
                    ax,
                    disappearance,
                    color="#7A1FA2", linewidth=2.8, alpha=0.95,
                    label="visible animal while partner disappears",
                )
                if use_social_imputation:
                    impute_mask = social[
                        "disappearance_masks_by_animal"
                    ][:, animal]
                    if impute_mask.any():
                        copied_xy = window_arr[
                            impute_mask, 1 - animal, :
                        ]
                        ax.scatter(
                            copied_xy[:, 0], copied_xy[:, 1],
                            s=22, marker="x", color="#000000",
                            linewidth=0.9, zorder=8,
                            label="copied partner location used in calculations",
                        )
            style_2d(
                ax,
                "Social-distance and disappearance locations "
                "(screening measures, not confirmed fighting)",
            )
            annotation = (
                f"Both visible <= "
                f"{rows[0]['social_distance_threshold_px']} px: "
                f"{rows[0]['frames_within_social_distance']} frames\n"
                + "Distance moved while within range: "
                + "; ".join(
                    f"animal {row['idtracker_animal_id']}="
                    f"{float(row['distance_moved_px_while_within_social_distance']):.3f} px"
                    for row in rows
                )
                + "\nSocial disappearance frames: "
                + "; ".join(
                    f"animal {row['idtracker_animal_id']}="
                    f"{row['social_disappearance_frames']}"
                    for row in rows
                )
                + f"\nTogether-separate-together return events: "
                f"{rows[0]['social_return_interaction_events']}"
                + "\nSocial disappearance calculation switch: "
                + ("ON" if use_social_imputation else "OFF")
                + "; imputed frames: "
                + "; ".join(
                    f"animal {row['idtracker_animal_id']}="
                    f"{row['social_disappearance_imputed_frames']}"
                    for row in rows
                )
            )
            fig.text(
                0.08, 0.04, annotation, ha="left", va="bottom",
                fontsize=8.5,
            )
            fig.tight_layout(
                rect=[0, 0.18, 1, min(0.91, plot_content_top)]
            )
            add_page_identity(fig)
            pdf.savefig(fig)
            plt.close(fig)

        if rois:
            fig, ax = plt.subplots(figsize=(8.5, 8.5))
            add_page_identity(fig)
            grid_size = 240
            xs = np.linspace(x_limits[0], x_limits[1], grid_size)
            ys = np.linspace(y_limits[1], y_limits[0], grid_size)
            grid_x, grid_y = np.meshgrid(xs, ys)
            grid_points = np.column_stack((grid_x.ravel(), grid_y.ravel()))

            primary_inside = points_inside_polygon(grid_points, rois[0])
            primary_edge_distance = distance_to_polygon_boundary(
                grid_points, rois[0]
            )
            wall_zone = (
                primary_inside
                & (primary_edge_distance <= float(rows[0]["wall_buffer_px"]))
            ).reshape(grid_x.shape)
            wall_rgba = np.zeros((*wall_zone.shape, 4))
            wall_rgba[wall_zone] = (0.0, 0.45, 0.70, 0.30)
            ax.imshow(
                wall_rgba,
                extent=(xs[0], xs[-1], ys[-1], ys[0]),
                origin="upper", interpolation="nearest", aspect="auto",
            )
            legend_patches = [
                Patch(
                    facecolor=(0.0, 0.45, 0.70, 0.30),
                    edgecolor="#0072B2",
                    label=(
                        f"primary wall buffer "
                        f"({rows[0]['wall_buffer_px']} px inward)"
                    ),
                )
            ]

            if is_fight and len(rois) > 1:
                fungus_inside = points_inside_polygon(grid_points, rois[1])
                fungus_edge_distance = distance_to_polygon_boundary(
                    grid_points, rois[1]
                )
                fungus_zone = (
                    fungus_inside
                    & (
                        fungus_edge_distance
                        <= float(rows[0]["fungus_buffer_px"])
                    )
                ).reshape(grid_x.shape)
                fungus_rgba = np.zeros((*fungus_zone.shape, 4))
                fungus_rgba[fungus_zone] = (0.80, 0.25, 0.55, 0.38)
                ax.imshow(
                    fungus_rgba,
                    extent=(xs[0], xs[-1], ys[-1], ys[0]),
                    origin="upper", interpolation="nearest", aspect="auto",
                )
                legend_patches.append(
                    Patch(
                        facecolor=(0.80, 0.25, 0.55, 0.38),
                        edgecolor="#CC79A7",
                        label=(
                            f"fungus edge buffer "
                            f"({rows[0]['fungus_buffer_px']} px inward)"
                        ),
                    )
                )
            draw_rois_2d(ax)
            for animal, xy in enumerate(window_arr.transpose(1, 0, 2)):
                finite = np.isfinite(xy).all(axis=1)
                draw_filtered_path_2d(
                    ax,
                    xy,
                    color=colors[animal % len(colors)],
                    linewidth=0.45, alpha=0.28,
                )
            ax.set_title(
                "Translucent ROI-buffer audit map "
                "(colored pixels are a display raster)"
            )
            ax.set_xlabel("global x position (pixels)")
            ax.set_ylabel("global y position (pixels)")
            ax.set_xlim(*x_limits)
            ax.set_ylim(*y_limits)
            ax.set_aspect("equal", adjustable="box")
            ax.grid(True, alpha=0.15)
            ax.legend(
                handles=legend_patches, frameon=False, fontsize=8,
                loc="upper center", bbox_to_anchor=(0.5, -0.10), ncol=2,
            )
            fig.text(
                0.5, 0.045,
                "Display raster only. CSV classifications use exact "
                "point-to-segment distances, not the raster.",
                ha="center", va="bottom", fontsize=8,
            )
            fig.tight_layout(rect=[0, 0.09, 1, plot_content_top])
            pdf.savefig(fig)
            plt.close(fig)

        # Metadata is deliberately the final page for fast visual review.
        fig = plt.figure(figsize=(8.5, 11))
        add_page_identity(fig)
        metadata_title_y = min(0.925, plot_content_top - 0.005)
        fig.suptitle(
            "IDtracker analysis-window metadata",
            fontsize=16,
            y=metadata_title_y,
        )
        summary_lines = [
            f"Post-processing script version: {rows[0]['script_version']}",
            f"Video: {video_name}",
            f"Cell: {cell_label}",
            f"QC record: {qc_record_id or 'not supplied'}",
            f"Canonical session: {session_folder.name}",
            f"Analysis: {analysis_type or 'unspecified'}",
            f"Inclusive global frames: {start} through {end}",
            (
                "Archived original start: "
                f"{rows[0]['archived_original_start_frame']}"
            ),
            (
                "Start decision source: "
                f"{rows[0]['start_frame_decision_source']}"
            ),
            (
                "Start decision provenance: "
                f"{rows[0]['start_frame_decision_provenance'] or 'no adjustment'}"
            ),
            f"End minus start: {end - start} frames",
            f"Coordinate observations in a complete window: {end - start + 1}",
            f"Displacement threshold: {rows[0]['movement_threshold_px']} pixels",
            (
                "One-frame movement-step threshold: reject adjacent steps > "
                f"{one_frame_jump_threshold_px:g} pixels"
            ),
            (
                "One-frame movement steps excluded by animal: "
                + "; ".join(
                    f"{row['idtracker_animal_id']}="
                    f"{row['one_frame_jumps_excluded']}"
                    for row in rows
                )
            ),
            (
                "Jump endpoint coordinates retained for frame-based ROI counts; "
                "PDF paths break at rejected steps."
            ),
            (
                "Jump QC status by animal: "
                + "; ".join(
                    f"{row['idtracker_animal_id']}={row['jump_qc_status']}"
                    for row in rows
                )
            ),
            f"Trajectory source: {rows[0]['trajectory_source_kind']}",
            f"Primary wall buffer: {rows[0]['wall_buffer_px']} pixels inward",
            (
                "Turtling candidate rule: "
                f"{rows[0]['turtling_window_frames']}-frame window; "
                f"path >= {rows[0]['turtling_min_path_px']} px; "
                f"radius90 <= {rows[0]['turtling_max_radius90_px']} px"
            ),
            (
                "  absolute turns >= "
                f"{rows[0]['turtling_min_turn_rotations']} rotations; "
                f"net/path <= {rows[0]['turtling_max_straightness']}; "
                f"max step <= {rows[0]['turtling_max_step_px']} px"
            ),
            (
                "Turtling candidate frames/proportion/events by animal: "
                + "; ".join(
                    f"{row['idtracker_animal_id']}="
                    f"{row['turtling_candidate_frames']}/"
                    f"{float(row['turtling_candidate_proportion_of_detected_frames']):.6f}/"
                    f"{row['turtling_candidate_events']}"
                    for row in rows
                )
            ),
        ]
        if is_fight:
            summary_lines.extend(
                [
                    f"Fungus edge buffer: {rows[0]['fungus_buffer_px']} pixels inward",
                    (
                        "Turtling rule for fights: candidate frames on or "
                        "inside the fungus ROI are excluded from CSV counts, "
                        "proportions, events, and PDF overlays."
                    ),
                    (
                        "Social distance threshold: <= "
                        f"{rows[0]['social_distance_threshold_px']} pixels"
                    ),
                    (
                        "Frames within social distance: "
                        f"{rows[0]['frames_within_social_distance']}"
                    ),
                    (
                        "Together-separate-together return events: "
                        f"{rows[0]['social_return_interaction_events']}"
                    ),
                    (
                        "Use social disappearance in distance/location "
                        "calculations: "
                        f"{rows[0]['use_social_disappearance_in_calculations']}"
                    ),
                    (
                        "Imputed frames by animal: "
                        + "; ".join(
                            f"{row['idtracker_animal_id']}="
                            f"{row['social_disappearance_imputed_frames']}"
                            for row in rows
                        )
                    ),
                ]
            )
        summary_lines.extend(
            [
                "",
                "Identity rows:",
                *[
                    (
                        f"  IDtracker animal {row['idtracker_animal_id']}: "
                        f"starting side={row['starting_side']}; "
                        f"threshold frame={row['threshold_crossing_global_frame'] or 'not reached'}"
                    )
                    for row in rows
                ],
                "",
                "Post-wake opportunity summaries:",
                *[
                    (
                        f"  IDtracker animal {row['idtracker_animal_id']}: "
                        f"status={row['post_wake_analysis_status']}; "
                        f"valid steps="
                        f"{row['post_wake_valid_movement_steps'] if row['post_wake_valid_movement_steps'] != '' else 'NA'}; "
                        f"distance="
                        f"{row['post_wake_total_distance_px'] if row['post_wake_total_distance_px'] != '' else 'NA'} px; "
                        f"distance/valid step="
                        f"{row['post_wake_distance_px_per_valid_step'] if row['post_wake_distance_px_per_valid_step'] != '' else 'NA'}"
                    )
                    for row in rows
                ],
                "",
                "Social-distance measures are screening summaries, not confirmed fights.",
                "Dark-red paths are provisional turtling candidates, not posture proof.",
                "No general interpolation is performed by this prototype.",
                (
                    "Optional social-disappearance partner-centroid substitution: "
                    f"{'ENABLED' if use_social_imputation else 'DISABLED'}."
                ),
                (
                    "Track lines break at original missing coordinates and "
                    f"adjacent steps >{one_frame_jump_threshold_px:g} pixels; "
                    "endpoint coordinates remain available for frame counts."
                ),
                "All axes use pixels or global frames; no seconds are used.",
            ]
        )
        wrapped_summary_lines = []
        for line in summary_lines:
            wrapped_summary_lines.extend(
                textwrap.wrap(
                    line,
                    width=88,
                    subsequent_indent="  ",
                    break_long_words=True,
                    break_on_hyphens=False,
                )
                or [""]
            )
        fig.text(
            0.06,
            min(0.86, metadata_title_y - 0.055),
            "\n".join(wrapped_summary_lines),
            va="top", ha="left", fontsize=8.5, family="monospace",
        )
        pdf.savefig(fig)
        plt.close(fig)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--trajectory", required=True)
    parser.add_argument("--session", required=True)
    parser.add_argument("--start", required=True, type=int)
    parser.add_argument("--window", default=7200, type=int)
    parser.add_argument("--threshold", default=30.0, type=float)
    parser.add_argument("--wall-buffer-px", default=30.0, type=float)
    parser.add_argument("--fungus-buffer-px", default=30.0, type=float)
    parser.add_argument(
        "--social-distance-threshold-px", default=60.0, type=float
    )
    parser.add_argument(
        "--one-frame-jump-threshold-px", default=200.0, type=float
    )
    parser.add_argument(
        "--use-social-disappearance-in-calculations",
        action="store_true",
        help=(
            "Copy the visible partner centroid into qualifying social-"
            "disappearance frames for distance and wall/fungus calculations."
        ),
    )
    parser.add_argument("--turtling-window-frames", default=120, type=int)
    parser.add_argument("--turtling-min-path-px", default=120.0, type=float)
    parser.add_argument(
        "--turtling-max-radius90-px", default=35.0, type=float
    )
    parser.add_argument(
        "--turtling-min-turn-rotations", default=3.0, type=float
    )
    parser.add_argument(
        "--turtling-max-straightness", default=0.25, type=float
    )
    parser.add_argument("--turtling-max-step-px", default=20.0, type=float)
    parser.add_argument("--analysis-type", default="")
    parser.add_argument("--analysis-start-original-global-frame", type=int)
    parser.add_argument(
        "--analysis-start-source", default="SOURCE_INTERVAL"
    )
    parser.add_argument(
        "--analysis-start-adjustment-provenance", default=""
    )
    parser.add_argument("--video", default="")
    parser.add_argument("--cell-label", default="")
    parser.add_argument("--qc-record-id", default="")
    parser.add_argument("--output", required=True)
    parser.add_argument("--plot-output")
    parser.add_argument(
        "--overwrite",
        action="store_true",
        help="Atomically replace a previous complete output at --output.",
    )
    args = parser.parse_args()

    rows = analyze(
        trajectory_file=Path(args.trajectory),
        session_folder=Path(args.session),
        start=args.start,
        window=args.window,
        threshold=args.threshold,
        wall_buffer_px=args.wall_buffer_px,
        fungus_buffer_px=args.fungus_buffer_px,
        analysis_type=args.analysis_type,
        social_distance_threshold_px=args.social_distance_threshold_px,
        use_social_disappearance_in_calculations=(
            args.use_social_disappearance_in_calculations
        ),
        one_frame_jump_threshold_px=args.one_frame_jump_threshold_px,
        turtling_window_frames=args.turtling_window_frames,
        turtling_min_path_px=args.turtling_min_path_px,
        turtling_max_radius90_px=args.turtling_max_radius90_px,
        turtling_min_turn_rotations=args.turtling_min_turn_rotations,
        turtling_max_straightness=args.turtling_max_straightness,
        turtling_max_step_px=args.turtling_max_step_px,
        analysis_start_original_global_frame=(
            args.analysis_start_original_global_frame
        ),
        analysis_start_source=args.analysis_start_source,
        analysis_start_adjustment_provenance=(
            args.analysis_start_adjustment_provenance
        ),
    )
    destination = Path(args.output)
    destination.parent.mkdir(parents=True, exist_ok=True)
    if destination.exists() and not args.overwrite:
        raise FileExistsError(f"Refusing to overwrite existing output: {destination}")
    temporary = destination.with_name(
        destination.name + f".partial.{os.getpid()}"
    )
    plot_destination = Path(args.plot_output) if args.plot_output else None
    if plot_destination and (not args.video.strip() or not args.cell_label.strip()):
        raise ValueError(
            "PDF creation requires both --video and --cell-label; an "
            "unidentified plot is not allowed."
        )
    plot_temporary = (
        plot_destination.with_name(
            plot_destination.name + f".partial.{os.getpid()}"
        )
        if plot_destination
        else None
    )
    try:
        with temporary.open("x", newline="", encoding="utf-8") as stream:
            writer = csv.DictWriter(stream, fieldnames=OUTPUT_COLUMNS)
            writer.writeheader()
            writer.writerows(rows)
            stream.flush()
            os.fsync(stream.fileno())
        if plot_destination:
            plot_destination.parent.mkdir(parents=True, exist_ok=True)
            if plot_destination.exists() and not args.overwrite:
                raise FileExistsError(
                    f"Refusing to overwrite existing plot: {plot_destination}"
                )
            write_plot_pdf(
                plot_temporary,
                Path(args.trajectory),
                Path(args.session),
                rows,
                args.analysis_type,
                args.video,
                args.cell_label,
                args.qc_record_id,
            )
            with plot_temporary.open("rb") as stream:
                os.fsync(stream.fileno())
        temporary.replace(destination)
        if plot_destination:
            plot_temporary.replace(plot_destination)
    except Exception:
        if temporary.exists():
            temporary.unlink()
        if plot_temporary and plot_temporary.exists():
            plot_temporary.unlink()
        raise
    print(
        json.dumps(
            {
                "status": "OK",
                "output": str(destination),
                "plot_output": str(plot_destination) if plot_destination else "",
                "rows": len(rows),
            }
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
