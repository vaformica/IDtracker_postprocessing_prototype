#!/usr/bin/env python3
"""Review-first GUI for minimal Firebird IDtracker.ai reprocessing."""
from __future__ import annotations

import csv
import io
import json
import math
import queue
import re
import shlex
import shutil
import subprocess
import sys
import threading
import time
from datetime import datetime
from pathlib import Path, PurePosixPath
import tkinter as tk
from tkinter import filedialog, messagebox, simpledialog, ttk
try:
    import tomllib
except ImportError:
    tomllib = None
try:
    import tomlkit
except ImportError:
    tomlkit = None


BASE = Path(__file__).resolve().parent
PROCESSOR = BASE / "processor.py"
SCRIPT_VERSION = (BASE / "VERSION").read_text(encoding="utf-8").strip()
SLURM_WORKER = BASE / "slurm_worker.py"
SLURM_FINALIZER = BASE / "slurm_finalize.py"
COMBINE_SCRIPT = BASE / "combine_results.py"
JUMP_AUDIT_SCRIPT = (BASE / "jump_audit.py").read_text(encoding="utf-8")
TRAJECTORY_NAMES = {
    "validated.npy": 0,
    "without_gaps.npy": 1,
    "trajectories_wo_gaps.npy": 2,
    "trajectories_without_gaps.npy": 3,
    "trajectories.npy": 4,
    "trajectories.h5": 5,
    "trajectories.csv": 6,
}
INTERVAL_KEYS = {
    "tracking_intervals",
    "tracking_interval",
    "intervals_to_track",
    "analysis_interval",
    "analysis_intervals",
}

BATCH_SESSION_RESOLVER = r"""
import json
import sys
from pathlib import Path

trajectory_rank = {
    "validated.npy": 0,
    "without_gaps.npy": 1,
    "trajectories_wo_gaps.npy": 2,
    "trajectories_without_gaps.npy": 3,
    "trajectories.npy": 4,
    "trajectories.h5": 5,
    "trajectories.csv": 6,
}
trajectory_status_by_name = {
    "validated.npy": "IDTRACKER_VALIDATED",
    "without_gaps.npy": "IDTRACKER_WITHOUT_GAPS",
    "trajectories_wo_gaps.npy": "IDTRACKER_LEGACY_WO_GAPS",
    "trajectories_without_gaps.npy": "IDTRACKER_LEGACY_WITHOUT_GAPS",
    "trajectories.npy": "IDTRACKER_RAW_NPY",
    "trajectories.h5": "IDTRACKER_RAW_H5",
    "trajectories.csv": "IDTRACKER_RAW_CSV",
}
raw_trajectory_names = ("trajectories.npy", "trajectories.h5", "trajectories.csv")

def read_text(path):
    try:
        return Path(path).read_text(encoding="utf-8")
    except Exception:
        return ""

def read_json(path):
    try:
        return json.loads(read_text(path))
    except Exception:
        return {}

items = json.load(sys.stdin)
results = []
for item in items:
    run_dir = Path(item["run_dir"])
    metadata = read_json(item["metadata_path"])
    session = ""
    link_source = ""
    for filename in ("session_link.txt", "session_path.txt"):
        value = read_text(run_dir / filename).strip()
        if value:
            session = value
            link_source = filename
            break
    if not session:
        value = str(metadata.get("session_path") or "").strip()
        if value:
            session = value
            link_source = "run_metadata.json:session_path"

    trajectories = []
    session_path = Path(session) if session else None
    if session_path and session_path.is_dir():
        for name in trajectory_rank:
            for direct in (
                session_path / name,
                session_path / "trajectories" / name,
            ):
                if direct.is_file():
                    trajectories.append(str(direct))
        for name in trajectory_rank:
            trajectories.extend(str(path) for path in session_path.rglob(name))
    trajectory = ""
    trajectory_resolution_status = "NO_TRAJECTORY"
    trajectory_candidates = sorted(set(trajectories))
    if trajectories:
        best_rank = min(
            trajectory_rank.get(Path(path).name, 99)
            for path in trajectory_candidates
        )
        best = [
            path for path in trajectory_candidates
            if trajectory_rank.get(Path(path).name, 99) == best_rank
        ]
        if len(best) == 1:
            trajectory = best[0]
            trajectory_resolution_status = trajectory_status_by_name[
                Path(trajectory).name
            ]
        else:
            trajectory_resolution_status = (
                "AMBIGUOUS_TRAJECTORY"
            )

    raw_trajectories = []
    if session_path and session_path.is_dir():
        for name in raw_trajectory_names:
            for direct in (
                session_path / name,
                session_path / "trajectories" / name,
            ):
                if direct.is_file():
                    raw_trajectories.append(str(direct))
        if not raw_trajectories:
            for name in raw_trajectory_names:
                raw_trajectories.extend(
                    str(path) for path in session_path.rglob(name)
                )

    session_json = {}
    if session_path and session_path.is_dir():
        direct = session_path / "session.json"
        if direct.is_file():
            session_json = read_json(direct)
        else:
            matches = list(session_path.rglob("session.json"))
            if matches:
                session_json = read_json(matches[0])

    source_toml = str(metadata.get("toml_source_path") or "")
    results.append(
        {
            "metadata": metadata,
            "session": session,
            "session_link_source": link_source,
            "trajectory": trajectory,
            "trajectory_resolution_status": trajectory_resolution_status,
            "trajectory_candidates": trajectory_candidates,
            "raw_trajectory_candidates": sorted(set(raw_trajectories)),
            "session_json": session_json,
            "source_toml": source_toml,
            "source_toml_text": read_text(source_toml) if source_toml else "",
        }
    )
json.dump(results, sys.stdout)
"""

COMBINE_RESULTS = (BASE / "combine_results.py").read_text(encoding="utf-8")
KNOWN_START_REVIEW_VIDEOS = {
    "Camera_1_40169154_20260630_1342_FIGHT_ACT1",
    "Camera_1_40169154_20260629_1319_ACT1.mp4",
    "Camera_1_40169154_20260627_1614_ACT2.mp4",
    "Camera_1_40169154_20260627_1316_ACT1.mp4",
    "Camera_3_40629046_20260627_1635_ACT2.mp4",
    "Camera_2_40359705_20260627_1619_ACT2.mp4",
    "Camera_2_40359705_20260628_1604_ACT2.mp4",
}


def normalized_video_name(path: str) -> str:
    name = PurePosixPath(path).name
    return name[:-4] if name.lower().endswith(".mp4") else name


def parse_video_fields(path: str) -> dict:
    stem = normalized_video_name(path)
    match = re.search(
        r"(?:^|_)Camera_(?P<camera>\d+)_(?P<camera_id>\d+)_"
        r"(?P<date>\d{8})_(?P<time>\d{4})(?P<remainder>.*)$",
        stem,
        flags=re.IGNORECASE,
    )
    act_match = re.search(r"(ACT\d+)", stem, flags=re.IGNORECASE)
    recording_date = match.group("date") if match else ""
    video_year = (
        recording_date[:4]
        if recording_date[:4] in {"2025", "2026"}
        else ""
    )
    return {
        "video_name": stem,
        "camera": match.group("camera") if match else "",
        "camera_id": match.group("camera_id") if match else "",
        "video_year": video_year,
        "recording_date": recording_date,
        "recording_time": match.group("time") if match else "",
        "act": act_match.group(1).upper() if act_match else "",
    }


KNOWN_START_REVIEW_STEMS = {
    normalized_video_name(name) for name in KNOWN_START_REVIEW_VIDEOS
}

START_REPORT_FIELDS = [
    "qc_record_id",
    "video",
    "camera",
    "camera_id",
    "video_year",
    "recording_date",
    "recording_time",
    "act",
    "cell_label",
    "analysis",
    "detected_start_global_frame",
    "start_status",
    "enter_start_global_frame",
    "interval_evidence",
    "canonical_session",
    "source_toml",
]

START_STATUS_HELP = """REVIEW DETECTED START
One positive start was detected. It is available for review but was not manually entered.

START_ZERO — correction required
The recorded start is zero, which is treated as a data-entry error.

NO INTERVAL — entry required
No recognized interval start exists in the source TOML or session JSON.

AMBIGUOUS — entry required
Recognized sources disagree. The GUI refuses to choose.

KNOWN MANUAL START REVIEW — entry required
The video is on the collaborator-provided review list, so manual entry is required.

START MANUALLY APPROVED
A positive global start was entered directly or imported from the editable CSV.

START APPROVED FROM JUMP AUDIT
The researcher clicked approval for a video-wide synchronized-disturbance
recommendation. The original start and audit evidence are retained in output
provenance columns."""

SETTINGS_FORMAT = "IDTRACKER_POSTPROCESSING_SETTINGS"
SETTINGS_SCHEMA_VERSION = 1
GUI_SETTINGS_KEYS = (
    "host",
    "key",
    "roots",
    "output_root",
    "remote_python",
    "window_frames",
    "threshold",
    "wall_buffer",
    "fungus_buffer",
    "social_distance",
    "one_frame_jump",
    "use_social_disappearance",
    "turtling_window",
    "turtling_min_path",
    "turtling_max_radius90",
    "turtling_min_turns",
    "turtling_max_straightness",
    "turtling_max_step",
    "execution_mode",
    "slurm_max_concurrent",
    "slurm_account",
    "slurm_partition",
    "slurm_time",
    "slurm_memory",
)


def saved_start_decisions(records):
    """Return auditable positive start decisions without animal-row duplication."""
    decisions = []
    seen = set()
    for record in records:
        try:
            start = int(str(record.get("start") or "").strip())
        except ValueError:
            continue
        if start <= 0:
            continue
        record_id = str(record.get("qc_record_id") or "").strip()
        stable_key = (
            normalized_video_name(record.get("video", "")),
            str(record.get("cell_label") or "").strip(),
            str(record.get("analysis") or "").strip().lower(),
        )
        key = ("QC", record_id) if record_id else ("STABLE",) + stable_key
        if key in seen:
            continue
        seen.add(key)
        decisions.append(
            {
                "scope": "SESSION",
                "qc_record_id": record_id,
                "video": record.get("video", ""),
                "cell_label": record.get("cell_label", ""),
                "analysis": record.get("analysis", ""),
                "start_global_frame": start,
                "archived_original_start_frame": record.get(
                    "archived_original_start", ""
                ),
                "status": record.get("status", ""),
                "decision_source": record.get(
                    "start_decision_source", ""
                ),
                "decision_provenance": record.get(
                    "start_decision_provenance", ""
                ),
            }
        )
    return decisions


def validate_settings_bundle(payload):
    """Validate a reusable settings bundle before any GUI state is changed."""
    if not isinstance(payload, dict):
        raise ValueError("Settings file must contain one JSON object")
    if payload.get("format") != SETTINGS_FORMAT:
        raise ValueError(
            f"Unrecognized settings format; expected {SETTINGS_FORMAT}"
        )
    if payload.get("schema_version") != SETTINGS_SCHEMA_VERSION:
        raise ValueError(
            "Unsupported settings schema version: "
            f"{payload.get('schema_version')!r}"
        )
    gui_settings = payload.get("gui_settings") or {}
    if not isinstance(gui_settings, dict):
        raise ValueError("gui_settings must be a JSON object")
    unknown = sorted(set(gui_settings) - set(GUI_SETTINGS_KEYS))
    if unknown:
        raise ValueError(
            "Unknown GUI setting(s): " + ", ".join(unknown)
        )
    positive_numeric = {
        "window_frames",
        "threshold",
        "social_distance",
        "one_frame_jump",
        "turtling_window",
        "turtling_min_path",
        "turtling_max_radius90",
        "turtling_min_turns",
        "turtling_max_step",
        "slurm_max_concurrent",
    }
    nonnegative_numeric = {"wall_buffer", "fungus_buffer"}
    for key in positive_numeric | nonnegative_numeric:
        if key not in gui_settings:
            continue
        try:
            number = float(gui_settings[key])
        except (TypeError, ValueError):
            raise ValueError(f"GUI setting {key} must be numeric") from None
        if key in positive_numeric and number <= 0:
            raise ValueError(f"GUI setting {key} must be positive")
        if key in nonnegative_numeric and number < 0:
            raise ValueError(f"GUI setting {key} cannot be negative")
    if "turtling_max_straightness" in gui_settings:
        try:
            straightness = float(gui_settings["turtling_max_straightness"])
        except (TypeError, ValueError):
            raise ValueError(
                "GUI setting turtling_max_straightness must be numeric"
            ) from None
        if not 0 <= straightness <= 1:
            raise ValueError(
                "GUI setting turtling_max_straightness must be between 0 and 1"
            )
    if (
        "use_social_disappearance" in gui_settings
        and not isinstance(gui_settings["use_social_disappearance"], bool)
    ):
        raise ValueError("use_social_disappearance must be true or false")
    if (
        "execution_mode" in gui_settings
        and gui_settings["execution_mode"]
        not in {"SLURM job array", "Direct SSH (small test only)"}
    ):
        raise ValueError("Unrecognized execution_mode in settings file")
    decisions = payload.get("start_decisions") or []
    if not isinstance(decisions, list):
        raise ValueError("start_decisions must be a JSON array")
    normalized_decisions = []
    for index, decision in enumerate(decisions, start=1):
        if not isinstance(decision, dict):
            raise ValueError(
                f"start_decisions item {index} must be a JSON object"
            )
        scope = str(decision.get("scope") or "SESSION").strip().upper()
        if scope not in {"SESSION", "VIDEO"}:
            raise ValueError(
                f"start_decisions item {index} has invalid scope {scope!r}"
            )
        try:
            start = int(decision.get("start_global_frame"))
        except (TypeError, ValueError):
            raise ValueError(
                f"start_decisions item {index} has a non-integer start"
            ) from None
        if start <= 0:
            raise ValueError(
                f"start_decisions item {index} must have a positive start"
            )
        record_id = str(decision.get("qc_record_id") or "").strip()
        video = str(decision.get("video") or "").strip()
        cell = str(decision.get("cell_label") or "").strip()
        analysis = str(decision.get("analysis") or "").strip().lower()
        if scope == "VIDEO" and not video:
            raise ValueError(
                f"start_decisions item {index} has VIDEO scope but no video"
            )
        if scope == "SESSION" and not record_id and not (
            video and cell and analysis
        ):
            raise ValueError(
                f"start_decisions item {index} lacks a QC ID or complete "
                "video/cell/analysis key"
            )
        normalized_decisions.append(
            {
                **decision,
                "scope": scope,
                "qc_record_id": record_id,
                "video": video,
                "cell_label": cell,
                "analysis": analysis,
                "start_global_frame": start,
            }
        )
    jump_audit = payload.get("jump_audit") or {}
    if not isinstance(jump_audit, dict):
        raise ValueError("jump_audit must be a JSON object")
    for key in ("summaries", "tracks"):
        if not isinstance(jump_audit.get(key) or [], list):
            raise ValueError(f"jump_audit.{key} must be a JSON array")
    return {
        **payload,
        "gui_settings": gui_settings,
        "start_decisions": normalized_decisions,
        "jump_audit": jump_audit,
    }


