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
from pathlib import Path

import numpy as np


SCRIPT_VERSION = "0.4.0"

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
    "analysis_start_global_frame",
    "analysis_timespan_frames",
    "analysis_end_global_frame_inclusive",
    "analysis_frame_observations_inclusive",
    "movement_threshold_px",
    "idtracker_animal_id",
    "starting_side",
    "threshold_crossing_global_frame",
    "latency_to_threshold_frames",
    "total_distance_px_in_analysis_window",
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
        run_mask = (~valid[:, missing_animal]) & valid[:, 1 - missing_animal]
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
    turtling_window_frames: int = 120,
    turtling_min_path_px: float = 120.0,
    turtling_max_radius90_px: float = 35.0,
    turtling_min_turn_rotations: float = 3.0,
    turtling_max_straightness: float = 0.25,
    turtling_max_step_px: float = 20.0,
) -> list[dict]:
    if start <= 0:
        raise ValueError("Analysis start must be greater than zero; zero is a data-entry flag")
    if window <= 0 or threshold <= 0:
        raise ValueError("Window frames and wake threshold must be positive")
    if wall_buffer_px < 0 or fungus_buffer_px < 0:
        raise ValueError("ROI-buffer widths cannot be negative")
    if social_distance_threshold_px <= 0:
        raise ValueError("The social-distance threshold must be positive")
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
    social = (
        compute_social_candidates(
            window_arr,
            social_distance_threshold_px=social_distance_threshold_px,
        )
        if is_fight
        else None
    )
    calculation_arr = window_arr.copy()
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
                window_arr[impute_mask, 1 - missing_animal, :]
            )
            imputed_frames_by_animal[missing_animal] = int(
                impute_mask.sum()
            )
    turtling_by_animal = [
        exclude_turtling_candidates_on_fungus(
            compute_turtling_candidates(
                window_arr[:, animal, :],
                window_frames=turtling_window_frames,
                min_path_px=turtling_min_path_px,
                max_radius90_px=turtling_max_radius90_px,
                min_turn_rotations=turtling_min_turn_rotations,
                max_straightness=turtling_max_straightness,
                max_step_px=turtling_max_step_px,
            ),
            window_arr[:, animal, :],
            secondary_roi,
        )
        for animal in range(window_arr.shape[1])
    ]
    starting_sides = ["NOT_APPLICABLE_NOT_FIGHT"] * window_arr.shape[1]
    if is_fight:
        starting_sides = ["UNASSIGNED_EXPECTED_TWO_ANIMALS"] * window_arr.shape[1]
        if window_arr.shape[1] == 2:
            start_xy = window_arr[0]
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
    output = []
    for individual in range(window_arr.shape[1]):
        observed_xy = window_arr[:, individual, :]
        original_valid = np.isfinite(observed_xy).all(axis=1)
        xy = calculation_arr[:, individual, :]
        valid = np.isfinite(xy).all(axis=1)
        warning = ""
        crossing = ""
        latency = ""
        baseline_x = ""
        baseline_y = ""
        status = "OK"
        warnings = []
        if trajectory_source_kind.startswith("IDTRACKER_RAW_"):
            warnings.append(
                "RAW_IDTRACKER_INPUT: no validated/without-gaps trajectory "
                "was available. Original missing counts are preserved; "
                "remaining invalid distance steps are excluded without gap bridging."
            )

        if not original_valid[0]:
            status = "NOT_CALCULATED"
            warnings.append(
                "The coordinate at the exact analysis-entry frame is missing; "
                "no later frame was substituted and no latency was calculated."
            )
        else:
            baseline = observed_xy[0]
            baseline_x, baseline_y = float(baseline[0]), float(baseline[1])
            displacement = np.full(len(observed_xy), np.nan)
            displacement[original_valid] = np.sqrt(
                np.sum(
                    (observed_xy[original_valid] - baseline) ** 2,
                    axis=1,
                )
            )
            hits = np.flatnonzero(displacement >= threshold)
            if hits.size:
                latency = int(hits[0])
                crossing = start + latency
            else:
                status = "THRESHOLD_NOT_REACHED"
                warnings.append(
                    "Threshold was not reached within the requested window."
                )

        differences = xy[1:] - xy[:-1]
        step_distances = np.sqrt(np.sum(differences ** 2, axis=1))
        valid_steps = valid[:-1] & valid[1:]
        if valid_steps.any():
            total_distance = float(step_distances[valid_steps].sum())
        else:
            total_distance = ""
            warnings.append(
                "No adjacent frame pair had valid coordinates at both endpoints; "
                "total distance was not calculated."
            )
        excluded_steps = int((~valid_steps).sum())
        missing_coordinate_frames = int((~original_valid).sum())
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
            if valid_steps.any():
                midpoints = (xy[:-1] + xy[1:]) / 2.0
                midpoint_in_roi[valid_steps] = points_inside_polygon(
                    midpoints[valid_steps], primary_roi
                )
                midpoint_distance_to_wall[valid_steps] = (
                    distance_to_polygon_boundary(
                        midpoints[valid_steps], primary_roi
                    )
                )
            step_in_wall = (
                valid_steps
                & midpoint_in_roi
                & (midpoint_distance_to_wall <= wall_buffer_px)
            )
            step_outside_wall = (
                valid_steps
                & midpoint_in_roi
                & (midpoint_distance_to_wall > wall_buffer_px)
            )
            distance_in_wall = float(step_distances[step_in_wall].sum())
            distance_outside_wall = float(
                step_distances[step_outside_wall].sum()
            )

            frames_outside_roi = int((valid & ~inside_roi).sum())
            distance_outside_roi = float(
                step_distances[valid_steps & ~midpoint_in_roi].sum()
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
                if valid_steps.any():
                    midpoints = (xy[:-1] + xy[1:]) / 2.0
                    segment_on_fungus[valid_steps] = points_inside_polygon(
                        midpoints[valid_steps], secondary_roi
                    )
                    segment_distance_to_fungus_edge[valid_steps] = (
                        distance_to_polygon_boundary(
                            midpoints[valid_steps], secondary_roi
                        )
                    )
                segment_in_fungus_buffer = (
                    valid_steps
                    & segment_on_fungus
                    & (
                        segment_distance_to_fungus_edge
                        <= fungus_buffer_px
                    )
                )
                segment_in_fungus_interior = (
                    valid_steps
                    & segment_on_fungus
                    & (
                        segment_distance_to_fungus_edge
                        > fungus_buffer_px
                    )
                )
                distance_on_fungus = float(
                    step_distances[valid_steps & segment_on_fungus].sum()
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
                    valid_steps
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
        warning = " ".join(warnings)

        output.append(
            {
                "script_version": SCRIPT_VERSION,
                "analysis_start_global_frame": start,
                "analysis_timespan_frames": window,
                "analysis_end_global_frame_inclusive": end_inclusive,
                "analysis_frame_observations_inclusive": window + 1,
                "movement_threshold_px": threshold,
                "idtracker_animal_id": individual,
                "starting_side": starting_sides[individual],
                "threshold_crossing_global_frame": crossing,
                "latency_to_threshold_frames": latency,
                "total_distance_px_in_analysis_window": total_distance,
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
                    original_valid.sum()
                ),
                "missing_coordinate_frames_in_window": int(
                    (~original_valid).sum()
                ),
                "result_status": status,
                "warning": warning,
                "trajectory_source_kind": trajectory_source_kind,
                "session_folder": str(session_folder),
                "trajectory_file": str(trajectory_file),
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
    start = int(rows[0]["analysis_start_global_frame"])
    end = int(rows[0]["analysis_end_global_frame_inclusive"])
    window_arr = arr[start : end + 1]
    global_frames = np.arange(start, end + 1)
    is_fight = "fight" in analysis_type.strip().lower()
    social = (
        compute_social_candidates(
            window_arr,
            social_distance_threshold_px=float(
                rows[0]["social_distance_threshold_px"]
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

    def add_page_identity(fig):
        fig.text(
            0.5, 0.99, page_video,
            ha="center", va="top", fontsize=9, fontweight="bold",
        )
        fig.text(
            0.5, 0.97, page_context,
            ha="center", va="top", fontsize=9, fontweight="bold",
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
            plotted = xy.copy()
            plotted[~finite] = np.nan
            label = (
                f"IDtracker animal {animal} "
                f"({rows[animal]['starting_side']})"
            )
            ax.plot(
                plotted[:, 0], plotted[:, 1],
                color=colors[animal % len(colors)], linewidth=0.65,
                alpha=0.8, label=label,
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
        fig.tight_layout(rect=[0, 0.08, 1, 0.93])
        pdf.savefig(fig)
        plt.close(fig)

        for animal, xy in enumerate(window_arr.transpose(1, 0, 2)):
            fig, ax = plt.subplots(figsize=(8.5, 11))
            add_page_identity(fig)
            draw_rois_2d(ax)
            finite = np.isfinite(xy).all(axis=1)
            plotted = xy.copy()
            plotted[~finite] = np.nan
            ax.plot(
                plotted[:, 0], plotted[:, 1],
                color=colors[animal % len(colors)], linewidth=0.7,
                alpha=0.85, label=f"IDtracker animal {animal} track",
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
            fig.tight_layout(rect=[0, 0.08, 1, 0.93])
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
            plotted = xy.copy()
            plotted[~finite] = np.nan
            ax.plot(
                plotted[:, 0], plotted[:, 1], global_frames,
                color=colors[(animal - 1) % len(colors)],
                linewidth=0.7, alpha=0.85,
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
            fontsize=14, y=0.91,
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
                base = xy.copy()
                base[~finite] = np.nan
                ax.plot(
                    base[:, 0], base[:, 1], color="#A0A0A0",
                    linewidth=0.6, alpha=0.55,
                    label=f"animal {animal} full track",
                )
                within = xy.copy()
                within[~(finite & social["within_mask"])] = np.nan
                ax.plot(
                    within[:, 0], within[:, 1], color="#E60049",
                    linewidth=2.6, alpha=0.95,
                    label="both visible and within social distance",
                )
                disappearance = xy.copy()
                disappearance[
                    ~(finite & social["disappearance_mask"])
                ] = np.nan
                ax.plot(
                    disappearance[:, 0], disappearance[:, 1],
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
            fig.tight_layout(rect=[0, 0.18, 1, 0.91])
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
                plotted = xy.copy()
                plotted[~finite] = np.nan
                ax.plot(
                    plotted[:, 0], plotted[:, 1],
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
            fig.tight_layout(rect=[0, 0.09, 1, 0.93])
            pdf.savefig(fig)
            plt.close(fig)

        # Metadata is deliberately the final page for fast visual review.
        fig = plt.figure(figsize=(8.5, 11))
        add_page_identity(fig)
        fig.suptitle("IDtracker analysis-window metadata", fontsize=16, y=0.925)
        summary_lines = [
            f"Post-processing script version: {rows[0]['script_version']}",
            f"Video: {video_name}",
            f"Cell: {cell_label}",
            f"QC record: {qc_record_id or 'not supplied'}",
            f"Canonical session: {session_folder.name}",
            f"Analysis: {analysis_type or 'unspecified'}",
            f"Inclusive global frames: {start} through {end}",
            f"End minus start: {end - start} frames",
            f"Coordinate observations in a complete window: {end - start + 1}",
            f"Displacement threshold: {rows[0]['movement_threshold_px']} pixels",
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
                "Social-distance measures are screening summaries, not confirmed fights.",
                "Dark-red paths are provisional turtling candidates, not posture proof.",
                "No general interpolation is performed by this prototype.",
                (
                    "Optional social-disappearance partner-centroid substitution: "
                    f"{'ENABLED' if use_social_imputation else 'DISABLED'}."
                ),
                "Lines break at coordinates missing in the selected IDtracker file.",
                "All axes use pixels or global frames; no seconds are used.",
            ]
        )
        fig.text(
            0.08, 0.88, "\n".join(summary_lines),
            va="top", ha="left", fontsize=9.5, family="monospace",
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
        turtling_window_frames=args.turtling_window_frames,
        turtling_min_path_px=args.turtling_min_path_px,
        turtling_max_radius90_px=args.turtling_max_radius90_px,
        turtling_min_turn_rotations=args.turtling_min_turn_rotations,
        turtling_max_straightness=args.turtling_max_straightness,
        turtling_max_step_px=args.turtling_max_step_px,
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
