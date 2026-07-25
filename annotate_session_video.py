#!/usr/bin/env python3
"""Create a provenance-rich annotated review video for one approved session."""
from __future__ import annotations

import argparse
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

import cv2
import numpy as np

from processor import (
    compute_social_candidates,
    compute_turtling_candidates,
    distance_to_polygon_boundary,
    load_rois,
    load_trajectories,
    points_inside_polygon,
    validate_trajectory_source,
)


SCRIPT_VERSION = "0.1.0"
COLORS = [(178, 114, 0), (0, 94, 213), (115, 158, 0), (167, 121, 204)]
WALL_BGR = np.asarray([178, 114, 0], dtype=np.float32)
FUNGUS_BGR = np.asarray([167, 121, 204], dtype=np.float32)
DARK_RED = (0, 0, 139)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def draw_text(
    frame: np.ndarray,
    text: str,
    origin: tuple[int, int],
    *,
    scale: float = 0.48,
    color: tuple[int, int, int] = (255, 255, 255),
    thickness: int = 1,
) -> None:
    cv2.putText(
        frame, text, origin, cv2.FONT_HERSHEY_SIMPLEX, scale,
        (0, 0, 0), thickness + 3, cv2.LINE_AA,
    )
    cv2.putText(
        frame, text, origin, cv2.FONT_HERSHEY_SIMPLEX, scale,
        color, thickness, cv2.LINE_AA,
    )


def local_polygon(polygon: np.ndarray, x0: int, y0: int) -> np.ndarray:
    shifted = polygon - np.asarray([x0, y0], dtype=float)
    return np.rint(shifted).astype(np.int32).reshape((-1, 1, 2))