def settings_bundle_from_combined_rows(rows, source_name="combined CSV"):
    """Recover settings and final starts from a prior combined-results CSV."""
    if not rows:
        raise ValueError("The combined-results CSV contains no data rows")
    required = {
        "qc_record_id",
        "video",
        "cell_label",
        "analysis_type",
        "analysis_start_frame",
    }
    missing = sorted(required - set(rows[0]))
    if missing:
        raise ValueError(
            "This is not a recognized combined-results CSV; missing: "
            + ", ".join(missing)
        )
    parameter_columns = {
        "analysis_timespan_frames": "window_frames",
        "movement_threshold_px": "threshold",
        "wall_buffer_px": "wall_buffer",
        "fungus_buffer_px": "fungus_buffer",
        "social_distance_threshold_px": "social_distance",
        "one_frame_jump_threshold_px": "one_frame_jump",
        "turtling_window_frames": "turtling_window",
        "turtling_min_path_px": "turtling_min_path",
        "turtling_max_radius90_px": "turtling_max_radius90",
        "turtling_min_turn_rotations": "turtling_min_turns",
        "turtling_max_straightness": "turtling_max_straightness",
        "turtling_max_step_px": "turtling_max_step",
    }
    gui_settings = {}
    for csv_column, setting_name in parameter_columns.items():
        values = {
            str(row.get(csv_column) or "").strip()
            for row in rows
            if str(row.get(csv_column) or "").strip()
        }
        if len(values) > 1:
            raise ValueError(
                f"Prior results contain conflicting {csv_column} values"
            )
        if values:
            gui_settings[setting_name] = values.pop()
    canonical_jump_values = {
        str(row.get("one_frame_jump_threshold_px") or "").strip()
        for row in rows
        if str(row.get("one_frame_jump_threshold_px") or "").strip()
    }
    legacy_jump_values = {
        str(row.get("jump_threshold_px") or "").strip()
        for row in rows
        if str(row.get("jump_threshold_px") or "").strip()
    }
    if len(legacy_jump_values) > 1:
        raise ValueError(
            "Prior results contain conflicting jump_threshold_px values"
        )
    if canonical_jump_values and legacy_jump_values:
        canonical = float(next(iter(canonical_jump_values)))
        legacy = float(next(iter(legacy_jump_values)))
        if not math.isclose(canonical, legacy):
            raise ValueError(
                "Prior results disagree between one_frame_jump_threshold_px "
                "and its jump_threshold_px compatibility alias"
            )
    if "one_frame_jump" not in gui_settings and legacy_jump_values:
        gui_settings["one_frame_jump"] = legacy_jump_values.pop()
    social_values = {
        str(row.get("use_social_disappearance_in_calculations") or "")
        .strip()
        .upper()
        for row in rows
        if str(row.get("use_social_disappearance_in_calculations") or "")
        .strip()
        .upper()
        in {"YES", "NO"}
    }
    if len(social_values) > 1:
        raise ValueError(
            "Prior results contain conflicting social-disappearance switches"
        )
    if social_values:
        gui_settings["use_social_disappearance"] = (
            social_values.pop() == "YES"
        )
    by_record = {}
    for line_number, row in enumerate(rows, start=2):
        record_id = str(row.get("qc_record_id") or "").strip()
        try:
            start = int(str(row.get("analysis_start_frame") or "").strip())
        except ValueError:
            raise ValueError(
                f"line {line_number}: analysis_start_frame is not an integer"
            ) from None
        candidate = {
            "scope": "SESSION",
            "qc_record_id": record_id,
            "video": row.get("video", ""),
            "cell_label": row.get("cell_label", ""),
            "analysis": row.get("analysis_type", ""),
            "start_global_frame": start,
            "archived_original_start_frame": row.get(
                "archived_original_start_frame", ""
            ),
            "status": {
                "JUMP_AUDIT_APPROVED": "START APPROVED FROM JUMP AUDIT",
                "SOURCE_INTERVAL": "REVIEW DETECTED START",
            }.get(
                row.get("start_frame_decision_source"),
                "START MANUALLY APPROVED",
            ),
            "decision_source": row.get(
                "start_frame_decision_source", ""
            ),
            "decision_provenance": row.get(
                "start_frame_decision_provenance", ""
            ),
        }
        previous = by_record.get(record_id)
        if previous and previous != candidate:
            raise ValueError(
                f"Conflicting animal rows for QC record {record_id}"
            )
        by_record[record_id] = candidate
    return validate_settings_bundle(
        {
            "format": SETTINGS_FORMAT,
            "schema_version": SETTINGS_SCHEMA_VERSION,
            "saved_at": "",
            "script_version": str(rows[0].get("script_version") or ""),
            "source": source_name,
            "gui_settings": gui_settings,
            "start_decisions": list(by_record.values()),
            "jump_audit": {"summaries": [], "tracks": []},
        }
    )


def _audit_csv_value(key, value):
    """Restore CSV-safe jump-audit values needed by the GUI."""
    text = str(value or "").strip()
    if key == "suggested_full_window_fits":
        return text.lower() in {"true", "1", "yes"}
    if key in {
        "approved_records",
        "animal_tracks",
        "tracks_with_jumps",
        "persistent_jump_tracks",
        "last_synchronized_disturbance_frame",
        "suggested_start_global_frame",
        "return_horizon_frames",
        "synchrony_tolerance_frames",
    }:
        if not text:
            return ""
        try:
            return int(float(text))
        except ValueError:
            return text
    if key == "jump_threshold_px":
        try:
            return float(text)
        except ValueError:
            return text
    if text.startswith(("[", "{")):
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            return text
    return value


def settings_bundle_from_jump_audit_rows(
    summaries, tracks=None, source_name="jump-audit CSV"
):
    """Recover an earlier audit table and its approved video decisions."""
    if not summaries:
        raise ValueError("The jump-audit video CSV contains no data rows")
    required = {
        "video",
        "analysis_type",
        "suggested_start_global_frame",
        "audit_version",
        "decision",
    }
    missing = sorted(required - set(summaries[0]))
    if missing:
        raise ValueError(
            "This is not a recognized jump-audit video CSV; missing: "
            + ", ".join(missing)
        )
    restored = [
        {key: _audit_csv_value(key, value) for key, value in row.items()}
        for row in summaries
    ]
    restored_tracks = [
        {key: _audit_csv_value(key, value) for key, value in row.items()}
        for row in (tracks or [])
    ]
    thresholds = {
        str(row.get("jump_threshold_px") or "").strip()
        for row in restored
        if str(row.get("jump_threshold_px") or "").strip()
    }
    if len(thresholds) > 1:
        raise ValueError("Jump-audit CSV contains conflicting thresholds")
    gui_settings = {}
    if thresholds:
        gui_settings["one_frame_jump"] = thresholds.pop()
    decisions = []
    for summary in restored:
        if str(summary.get("decision") or "").strip().upper() != "APPROVED":
            continue
        start = summary.get("suggested_start_global_frame")
        if start == "":
            raise ValueError(
                f"Approved audit row for {summary.get('video')} has no start"
            )
        decisions.append(
            {
                "scope": "VIDEO",
                "qc_record_id": "",
                "video": summary.get("video", ""),
                "cell_label": "",
                "analysis": summary.get("analysis_type", ""),
                "start_global_frame": int(start),
                "archived_original_start_frame": "",
                "status": "START APPROVED FROM JUMP AUDIT",
                "decision_source": "JUMP_AUDIT_APPROVED",
                "decision_provenance": (
                    f"Restored approved jump audit v"
                    f"{summary.get('audit_version')}; last synchronized "
                    f"disturbance frame "
                    f"{summary.get('last_synchronized_disturbance_frame')}; "
                    f"jump threshold {summary.get('jump_threshold_px')} px; "
                    f"approved replacement start {start}"
                ),
            }
        )
    return validate_settings_bundle(
        {
            "format": SETTINGS_FORMAT,
            "schema_version": SETTINGS_SCHEMA_VERSION,
            "saved_at": "",
            "script_version": "",
            "source": source_name,
            "gui_settings": gui_settings,
            "start_decisions": decisions,
            "jump_audit": {
                "timestamp": "",
                "summaries": restored,
                "tracks": restored_tracks,
            },
        }
    )


def make_missing_start_report(records):
    return [
        {
            "qc_record_id": record["qc_record_id"],
            "video": record["video"],
            "camera": record["camera"],
            "camera_id": record["camera_id"],
            "video_year": record.get("video_year", ""),
            "recording_date": record["recording_date"],
            "recording_time": record["recording_time"],
            "act": record["act"],
            "cell_label": record["cell_label"],
            "analysis": record["analysis"],
            "detected_start_global_frame": record["detected"],
            "start_status": record["status"],
            "enter_start_global_frame": "",
            "interval_evidence": record["source"],
            "canonical_session": record["session"],
            "source_toml": record["toml"],
        }
        for record in records
        if not str(record.get("start", "")).strip()
    ]


def make_missing_trajectory_report(records):
    return [
        {
            "qc_record_id": record["qc_record_id"],
            "video": record["video"],
            "camera": record["camera"],
            "video_year": record.get("video_year", ""),
            "recording_date": record["recording_date"],
            "recording_time": record["recording_time"],
            "act": record["act"],
            "cell_label": record["cell_label"],
            "analysis": record["analysis"],
            "trajectory_status": "NO_USABLE_TRAJECTORY",
            "resolution_detail": record.get(
                "trajectory_diagnostic", record["trajectory_status"]
            ),
            "canonical_session": record["session"],
            "raw_trajectory_candidates": "; ".join(
                record.get("raw_trajectory_candidates") or []
            ),
        }
        for record in records
        if not record.get("processable")
    ]


def validate_start_report_updates(report_rows, records):
    records_by_id = {record["qc_record_id"]: record for record in records}
    seen = set()
    updates = []
    errors = []
    for line_number, row in enumerate(report_rows, start=2):
        record_id = str(row.get("qc_record_id") or "").strip()
        entered = str(row.get("enter_start_global_frame") or "").strip()
        if not record_id:
            errors.append(f"line {line_number}: qc_record_id is blank")
            continue
        if record_id in seen:
            errors.append(f"line {line_number}: duplicate qc_record_id {record_id}")
            continue
        seen.add(record_id)
        if not entered:
            continue
        if record_id not in records_by_id:
            errors.append(f"line {line_number}: unknown qc_record_id {record_id}")
            continue
        try:
            value = int(entered)
        except ValueError:
            errors.append(
                f"line {line_number}: enter_start_global_frame must be an integer"
            )
            continue
        if value <= 0:
            errors.append(
                f"line {line_number}: enter_start_global_frame must be greater than zero"
            )
            continue
        updates.append((records_by_id[record_id], value))
    if errors:
        raise ValueError("\n".join(errors))
    return updates


class SSH:
    def __init__(self, host: str, key: str):
        self.host = host
        self.key = str(Path(key).expanduser())

    def run(self, command: str, input_text: str | None = None, timeout: int = 900):
        invocation = ["ssh", "-o", "BatchMode=yes"]
        if self.key:
            invocation += ["-o", "IdentitiesOnly=yes", "-i", self.key]
        invocation += [self.host, "bash", "-lc", shlex.quote(command)]
        result = subprocess.run(
            invocation,
            input=input_text,
            text=True,
            capture_output=True,
            timeout=timeout,
        )
        if result.returncode:
            raise RuntimeError(result.stderr.strip() or result.stdout.strip())
        return result.stdout

    def download(self, remote_path: str, local_path: str, timeout: int = 900):
        invocation = ["scp", "-o", "BatchMode=yes"]
        if self.key:
            invocation += ["-o", "IdentitiesOnly=yes", "-i", self.key]
        invocation += [f"{self.host}:{remote_path}", local_path]
        result = subprocess.run(
            invocation,
            text=True,
            capture_output=True,
            timeout=timeout,
        )
        if result.returncode:
            raise RuntimeError(result.stderr.strip() or result.stdout.strip())

    def download_directory(
        self, remote_path: str, local_path: str, timeout: int = 1800
    ):
        Path(local_path).mkdir(parents=True, exist_ok=True)
        invocation = ["scp", "-r", "-o", "BatchMode=yes"]
        if self.key:
            invocation += ["-o", "IdentitiesOnly=yes", "-i", self.key]
        invocation += [
            f"{self.host}:{remote_path.rstrip('/')}/.",
            local_path,
        ]
        result = subprocess.run(
            invocation,
            text=True,
            capture_output=True,
            timeout=timeout,
        )
        if result.returncode:
            raise RuntimeError(result.stderr.strip() or result.stdout.strip())


def session_for(path: str) -> str:
    item = PurePosixPath(path)
    return str(item.parent.parent if item.parent.name == "trajectories" else item.parent)


def find_interval_candidates(obj, trail="session_json"):
    found = []
    if isinstance(obj, dict):
        for key, value in obj.items():
            here = f"{trail}.{key}"
            if str(key).lower() in INTERVAL_KEYS:
                found.extend(extract_pairs(value, here))
            found.extend(find_interval_candidates(value, here))
    elif isinstance(obj, list):
        for index, value in enumerate(obj):
            found.extend(find_interval_candidates(value, f"{trail}[{index}]"))
    return found


def extract_pairs(value, source):
    if (
        isinstance(value, (list, tuple))
        and len(value) >= 2
        and all(isinstance(x, (int, float)) and not isinstance(x, bool) for x in value[:2])
    ):
        return [(int(value[0]), int(value[1]), source)]
    output = []
    if isinstance(value, (list, tuple)):
        for index, child in enumerate(value):
            output.extend(extract_pairs(child, f"{source}[{index}]"))
    return output


def expand_remote_path(path: str, remote_home: str) -> str:
    path = path.strip()
    if path == "~":
        return remote_home
    if path.startswith("~/"):
        return remote_home.rstrip("/") + "/" + path[2:]
    return path


def automatic_download_paths(token: str, home: Path | None = None) -> dict:
    """Return the atomic one-folder Mac download layout for one batch."""
    home = Path.home() if home is None else Path(home)
    downloads = home / "Downloads"
    local_root = (
        downloads if downloads.is_dir() else home
    ) / "IDtracker_postprocessing_results"
    completed_folder = local_root / f"completed_run_{token}"
    partial_folder = local_root / f".completed_run_{token}.partial"
    return {
        "root": local_root,
        "completed_folder": completed_folder,
        "partial_folder": partial_folder,
        "partial_csv": partial_folder / f"combined_results_{token}.csv",
        "partial_pdfs": partial_folder / "pdfs",
    }


def jump_audit_start_for_record(record: dict) -> tuple[int, str] | None:
    """Choose a positive start for read-only audit, never for processing.

    A final GUI-approved start is preferred. If it is blank because the video
    was deliberately placed on manual start review, one unambiguous positive
    detected interval may be used only to inspect jump timing. Zero, missing,
    and conflicting detected starts remain unauditable.
    """
    for key, basis in (
        ("start", "FINAL_APPROVED_START"),
        ("detected", "POSITIVE_DETECTED_START_AUDIT_ONLY"),
    ):
        try:
            value = int(str(record.get(key, "")).strip())
        except (TypeError, ValueError):
            continue
        if value > 0:
            return value, basis
    return None


def parse_toml(text: str):
    if tomllib is not None:
        return tomllib.loads(text)
    if tomlkit is not None:
        return tomlkit.parse(text)
    raise RuntimeError(
        "TOML parsing is unavailable. Use Python 3.11+ or install tomlkit; "
        "intervals will not be guessed from raw text."
    )