def build_buffer_overlay(
    shape: tuple[int, int],
    rois: list[np.ndarray],
    x0: int,
    y0: int,
    wall_buffer_px: float,
    fungus_buffer_px: float,
) -> np.ndarray:
    height, width = shape
    yy, xx = np.mgrid[y0 : y0 + height, x0 : x0 + width]
    points = np.column_stack((xx.ravel(), yy.ravel()))
    overlay = np.zeros((height, width, 3), dtype=np.float32)
    primary_inside = points_inside_polygon(points, rois[0])
    primary_edge = distance_to_polygon_boundary(points, rois[0])
    wall = (primary_inside & (primary_edge <= wall_buffer_px)).reshape(shape)
    overlay[wall] = WALL_BGR
    if len(rois) > 1:
        fungus_inside = points_inside_polygon(points, rois[1])
        fungus_edge = distance_to_polygon_boundary(points, rois[1])
        fungus = (
            fungus_inside & (fungus_edge <= fungus_buffer_px)
        ).reshape(shape)
        overlay[fungus] = FUNGUS_BGR
    return overlay


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--video", type=Path, required=True)
    parser.add_argument("--trajectory", type=Path, required=True)
    parser.add_argument("--session-folder", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--provenance-output", type=Path, required=True)
    parser.add_argument("--video-name", required=True)
    parser.add_argument("--cell-label", required=True)
    parser.add_argument("--qc-record-id", required=True)
    parser.add_argument("--analysis-start", type=int, required=True)
    parser.add_argument("--analysis-timespan", type=int, default=7200)
    parser.add_argument("--wall-buffer-px", type=float, default=30.0)
    parser.add_argument("--fungus-buffer-px", type=float, default=30.0)
    parser.add_argument("--social-distance-px", type=float, default=60.0)
    parser.add_argument("--crop-padding-px", type=int, default=40)
    parser.add_argument("--tail-frames", type=int, default=60)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    if args.analysis_start <= 0 or args.analysis_timespan <= 0:
        raise ValueError("Analysis start and timespan must be positive")
    trajectory_kind = validate_trajectory_source(args.trajectory)
    arr = load_trajectories(args.trajectory)
    end = args.analysis_start + args.analysis_timespan
    if end >= len(arr):
        raise ValueError(
            f"Requested inclusive frames {args.analysis_start}-{end}, "
            f"but trajectory ends at {len(arr) - 1}"
        )
    window = arr[args.analysis_start : end + 1]
    if window.shape[1] != 2:
        raise ValueError("Fight review video requires exactly two animals")
    rois = load_rois(args.session_folder)
    if len(rois) < 2:
        raise ValueError("Fight review video requires primary and fungus ROIs")

    social = compute_social_candidates(window, args.social_distance_px)
    if social["status"] != "CALCULATED_FIGHT_TWO_ANIMALS":
        raise ValueError(social["status"])
    effective = window.copy()
    for missing_animal in (0, 1):
        mask = social["disappearance_masks_by_animal"][:, missing_animal]
        effective[mask, missing_animal] = window[mask, 1 - missing_animal]

    fungus_by_animal = np.zeros((len(window), 2), dtype=bool)
    turtling_by_animal = []
    for animal in (0, 1):
        valid = np.isfinite(window[:, animal]).all(axis=1)
        fungus_by_animal[valid, animal] = points_inside_polygon(
            window[valid, animal], rois[1]
        )
        result = compute_turtling_candidates(window[:, animal])
        # Scientific rule: secondary-ROI frames are never counted or displayed
        # as turtling, because turtling almost never occurs on the fungus.
        result["mask"] &= ~fungus_by_animal[:, animal]
        turtling_by_animal.append(result)

    capture = cv2.VideoCapture(str(args.video))
    if not capture.isOpened():
        raise RuntimeError(f"Could not open source video: {args.video}")
    fps = float(capture.get(cv2.CAP_PROP_FPS))
    source_width = int(capture.get(cv2.CAP_PROP_FRAME_WIDTH))
    source_height = int(capture.get(cv2.CAP_PROP_FRAME_HEIGHT))
    if fps <= 0 or source_width <= 0 or source_height <= 0:
        raise RuntimeError("Source video metadata is invalid")

    primary = rois[0]
    x0 = max(0, int(np.floor(primary[:, 0].min())) - args.crop_padding_px)
    y0 = max(0, int(np.floor(primary[:, 1].min())) - args.crop_padding_px)
    x1 = min(
        source_width,
        int(np.ceil(primary[:, 0].max())) + args.crop_padding_px + 1,
    )
    y1 = min(
        source_height,
        int(np.ceil(primary[:, 1].max())) + args.crop_padding_px + 1,
    )
    crop_width, crop_height = x1 - x0, y1 - y0
    header_height = 112
    canvas_width = max(crop_width, 960)
    crop_canvas_x = (canvas_width - crop_width) // 2
    output_size = (canvas_width, crop_height + header_height)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    temporary = args.output.with_name(args.output.name + ".partial.mp4")
    writer = cv2.VideoWriter(
        str(temporary), cv2.VideoWriter_fourcc(*"mp4v"), fps, output_size
    )
    if not writer.isOpened():
        raise RuntimeError("Could not initialize MP4 writer")

    buffer_overlay = build_buffer_overlay(
        (crop_height, crop_width), rois, x0, y0,
        args.wall_buffer_px, args.fungus_buffer_px,
    )
    roi_local = [local_polygon(roi, x0, y0) for roi in rois[:2]]
    capture.set(cv2.CAP_PROP_POS_FRAMES, args.analysis_start)
    frames_written = 0
    try:
        for offset in range(len(window)):
            ok, source = capture.read()
            if not ok:
                raise RuntimeError(
                    f"Video decode failed at global frame "
                    f"{args.analysis_start + offset}"
                )
            crop = source[y0:y1, x0:x1].copy()
            colored = buffer_overlay > 0
            blended = (
                crop.astype(np.float32) * 0.76 + buffer_overlay * 0.24
            ).astype(np.uint8)
            crop[colored.any(axis=2)] = blended[colored.any(axis=2)]
            cv2.polylines(crop, [roi_local[0]], True, (115, 158, 0), 2)
            cv2.polylines(crop, [roi_local[1]], True, (167, 121, 204), 2)

            for animal in (0, 1):
                tail_start = max(0, offset - args.tail_frames + 1)
                tail = effective[tail_start : offset + 1, animal]
                valid_tail = np.isfinite(tail).all(axis=1)
                if valid_tail.sum() >= 2:
                    points = np.rint(
                        tail[valid_tail] - np.asarray([x0, y0])
                    ).astype(np.int32).reshape((-1, 1, 2))
                    cv2.polylines(
                        crop, [points], False, COLORS[animal], 2, cv2.LINE_AA
                    )
                original_valid = np.isfinite(window[offset, animal]).all()
                effective_valid = np.isfinite(effective[offset, animal]).all()
                if not effective_valid:
                    continue
                point = tuple(
                    np.rint(
                        effective[offset, animal] - np.asarray([x0, y0])
                    ).astype(int)
                )
                copied = bool(
                    social["disappearance_masks_by_animal"][offset, animal]
                )
                turtling = bool(turtling_by_animal[animal]["mask"][offset])
                if copied:
                    cv2.drawMarker(
                        crop, point, (0, 255, 255), cv2.MARKER_TILTED_CROSS,
                        22, 3, cv2.LINE_AA,
                    )
                else:
                    cv2.circle(crop, point, 10, COLORS[animal], -1, cv2.LINE_AA)
                    cv2.circle(crop, point, 10, (0, 0, 0), 2, cv2.LINE_AA)
                if turtling:
                    cv2.circle(crop, point, 18, DARK_RED, 4, cv2.LINE_AA)
                label = f"ID {animal}"
                if copied:
                    label += " COPIED-social-disappearance"
                elif not original_valid:
                    label += " original-missing"
                if turtling:
                    label += " POTENTIAL-TURTLING"
                label_size = cv2.getTextSize(
                    label, cv2.FONT_HERSHEY_SIMPLEX, 0.43, 1
                )[0]
                label_x = point[0] + 13
                if label_x + label_size[0] >= crop_width - 4:
                    label_x = max(4, point[0] - label_size[0] - 13)
                label_y = max(18, point[1] - 12)
                draw_text(
                    crop, label, (label_x, label_y),
                    scale=0.43, color=(0, 255, 255) if copied else (255, 255, 255),
                )

            canvas = np.zeros((output_size[1], output_size[0], 3), np.uint8)
            global_frame = args.analysis_start + offset
            draw_text(
                canvas,
                f"{args.video_name} | cell {args.cell_label} | "
                f"global frame {global_frame} | analysis {offset + 1}/{len(window)}",
                (10, 23), scale=0.46,
            )
            draw_text(
                canvas,
                f"IDtracker IDs: 0 blue, 1 orange | yellow X = copied "
                f"partner centroid (social disappearance ON)",
                (10, 47), scale=0.43,
            )
            draw_text(
                canvas,
                f"cyan = primary wall buffer {args.wall_buffer_px:g}px | "
                f"purple = fungus edge buffer {args.fungus_buffer_px:g}px | "
                f"dark-red ring = potential turtling (fungus excluded)",
                (10, 70), scale=0.40,
            )
            draw_text(
                canvas,
                f"QC APPROVED: {args.qc_record_id} | trajectory: "
                f"{trajectory_kind} | annotator v{SCRIPT_VERSION}",
                (10, 94), scale=0.39,
            )
            canvas[
                header_height:,
                crop_canvas_x : crop_canvas_x + crop_width,
            ] = crop
            writer.write(canvas)
            frames_written += 1
    finally:
        capture.release()
        writer.release()

    if frames_written != len(window):
        temporary.unlink(missing_ok=True)
        raise RuntimeError(
            f"Wrote {frames_written} frames; expected {len(window)}"
        )
    temporary.replace(args.output)
    imputed_counts = [
        int(social["disappearance_masks_by_animal"][:, animal].sum())
        for animal in (0, 1)
    ]
    turtling_counts = [
        int(turtling_by_animal[animal]["mask"].sum()) for animal in (0, 1)
    ]
    provenance = {
        "artifact_type": "scientific_annotated_review_video",
        "created_utc": datetime.now(timezone.utc).isoformat(),
        "annotator_script": str(Path(__file__).resolve()),
        "annotator_script_version": SCRIPT_VERSION,
        "video_name": args.video_name,
        "cell_label": args.cell_label,
        "analysis_type": "fight",
        "qc_decision": "APPROVED",
        "qc_record_id": args.qc_record_id,
        "analysis_start_global_frame": args.analysis_start,
        "analysis_end_global_frame_inclusive": end,
        "analysis_timespan_frames": args.analysis_timespan,
        "frames_written": frames_written,
        "frames_per_second": fps,
        "source_video": str(args.video),
        "source_video_size_bytes": args.video.stat().st_size,
        "trajectory_file": str(args.trajectory),
        "trajectory_source_kind": trajectory_kind,
        "trajectory_sha256": sha256(args.trajectory),
        "session_folder": str(args.session_folder),
        "session_json_sha256": sha256(args.session_folder / "session.json"),
        "social_disappearance_substitution_enabled": True,
        "social_distance_threshold_px": args.social_distance_px,
        "social_disappearance_imputed_frames_by_animal": imputed_counts,
        "wall_buffer_px": args.wall_buffer_px,
        "fungus_buffer_px": args.fungus_buffer_px,
        "potential_turtling_uses_original_coordinates": True,
        "potential_turtling_excludes_secondary_fungus_roi": True,
        "potential_turtling_candidate_frames_by_animal": turtling_counts,
        "turtling_defaults": {
            "window_frames": 120,
            "min_path_px": 120.0,
            "max_radius90_px": 35.0,
            "min_turn_rotations": 3.0,
            "max_straightness": 0.25,
            "max_step_px": 20.0,
        },
        "output_video": str(args.output),
        "output_video_sha256": sha256(args.output),
        "interpretation_warning": (
            "Potential turtling is a provisional centroid-path candidate, "
            "not proof of upside-down posture."
        ),
    }
    args.provenance_output.parent.mkdir(parents=True, exist_ok=True)
    args.provenance_output.write_text(
        json.dumps(provenance, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps(provenance, indent=2))


if __name__ == "__main__":
    main()