class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("Firebird IDtracker Post-processing — Minimal Scientific Review")
        self.geometry("1250x820")
        self.minsize(900, 650)
        self.work = queue.Queue()
        self.rows = {}
        self._build()
        self.after(100, self._poll)

    def _build(self):
        self.host = tk.StringVar(value="firebird")
        self.key = tk.StringVar(value="~/.ssh/id_ed25519_firebird")
        self.roots = tk.StringVar(
            value="/data/labs/vformic1-swat-lab/idtracker_pipeline_runs"
        )
        self.output_root = tk.StringVar(value="~/idtracker_reprocessing_v1")
        self.remote_python = tk.StringVar(
            value="~/miniconda3/envs/idtracker_reprocess_v1/bin/python"
        )
        self.scan_running = False
        self.processing_running = False
        self.jump_audit_running = False
        self.last_combined_remote = ""
        self.last_plot_remote = ""
        self.current_batch_token = ""
        self.auto_download_started_for = ""
        self.all_records = []
        self.filtered_records = []
        self.jump_audit_summaries = []
        self.jump_audit_tracks = []
        self.jump_audit_rows = {}
        self.jump_audit_timestamp = ""
        self.loaded_start_decisions = []
        self.loaded_settings_source = ""
        self.sort_column = "video_name"
        self.sort_reverse = False

        self.notebook = ttk.Notebook(self)
        self.notebook.pack(fill="both", expand=True, padx=10, pady=8)
        self.setup_tab = ttk.Frame(self.notebook)
        self.sessions_tab = ttk.Frame(self.notebook)
        self.jump_audit_tab = ttk.Frame(self.notebook)
        self.logs_tab = ttk.Frame(self.notebook)
        self.notebook.add(self.setup_tab, text="Setup & Run")
        self.notebook.add(self.sessions_tab, text="Sessions")
        self.notebook.add(self.jump_audit_tab, text="Jump Audit")
        self.notebook.add(self.logs_tab, text="Logs & Diagnostics")

        saved_settings = ttk.LabelFrame(
            self.setup_tab,
            text="Reuse a previous troubleshooting setup",
        )
        saved_settings.pack(fill="x", padx=10, pady=(8, 4))
        ttk.Button(
            saved_settings,
            text="Load previous settings or results",
            command=self.load_previous_settings,
        ).grid(row=0, column=0, sticky="w", padx=8, pady=6)
        ttk.Button(
            saved_settings,
            text="Save current settings and decisions",
            command=self.save_current_settings,
        ).grid(row=0, column=1, sticky="w", padx=8, pady=6)
        self.saved_settings_status = tk.StringVar(
            value=(
                "Loads reusable JSON, a prior combined-results CSV, or a "
                "Jump Audit video CSV."
            )
        )
        ttk.Label(
            saved_settings,
            textvariable=self.saved_settings_status,
            anchor="w",
        ).grid(row=0, column=2, sticky="ew", padx=8, pady=6)
        saved_settings.columnconfigure(2, weight=1)

        connection = ttk.LabelFrame(
            self.setup_tab,
            text="1. Firebird connection and recursive search",
        )
        connection.pack(fill="x", padx=10, pady=8)
        fields = [
            ("SSH host", self.host),
            ("SSH private key", self.key),
            ("Firebird pipeline project root", self.roots),
            ("Remote output folder", self.output_root),
            ("Installed Firebird Python", self.remote_python),
        ]
        for row, (label, variable) in enumerate(fields):
            ttk.Label(connection, text=label).grid(row=row, column=0, sticky="w", padx=6, pady=3)
            ttk.Entry(connection, textvariable=variable).grid(row=row, column=1, sticky="ew", padx=6)
        connection.columnconfigure(1, weight=1)
        ttk.Button(connection, text="Test SSH", command=self.test_ssh).grid(row=0, column=2, padx=6)
        self.scan_button = ttk.Button(
            connection, text="Scan approved runs", command=self.scan
        )
        self.scan_button.grid(row=2, column=2, padx=6)

        controls = ttk.LabelFrame(
            self.setup_tab, text="2. Only requested calculations"
        )
        controls.pack(fill="x", padx=10, pady=4)
        self.window_frames = tk.StringVar(value="7200")
        self.threshold = tk.StringVar(value="30")
        self.wall_buffer = tk.StringVar(value="30")
        self.fungus_buffer = tk.StringVar(value="30")
        self.social_distance = tk.StringVar(value="60")
        self.one_frame_jump = tk.StringVar(value="200")
        self.use_social_disappearance = tk.BooleanVar(value=True)
        parameter_fields = [
            (
                0, 0, "Inclusive end - start (frames)",
                self.window_frames, 10,
            ),
            (
                0, 2, "Displacement threshold (pixels)",
                self.threshold, 10,
            ),
            (1, 0, "Primary wall buffer (pixels)", self.wall_buffer, 10),
            (
                1, 2, "Fight fungus inward buffer (pixels)",
                self.fungus_buffer, 10,
            ),
            (
                2, 0, "Fight social distance (pixels)",
                self.social_distance, 10,
            ),
            (
                3, 0, "Coordinate-jump threshold (pixels; provisional)",
                self.one_frame_jump, 10,
            ),
        ]
        for row, column, label, variable, width in parameter_fields:
            ttk.Label(controls, text=label).grid(
                row=row, column=column, sticky="w", padx=(8, 4), pady=4
            )
            ttk.Entry(
                controls, textvariable=variable, width=width
            ).grid(
                row=row, column=column + 1, sticky="w", padx=(0, 18), pady=4
            )
        ttk.Checkbutton(
            controls,
            text="Use social disappearance in distance/location calculations",
            variable=self.use_social_disappearance,
        ).grid(
            row=2, column=2, columnspan=3, sticky="w", padx=8, pady=4
        )
        ttk.Label(
            controls,
            text=(
                "Checked by default. The imputed-frame CSV column counts only "
                "partner locations actually copied for that animal."
            ),
        ).grid(
            row=4, column=0, columnspan=5, sticky="w", padx=8, pady=(2, 6)
        )
        controls.columnconfigure(4, weight=1)
        ttk.Button(
            controls,
            text="Edit selected start frame",
            command=self.edit_start,
        ).grid(row=5, column=0, columnspan=2, sticky="w", padx=8, pady=(2, 8))
        turtling_controls = ttk.LabelFrame(
            self.setup_tab,
            text="3. Provisional tight-loop turtling candidate detector",
        )
        turtling_controls.pack(fill="x", padx=10, pady=4)
        self.turtling_window = tk.StringVar(value="120")
        self.turtling_min_path = tk.StringVar(value="120")
        self.turtling_max_radius90 = tk.StringVar(value="35")
        self.turtling_min_turns = tk.StringVar(value="3")
        self.turtling_max_straightness = tk.StringVar(value="0.25")
        self.turtling_max_step = tk.StringVar(value="20")
        turtling_fields = [
            (0, 0, "Window (frames)", self.turtling_window),
            (0, 2, "Minimum path (pixels)", self.turtling_min_path),
            (0, 4, "Maximum radius90 (pixels)", self.turtling_max_radius90),
            (1, 0, "Minimum absolute turns (rotations)", self.turtling_min_turns),
            (1, 2, "Maximum net/path (proportion)", self.turtling_max_straightness),
            (1, 4, "Maximum adjacent step (pixels)", self.turtling_max_step),
        ]
        for row, column, label, variable in turtling_fields:
            ttk.Label(turtling_controls, text=label).grid(
                row=row, column=column, sticky="w", padx=(8, 4), pady=4
            )
            ttk.Entry(
                turtling_controls, textvariable=variable, width=9
            ).grid(
                row=row, column=column + 1,
                sticky="w", padx=(0, 16), pady=4,
            )
        ttk.Label(
            turtling_controls,
            text=(
                "Dark-red PDF paths are trajectory candidates only; centroid "
                "coordinates cannot prove that a beetle is upside down."
            ),
        ).grid(
            row=2, column=0, columnspan=6,
            sticky="w", padx=8, pady=(2, 7),
        )

        execution_controls = ttk.LabelFrame(
            self.setup_tab,
            text="4. Firebird execution",
        )
        execution_controls.pack(fill="x", padx=10, pady=4)
        self.execution_mode = tk.StringVar(value="SLURM job array")
        self.slurm_max_concurrent = tk.StringVar(value="20")
        self.slurm_account = tk.StringVar(value="swat")
        self.slurm_partition = tk.StringVar(value="")
        self.slurm_time = tk.StringVar(value="02:00:00")
        self.slurm_memory = tk.StringVar(value="4G")
        ttk.Label(execution_controls, text="Mode").grid(
            row=0, column=0, sticky="w", padx=(8, 4), pady=4
        )
        ttk.Combobox(
            execution_controls,
            textvariable=self.execution_mode,
            values=["SLURM job array", "Direct SSH (small test only)"],
            state="readonly",
            width=27,
        ).grid(row=0, column=1, sticky="w", padx=(0, 16), pady=4)
        slurm_fields = [
            (0, 2, "Maximum simultaneous jobs", self.slurm_max_concurrent, 7),
            (0, 4, "Account", self.slurm_account, 10),
            (
                1, 0, "Partition (blank = cluster default)",
                self.slurm_partition, 14,
            ),
            (1, 2, "Time per session", self.slurm_time, 10),
            (1, 4, "Memory per session", self.slurm_memory, 8),
        ]
        for row, column, label, variable, width in slurm_fields:
            ttk.Label(execution_controls, text=label).grid(
                row=row, column=column, sticky="w", padx=(8, 4), pady=4
            )
            ttk.Entry(
                execution_controls, textvariable=variable, width=width
            ).grid(
                row=row, column=column + 1,
                sticky="w", padx=(0, 16), pady=4,
            )
        ttk.Label(
            execution_controls,
            text=(
                "SLURM runs one approved session per array task, then combines "
                "and promotes results only if every task succeeds."
            ),
        ).grid(
            row=2, column=0, columnspan=6, sticky="w", padx=8, pady=(0, 5)
        )

        results = ttk.LabelFrame(
            self.setup_tab,
            text="5. Results from the latest completed processing run",
        )
        results.pack(fill="x", padx=10, pady=4)
        self.results_status = tk.StringVar(
            value="After processing, download the matching CSV and PDF folder here."
        )
        ttk.Label(
            results, textvariable=self.results_status, anchor="w"
        ).grid(row=0, column=0, columnspan=2, sticky="ew", padx=8, pady=(5, 2))
        self.download_button = ttk.Button(
            results,
            text="Download CSV from this run",
            command=self.download_combined,
        )
        self.download_button.grid(
            row=1, column=0, sticky="w", padx=8, pady=(2, 8)
        )
        self.plot_download_button = ttk.Button(
            results,
            text="Download PDFs from this run",
            command=self.download_plot_folder,
        )
        self.plot_download_button.grid(
            row=1, column=1, sticky="w", padx=8, pady=(2, 8)
        )
        results.columnconfigure(2, weight=1)

        sessions_tab = self.sessions_tab
        logs_tab = self.logs_tab

        filter_bar = ttk.LabelFrame(sessions_tab, text="Find and filter approved sessions")
        filter_bar.grid(row=0, column=0, columnspan=2, sticky="ew", padx=4, pady=4)
        self.search_filter = tk.StringVar()
        self.start_filter = tk.StringVar(value="All start statuses")
        self.analysis_filter = tk.StringVar(value="All analyses")
        self.camera_filter = tk.StringVar(value="All cameras")
        self.date_filter = tk.StringVar(value="All dates")
        self.act_filter = tk.StringVar(value="All ACTs")
        ttk.Label(filter_bar, text="Search").grid(
            row=0, column=0, sticky="w", padx=(6, 2), pady=3
        )
        search_entry = ttk.Entry(filter_bar, textvariable=self.search_filter, width=26)
        search_entry.grid(row=0, column=1, sticky="ew", padx=2, pady=3)
        self.start_filter_box = ttk.Combobox(
            filter_bar,
            textvariable=self.start_filter,
            values=[
                "All start statuses",
                "Needs new start",
                "Ready to process",
                "Manually approved start",
                "Jump-audit approved start",
                "No usable trajectory",
            ],
            state="readonly",
            width=22,
        )
        self.start_filter_box.grid(row=0, column=2, padx=4, pady=3)
        self.analysis_filter_box = ttk.Combobox(
            filter_bar, textvariable=self.analysis_filter,
            values=["All analyses", "ba", "fight"], state="readonly", width=12,
        )
        self.analysis_filter_box.grid(row=0, column=3, padx=4, pady=3)
        self.camera_filter_box = ttk.Combobox(
            filter_bar, textvariable=self.camera_filter,
            values=["All cameras"], state="readonly", width=13,
        )
        self.camera_filter_box.grid(row=1, column=0, padx=4, pady=3)
        self.date_filter_box = ttk.Combobox(
            filter_bar, textvariable=self.date_filter,
            values=["All dates"], state="readonly", width=13,
        )
        self.date_filter_box.grid(row=1, column=1, sticky="w", padx=4, pady=3)
        self.act_filter_box = ttk.Combobox(
            filter_bar, textvariable=self.act_filter,
            values=["All ACTs"], state="readonly", width=11,
        )
        self.act_filter_box.grid(row=1, column=2, padx=4, pady=3)
        ttk.Button(
            filter_bar, text="Clear filters", command=self.clear_filters
        ).grid(row=1, column=3, sticky="w", padx=6, pady=3)
        filter_bar.columnconfigure(1, weight=1)
        for variable in (
            self.search_filter,
            self.start_filter,
            self.analysis_filter,
            self.camera_filter,
            self.date_filter,
            self.act_filter,
        ):
            variable.trace_add("write", lambda *_: self.apply_filters())

        start_file_bar = ttk.Frame(sessions_tab)
        start_file_bar.grid(
            row=1, column=0, columnspan=2, sticky="ew", padx=4, pady=(0, 4)
        )
        ttk.Button(
            start_file_bar,
            text="Export sessions needing start times",
            command=self.export_missing_start_report,
        ).grid(row=0, column=0, sticky="w", padx=4, pady=2)
        ttk.Button(
            start_file_bar,
            text="Import completed start-time CSV",
            command=self.import_start_report,
        ).grid(row=0, column=1, sticky="w", padx=4, pady=2)
        ttk.Button(
            start_file_bar,
            text="Explain start statuses",
            command=lambda: messagebox.showinfo(
                "Start-frame review statuses", START_STATUS_HELP
            ),
        ).grid(row=1, column=0, sticky="w", padx=4, pady=2)
        ttk.Button(
            start_file_bar,
            text="Export sessions with no trajectory file",
            command=self.export_missing_trajectory_report,
        ).grid(row=1, column=1, sticky="w", padx=4, pady=2)
        self.process_button = ttk.Button(
            start_file_bar,
            text="Process checked sessions",
            command=self.process,
        )
        self.process_button.grid(
            row=0, column=2, rowspan=2, sticky="nsw", padx=(18, 4), pady=2
        )
        ttk.Label(
            start_file_bar,
            text=(
                "The process button uses every row marked Yes in the "
                "Process? column."
            ),
        ).grid(row=0, column=3, rowspan=2, sticky="w", padx=4, pady=2)
        ttk.Button(
            start_file_bar,
            text="Check all filtered ready sessions",
            command=self.check_all_filtered_ready,
        ).grid(row=2, column=0, sticky="w", padx=4, pady=(4, 2))
        ttk.Button(
            start_file_bar,
            text="Uncheck all sessions",
            command=self.uncheck_all_sessions,
        ).grid(row=2, column=1, sticky="w", padx=4, pady=(4, 2))
        self.jump_audit_button = ttk.Button(
            start_file_bar,
            text="Audit jumps in all approved BA + fights",
            command=self.run_jump_audit,
        )
        self.jump_audit_button.grid(
            row=2, column=2, sticky="w", padx=(18, 4), pady=(4, 2)
        )
        start_file_bar.columnconfigure(3, weight=1)

        columns = (
            "use", "trajectory_status", "status", "start", "video_name", "camera",
            "video_year", "recording_date", "recording_time", "act", "cell_label",
            "analysis", "run_timestamp", "qc_record_id",
        )
        self.table = ttk.Treeview(sessions_tab, columns=columns, show="headings", selectmode="extended")
        labels = {
            "use": "Process?",
            "trajectory_status": "IDtracker trajectory",
            "status": "Start review",
            "start": "Global start",
            "video_name": "Video",
            "camera": "Camera",
            "video_year": "Year",
            "recording_date": "Date",
            "recording_time": "Time",
            "act": "ACT",
            "cell_label": "Cell",
            "analysis": "Analysis",
            "run_timestamp": "Approved run date",
            "qc_record_id": "QC record",
        }
        widths = {
            "use": 70, "trajectory_status": 225, "status": 205,
            "start": 100, "video_name": 330,
            "camera": 70, "video_year": 65,
            "recording_date": 95, "recording_time": 70,
            "act": 70, "cell_label": 70, "analysis": 75,
            "run_timestamp": 150, "qc_record_id": 280,
        }
        for name in columns:
            self.table.heading(
                name,
                text=labels[name],
                command=lambda column=name: self.sort_by(column),
            )
            self.table.column(name, width=widths[name], anchor="w")
        sessions_tab.rowconfigure(2, weight=1)
        sessions_tab.columnconfigure(0, weight=1)
        session_y_scroll = ttk.Scrollbar(
            sessions_tab, orient="vertical", command=self.table.yview
        )
        session_x_scroll = ttk.Scrollbar(
            sessions_tab, orient="horizontal", command=self.table.xview
        )
        self.table.configure(
            yscrollcommand=session_y_scroll.set,
            xscrollcommand=session_x_scroll.set,
        )
        self.table.grid(row=2, column=0, sticky="nsew")
        session_y_scroll.grid(row=2, column=1, sticky="ns")
        session_x_scroll.grid(row=3, column=0, sticky="ew")
        self.table.bind("<Double-1>", self.toggle_or_edit)
        self.table.bind("<<TreeviewSelect>>", self.show_record_details)
        self.details = tk.StringVar(
            value="Select a session to see interval evidence and full Firebird paths."
        )
        ttk.Label(
            sessions_tab,
            textvariable=self.details,
            anchor="w",
            justify="left",
            wraplength=1350,
        ).grid(row=4, column=0, columnspan=2, sticky="ew", padx=6, pady=5)

        audit_controls = ttk.Frame(self.jump_audit_tab)
        audit_controls.pack(fill="x", padx=6, pady=6)
        ttk.Button(
            audit_controls,
            text="Run audit on all approved BA + fights",
            command=self.run_jump_audit,
        ).pack(side="left", padx=4)
        ttk.Button(
            audit_controls,
            text="Approve selected start recommendation",
            command=self.approve_jump_recommendation,
        ).pack(side="left", padx=4)
        ttk.Button(
            audit_controls,
            text="Export audit and decisions",
            command=self.export_jump_audit,
        ).pack(side="left", padx=4)
        self.jump_audit_status = tk.StringVar(
            value=(
                "Run the read-only audit after scanning. No start changes are "
                "made until you approve a video recommendation."
            )
        )
        ttk.Label(
            self.jump_audit_tab,
            textvariable=self.jump_audit_status,
            anchor="w",
            justify="left",
            wraplength=1320,
        ).pack(fill="x", padx=10, pady=(0, 6))
        audit_table_frame = ttk.Frame(self.jump_audit_tab)
        audit_table_frame.pack(fill="both", expand=True, padx=6, pady=(0, 6))
        audit_columns = (
            "decision",
            "audit_status",
            "video",
            "analysis_type",
            "current_starts",
            "suggested_start_global_frame",
            "last_synchronized_disturbance_frame",
            "approved_records",
            "tracks_with_jumps",
            "persistent_jump_tracks",
            "synchronized_disturbance_clusters",
        )
        self.jump_audit_table = ttk.Treeview(
            audit_table_frame,
            columns=audit_columns,
            show="headings",
            selectmode="extended",
        )
        audit_labels = {
            "decision": "Decision",
            "audit_status": "Audit result",
            "video": "Video",
            "analysis_type": "Type",
            "current_starts": "Current start(s)",
            "suggested_start_global_frame": "Suggested start",
            "last_synchronized_disturbance_frame": "Last disturbance",
            "approved_records": "Approved sessions",
            "tracks_with_jumps": "Tracks with jumps",
            "persistent_jump_tracks": "Persistent tracks",
            "synchronized_disturbance_clusters": "Video-wide events",
        }
        audit_widths = {
            "decision": 105,
            "audit_status": 310,
            "video": 390,
            "analysis_type": 75,
            "current_starts": 115,
            "suggested_start_global_frame": 115,
            "last_synchronized_disturbance_frame": 115,
            "approved_records": 105,
            "tracks_with_jumps": 105,
            "persistent_jump_tracks": 105,
            "synchronized_disturbance_clusters": 105,
        }
        for column in audit_columns:
            self.jump_audit_table.heading(
                column, text=audit_labels[column]
            )
            self.jump_audit_table.column(
                column, width=audit_widths[column], anchor="w"
            )
        audit_y = ttk.Scrollbar(
            audit_table_frame,
            orient="vertical",
            command=self.jump_audit_table.yview,
        )
        audit_x = ttk.Scrollbar(
            audit_table_frame,
            orient="horizontal",
            command=self.jump_audit_table.xview,
        )
        self.jump_audit_table.configure(
            yscrollcommand=audit_y.set,
            xscrollcommand=audit_x.set,
        )
        self.jump_audit_table.grid(row=0, column=0, sticky="nsew")
        audit_y.grid(row=0, column=1, sticky="ns")
        audit_x.grid(row=1, column=0, sticky="ew")
        audit_table_frame.rowconfigure(0, weight=1)
        audit_table_frame.columnconfigure(0, weight=1)

        diagnostic_buttons = ttk.Frame(logs_tab)
        diagnostic_buttons.pack(fill="x", padx=6, pady=6)
        ttk.Button(
            diagnostic_buttons, text="Run connection diagnostics",
            command=self.run_diagnostics,
        ).pack(side="left", padx=4)
        ttk.Button(
            diagnostic_buttons, text="Clear log",
            command=lambda: self.log_text.delete("1.0", "end"),
        ).pack(side="left", padx=4)
        ttk.Button(
            diagnostic_buttons, text="Copy log",
            command=self.copy_log,
        ).pack(side="left", padx=4)
        self.log_text = tk.Text(logs_tab, wrap="none", state="normal")
        log_scroll = ttk.Scrollbar(logs_tab, command=self.log_text.yview)
        log_x_scroll = ttk.Scrollbar(
            logs_tab, orient="horizontal", command=self.log_text.xview
        )
        self.log_text.configure(
            yscrollcommand=log_scroll.set,
            xscrollcommand=log_x_scroll.set,
        )
        log_scroll.pack(side="right", fill="y")
        log_x_scroll.pack(side="bottom", fill="x", padx=6)
        self.log_text.pack(fill="both", expand=True, padx=(6, 0), pady=(0, 6))
        self._append_log(
            "Ready. The log reports each SSH phase. Scanning and diagnostics do not modify Firebird."
        )

        self.status = tk.StringVar(value="Ready. Scanning does not modify Firebird.")
        ttk.Label(self, textvariable=self.status).pack(fill="x", padx=10, pady=6)

    def ssh(self):
        return SSH(self.host.get().strip(), self.key.get().strip())

    def _background(self, function):
        threading.Thread(target=lambda: self._run_guarded(function), daemon=True).start()

    def _run_guarded(self, function):
        try:
            function()
        except Exception as exc:
            self.work.put(("log", f"ERROR: {exc}"))
            self.work.put(("error", str(exc)))

    def log(self, message):
        self.work.put(("log", str(message)))

    def _append_log(self, message):
        timestamp = datetime.now().strftime("%H:%M:%S")
        self.log_text.insert("end", f"[{timestamp}] {message}\n")
        self.log_text.see("end")

    def _poll(self):
        try:
            while True:
                kind, payload = self.work.get_nowait()
                if kind == "error":
                    messagebox.showerror("Operation stopped", payload)
                    self.status.set("Stopped with an error; no result was silently accepted.")
                elif kind == "status":
                    self.status.set(payload)
                elif kind == "scan":
                    self.load_scan(payload)
                elif kind == "jump_audit_result":
                    self.load_jump_audit(payload)
                elif kind == "log":
                    self._append_log(payload)
                elif kind == "show_logs":
                    self.notebook.select(self.logs_tab)
                elif kind == "scan_done":
                    self.scan_running = False
                    self.scan_button.configure(state="normal")
                elif kind == "jump_audit_done":
                    self.jump_audit_running = False
                    self.jump_audit_button.configure(state="normal")
                elif kind == "processing_done":
                    self.processing_running = False
                    self.process_button.configure(state="normal")
                    self.download_button.configure(state="normal")
                    self.plot_download_button.configure(state="normal")
                elif kind == "processing_complete":
                    self._completion_alert(payload)
                elif kind == "combined_ready":
                    self.last_combined_remote = payload
                    self.download_button.configure(state="normal")
                elif kind == "plots_ready":
                    self.last_plot_remote = payload
                    self.plot_download_button.configure(state="normal")
                    self.results_status.set(
                        "The matching CSV and PDF folder from this completed run "
                        "are ready to download."
                    )
                    self.auto_download_latest_run()
                elif kind == "processing_results_failed":
                    self.results_status.set(
                        "This run stopped before replacing the complete result "
                        "batch. The buttons can still locate the previous run."
                    )
                elif kind == "auto_download_complete":
                    self.results_status.set(
                        f"CSV and PDF folder automatically saved on this Mac: "
                        f"{payload}"
                    )
                elif kind == "prompt_plot_download":
                    self.last_plot_remote = payload
                    self._prompt_plot_folder(payload)
                elif kind == "plot_download_done":
                    self.plot_download_button.configure(state="normal")
                elif kind == "prompt_download":
                    self.last_combined_remote = payload
                    self.download_button.configure(state="normal")
                    self._prompt_combined_download(payload)
                elif kind == "download_lookup_done":
                    self.download_button.configure(state="normal")
        except queue.Empty:
            pass
        self.after(100, self._poll)

    def _completion_alert(self, payload):
        """Give an audible and visible alert only after a complete promotion."""
        try:
            if sys.platform == "darwin":
                sound = Path("/System/Library/Sounds/Glass.aiff")
                if sound.is_file():
                    subprocess.Popen(
                        ["afplay", str(sound)],
                        stdout=subprocess.DEVNULL,
                        stderr=subprocess.DEVNULL,
                    )
                else:
                    self.bell()
            else:
                self.bell()
        except Exception:
            self.bell()
        messagebox.showinfo(
            "Processing complete",
            (
                f"Everything is done.\n\n"
                f"Processed: {payload['processed']} ready session(s)\n"
                f"Skipped: {payload['skipped']} session(s)\n"
                f"Script version: {payload['script_version']}\n\n"
                "The complete combined CSV and matching PDF folder are ready "
                "to download."
            ),
        )

    def test_ssh(self):
        def action():
            self.log("Testing SSH connection...")
            host = self.ssh().run("hostname").strip()
            self.log(f"SSH connection succeeded: {host}")
            self.work.put(("status", "Connected: " + host))
        self._background(action)

    def copy_log(self):
        self.clipboard_clear()
        self.clipboard_append(self.log_text.get("1.0", "end-1c"))
        self.status.set("Diagnostic log copied to the clipboard.")

    def run_diagnostics(self):
        entered_root = self.roots.get().strip()

        def action():
            self.log("Starting read-only connection diagnostics.")
            remote_home = self.ssh().run('printf "%s" "$HOME"').strip()
            project_root = expand_remote_path(entered_root, remote_home).rstrip("/")
            qc_path = project_root + "/QC/run_status.csv"
            remote_python = expand_remote_path(self.remote_python.get(), remote_home)
            pipeline_python = (
                remote_home.rstrip("/")
                + "/miniconda3/envs/beetle_pipeline/bin/python"
            )
            prototype_python = (
                remote_home.rstrip("/")
                + "/miniconda3/envs/idtracker_reprocess_v1/bin/python"
            )
            command = (
                "printf 'hostname='; hostname; "
                "printf 'user='; whoami; "
                f"if [[ -r {shlex.quote(qc_path)} ]]; then "
                f"printf 'qc_file=readable\\n'; wc -l < {shlex.quote(qc_path)} | "
                "awk '{print \"qc_lines=\" $1}'; "
                f"stat -c 'qc_bytes=%s qc_modified=%y' {shlex.quote(qc_path)} 2>/dev/null || "
                f"stat -f 'qc_bytes=%z qc_modified=%Sm' {shlex.quote(qc_path)}; "
                "else printf 'qc_file=MISSING_OR_UNREADABLE\\n'; fi; "
                + "for candidate in "
                + " ".join(
                    shlex.quote(path)
                    for path in dict.fromkeys(
                        [remote_python, prototype_python, pipeline_python]
                    )
                )
                + "; do "
                + "if [[ -x \"$candidate\" ]]; then "
                + "\"$candidate\" -c "
                + shlex.quote(
                    "import sys,numpy,h5py; "
                    "print('usable_python='+sys.executable); "
                    "print('numpy='+numpy.__version__+' h5py='+h5py.__version__)"
                )
                + " 2>&1 || printf 'python_missing_dependency=%s\\n' \"$candidate\"; "
                + "else printf 'python_missing=%s\\n' \"$candidate\"; fi; done"
            )
            output = self.ssh().run(command, timeout=120)
            for line in output.splitlines():
                self.log(line)
            self.log("Diagnostics completed.")
            self.work.put(("status", "Diagnostics completed; see Logs & Diagnostics."))
            self.work.put(("show_logs", None))

        self._background(action)

    def scan(self):
        if self.scan_running:
            self.notebook.select(self.logs_tab)
            self.status.set("A scan is already running; see Logs & Diagnostics.")
            return
        entered_root = self.roots.get().strip()
        if not entered_root:
            messagebox.showwarning(
                "Pipeline project root required",
                "Enter the Firebird pipeline project root containing QC/run_status.csv.",
            )
            return

        def action():
            started = datetime.now()
            self.log("Scan started.")
            self.work.put(("show_logs", None))
            self.log(f"Configured project root: {entered_root}")
            remote_home = self.ssh().run('printf "%s" "$HOME"').strip()
            project_root = expand_remote_path(entered_root, remote_home).rstrip("/")
            qc_path = project_root + "/QC/run_status.csv"
            self.log(f"Authoritative QC file: {qc_path}")
            self.work.put(("status", "Reading authoritative QC approvals and selecting newest approved records..."))
            qc_text = self.ssh().run(
                f"test -f {shlex.quote(qc_path)} || "
                f"{{ echo {shlex.quote('Authoritative QC file is missing: ' + qc_path)} >&2; exit 1; }}; "
                f"cat -- {shlex.quote(qc_path)}",
                timeout=900,
            )
            self.log(f"QC file read completed: {len(qc_text):,} characters.")
            candidates = []
            qc_rows = list(csv.DictReader(io.StringIO(qc_text)))
            self.log(f"QC rows parsed: {len(qc_rows):,}.")
            skipped_missing_identity = 0
            for qc_row in qc_rows:
                decision = str(qc_row.get("qc_decision") or "").strip().upper()
                if decision not in {"APPROVED", "DONE"}:
                    continue
                run_dir = str(qc_row.get("run_dir") or "").strip()
                if not run_dir:
                    continue
                metadata_path = run_dir.rstrip("/") + "/run_metadata.json"
                video = str(qc_row.get("video") or "")
                cell = str(qc_row.get("cell") or "").strip()
                analysis = str(qc_row.get("analysis") or "").strip().lower()
                if not video or not cell:
                    skipped_missing_identity += 1
                    continue
                candidates.append(
                    {
                        "metadata_path": metadata_path,
                        "video": video,
                        "cell": cell,
                        "analysis": analysis,
                        "run_dir": run_dir,
                        "run_index": int(qc_row.get("run_index") or -1),
                        "run_timestamp": str(
                            qc_row.get("date_run")
                            or qc_row.get("collected_at")
                            or ""
                        ),
                        "record_id": str(qc_row.get("record_id") or ""),
                        "qc_decision": "APPROVED",
                    }
                )
            self.log(
                f"Approved QC rows eligible before deduplication: {len(candidates):,}; "
                f"approved rows missing video/cell: {skipped_missing_identity:,}."
            )

            newest = {}
            for candidate in candidates:
                cell_key = (
                    candidate["video"],
                    candidate["cell"],
                    candidate["analysis"],
                )
                rank = (
                    candidate["run_timestamp"],
                    candidate["run_index"],
                    candidate["metadata_path"],
                )
                if cell_key not in newest or rank > newest[cell_key][0]:
                    newest[cell_key] = (rank, candidate)
            self.log(
                f"Newest approved video/cell/analysis records after deduplication: {len(newest):,}."
            )

            records = []
            selected = sorted(
                newest.values(),
                key=lambda item: (item[1]["video"], item[1]["cell"]),
            )
            self.log(
                f"Resolving {len(selected):,} canonical session links in one batched SSH call."
            )
            resolver_input = [
                {
                    "run_dir": candidate["run_dir"],
                    "metadata_path": candidate["metadata_path"],
                }
                for _, candidate in selected
            ]
            resolver_output = self.ssh().run(
                "python3 -c " + shlex.quote(BATCH_SESSION_RESOLVER),
                input_text=json.dumps(resolver_input),
                timeout=1800,
            )
            resolved_items = json.loads(resolver_output)
            if len(resolved_items) != len(selected):
                raise RuntimeError(
                    "Canonical-session resolver returned a different record count: "
                    f"{len(resolved_items)} versus {len(selected)}"
                )
            self.log("Canonical session-link batch completed.")

            blocked_trajectory_count = 0
            for position, ((_, candidate), resolved) in enumerate(
                zip(selected, resolved_items), 1
            ):
                if position == 1 or position % 100 == 0 or position == len(selected):
                    message = f"Interpreting resolved sessions: {position:,} of {len(selected):,}."
                    self.log(message)
                    self.work.put(("status", message))
                run_dir = candidate["run_dir"]
                metadata = resolved.get("metadata") or {}
                candidate["source_toml"] = str(resolved.get("source_toml") or "")
                trajectory = str(resolved.get("trajectory") or "")
                trajectory_status = str(
                    resolved.get("trajectory_resolution_status")
                    or "NO_TRAJECTORY"
                )
                trajectory_diagnostic = trajectory_status
                raw_trajectory_candidates = list(
                    resolved.get("raw_trajectory_candidates") or []
                )
                session = str(resolved.get("session") or "")
                if not session:
                    self.log(
                        f"WARNING: canonical session link is missing for QC "
                        f"{candidate['record_id']} under {run_dir}"
                    )
                    continue
                if not trajectory:
                    blocked_trajectory_count += 1
                    self.log(
                        f"BLOCKED: {trajectory_status} in canonical session "
                        f"{session} for QC {candidate['record_id']}. "
                        "No recognized validated, without-gaps, or raw "
                        "IDtracker trajectory is available."
                    )
                elif trajectory_status.startswith("IDTRACKER_RAW_"):
                    self.log(
                        f"RAW FALLBACK: {trajectory_status} selected for QC "
                        f"{candidate['record_id']} at {trajectory}. Missing "
                        "coordinates will be preserved and reported."
                    )
                session_json = resolved.get("session_json") or {}
                pairs = []
                toml_raw = str(resolved.get("source_toml_text") or "")
                if toml_raw:
                    try:
                        pairs.extend(
                            find_interval_candidates(
                                parse_toml(toml_raw), "source_toml"
                            )
                        )
                    except Exception as exc:
                        self.log(
                            f"WARNING: source TOML interval could not be read for "
                            f"QC {candidate['record_id']}: {exc}"
                        )
                pairs.extend(find_interval_candidates(session_json))
                starts = sorted(set(pair[0] for pair in pairs))
                if len(starts) == 1:
                    detected = starts[0]
                    source = "; ".join(sorted(set(p[2] for p in pairs if p[0] == detected)))
                    status = "START_ZERO — correction required" if detected == 0 else "REVIEW DETECTED START"
                    approved = "" if detected == 0 else str(detected)
                elif not starts:
                    detected, source, approved = "", "", ""
                    status = "NO INTERVAL — entry required"
                else:
                    detected, source, approved = ",".join(map(str, starts)), "conflicting interval fields", ""
                    status = "AMBIGUOUS — entry required"
                if normalized_video_name(candidate["video"]) in KNOWN_START_REVIEW_STEMS:
                    approved = ""
                    status = "KNOWN MANUAL START REVIEW — entry required"
                video_fields = parse_video_fields(candidate["video"])
                if not video_fields["video_year"]:
                    self.log(
                        "WARNING: video_year left blank because no recognized "
                        "2025 or 2026 recording date could be parsed from "
                        f"{candidate['video']}"
                    )
                records.append(
                    {"session": session, "trajectory": trajectory, "detected": detected,
                     "source": source, "start": approved, "status": status, "use": "No",
                     "archived_original_start": approved,
                     "start_decision_source": (
                         "SOURCE_INTERVAL" if approved else ""
                     ),
                     "start_decision_provenance": (
                         f"Detected from {source}" if approved else ""
                     ),
                     "trajectory_status": trajectory_status,
                     "trajectory_diagnostic": trajectory_diagnostic,
                     "raw_trajectory_candidates": raw_trajectory_candidates,
                     "processable": bool(trajectory),
                     "video": candidate["video"],
                     "cell_label": candidate["cell"],
                     "analysis": candidate["analysis"],
                     "qc_record_id": candidate["record_id"],
                     "cell": f"{PurePosixPath(candidate['video']).name} / {candidate['cell']}",
                     "run": (
                         f"{candidate['run_timestamp']} (#{candidate['run_index']}; "
                         f"QC {candidate['record_id']})"
                     ),
                     "toml": candidate["source_toml"],
                     "selection_reason": (
                         "Newest date_run, then run_index, among authoritative QC "
                         f"records marked APPROVED for video/cell/analysis ({candidate['analysis']})"
                     ),
                     **video_fields,
                 }
                )
                if not trajectory:
                    records[-1]["trajectory_status"] = "NO_USABLE_TRAJECTORY"
            self.work.put(("scan", records))
            elapsed = (datetime.now() - started).total_seconds()
            self.log(
                f"Scan completed: {len(records):,} sessions resolved in "
                f"{elapsed:.1f} seconds; {blocked_trajectory_count:,} blocked "
                "because no recognized IDtracker trajectory file was available. "
                "Raw files were selected when no gap-filled file existed."
            )

        self.scan_running = True
        self.scan_button.configure(state="disabled")

        def guarded_scan():
            try:
                action()
            finally:
                self.work.put(("scan_done", None))

        self._background(guarded_scan)

    def load_scan(self, records):
        self.all_records = list(records)
        restored_message = ""
        if self.loaded_start_decisions:
            try:
                restored, unmatched = self._apply_loaded_start_decisions(
                    self.loaded_start_decisions,
                    self.loaded_settings_source,
                )
                restored_message = (
                    f" Restored {restored} saved start decision(s); "
                    f"{len(unmatched)} saved decision(s) did not match the "
                    "current approved-session scan."
                )
                self.log(restored_message.strip())
                for item in unmatched:
                    self.log(f"UNMATCHED SAVED START: {item}")
            except Exception as exc:
                self.log(
                    "ERROR: saved start decisions were not applied after scan: "
                    f"{exc}"
                )
                messagebox.showerror(
                    "Saved starts not applied",
                    "The approved-session scan succeeded, but no saved start "
                    "decision was applied because validation failed.\n\n"
                    + str(exc),
                )
        self.camera_filter_box.configure(
            values=["All cameras"]
            + sorted({r["camera"] for r in records if r["camera"]})
        )
        self.date_filter_box.configure(
            values=["All dates"]
            + sorted({r["recording_date"] for r in records if r["recording_date"]})
        )
        self.act_filter_box.configure(
            values=["All ACTs"]
            + sorted({r["act"] for r in records if r["act"]})
        )
        self.apply_filters()
        self.notebook.select(self.sessions_tab)
        zero_or_missing = sum(
            not str(record["start"]).strip() for record in records
        )
        blocked = sum(not record.get("processable") for record in records)
        known = sum(
            record["status"].startswith("KNOWN MANUAL") for record in records
        )
        ready = sum(
            bool(str(record["start"]).strip()) and record.get("processable")
            for record in records
        )
        self.status.set(
            f"Newest approved cell runs: {len(records)} total; {ready} are ready "
            f"to process; {zero_or_missing} require a start; {blocked} lack a "
            "recognized IDtracker trajectory of any supported type; "
            f"{known} match the collaborator list. Older repeats were excluded."
            + restored_message
        )

    def _settings_folder(self):
        downloads = Path.home() / "Downloads"
        base = downloads if downloads.is_dir() else Path.home()
        return (
            base
            / "IDtracker_postprocessing_results"
            / "saved_settings"
        )

    def _gui_settings_values(self):
        return {
            key: getattr(self, key).get()
            for key in GUI_SETTINGS_KEYS
        }

    def _apply_gui_settings(self, settings):
        for key, value in settings.items():
            variable = getattr(self, key)
            if key == "use_social_disappearance":
                variable.set(bool(value))
            else:
                variable.set(str(value))

    def _apply_loaded_start_decisions(self, decisions, source_name):
        """Atomically match and apply saved decisions to the current scan."""
        if not self.all_records:
            return 0, [
                decision.get("qc_record_id")
                or decision.get("video")
                or "unnamed decision"
                for decision in decisions
            ]
        by_id = {
            str(record.get("qc_record_id") or "").strip(): record
            for record in self.all_records
            if str(record.get("qc_record_id") or "").strip()
        }
        by_stable_key = {}
        for record in self.all_records:
            key = (
                normalized_video_name(record.get("video", "")),
                str(record.get("cell_label") or "").strip(),
                str(record.get("analysis") or "").strip().lower(),
            )
            by_stable_key.setdefault(key, []).append(record)

        planned = {}
        unmatched = []
        for decision in decisions:
            scope = decision["scope"]
            targets = []
            if scope == "VIDEO":
                video_key = normalized_video_name(decision["video"])
                analysis = str(decision.get("analysis") or "").lower()
                targets = [
                    record
                    for record in self.all_records
                    if normalized_video_name(record.get("video", ""))
                    == video_key
                    and (
                        not analysis
                        or str(record.get("analysis") or "").lower()
                        == analysis
                    )
                ]
            else:
                record_id = decision.get("qc_record_id", "")
                if record_id and record_id in by_id:
                    target = by_id[record_id]
                    expected_video = normalized_video_name(
                        decision.get("video", "")
                    )
                    expected_cell = str(
                        decision.get("cell_label") or ""
                    ).strip()
                    expected_analysis = str(
                        decision.get("analysis") or ""
                    ).strip().lower()
                    if (
                        expected_video
                        and normalized_video_name(target.get("video", ""))
                        != expected_video
                    ):
                        raise ValueError(
                            f"QC record {record_id} now points to a different "
                            "video; settings load was rejected"
                        )
                    if (
                        expected_cell
                        and str(target.get("cell_label") or "").strip()
                        != expected_cell
                    ):
                        raise ValueError(
                            f"QC record {record_id} now points to a different "
                            "cell; settings load was rejected"
                        )
                    if (
                        expected_analysis
                        and str(target.get("analysis") or "").strip().lower()
                        != expected_analysis
                    ):
                        raise ValueError(
                            f"QC record {record_id} now points to a different "
                            "analysis type; settings load was rejected"
                        )
                    targets = [target]
                else:
                    stable_key = (
                        normalized_video_name(decision.get("video", "")),
                        str(decision.get("cell_label") or "").strip(),
                        str(decision.get("analysis") or "").strip().lower(),
                    )
                    candidates = by_stable_key.get(stable_key, [])
                    if len(candidates) > 1:
                        raise ValueError(
                            "Saved stable key matches more than one current "
                            f"session: {stable_key}"
                        )
                    targets = candidates
            if not targets:
                unmatched.append(
                    decision.get("qc_record_id")
                    or (
                        f"{decision.get('video')} / "
                        f"{decision.get('cell_label') or 'all cells'}"
                    )
                )
                continue
            for target in targets:
                target_id = id(target)
                previous = planned.get(target_id)
                if (
                    previous
                    and previous["start_global_frame"]
                    != decision["start_global_frame"]
                ):
                    raise ValueError(
                        "Conflicting saved starts target current QC record "
                        f"{target.get('qc_record_id')}"
                    )
                planned[target_id] = {
                    "record": target,
                    **decision,
                }

        restored_at = datetime.now().astimezone().isoformat(
            timespec="seconds"
        )
        for update in planned.values():
            record = update["record"]
            current_start = record.get("start", "")
            archived = str(
                update.get("archived_original_start_frame") or ""
            ).strip()
            if not archived:
                archived = str(
                    record.get("archived_original_start") or current_start
                )
            provenance = str(
                update.get("decision_provenance") or ""
            ).strip()
            restoration = (
                f"Restored {restored_at} from {Path(source_name).name}"
            )
            record["archived_original_start"] = archived
            record["start"] = str(update["start_global_frame"])
            record["status"] = (
                update.get("status")
                or (
                    "START APPROVED FROM JUMP AUDIT"
                    if update.get("decision_source")
                    == "JUMP_AUDIT_APPROVED"
                    else "START MANUALLY APPROVED"
                )
            )
            record["start_decision_source"] = (
                update.get("decision_source")
                or "RESTORED_PREVIOUS_SETTINGS"
            )
            record["start_decision_provenance"] = (
                f"{provenance}; {restoration}"
                if provenance
                else restoration
            )
        return len(planned), unmatched

    def save_current_settings(self):
        folder = self._settings_folder()
        folder.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        destination_text = filedialog.asksaveasfilename(
            title="Save reusable post-processing settings",
            initialdir=str(folder),
            initialfile=f"postprocessing_settings_{stamp}.json",
            defaultextension=".json",
            filetypes=[("JSON settings", "*.json")],
            confirmoverwrite=True,
        )
        if not destination_text:
            return
        destination = Path(destination_text)
        payload = validate_settings_bundle(
            {
                "format": SETTINGS_FORMAT,
                "schema_version": SETTINGS_SCHEMA_VERSION,
                "saved_at": datetime.now().astimezone().isoformat(
                    timespec="seconds"
                ),
                "script_version": SCRIPT_VERSION,
                "gui_settings": self._gui_settings_values(),
                "start_decisions": saved_start_decisions(
                    self.all_records
                ),
                "jump_audit": {
                    "timestamp": self.jump_audit_timestamp,
                    "summaries": self.jump_audit_summaries,
                    "tracks": self.jump_audit_tracks,
                },
            }
        )
        temporary = destination.with_name(destination.name + ".partial")
        if temporary.exists():
            messagebox.showerror(
                "Partial settings file exists",
                f"Refusing to overwrite:\n{temporary}",
            )
            return
        try:
            with temporary.open("x", encoding="utf-8") as stream:
                json.dump(payload, stream, indent=2, sort_keys=True)
                stream.write("\n")
            temporary.replace(destination)
        except Exception:
            if temporary.exists():
                temporary.unlink()
            raise
        self.saved_settings_status.set(
            f"Saved {len(payload['start_decisions'])} start decision(s): "
            f"{destination.name}"
        )
        self.log(
            f"Saved reusable settings, {len(payload['start_decisions'])} "
            f"start decision(s), and {len(self.jump_audit_summaries)} "
            f"jump-audit video row(s) to {destination}"
        )
        messagebox.showinfo(
            "Settings saved",
            f"Saved reusable settings and decisions:\n\n{destination}",
        )

    @staticmethod
    def _read_csv_rows(path):
        with path.open(newline="", encoding="utf-8-sig") as stream:
            return list(csv.DictReader(stream))

    def load_previous_settings(self):
        folder = self._settings_folder()
        initial = folder if folder.is_dir() else folder.parent
        source_text = filedialog.askopenfilename(
            title="Load previous settings, results, or Jump Audit",
            initialdir=str(initial),
            filetypes=[
                ("Reusable settings or CSV", "*.json *.csv"),
                ("JSON settings", "*.json"),
                ("CSV files", "*.csv"),
                ("All files", "*"),
            ],
        )
        if not source_text:
            return
        source = Path(source_text)
        try:
            supplement_existing = False
            if source.suffix.lower() == ".json":
                bundle = validate_settings_bundle(
                    json.loads(source.read_text(encoding="utf-8"))
                )
            elif source.suffix.lower() == ".csv":
                rows = self._read_csv_rows(source)
                fields = set(rows[0]) if rows else set()
                if {
                    "analysis_start_frame",
                    "qc_record_id",
                    "script_version",
                }.issubset(fields):
                    bundle = settings_bundle_from_combined_rows(
                        rows, source.name
                    )
                elif {
                    "audit_version",
                    "suggested_start_global_frame",
                    "decision",
                }.issubset(fields):
                    supplement_existing = True
                    tracks = []
                    if source.name.endswith("_videos.csv"):
                        tracks_path = source.with_name(
                            source.name.replace(
                                "_videos.csv", "_tracks.csv"
                            )
                        )
                        if tracks_path.is_file():
                            tracks = self._read_csv_rows(tracks_path)
                    bundle = settings_bundle_from_jump_audit_rows(
                        rows, tracks, source.name
                    )
                else:
                    raise ValueError(
                        "CSV is neither a combined-results file nor a Jump "
                        "Audit video-summary file"
                    )
            else:
                raise ValueError("Choose a .json or .csv settings source")

            decisions = bundle["start_decisions"]
            if self.all_records:
                restored, unmatched = self._apply_loaded_start_decisions(
                    decisions, str(source)
                )
            else:
                restored, unmatched = 0, []
            self._apply_gui_settings(bundle["gui_settings"])
            if supplement_existing and self.loaded_start_decisions:
                self.loaded_start_decisions = (
                    list(self.loaded_start_decisions) + decisions
                )
                self.loaded_settings_source = (
                    self.loaded_settings_source + " + " + str(source)
                )
            else:
                self.loaded_start_decisions = decisions
                self.loaded_settings_source = str(source)
            audit = bundle.get("jump_audit") or {}
            summaries = list(audit.get("summaries") or [])
            tracks = list(audit.get("tracks") or [])
            if summaries:
                self.jump_audit_summaries = summaries
                self.jump_audit_tracks = tracks
                self.jump_audit_timestamp = (
                    str(audit.get("timestamp") or "").strip()
                    or datetime.fromtimestamp(
                        source.stat().st_mtime
                    ).strftime("%Y%m%d_%H%M%S")
                )
                self._render_jump_audit()
                self.jump_audit_status.set(
                    f"Loaded previous Jump Audit from {source.name}: "
                    f"{len(summaries)} video row(s), "
                    f"{sum(str(row.get('decision')).upper() == 'APPROVED' for row in summaries)} "
                    "approved decision(s). No new Firebird audit was run."
                )
            self.apply_filters()
        except Exception as exc:
            messagebox.showerror(
                "Previous settings rejected",
                "No settings or start decisions were changed.\n\n"
                + str(exc),
            )
            return

        if not self.all_records and decisions:
            decision_message = (
                f"{len(self.loaded_start_decisions)} start decision(s) are "
                "queued and will be "
                "matched after Scan approved runs."
            )
        else:
            decision_message = (
                f"Restored {restored} current start decision(s); "
                f"{len(unmatched)} did not match."
            )
        self.saved_settings_status.set(
            f"Loaded {source.name}; jump threshold "
            f"{self.one_frame_jump.get()} px. {decision_message}"
        )
        self.log(
            f"Loaded previous settings from {source}; {decision_message}"
        )
        for item in unmatched:
            self.log(f"UNMATCHED SAVED START: {item}")
        messagebox.showinfo(
            "Previous settings loaded",
            f"Loaded:\n{source}\n\n{decision_message}\n\n"
            f"Current jump threshold: {self.one_frame_jump.get()} px.\n"
            "Review the visible settings before processing.",
        )

    def clear_filters(self):
        self.search_filter.set("")
        self.start_filter.set("All start statuses")
        self.analysis_filter.set("All analyses")
        self.camera_filter.set("All cameras")
        self.date_filter.set("All dates")
        self.act_filter.set("All ACTs")

    def export_missing_start_report(self):
        rows = make_missing_start_report(self.all_records)
        if not rows:
            messagebox.showinfo(
                "No missing starts",
                "Every currently scanned approved session has a positive start.",
            )
            return
        destination_text = filedialog.asksaveasfilename(
            title="Save editable missing-start report",
            initialdir=str(
                (Path.home() / "Downloads")
                if (Path.home() / "Downloads").is_dir()
                else Path.home()
            ),
            initialfile=(
                "sessions_needing_start_times_"
                + datetime.now().strftime("%Y%m%d_%H%M%S")
                + ".csv"
            ),
            defaultextension=".csv",
            filetypes=[("CSV files", "*.csv")],
            confirmoverwrite=True,
        )
        if not destination_text:
            return
        destination = Path(destination_text)
        temporary = destination.with_name(destination.name + ".partial")
        if temporary.exists():
            messagebox.showerror(
                "Partial file exists",
                f"Refusing to overwrite existing partial file:\n{temporary}",
            )
            return
        try:
            with temporary.open("x", newline="", encoding="utf-8") as stream:
                writer = csv.DictWriter(stream, fieldnames=START_REPORT_FIELDS)
                writer.writeheader()
                writer.writerows(rows)
            temporary.replace(destination)
        except Exception:
            if temporary.exists():
                temporary.unlink()
            raise
        self.log(
            f"Exported {len(rows)} sessions needing start times to {destination}"
        )
        self.status.set(
            f"Exported {len(rows)} sessions needing start times."
        )
        messagebox.showinfo(
            "Start-time report created",
            f"Created {len(rows)} editable rows:\n\n{destination}\n\n"
            "Fill only enter_start_global_frame with positive global-frame integers. "
            "You can import it in this GUI or attach it to our Codex conversation.",
        )

    def export_missing_trajectory_report(self):
        rows = make_missing_trajectory_report(self.all_records)
        if not rows:
            messagebox.showinfo(
                "Every session has a trajectory",
                "Every scanned approved session has a recognized validated, "
                "without-gaps, or raw IDtracker trajectory.",
            )
            return
        destination_text = filedialog.asksaveasfilename(
            title="Save sessions with no usable trajectory file",
            initialdir=str(
                (Path.home() / "Downloads")
                if (Path.home() / "Downloads").is_dir()
                else Path.home()
            ),
            initialfile=(
                "sessions_with_no_usable_trajectory_"
                + datetime.now().strftime("%Y%m%d_%H%M%S")
                + ".csv"
            ),
            defaultextension=".csv",
            filetypes=[("CSV files", "*.csv")],
            confirmoverwrite=True,
        )
        if not destination_text:
            return
        destination = Path(destination_text)
        temporary = destination.with_name(destination.name + ".partial")
        try:
            with temporary.open("x", newline="", encoding="utf-8") as stream:
                writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
                writer.writeheader()
                writer.writerows(rows)
            temporary.replace(destination)
        except Exception:
            if temporary.exists():
                temporary.unlink()
            raise
        self.log(
            f"Exported {len(rows)} session(s) with no usable trajectory "
            f"to {destination}"
        )
        messagebox.showinfo(
            "No-trajectory report created",
            f"Saved {len(rows)} specific session(s) to:\n\n{destination}",
        )

    def import_start_report(self):
        source_text = filedialog.askopenfilename(
            title="Choose completed start-time CSV",
            initialdir=str(
                (Path.home() / "Downloads")
                if (Path.home() / "Downloads").is_dir()
                else Path.home()
            ),
            filetypes=[("CSV files", "*.csv"), ("All files", "*")],
        )
        if not source_text:
            return
        source = Path(source_text)
        try:
            with source.open(newline="", encoding="utf-8-sig") as stream:
                reader = csv.DictReader(stream)
                fields = reader.fieldnames or []
                required = {"qc_record_id", "enter_start_global_frame"}
                missing = sorted(required - set(fields))
                if missing:
                    raise ValueError(
                        "Missing required column(s): " + ", ".join(missing)
                    )
                report_rows = list(reader)
            updates = validate_start_report_updates(
                report_rows, self.all_records
            )
        except Exception as exc:
            messagebox.showerror(
                "Start-time import rejected",
                "No table values were changed.\n\n" + str(exc),
            )
            return
        if not updates:
            messagebox.showinfo(
                "No completed entries",
                "The file contains no filled enter_start_global_frame values.",
            )
            return
        for record, value in updates:
            if not str(record.get("archived_original_start", "")).strip():
                record["archived_original_start"] = record.get(
                    "start", ""
                )
            record["start"] = str(value)
            record["status"] = "START MANUALLY APPROVED"
            record["start_decision_source"] = "MANUAL_CSV_IMPORT"
            record["start_decision_provenance"] = (
                f"Manually imported from {source.name}"
            )
        self.apply_filters()
        self.log(
            f"Imported {len(updates)} manually approved global starts from {source}"
        )
        messagebox.showinfo(
            "Start times imported",
            f"Applied {len(updates)} positive global start values atomically.",
        )

    def run_jump_audit(self):
        if self.jump_audit_running:
            self.notebook.select(self.jump_audit_tab)
            self.status.set("The jump audit is already running.")
            return
        try:
            window = int(self.window_frames.get())
            jump_threshold = float(self.one_frame_jump.get())
            if window <= 0 or jump_threshold <= 0:
                raise ValueError
        except (TypeError, ValueError):
            messagebox.showerror(
                "Invalid jump-audit settings",
                "The analysis span and jump threshold must be positive.",
            )
            return
        auditable = []
        using_detected_start = 0
        for record in self.all_records:
            analysis = str(record.get("analysis") or "").lower()
            audit_start = jump_audit_start_for_record(record)
            if (
                record.get("processable")
                and analysis in {"ba", "fight"}
                and audit_start is not None
            ):
                start_value, start_basis = audit_start
                auditable.append((record, start_value, start_basis))
                if start_basis == "POSITIVE_DETECTED_START_AUDIT_ONLY":
                    using_detected_start += 1
        if not auditable:
            messagebox.showwarning(
                "No auditable BA or fight sessions",
                "Scan approved runs first. The audit needs either a final "
                "positive start or one unambiguous positive detected interval.",
            )
            return

        manifest = {
            "jump_threshold_px": jump_threshold,
            "window_frames": window,
            "records": [
                {
                    "video": record["video"],
                    "analysis": record["analysis"],
                    "cell_label": record["cell_label"],
                    "qc_record_id": record["qc_record_id"],
                    "trajectory": record["trajectory"],
                    "start": start_value,
                    "audit_start_basis": start_basis,
                }
                for record, start_value, start_basis in auditable
            ],
        }

        def action():
            self.log(
                f"Jump audit started for {len(auditable)} approved BA/fight "
                f"session(s) with positive start evidence; "
                f"{using_detected_start} use a positive detected interval for "
                "audit only; "
                f"threshold={jump_threshold:g} px; inclusive span={window}."
            )
            self.work.put(("show_logs", None))
            remote_home = self.ssh().run('printf "%s" "$HOME"').strip()
            remote_python = expand_remote_path(
                self.remote_python.get(), remote_home
            )
            output = self.ssh().run(
                f"{shlex.quote(remote_python)} -c "
                + shlex.quote(JUMP_AUDIT_SCRIPT),
                input_text=json.dumps(manifest),
                timeout=3600,
            )
            result = json.loads(output)
            result["audited_session_count"] = len(auditable)
            result["detected_start_audit_only_count"] = (
                using_detected_start
            )
            result["created_at"] = datetime.now().astimezone().isoformat(
                timespec="seconds"
            )
            self.work.put(("jump_audit_result", result))
            self.log(
                f"Jump audit completed: {len(result['summaries'])} video(s), "
                f"{len(result['tracks'])} IDtracker animal track(s)."
            )

        self.jump_audit_running = True
        self.jump_audit_button.configure(state="disabled")
        self.status.set(
            f"Auditing {len(auditable)} approved BA/fight sessions with "
            "positive start evidence..."
        )

        def guarded():
            try:
                action()
            finally:
                self.work.put(("jump_audit_done", None))

        self._background(guarded)

    def _render_jump_audit(self):
        for item in self.jump_audit_table.get_children():
            self.jump_audit_table.delete(item)
        self.jump_audit_rows.clear()
        columns = self.jump_audit_table["columns"]
        for summary in self.jump_audit_summaries:
            item = self.jump_audit_table.insert(
                "",
                "end",
                values=tuple(summary.get(column, "") for column in columns),
            )
            self.jump_audit_rows[item] = summary

    def load_jump_audit(self, result):
        self.jump_audit_summaries = list(result.get("summaries") or [])
        self.jump_audit_tracks = list(result.get("tracks") or [])
        self.jump_audit_timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        for summary in self.jump_audit_summaries:
            summary["decision"] = (
                "PENDING REVIEW"
                if summary.get("suggested_start_global_frame") != ""
                else "NO START CHANGE"
            )
        self._render_jump_audit()
        recommended = sum(
            bool(summary.get("suggested_start_global_frame"))
            for summary in self.jump_audit_summaries
        )
        path_text = self._write_jump_audit_files()
        self.jump_audit_status.set(
            f"Audited {result.get('audited_session_count', 0)} approved "
            f"BA/fight sessions across {len(self.jump_audit_summaries)} videos; "
            f"{result.get('detected_start_audit_only_count', 0)} session(s) "
            "used detected intervals for audit only. "
            f"{recommended} video(s) have a reviewable start recommendation. "
            "No starts have been changed."
        )
        self.status.set(
            f"Jump audit complete: {recommended} video-level start "
            "recommendation(s); approval is required."
        )
        self.notebook.select(self.jump_audit_tab)
        messagebox.showinfo(
            "Jump audit complete",
            f"Found {recommended} video-level start recommendation(s).\n\n"
            "No start was changed. Select a recommendation and click Approve.\n\n"
            f"Timestamped audit CSV files:\n{path_text}",
        )

    @staticmethod
    def _csv_safe_audit_row(row):
        output = {}
        for key, value in row.items():
            if isinstance(value, (dict, list)):
                output[key] = json.dumps(value, sort_keys=True)
            else:
                output[key] = value
        return output

    def _jump_audit_folder(self):
        downloads = Path.home() / "Downloads"
        base = downloads if downloads.is_dir() else Path.home()
        return (
            base
            / "IDtracker_postprocessing_results"
            / "jump_audits"
        )

    def _write_jump_audit_files(self, folder=None):
        if not self.jump_audit_summaries:
            return ""
        destination = Path(folder) if folder else self._jump_audit_folder()
        destination.mkdir(parents=True, exist_ok=True)
        stamp = self.jump_audit_timestamp or datetime.now().strftime(
            "%Y%m%d_%H%M%S"
        )
        paths = []
        for label, rows in (
            ("videos", self.jump_audit_summaries),
            ("tracks", self.jump_audit_tracks),
        ):
            if not rows:
                continue
            path = destination / f"jump_audit_{stamp}_{label}.csv"
            safe_rows = [self._csv_safe_audit_row(row) for row in rows]
            fields = list(safe_rows[0])
            with path.open("w", newline="", encoding="utf-8") as stream:
                writer = csv.DictWriter(
                    stream, fieldnames=fields, extrasaction="ignore"
                )
                writer.writeheader()
                writer.writerows(safe_rows)
            paths.append(str(path))
        return "\n".join(paths)

    def export_jump_audit(self):
        if not self.jump_audit_summaries:
            messagebox.showinfo(
                "No jump audit",
                "Run the jump audit before exporting.",
            )
            return
        destination = filedialog.askdirectory(
            title="Choose folder for jump-audit CSV files",
            initialdir=str(self._jump_audit_folder()),
            mustexist=False,
        )
        if not destination:
            return
        paths = self._write_jump_audit_files(destination)
        messagebox.showinfo(
            "Jump audit exported",
            f"Saved the video summary and detailed track audit:\n\n{paths}",
        )

    def approve_jump_recommendation(self):
        selected = self.jump_audit_table.selection()
        if not selected:
            messagebox.showinfo(
                "Select a recommendation",
                "Select one or more video rows in the Jump Audit table.",
            )
            return
        summaries = [self.jump_audit_rows[item] for item in selected]
        invalid = [
            summary["video"]
            for summary in summaries
            if summary.get("suggested_start_global_frame") == ""
            or summary.get("suggested_full_window_fits") is not True
        ]
        if invalid:
            messagebox.showerror(
                "Recommendation cannot be approved",
                "These selected videos do not have a complete-window start "
                "recommendation:\n\n" + "\n".join(invalid),
            )
            return
        details = "\n".join(
            f"{summary['video']}: {summary['current_starts']} -> "
            f"{summary['suggested_start_global_frame']}"
            for summary in summaries
        )
        if not messagebox.askyesno(
            "Approve disturbance-adjusted starts",
            "Apply these recommendations to every approved session belonging "
            "to each video?\n\n"
            + details
            + "\n\nThe original starts and audit evidence will remain in "
            "the processed CSV provenance columns.",
        ):
            return
        approved_at = datetime.now().astimezone().isoformat(
            timespec="seconds"
        )
        changed = 0
        for summary in summaries:
            video = summary["video"]
            new_start = int(summary["suggested_start_global_frame"])
            for record in self.all_records:
                if record.get("video") != video:
                    continue
                old_start = str(record.get("start", ""))
                if not str(record.get("archived_original_start", "")).strip():
                    record["archived_original_start"] = old_start
                record["start"] = str(new_start)
                record["status"] = "START APPROVED FROM JUMP AUDIT"
                record["start_decision_source"] = "JUMP_AUDIT_APPROVED"
                record["start_decision_provenance"] = (
                    f"Approved {approved_at}; audit v"
                    f"{summary['audit_version']}; previous start {old_start}; "
                    f"last synchronized disturbance frame "
                    f"{summary['last_synchronized_disturbance_frame']}; "
                    f"jump threshold {summary['jump_threshold_px']} px; "
                    f"approved replacement start {new_start}"
                )
                changed += 1
            summary["decision"] = "APPROVED"
        self._render_jump_audit()
        self.apply_filters()
        self._write_jump_audit_files()
        self.log(
            f"Approved {len(summaries)} video-level jump-audit start "
            f"recommendation(s), updating {changed} approved session row(s)."
        )
        messagebox.showinfo(
            "Start recommendations approved",
            f"Updated {changed} approved session row(s).\n\n"
            "The final start will appear near the front of the results CSV; "
            "the archived original and decision provenance will appear near "
            "the end.",
        )

    def apply_filters(self):
        if not hasattr(self, "table"):
            return
        search = self.search_filter.get().strip().lower()
        start_mode = self.start_filter.get()
        analysis = self.analysis_filter.get()
        camera = self.camera_filter.get()
        date = self.date_filter.get()
        act = self.act_filter.get()
        filtered = []
        for record in self.all_records:
            needs_start = not str(record.get("start", "")).strip()
            if start_mode == "Needs new start" and not needs_start:
                continue
            if (
                start_mode == "Ready to process"
                and (needs_start or not record.get("processable"))
            ):
                continue
            if (
                start_mode == "Manually approved start"
                and record.get("status") != "START MANUALLY APPROVED"
            ):
                continue
            if (
                start_mode == "Jump-audit approved start"
                and record.get("status")
                != "START APPROVED FROM JUMP AUDIT"
            ):
                continue
            if (
                start_mode == "No usable trajectory"
                and record.get("processable")
            ):
                continue
            if analysis != "All analyses" and record.get("analysis") != analysis:
                continue
            if camera != "All cameras" and record.get("camera") != camera:
                continue
            if date != "All dates" and record.get("recording_date") != date:
                continue
            if act != "All ACTs" and record.get("act") != act:
                continue
            searchable = " ".join(
                str(record.get(key, ""))
                for key in (
                    "video_name", "camera", "camera_id", "video_year",
                    "recording_date",
                    "recording_time", "act", "cell_label", "analysis",
                    "trajectory_status", "status", "qc_record_id",
                )
            ).lower()
            if search and search not in searchable:
                continue
            filtered.append(record)
        self.filtered_records = filtered
        self._render_records()
        self.status.set(
            f"Showing {len(filtered)} of {len(self.all_records)} approved sessions."
        )

    def sort_by(self, column):
        if self.sort_column == column:
            self.sort_reverse = not self.sort_reverse
        else:
            self.sort_column = column
            self.sort_reverse = False
        self._render_records()

    def _sort_value(self, record):
        value = record.get(self.sort_column, "")
        if self.sort_column in {
            "start", "camera", "video_year", "recording_date",
            "recording_time"
        }:
            try:
                return (0, int(value))
            except (TypeError, ValueError):
                return (1, 0)
        return (0, str(value).lower())

    def _render_records(self):
        for item in self.table.get_children():
            self.table.delete(item)
        self.rows.clear()
        ordered = sorted(
            self.filtered_records,
            key=self._sort_value,
            reverse=self.sort_reverse,
        )
        value_keys = (
            "use", "trajectory_status", "status", "start", "video_name", "camera",
            "video_year", "recording_date", "recording_time", "act", "cell_label",
            "analysis", "run_timestamp", "qc_record_id",
        )
        for record in ordered:
            item = self.table.insert(
                "", "end", values=tuple(record.get(key, "") for key in value_keys)
            )
            self.rows[item] = record

    def show_record_details(self, _event=None):
        selected = self.table.selection()
        if not selected:
            return
        record = self.rows[selected[0]]
        self.details.set(
            f"Detected start: {record.get('detected') or 'none'} | "
            f"Interval evidence: {record.get('source') or 'none'}\n"
            f"Final start decision: {record.get('start') or 'none'} | "
            f"Decision source: "
            f"{record.get('start_decision_source') or 'none'}\n"
            f"Archived original start: "
            f"{record.get('archived_original_start') or 'none'} | "
            f"Decision provenance: "
            f"{record.get('start_decision_provenance') or 'none'}\n"
            f"Canonical session: {record.get('session')}\n"
            f"IDtracker trajectory status: {record.get('trajectory_status')}\n"
            f"Selected trajectory: "
            f"{record.get('trajectory') or 'none - processing blocked'}\n"
            f"Raw trajectory candidates: "
            f"{record.get('raw_trajectory_candidates') or 'none'}\n"
            f"Source TOML: {record.get('toml') or 'not recorded'}"
        )

    def toggle_or_edit(self, event):
        region = self.table.identify_region(event.x, event.y)
        if region != "cell":
            return
        item = self.table.identify_row(event.y)
        column = self.table.identify_column(event.x)
        if not item:
            return
        if column == "#1":
            if not self.rows[item].get("processable"):
                messagebox.showwarning(
                    "Processing blocked",
                    "This session has no recognized validated, without-gaps, "
                    "or raw IDtracker trajectory file.",
                )
                return
            self.rows[item]["use"] = "No" if self.rows[item]["use"] == "Yes" else "Yes"
            self._refresh(item)
        elif column == "#4":
            self.edit_start()

    def check_all_filtered_ready(self):
        checked = 0
        for record in self.filtered_records:
            try:
                positive_start = int(record.get("start", "")) > 0
            except (TypeError, ValueError):
                positive_start = False
            if record.get("processable") and positive_start:
                record["use"] = "Yes"
                checked += 1
        self._render_records()
        self.status.set(
            f"Checked {checked} filtered ready approved session(s)."
        )

    def uncheck_all_sessions(self):
        for record in self.all_records:
            record["use"] = "No"
        self._render_records()
        self.status.set("Unchecked all approved sessions.")

    def edit_start(self):
        selected = self.table.selection()
        if not selected:
            messagebox.showinfo("Select rows", "Select one or more session rows first.")
            return
        value = simpledialog.askinteger(
            "Approved analysis entry",
            "Enter the analysis-entry GLOBAL frame for the selected session(s).\nZero is not accepted.",
            minvalue=1,
        )
        if value is None:
            return
        selected_records = [self.rows[item] for item in selected]
        for record in selected_records:
            if not str(record.get("archived_original_start", "")).strip():
                record["archived_original_start"] = record.get("start", "")
            record["start"] = str(value)
            record["status"] = "START MANUALLY APPROVED"
            record["start_decision_source"] = "MANUAL_GUI_ENTRY"
            record["start_decision_provenance"] = (
                "Manually entered in the Sessions tab"
            )
        self.apply_filters()

    def _refresh(self, item):
        self.apply_filters()

    def auto_download_latest_run(self):
        """Save the completed matching CSV/PDF batch on the Mac automatically."""
        token = self.current_batch_token
        if (
            not token
            or not self.last_combined_remote
            or not self.last_plot_remote
            or self.auto_download_started_for == token
        ):
            return
        self.auto_download_started_for = token
        remote_csv = self.last_combined_remote
        remote_pdfs = self.last_plot_remote
        paths = automatic_download_paths(token)
        local_root = paths["root"]
        completed_folder = paths["completed_folder"]
        partial_folder = paths["partial_folder"]
        partial_csv = paths["partial_csv"]
        partial_pdfs = paths["partial_pdfs"]

        def action():
            local_root.mkdir(parents=True, exist_ok=True)
            if completed_folder.exists() or partial_folder.exists():
                raise FileExistsError(
                    "Refusing to overwrite an existing automatic download: "
                    f"{completed_folder}"
                )
            try:
                partial_folder.mkdir()
                self.log(
                    f"Automatically staging completed CSV on Mac: "
                    f"{partial_csv}"
                )
                self.ssh().download(
                    remote_csv, str(partial_csv), timeout=900
                )
                self.log(
                    f"Automatically staging completed PDF folder on Mac: "
                    f"{partial_pdfs}"
                )
                self.ssh().download_directory(
                    remote_pdfs, str(partial_pdfs), timeout=1800
                )
                partial_folder.replace(completed_folder)
            except Exception:
                if partial_folder.exists():
                    shutil.rmtree(partial_folder)
                raise
            self.log(
                f"Automatic Mac download completed in one folder: "
                f"{completed_folder}"
            )
            self.work.put(
                ("auto_download_complete", str(completed_folder))
            )
            self.work.put((
                "status",
                f"Completed results saved on Mac in {completed_folder}",
            ))

        self._background(action)

    def download_combined(self):
        if not self.last_combined_remote:
            self.download_button.configure(state="disabled")

            def locate():
                try:
                    remote_home = self.ssh().run(
                        'printf "%s" "$HOME"'
                    ).strip()
                    output_root = expand_remote_path(
                        self.output_root.get(), remote_home
                    ).rstrip("/")
                    latest = (
                        output_root
                        + "/combined_results_latest.csv"
                    )
                    found = self.ssh().run(
                        f"test -f {shlex.quote(latest)} && "
                        f"printf '%s\\n' {shlex.quote(latest)}",
                        timeout=120,
                    ).strip()
                    if not found:
                        raise RuntimeError(
                            "No completed combined result exists under "
                            f"{output_root}."
                        )
                    self.work.put(("prompt_download", found))
                finally:
                    self.work.put(("download_lookup_done", None))

            self._background(locate)
            return
        self._prompt_combined_download(self.last_combined_remote)

    def _prompt_combined_download(self, remote_path):
        downloads = Path.home() / "Downloads"
        destination = filedialog.asksaveasfilename(
            title="Save combined IDtracker results",
            initialdir=str(downloads if downloads.is_dir() else Path.home()),
            initialfile=PurePosixPath(remote_path).name,
            defaultextension=".csv",
            filetypes=[("CSV files", "*.csv")],
            confirmoverwrite=True,
        )
        if not destination:
            return
        self.download_button.configure(state="disabled")

        def action():
            try:
                self.log(f"Downloading combined CSV: {remote_path}")
                self.ssh().download(remote_path, destination, timeout=900)
                self.log(f"Combined CSV downloaded to: {destination}")
                self.work.put(
                    ("status", f"Combined CSV downloaded to {destination}")
                )
            finally:
                self.work.put(("combined_ready", remote_path))

        self._background(action)

    def download_plot_folder(self):
        if self.last_plot_remote:
            self._prompt_plot_folder(self.last_plot_remote)
            return

        self.plot_download_button.configure(state="disabled")

        def locate():
            try:
                remote_home = self.ssh().run('printf "%s" "$HOME"').strip()
                output_root = expand_remote_path(
                    self.output_root.get(), remote_home
                ).rstrip("/")
                remote_path = (
                    output_root
                    + "/combined_results_latest_pdfs"
                )
                found = self.ssh().run(
                    f"test -d {shlex.quote(remote_path)} && "
                    f"find {shlex.quote(remote_path)} -maxdepth 1 -type f "
                    r"-name '*.pdf' -print -quit",
                    timeout=120,
                ).strip()
                if not found:
                    raise RuntimeError(
                        f"No PDF plots exist yet under {remote_path}"
                    )
                self.work.put(("prompt_plot_download", remote_path))
            finally:
                self.work.put(("plot_download_done", None))

        self._background(locate)

    def _prompt_plot_folder(self, remote_path):
        downloads = Path.home() / "Downloads"
        destination = filedialog.askdirectory(
            title="Choose a folder for the IDtracker PDF plots",
            initialdir=str(
                downloads if downloads.is_dir() else Path.home()
            ),
            mustexist=True,
        )
        if not destination:
            return
        destination = str(
            Path(destination) / PurePosixPath(remote_path).name
        )
        self.plot_download_button.configure(state="disabled")

        def action():
            try:
                self.log(
                    f"Downloading PDF plot folder: {remote_path} -> "
                    f"{destination}"
                )
                self.ssh().download_directory(
                    remote_path, destination, timeout=1800
                )
                self.log(f"PDF plot folder downloaded to: {destination}")
                self.work.put(
                    ("status", f"PDF plots downloaded to {destination}")
                )
            finally:
                self.work.put(("plot_download_done", None))

        self._background(action)

    @staticmethod
    def _write_remote_text(ssh, remote_python, remote_path, text):
        command = (
            f"{shlex.quote(remote_python)} -c "
            + shlex.quote(
                "import sys; from pathlib import Path; "
                "path=Path(sys.argv[1]); path.parent.mkdir(parents=True, exist_ok=True); "
                "path.write_text(sys.stdin.read(), encoding='utf-8')"
            )
            + " "
            + shlex.quote(remote_path)
        )
        ssh.run(command, input_text=text, timeout=300)

    def _run_slurm_batch(
        self,
        chosen,
        blocked,
        parameters,
        batch_token,
        processing_created_at,
    ):
        ssh = self.ssh()
        remote_home = ssh.run('printf "%s" "$HOME"').strip()
        output_root = expand_remote_path(
            self.output_root.get(), remote_home
        ).rstrip("/")
        remote_python = expand_remote_path(
            self.remote_python.get(), remote_home
        )
        batch_folder = f"{output_root}/slurm_batches/{batch_token}"
        status_folder = f"{batch_folder}/status"
        result_folder = f"{batch_folder}/results"
        log_folder = f"{batch_folder}/logs"
        plot_stage = f"{batch_folder}/pdfs_staged"
        matplotlib_cache = f"{batch_folder}/matplotlib_cache"
        processor_path = f"{batch_folder}/processor.py"
        worker_path = f"{batch_folder}/slurm_worker.py"
        finalize_path = f"{batch_folder}/slurm_finalize.py"
        combine_path = f"{batch_folder}/combine_results.py"
        manifest_path = f"{batch_folder}/manifest.json"
        completion_marker = f"{batch_folder}/batch_complete.json"
        combined_stage = f"{batch_folder}/combined_results_staged.csv"
        combined_destination = f"{output_root}/combined_results_latest.csv"
        plot_folder = f"{output_root}/combined_results_latest_pdfs"
        plot_previous = f"{output_root}/.plot_pdfs_previous"

        self.log(
            f"Preparing SLURM batch {batch_token} for {len(chosen)} "
            f"approved ready session(s); script version={SCRIPT_VERSION}."
        )
        for record in blocked:
            self.log(
                "SKIPPED NO_USABLE_TRAJECTORY: "
                f"{record['qc_record_id']} | {record['video']} | "
                f"{record['cell_label']} | {record['session']} | "
                f"{record['trajectory_status']} | "
                f"{record.get('trajectory_diagnostic', '')}"
            )
        self.work.put(("show_logs", None))
        ssh.run(
            f"command -v sbatch >/dev/null && "
            f"command -v squeue >/dev/null && "
            f"command -v sacct >/dev/null && "
            f"test -x {shlex.quote(remote_python)} && "
            f"mkdir -p {shlex.quote(status_folder)} "
            f"{shlex.quote(result_folder)} {shlex.quote(log_folder)} "
            f"{shlex.quote(plot_stage)} {shlex.quote(matplotlib_cache)}",
            timeout=120,
        )
        ssh.run(
            f"{shlex.quote(remote_python)} -c "
            + shlex.quote("import numpy, h5py, matplotlib"),
            timeout=120,
        )
        self._write_remote_text(
            ssh, remote_python, processor_path,
            PROCESSOR.read_text(encoding="utf-8"),
        )
        self._write_remote_text(
            ssh, remote_python, worker_path,
            SLURM_WORKER.read_text(encoding="utf-8"),
        )
        self._write_remote_text(
            ssh, remote_python, finalize_path,
            SLURM_FINALIZER.read_text(encoding="utf-8"),
        )
        self._write_remote_text(
            ssh, remote_python, combine_path,
            COMBINE_SCRIPT.read_text(encoding="utf-8"),
        )

        items = []
        for index, record in enumerate(chosen):
            result_path = f"{result_folder}/{index:05d}.csv"
            plot_identity = (
                f"{PurePosixPath(record['video']).stem}"
                f"__{record['cell_label']}"
                f"__{record['qc_record_id']}"
            )
            plot_stem = re.sub(
                r"[^A-Za-z0-9_.-]+", "_", plot_identity
            ).strip("._") or f"session_{index}"
            plot_output = f"{plot_stage}/{index:05d}__{plot_stem}.pdf"
            processor_args = [
                "--trajectory", record["trajectory"],
                "--session", record["session"],
                "--start", str(record["start"]),
                "--window", str(parameters["window"]),
                "--threshold", str(parameters["threshold"]),
                "--wall-buffer-px", str(parameters["wall_buffer"]),
                "--fungus-buffer-px", str(parameters["fungus_buffer"]),
                "--social-distance-threshold-px",
                str(parameters["social_distance"]),
                "--one-frame-jump-threshold-px",
                str(parameters["one_frame_jump"]),
                "--turtling-window-frames",
                str(parameters["turtling_window"]),
                "--turtling-min-path-px",
                str(parameters["turtling_min_path"]),
                "--turtling-max-radius90-px",
                str(parameters["turtling_max_radius90"]),
                "--turtling-min-turn-rotations",
                str(parameters["turtling_min_turns"]),
                "--turtling-max-straightness",
                str(parameters["turtling_max_straightness"]),
                "--turtling-max-step-px",
                str(parameters["turtling_max_step"]),
                "--analysis-type", record["analysis"],
                "--analysis-start-original-global-frame",
                str(
                    record.get("archived_original_start")
                    or record["start"]
                ),
                "--analysis-start-source",
                record.get("start_decision_source") or "SOURCE_INTERVAL",
                "--analysis-start-adjustment-provenance",
                record.get("start_decision_provenance") or "",
                "--video", record["video"],
                "--cell-label", record["cell_label"],
                "--qc-record-id", record["qc_record_id"],
                "--output", result_path,
                "--plot-output", plot_output,
                "--overwrite",
            ]
            if parameters["use_social_disappearance"]:
                processor_args.append(
                    "--use-social-disappearance-in-calculations"
                )
            items.append(
                {
                    "processor_args": processor_args,
                    "source_result_file": result_path,
                    "plot_output": plot_output,
                    "qc_record_id": record["qc_record_id"],
                    "video": record["video"],
                    "cell_label": record["cell_label"],
                    "analysis_type": record["analysis"],
                    "camera": record["camera"],
                    "camera_id": record["camera_id"],
                    "video_year": record["video_year"],
                    "recording_date": record["recording_date"],
                    "recording_time": record["recording_time"],
                    "act": record["act"],
                    "processing_batch_id": batch_token,
                    "processing_created_at": processing_created_at,
                    "processing_execution_mode": "SLURM_ARRAY",
                }
            )
        manifest = {
            "schema_version": 1,
            "script_version": SCRIPT_VERSION,
            "remote_python": remote_python,
            "processor_path": processor_path,
            "combine_script": combine_path,
            "status_folder": status_folder,
            "matplotlib_cache": matplotlib_cache,
            "plot_stage": plot_stage,
            "plot_folder": plot_folder,
            "plot_previous": plot_previous,
            "combined_stage": combined_stage,
            "combined_destination": combined_destination,
            "completion_marker": completion_marker,
            "items": items,
        }
        self._write_remote_text(
            ssh,
            remote_python,
            manifest_path,
            json.dumps(manifest, indent=2, sort_keys=True),
        )

        sbatch_options = [
            "sbatch",
            "--parsable",
            f"--job-name=idpp_{batch_token[:14]}",
            f"--array=0-{len(items) - 1}%{parameters['slurm_max_concurrent']}",
            "--cpus-per-task=1",
            f"--mem={parameters['slurm_memory']}",
            f"--time={parameters['slurm_time']}",
            f"--output={log_folder}/task_%A_%a.out",
            f"--error={log_folder}/task_%A_%a.err",
        ]
        if parameters["slurm_account"]:
            sbatch_options.append(
                f"--account={parameters['slurm_account']}"
            )
        if parameters["slurm_partition"]:
            sbatch_options.append(
                f"--partition={parameters['slurm_partition']}"
            )
        worker_command = (
            f"{shlex.quote(remote_python)} {shlex.quote(worker_path)} "
            f"{shlex.quote(manifest_path)}"
        )
        array_submit = " ".join(
            shlex.quote(value) for value in sbatch_options
        ) + " --wrap=" + shlex.quote(worker_command)
        array_job_id = (
            ssh.run(array_submit, timeout=120).strip().split(";", 1)[0]
        )
        if not array_job_id.isdigit():
            raise RuntimeError(
                f"Could not parse SLURM array job ID: {array_job_id!r}"
            )

        finalize_options = [
            "sbatch",
            "--parsable",
            f"--job-name=idpp_finish_{batch_token[:10]}",
            f"--dependency=afterany:{array_job_id}",
            "--cpus-per-task=1",
            "--mem=2G",
            "--time=00:30:00",
            f"--output={log_folder}/finalize_%j.out",
            f"--error={log_folder}/finalize_%j.err",
        ]
        if parameters["slurm_account"]:
            finalize_options.append(
                f"--account={parameters['slurm_account']}"
            )
        if parameters["slurm_partition"]:
            finalize_options.append(
                f"--partition={parameters['slurm_partition']}"
            )
        finalize_command = (
            f"{shlex.quote(remote_python)} {shlex.quote(finalize_path)} "
            f"{shlex.quote(manifest_path)}"
        )
        finalize_submit = " ".join(
            shlex.quote(value) for value in finalize_options
        ) + " --wrap=" + shlex.quote(finalize_command)
        finalize_job_id = (
            ssh.run(finalize_submit, timeout=120).strip().split(";", 1)[0]
        )
        if not finalize_job_id.isdigit():
            raise RuntimeError(
                f"Could not parse SLURM finalizer job ID: "
                f"{finalize_job_id!r}"
            )
        self.log(
            f"SLURM submitted: array job {array_job_id}; dependent finalizer "
            f"job {finalize_job_id}; maximum simultaneous array tasks "
            f"{parameters['slurm_max_concurrent']}."
        )
        self.work.put((
            "status",
            f"SLURM array {array_job_id}: 0 of {len(items)} task(s) finished. "
            f"Finalizer: {finalize_job_id}.",
        ))

        summary_code = (
            "import json,sys; from pathlib import Path; "
            "m=json.loads(Path(sys.argv[1]).read_text()); "
            "s=[json.loads(p.read_text()) for p in "
            "sorted(Path(m['status_folder']).glob('*.json'))]; "
            "marker=Path(m['completion_marker']); "
            "print(json.dumps({'finished':len(s),"
            "'failed':[x for x in s if x.get('status')!='SUCCESS'],"
            "'complete':json.loads(marker.read_text()) if marker.exists() "
            "else None}))"
        )
        deadline = time.monotonic() + 24 * 60 * 60
        last_progress = None
        finalizer_completed_without_marker = 0
        while time.monotonic() < deadline:
            summary_text = ssh.run(
                f"{shlex.quote(remote_python)} -c "
                f"{shlex.quote(summary_code)} "
                f"{shlex.quote(manifest_path)}",
                timeout=120,
            ).strip()
            summary = json.loads(summary_text)
            progress = (int(summary["finished"]), len(summary["failed"]))
            if progress != last_progress:
                self.log(
                    f"SLURM array {array_job_id}: {progress[0]} of "
                    f"{len(items)} task(s) wrote status; failures={progress[1]}."
                )
                self.work.put((
                    "status",
                    f"SLURM array {array_job_id}: {progress[0]} of "
                    f"{len(items)} finished; finalizer {finalize_job_id}.",
                ))
                last_progress = progress
            if summary["failed"]:
                first = summary["failed"][0]
                raise RuntimeError(
                    "SLURM session task failed. "
                    f"QC={first.get('qc_record_id', 'unknown')}; "
                    f"error={first.get('error', 'see Firebird SLURM logs')}; "
                    f"logs={log_folder}"
                )
            if summary["complete"]:
                complete = summary["complete"]
                self.work.put(("combined_ready", complete["combined_output"]))
                self.work.put(("plots_ready", complete["pdf_folder"]))
                self.work.put((
                    "status",
                    f"SLURM batch completed: {len(items)} ready session(s); "
                    f"skipped {len(blocked)} unready session(s).",
                ))
                self.log(
                    f"SLURM batch completed successfully. Array job "
                    f"{array_job_id}; finalizer job {finalize_job_id}; "
                    f"combined CSV: {complete['combined_output']}; "
                    f"PDF folder: {complete['pdf_folder']}."
                )
                self.work.put((
                    "processing_complete",
                    {
                        "processed": len(items),
                        "skipped": len(blocked),
                        "script_version": SCRIPT_VERSION,
                    },
                ))
                return

            queue_text = ssh.run(
                f"squeue -h -j "
                f"{shlex.quote(array_job_id + ',' + finalize_job_id)} "
                f"-o '%i|%T'",
                timeout=120,
            ).strip()
            accounting = ssh.run(
                f"sacct -n -P -j "
                f"{shlex.quote(array_job_id + ',' + finalize_job_id)} "
                f"--format=JobIDRaw,State,ExitCode",
                timeout=120,
            )
            failure_states = {
                "FAILED", "CANCELLED", "TIMEOUT", "OUT_OF_MEMORY",
                "NODE_FAIL", "BOOT_FAIL", "DEADLINE",
                "PREEMPTED", "REVOKED",
            }
            finalizer_is_completed = False
            for line in accounting.splitlines():
                parts = line.split("|")
                if len(parts) < 2:
                    continue
                state = (
                    parts[1].split(None, 1)[0].split("+", 1)[0]
                )
                if state in failure_states:
                    raise RuntimeError(
                        f"SLURM job {parts[0]} ended as {parts[1]}; "
                        f"logs={log_folder}"
                    )
                if (
                    parts[0] == finalize_job_id
                    and state == "COMPLETED"
                ):
                    finalizer_is_completed = True
            if finalizer_is_completed:
                finalizer_completed_without_marker += 1
                if finalizer_completed_without_marker >= 3:
                    raise RuntimeError(
                        f"SLURM finalizer {finalize_job_id} completed but no "
                        f"success marker appeared; logs={log_folder}"
                    )
            else:
                finalizer_completed_without_marker = 0
            time.sleep(10)
        raise RuntimeError(
            f"Stopped monitoring SLURM after 24 hours. Jobs may still exist: "
            f"array={array_job_id}, finalizer={finalize_job_id}; "
            f"logs={log_folder}"
        )

    def process(self):
        if self.processing_running:
            self.notebook.select(self.logs_tab)
            self.status.set("Processing is already running; see Logs & Diagnostics.")
            return
        selected = [
            record for record in self.all_records if record["use"] == "Yes"
        ]
        if not selected:
            messagebox.showwarning("No sessions checked", "Double-click the Process? cell for a few reviewed examples.")
            return
        blocked = [
            record for record in selected if not record.get("processable")
        ]
        chosen = [
            record for record in selected if record.get("processable")
        ]
        if not chosen:
            messagebox.showwarning(
                "No ready sessions checked",
                f"All {len(blocked)} checked session(s) lack any recognized "
                "validated, without-gaps, or raw IDtracker trajectory file.",
            )
            return
        try:
            window = int(self.window_frames.get())
            threshold = float(self.threshold.get())
            wall_buffer = float(self.wall_buffer.get())
            fungus_buffer = float(self.fungus_buffer.get())
            social_distance = float(self.social_distance.get())
            one_frame_jump = float(self.one_frame_jump.get())
            use_social_disappearance = bool(
                self.use_social_disappearance.get()
            )
            turtling_window = int(self.turtling_window.get())
            turtling_min_path = float(self.turtling_min_path.get())
            turtling_max_radius90 = float(
                self.turtling_max_radius90.get()
            )
            turtling_min_turns = float(self.turtling_min_turns.get())
            turtling_max_straightness = float(
                self.turtling_max_straightness.get()
            )
            turtling_max_step = float(self.turtling_max_step.get())
            execution_mode = self.execution_mode.get()
            slurm_max_concurrent = int(self.slurm_max_concurrent.get())
            slurm_account = self.slurm_account.get().strip()
            slurm_partition = self.slurm_partition.get().strip()
            slurm_time = self.slurm_time.get().strip()
            slurm_memory = self.slurm_memory.get().strip()
            if (
                window <= 0
                or threshold <= 0
                or wall_buffer < 0
                or fungus_buffer < 0
                or social_distance <= 0
                or one_frame_jump <= 0
                or turtling_window < 3
                or turtling_min_path <= 0
                or turtling_max_radius90 < 5
                or turtling_min_turns <= 0
                or not 0 <= turtling_max_straightness <= 1
                or turtling_max_step <= 0
                or slurm_max_concurrent <= 0
                or not slurm_time
                or not slurm_memory
            ):
                raise ValueError
            for record in chosen:
                if int(record["start"]) <= 0:
                    raise ValueError
        except (ValueError, TypeError):
            messagebox.showerror(
                "Invalid review values",
                "Every checked row needs a positive approved start, window, wake "
                "threshold. ROI buffer widths cannot be negative. Social "
                "distance and one-frame jump thresholds must be positive. "
                "Turtling settings require "
                "a window of at least 3 frames, radius90 of at least 5 pixels, "
                "positive path/turn/step thresholds, and net/path from 0 to 1.",
            )
            return
        skip_message = (
            f"\n{len(blocked)} unready checked session(s) will be marked "
            "NO_USABLE_TRAJECTORY and skipped; ready sessions will continue.\n"
            if blocked
            else ""
        )
        confirm_message = (
            f"Process {len(chosen)} checked session(s) only?\n\n"
            f"Execution: {execution_mode}\n"
            + (
                f"SLURM maximum simultaneous tasks: {slurm_max_concurrent}\n"
                f"SLURM account: {slurm_account or 'cluster default'}\n"
                f"SLURM partition: {slurm_partition or 'cluster default'}\n"
                f"SLURM time/memory per session: {slurm_time} / {slurm_memory}\n"
                if execution_mode == "SLURM job array"
                else ""
            )
            +
            f"Inclusive end − start: {window} frames\nThreshold: {threshold:g} pixels\n"
            f"Wall buffer: {wall_buffer:g} pixels\n"
            f"Fungus inward buffer for fights: {fungus_buffer:g} pixels\n"
            f"Fight social distance: {social_distance:g} pixels\n"
            f"Coordinate-jump threshold: {one_frame_jump:g} pixels\n"
            f"Use social disappearance in distance/location calculations: "
            f"{'YES' if use_social_disappearance else 'NO'}\n"
            f"Turtling candidate rule: {turtling_window} frames, "
            f"path >= {turtling_min_path:g} px, "
            f"radius90 <= {turtling_max_radius90:g} px, "
            f"turns >= {turtling_min_turns:g} rotations, "
            f"net/path <= {turtling_max_straightness:g}, "
            f"maximum step <= {turtling_max_step:g} px\n"
            + skip_message
            +
            "The best available IDtracker trajectory is used: validated and "
            "without-gaps files are preferred, with raw trajectories used as "
            "fallbacks. This prototype does not add interpolation; missing "
            "coordinates and jump-QC exclusions are reported. Previous complete "
            "results and PDF plots for these sessions will be atomically replaced."
        )
        if not messagebox.askyesno(
            "Confirm scientific processing",
            confirm_message,
        ):
            return

        batch_token = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
        processing_created_at = datetime.now().astimezone().isoformat(
            timespec="seconds"
        )
        self.current_batch_token = batch_token
        self.auto_download_started_for = ""

        parameters = {
            "window": window,
            "threshold": threshold,
            "wall_buffer": wall_buffer,
            "fungus_buffer": fungus_buffer,
            "social_distance": social_distance,
            "one_frame_jump": one_frame_jump,
            "use_social_disappearance": use_social_disappearance,
            "turtling_window": turtling_window,
            "turtling_min_path": turtling_min_path,
            "turtling_max_radius90": turtling_max_radius90,
            "turtling_min_turns": turtling_min_turns,
            "turtling_max_straightness": turtling_max_straightness,
            "turtling_max_step": turtling_max_step,
            "slurm_max_concurrent": slurm_max_concurrent,
            "slurm_account": slurm_account,
            "slurm_partition": slurm_partition,
            "slurm_time": slurm_time,
            "slurm_memory": slurm_memory,
        }

        def direct_action():
            script = PROCESSOR.read_text(encoding="utf-8")
            remote_home = self.ssh().run('printf "%s" "$HOME"').strip()
            output_root = expand_remote_path(self.output_root.get(), remote_home)
            remote_python = expand_remote_path(self.remote_python.get(), remote_home)
            self.log(
                f"Processing started for {len(chosen)} checked session(s); "
                f"script version={SCRIPT_VERSION}; "
                f"inclusive span={window}, wake threshold={threshold:g} px, "
                f"wall buffer={wall_buffer:g} px, "
                f"fungus buffer={fungus_buffer:g} px, "
                f"social distance={social_distance:g} px, "
                f"coordinate-jump threshold={one_frame_jump:g} px, "
                f"social disappearance calculation switch="
                f"{'ON' if use_social_disappearance else 'OFF'}, "
                f"turtling window={turtling_window} frames, "
                f"min path={turtling_min_path:g} px, "
                f"max radius90={turtling_max_radius90:g} px, "
                f"min turns={turtling_min_turns:g}, "
                f"max net/path={turtling_max_straightness:g}, "
                f"max step={turtling_max_step:g} px."
            )
            for record in blocked:
                self.log(
                    "SKIPPED NO_USABLE_TRAJECTORY: "
                    f"{record['qc_record_id']} | {record['video']} | "
                    f"{record['cell_label']} | {record['session']} | "
                    f"{record['trajectory_status']} | "
                    f"{record.get('trajectory_diagnostic', '')}"
                )
            self.work.put(("show_logs", None))
            self.ssh().run(
                f"test -x {shlex.quote(remote_python)} || "
                f"{{ echo {shlex.quote('Firebird Conda environment idtracker_reprocess_v1 was not found. Run install_both.command first.')} >&2; exit 1; }}"
            )
            self.ssh().run(
                f"{shlex.quote(remote_python)} -c "
                + shlex.quote("import matplotlib"),
                timeout=120,
            )
            combined_items = []
            plot_folder = (
                output_root.rstrip("/")
                + "/combined_results_latest_pdfs"
            )
            plot_stage = (
                output_root.rstrip("/")
                + "/.plot_pdfs_partial_"
                + batch_token
            )
            matplotlib_cache = output_root.rstrip("/") + "/.matplotlib_cache"
            self.ssh().run(
                f"mkdir -p {shlex.quote(matplotlib_cache)} "
                f"{shlex.quote(plot_stage)}",
                timeout=120,
            )
            for index, record in enumerate(chosen, 1):
                self.work.put(("status", f"Processing reviewed session {index} of {len(chosen)}..."))
                safe_name = PurePosixPath(record["session"]).name.replace(" ", "_")
                destination = (
                    output_root.rstrip("/")
                    + f"/{safe_name}/processed_result_latest.csv"
                )
                plot_identity = (
                    f"{PurePosixPath(record['video']).stem}"
                    f"__{record['cell_label']}"
                    f"__{record['qc_record_id']}"
                )
                plot_stem = re.sub(
                    r"[^A-Za-z0-9_.-]+", "_", plot_identity
                ).strip("._") or f"session_{index}"
                plot_destination = plot_stage + f"/{plot_stem}.pdf"
                command_parts = [
                        "env",
                        shlex.quote("MPLCONFIGDIR=" + matplotlib_cache),
                        shlex.quote(remote_python), "-",
                        "--trajectory", shlex.quote(record["trajectory"]),
                        "--session", shlex.quote(record["session"]),
                        "--start", record["start"],
                        "--window", str(window),
                        "--threshold", str(threshold),
                        "--wall-buffer-px", str(wall_buffer),
                        "--fungus-buffer-px", str(fungus_buffer),
                        "--social-distance-threshold-px",
                        str(social_distance),
                        "--one-frame-jump-threshold-px",
                        str(one_frame_jump),
                        "--turtling-window-frames", str(turtling_window),
                        "--turtling-min-path-px", str(turtling_min_path),
                        "--turtling-max-radius90-px",
                        str(turtling_max_radius90),
                        "--turtling-min-turn-rotations",
                        str(turtling_min_turns),
                        "--turtling-max-straightness",
                        str(turtling_max_straightness),
                        "--turtling-max-step-px",
                        str(turtling_max_step),
                        "--analysis-type", shlex.quote(record["analysis"]),
                        "--analysis-start-original-global-frame",
                        shlex.quote(
                            str(
                                record.get("archived_original_start")
                                or record["start"]
                            )
                        ),
                        "--analysis-start-source",
                        shlex.quote(
                            record.get("start_decision_source")
                            or "SOURCE_INTERVAL"
                        ),
                        "--analysis-start-adjustment-provenance",
                        shlex.quote(
                            record.get("start_decision_provenance") or ""
                        ),
                        "--video", shlex.quote(record["video"]),
                        "--cell-label", shlex.quote(record["cell_label"]),
                        "--qc-record-id", shlex.quote(record["qc_record_id"]),
                        "--output", shlex.quote(destination),
                        "--plot-output", shlex.quote(plot_destination),
                        "--overwrite",
                    ]
                if use_social_disappearance:
                    command_parts.append(
                        "--use-social-disappearance-in-calculations"
                    )
                command = " ".join(command_parts)
                self.log(
                    f"Processing {index}/{len(chosen)}: {record['cell']} -> {destination}"
                )
                result = self.ssh().run(
                    command, input_text=script, timeout=3600
                ).strip()
                self.log(result or f"Completed {record['cell']}")
                combined_items.append(
                    {
                        "source_result_file": destination,
                        "qc_record_id": record["qc_record_id"],
                        "video": record["video"],
                        "cell_label": record["cell_label"],
                        "analysis_type": record["analysis"],
                        "camera": record["camera"],
                        "camera_id": record["camera_id"],
                        "video_year": record["video_year"],
                        "recording_date": record["recording_date"],
                        "recording_time": record["recording_time"],
                        "act": record["act"],
                        "processing_batch_id": batch_token,
                        "processing_created_at": processing_created_at,
                        "processing_execution_mode": "DIRECT_SSH",
                    }
                )
            combined_destination = (
                output_root.rstrip("/")
                + "/combined_results_latest.csv"
            )
            combined_stage = (
                output_root.rstrip("/")
                + "/.combined_results_partial_"
                + batch_token
                + ".csv"
            )
            combine_request = {
                "items": combined_items,
                "destination": combined_stage,
                "overwrite": True,
            }
            self.log(
                f"Combining {len(combined_items)} per-session CSV files into "
                "a staged complete batch before replacing the latest outputs."
            )
            combined_result = self.ssh().run(
                shlex.quote(remote_python)
                + " -c "
                + shlex.quote(COMBINE_RESULTS),
                input_text=json.dumps(combine_request),
                timeout=900,
            ).strip()
            self.log(combined_result)
            plot_previous = (
                output_root.rstrip("/") + "/.plot_pdfs_previous"
            )
            promote_command = (
                "set -e; "
                f"rm -rf {shlex.quote(plot_previous)}; "
                f"if test -d {shlex.quote(plot_folder)}; then "
                f"mv {shlex.quote(plot_folder)} {shlex.quote(plot_previous)}; "
                "fi; "
                f"if mv {shlex.quote(plot_stage)} {shlex.quote(plot_folder)}; "
                f"then if mv -f {shlex.quote(combined_stage)} "
                f"{shlex.quote(combined_destination)}; "
                f"then rm -rf {shlex.quote(plot_previous)}; "
                "else "
                f"rm -rf {shlex.quote(plot_folder)}; "
                f"if test -d {shlex.quote(plot_previous)}; then "
                f"mv {shlex.quote(plot_previous)} {shlex.quote(plot_folder)}; "
                "fi; exit 1; fi; "
                "else "
                f"if test -d {shlex.quote(plot_previous)}; then "
                f"mv {shlex.quote(plot_previous)} {shlex.quote(plot_folder)}; "
                "fi; exit 1; fi"
            )
            self.log(
                "Promoting the complete PDF batch to "
                "combined_results_latest_pdfs; "
                "an incomplete batch cannot replace it."
            )
            self.ssh().run(promote_command, timeout=300)
            self.work.put(("combined_ready", combined_destination))
            self.work.put(("plots_ready", plot_folder))
            self.work.put((
                "status",
                f"Finished {len(chosen)} ready session(s); skipped "
                f"{len(blocked)} NO_USABLE_TRAJECTORY session(s). "
                f"Outputs: {output_root}",
            ))
            self.log(
                f"Processing finished for {len(chosen)} ready session(s); "
                f"skipped {len(blocked)} NO_USABLE_TRAJECTORY session(s). "
                f"Combined CSV: {combined_destination}. "
                f"PDF folder: {plot_folder}"
            )
            self.work.put((
                "processing_complete",
                {
                    "processed": len(chosen),
                    "skipped": len(blocked),
                    "script_version": SCRIPT_VERSION,
                },
            ))

        self.processing_running = True
        self.process_button.configure(state="disabled")
        self.download_button.configure(state="disabled")
        self.plot_download_button.configure(state="disabled")
        self.last_combined_remote = ""
        self.last_plot_remote = ""
        self.results_status.set(
            "Processing is running. Download buttons will return when the "
            "complete CSV and PDF batch is ready."
        )

        def guarded_processing():
            try:
                if execution_mode == "SLURM job array":
                    self._run_slurm_batch(
                        chosen,
                        blocked,
                        parameters,
                        batch_token,
                        processing_created_at,
                    )
                else:
                    direct_action()
            except Exception:
                self.work.put(("processing_results_failed", None))
                raise
            finally:
                self.work.put(("processing_done", None))

        self._background(guarded_processing)


if __name__ == "__main__":
    App().mainloop()
