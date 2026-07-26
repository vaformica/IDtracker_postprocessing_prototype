#!/usr/bin/env python3
"""Independent post-processing discovery and QC-state helpers.

This module deliberately does not read or write the IDtracker pipeline's
``QC/run_status.csv``. IDtracker execution and post-processing review are two
different quality-control layers.
"""
from __future__ import annotations

import hashlib
import re
from pathlib import PurePosixPath


QC_SCHEMA_VERSION = 1
QC_DECISIONS = {"UNREVIEWED", "APPROVED", "RERUN"}
QC_EVENT_FIELDS = [
    "qc_schema_version",
    "decision_id",
    "decided_at",
    "reviewer",
    "decision",
    "reason",
    "session_record_id",
    "session_key",
    "session_path",
    "trajectory_file",
    "trajectory_source_kind",
    "video",
    "cell_label",
    "analysis_type",
    "camera",
    "camera_id",
    "video_year",
    "recording_date",
    "recording_time",
    "act",
    "session_run_timestamp",
    "duplicate_rank",
    "duplicate_count",
    "processing_batch_id",
    "processing_created_at",
    "processing_execution_mode",
    "source_result_file",
    "plot_file",
    "script_version",
]
APPROVED_QC_FIELDS = [
    "postprocessing_qc_decision",
    "postprocessing_qc_decided_at",
    "postprocessing_qc_reviewer",
    "postprocessing_qc_reason",
    "postprocessing_qc_session_record_id",
    "postprocessing_qc_session_key",
    "postprocessing_qc_duplicate_rank",
    "postprocessing_qc_duplicate_count",
]


def parse_search_roots(value: str) -> list[str]:
    """Parse newline, semicolon, or comma separated Firebird search roots."""
    roots = []
    for item in re.split(r"[\n;,]+", str(value or "")):
        item = item.strip()
        if item and item not in roots:
            roots.append(item)
    return roots


def normalized_video_stem(value: str) -> str:
    name = PurePosixPath(str(value or "")).name
    return re.sub(r"\.(mp4|avi|mov|mkv)$", "", name, flags=re.IGNORECASE)


def session_key(record: dict) -> str:
    """Return the biological processing key; blank means identity incomplete."""
    video = normalized_video_stem(record.get("video", "")).strip().lower()
    cell = str(record.get("cell_label") or "").strip().upper()
    analysis = str(record.get("analysis") or "").strip().lower()
    if (
        not video
        or re.fullmatch(r"[A-Z]\d+", cell) is None
        or analysis not in {"ba", "fight"}
    ):
        return ""
    return f"{video}|{cell}|{analysis}"


def session_record_id(record: dict) -> str:
    supplied = str(
        record.get("session_record_id")
        or record.get("record_id")
        or ""
    ).strip()
    if supplied:
        return supplied
    identity = "|".join(
        [
            str(record.get("session") or ""),
            str(record.get("trajectory") or ""),
            str(record.get("video") or ""),
            str(record.get("cell_label") or ""),
            str(record.get("analysis") or ""),
        ]
    )
    return "SESSION_" + hashlib.sha256(
        identity.encode("utf-8")
    ).hexdigest()[:20].upper()


def _numeric(value, default=-1):
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def discovery_rank(record: dict) -> tuple:
    """Rank repeated runs deterministically, newest first when reversed."""
    return (
        str(record.get("session_run_timestamp") or ""),
        str(record.get("run_timestamp") or ""),
        _numeric(record.get("trajectory_mtime_ns")),
        _numeric(record.get("attempt_index")),
        _numeric(record.get("run_index")),
        str(record.get("session") or ""),
        str(record.get("trajectory") or ""),
    )


def deduplicate_discovered_sessions(records: list[dict]) -> list[dict]:
    """Annotate every discovered run while retaining all duplicate evidence."""
    output = [dict(record) for record in records]
    groups: dict[str, list[dict]] = {}
    for record in output:
        record["session_record_id"] = session_record_id(record)
        record["session_key"] = session_key(record)
        record["postprocessing_qc_decision"] = str(
            record.get("postprocessing_qc_decision") or "UNREVIEWED"
        ).upper()
        if not record["session_key"]:
            record.update(
                {
                    "duplicate_rank": "",
                    "duplicate_count": "",
                    "duplicate_status": "IDENTITY_INCOMPLETE",
                    "canonical_for_review": False,
                    "use": "No",
                }
            )
            continue
        groups.setdefault(record["session_key"], []).append(record)

    for key_records in groups.values():
        ordered = sorted(key_records, key=discovery_rank, reverse=True)
        total = len(ordered)
        for rank, record in enumerate(ordered, 1):
            record["duplicate_rank"] = rank
            record["duplicate_count"] = total
            record["canonical_for_review"] = rank == 1
            record["duplicate_status"] = (
                "CANONICAL_NEWEST"
                if rank == 1
                else "SUPERSEDED_DUPLICATE"
            )
            if rank != 1:
                record["use"] = "No"
    return output


def apply_latest_qc_events(
    records: list[dict], events: list[dict]
) -> list[dict]:
    """Attach the latest independent post-processing decision by run ID."""
    latest = {}
    for event in events:
        record_id = str(event.get("session_record_id") or "").strip()
        if not record_id:
            continue
        rank = (
            str(event.get("decided_at") or ""),
            str(event.get("decision_id") or ""),
        )
        if record_id not in latest or rank > latest[record_id][0]:
            latest[record_id] = (rank, event)
    for record in records:
        event = latest.get(str(record.get("session_record_id") or ""))
        if not event:
            record["postprocessing_qc_decision"] = "UNREVIEWED"
            record["postprocessing_qc_reason"] = ""
            record["postprocessing_qc_decided_at"] = ""
            record["postprocessing_qc_reviewer"] = ""
            continue
        event = event[1]
        record["postprocessing_qc_decision"] = str(
            event.get("decision") or "UNREVIEWED"
        ).upper()
        record["postprocessing_qc_reason"] = str(
            event.get("reason") or ""
        )
        record["postprocessing_qc_decided_at"] = str(
            event.get("decided_at") or ""
        )
        record["postprocessing_qc_reviewer"] = str(
            event.get("reviewer") or ""
        )
        for key in (
            "processing_batch_id",
            "processing_created_at",
            "processing_execution_mode",
            "source_result_file",
            "plot_file",
        ):
            if event.get(key):
                record[key] = event[key]
    return records


def make_duplicate_report(records: list[dict]) -> list[dict]:
    fields = (
        "session_key",
        "duplicate_rank",
        "duplicate_count",
        "duplicate_status",
        "canonical_for_review",
        "video",
        "cell_label",
        "analysis",
        "session_run_timestamp",
        "run_timestamp",
        "attempt_index",
        "run_index",
        "session_record_id",
        "session",
        "trajectory",
        "trajectory_status",
    )
    duplicates = [
        record for record in records
        if _numeric(record.get("duplicate_count"), 0) > 1
    ]
    return [
        {field: record.get(field, "") for field in fields}
        for record in sorted(
            duplicates,
            key=lambda item: (
                str(item.get("session_key") or ""),
                _numeric(item.get("duplicate_rank"), 999999),
            ),
        )
    ]


def make_rerun_report(records: list[dict]) -> list[dict]:
    fields = (
        "postprocessing_qc_decided_at",
        "postprocessing_qc_reviewer",
        "postprocessing_qc_reason",
        "video",
        "cell_label",
        "analysis",
        "session_record_id",
        "session",
        "trajectory",
        "trajectory_status",
        "start",
        "status",
        "source",
        "toml",
    )
    reruns = [
        record for record in records
        if record.get("postprocessing_qc_decision") == "RERUN"
    ]
    return [
        {field: record.get(field, "") for field in fields}
        for record in sorted(
            reruns,
            key=lambda item: (
                str(item.get("video") or ""),
                str(item.get("cell_label") or ""),
            ),
        )
    ]


RECURSIVE_SESSION_DISCOVERY = r'''
import hashlib
import json
import os
import sys
from pathlib import Path

request = json.load(sys.stdin)
roots = [Path(value).expanduser() for value in request["roots"]]
trajectory_rank = {
    "validated.npy": 0,
    "without_gaps.npy": 1,
    "trajectories_wo_gaps.npy": 2,
    "trajectories_without_gaps.npy": 3,
    "trajectories.npy": 4,
    "trajectories.h5": 5,
    "trajectories.csv": 6,
}
trajectory_status = {
    "validated.npy": "IDTRACKER_VALIDATED",
    "without_gaps.npy": "IDTRACKER_WITHOUT_GAPS",
    "trajectories_wo_gaps.npy": "IDTRACKER_LEGACY_WO_GAPS",
    "trajectories_without_gaps.npy": "IDTRACKER_LEGACY_WITHOUT_GAPS",
    "trajectories.npy": "IDTRACKER_RAW_NPY",
    "trajectories.h5": "IDTRACKER_RAW_H5",
    "trajectories.csv": "IDTRACKER_RAW_CSV",
}
skip_dirs = {
    ".git", "__pycache__", "venv", "venv-mac", "node_modules",
    "idtracker_reprocessing_v1", "combined_results_latest_pdfs",
}

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

def resolve_session_from_metadata(metadata_path, metadata):
    run_dir = metadata_path.parent
    for name in ("session_link.txt", "session_path.txt"):
        value = read_text(run_dir / name).strip()
        if value:
            return value, name
    value = str(metadata.get("session_path") or "").strip()
    if value:
        return value, "run_metadata.json:session_path"
    return "", ""

def add_trajectory(grouped, path):
    parent = path.parent
    for ancestor in path.parents:
        if ancestor.name == "trajectories":
            parent = ancestor.parent
            break
    grouped.setdefault(str(parent), set()).add(str(path))

metadata_paths = []
trajectory_groups = {}
missing_roots = []
for root in roots:
    if not root.exists():
        missing_roots.append(str(root))
        continue
    if root.is_file():
        if root.name == "run_metadata.json":
            metadata_paths.append(root)
        elif root.name in trajectory_rank:
            add_trajectory(trajectory_groups, root)
        continue
    for directory, dirnames, filenames in os.walk(root):
        dirnames[:] = [
            name for name in dirnames
            if name not in skip_dirs and not name.startswith(".")
        ]
        current = Path(directory)
        if "run_metadata.json" in filenames:
            metadata_paths.append(current / "run_metadata.json")
        for name in trajectory_rank:
            if name in filenames:
                add_trajectory(trajectory_groups, current / name)

associations = {}
for metadata_path in sorted(set(metadata_paths)):
    metadata = read_json(metadata_path)
    session, link_source = resolve_session_from_metadata(
        metadata_path, metadata
    )
    if not session:
        continue
    associations.setdefault(session, []).append(
        {
            "metadata_path": str(metadata_path),
            "metadata": metadata,
            "link_source": link_source,
        }
    )
    session_path = Path(session)
    if session_path.is_dir() and session not in trajectory_groups:
        for name in trajectory_rank:
            for candidate in (
                session_path / "trajectories" / name,
                session_path / name,
            ):
                if candidate.is_file():
                    add_trajectory(trajectory_groups, candidate)

def session_payload(session, candidates):
    session_path = Path(session)
    candidates = sorted(set(candidates))
    ranked = sorted(
        candidates,
        key=lambda value: (
            trajectory_rank.get(Path(value).name, 99),
            0 if Path(value).parent.name == "trajectories" else 1,
            value,
        ),
    )
    selected = ranked[0] if ranked else ""
    selected_rank = (
        trajectory_rank.get(Path(selected).name, 99) if selected else 99
    )
    same_priority = [
        value for value in ranked
        if trajectory_rank.get(Path(value).name, 99) == selected_rank
    ]
    resolution = (
        trajectory_status.get(Path(selected).name, "NO_TRAJECTORY")
        if len(same_priority) == 1
        else "AMBIGUOUS_TRAJECTORY"
    )
    if len(same_priority) != 1:
        selected = ""
    session_json_path = session_path / "session.json"
    session_json = read_json(session_json_path)
    if not session_json:
        matches = list(session_path.glob("**/session.json"))
        if matches:
            session_json_path = matches[0]
            session_json = read_json(session_json_path)
    timestamp = ""
    timers = session_json.get("timers") or {}
    tracking = timers.get("Tracking session") or {}
    timestamp = str(
        tracking.get("finish_time")
        or tracking.get("start_time")
        or ""
    )
    mtime_ns = 0
    for value in candidates:
        try:
            mtime_ns = max(mtime_ns, Path(value).stat().st_mtime_ns)
        except OSError:
            pass
    raw = [
        value for value in candidates
        if Path(value).name in {
            "trajectories.npy", "trajectories.h5", "trajectories.csv"
        }
    ]
    return {
        "session": session,
        "trajectory": selected,
        "trajectory_resolution_status": resolution,
        "trajectory_candidates": candidates,
        "raw_trajectory_candidates": raw,
        "session_json": session_json,
        "session_json_path": str(session_json_path),
        "session_run_timestamp": timestamp,
        "trajectory_mtime_ns": mtime_ns,
    }

results = []
all_sessions = sorted(set(trajectory_groups) | set(associations))
for session in all_sessions:
    base = session_payload(session, trajectory_groups.get(session, set()))
    linked = associations.get(session) or []
    if linked:
        for link in linked:
            metadata = link["metadata"]
            metadata_video = (
                metadata.get("video_filename")
                or Path(str(metadata.get("video_path") or "")).name
            )
            session_video_paths = (
                base["session_json"].get("video_paths") or []
            )
            session_video = (
                Path(str(session_video_paths[0])).name
                if session_video_paths
                else ""
            )
            video = metadata_video or session_video
            source_toml = str(
                metadata.get("toml_source_path")
                or metadata.get("toml_run_copy_path")
                or ""
            )
            identity = "|".join(
                [
                    session,
                    str(link["metadata_path"]),
                    str(metadata.get("record_id") or ""),
                ]
            )
            record_id = str(metadata.get("record_id") or "").strip()
            if not record_id:
                record_id = "SESSION_" + hashlib.sha256(
                    identity.encode()
                ).hexdigest()[:20].upper()
            results.append(
                {
                    **base,
                    "session_record_id": record_id,
                    "metadata_path": link["metadata_path"],
                    "session_link_source": link["link_source"],
                    "video": video,
                    "cell_label": metadata.get("cell_label") or "",
                    "analysis": str(
                        metadata.get("analysis_type") or ""
                    ).lower(),
                    "run_index": metadata.get("run_index", ""),
                    "attempt_index": metadata.get("attempt_index", ""),
                    "run_timestamp": metadata.get("run_timestamp", ""),
                    "source_toml": source_toml,
                    "source_toml_text": (
                        read_text(source_toml) if source_toml else ""
                    ),
                    "identity_source": (
                        "RUN_METADATA_LINK"
                        if metadata_video
                        else "RUN_METADATA_LINK_SESSION_VIDEO_FALLBACK"
                    ),
                }
            )
        continue
    session_json = base["session_json"]
    video_paths = session_json.get("video_paths") or []
    video = Path(str(video_paths[0])).name if video_paths else ""
    lowered = video.lower()
    analysis = "fight" if "fight" in lowered else ("ba" if video else "")
    identity = "|".join([session, video, analysis])
    results.append(
        {
            **base,
            "session_record_id": "SESSION_" + hashlib.sha256(
                identity.encode()
            ).hexdigest()[:20].upper(),
            "metadata_path": "",
            "session_link_source": "",
            "video": video,
            "cell_label": str(session_json.get("cell_label") or ""),
            "analysis": analysis,
            "run_index": "",
            "attempt_index": "",
            "run_timestamp": base["session_run_timestamp"],
            "source_toml": "",
            "source_toml_text": "",
            "identity_source": "SESSION_JSON_ONLY",
        }
    )

json.dump(
    {
        "records": results,
        "roots": [str(root) for root in roots],
        "missing_roots": missing_roots,
        "metadata_files_found": len(set(metadata_paths)),
        "session_folders_found": len(all_sessions),
    },
    sys.stdout,
)
'''


REMOTE_QC_STATE = r'''
import csv
import json
import os
import sys
from pathlib import Path

request = json.load(sys.stdin)
state_dir = Path(request["state_dir"])
state_dir.mkdir(parents=True, exist_ok=True)
history_path = state_dir / "postprocessing_qc_decision_history.csv"
current_path = state_dir / "postprocessing_qc_current.csv"
approved_path = state_dir / "approved_results_latest.csv"
rerun_path = state_dir / "sessions_marked_rerun_latest.csv"
event_fields = request["event_fields"]
approved_qc_fields = request["approved_qc_fields"]

def read_rows(path):
    if not path.is_file():
        return []
    with path.open(newline="", encoding="utf-8-sig") as stream:
        return list(csv.DictReader(stream))

def write_atomic(path, fieldnames, rows):
    temporary = path.with_name(path.name + f".partial.{os.getpid()}")
    try:
        with temporary.open("w", newline="", encoding="utf-8") as stream:
            writer = csv.DictWriter(
                stream, fieldnames=fieldnames, extrasaction="ignore"
            )
            writer.writeheader()
            writer.writerows(rows)
        temporary.replace(path)
    except Exception:
        if temporary.exists():
            temporary.unlink()
        raise

history = read_rows(history_path)
for event in request.get("events") or []:
    history.append({field: event.get(field, "") for field in event_fields})
if request.get("events"):
    write_atomic(history_path, event_fields, history)

latest = {}
for event in history:
    record_id = str(event.get("session_record_id") or "")
    if not record_id:
        continue
    rank = (
        str(event.get("decided_at") or ""),
        str(event.get("decision_id") or ""),
    )
    if record_id not in latest or rank > latest[record_id][0]:
        latest[record_id] = (rank, event)
current = [
    value[1] for value in sorted(
        latest.values(),
        key=lambda item: (
            str(item[1].get("video") or ""),
            str(item[1].get("cell_label") or ""),
            str(item[1].get("analysis_type") or ""),
        ),
    )
]
write_atomic(current_path, event_fields, current)

canonical_ids = set(request.get("canonical_record_ids") or [])
def is_current_canonical(row):
    return (
        not canonical_ids
        or str(row.get("session_record_id") or "") in canonical_ids
    )

reruns = [
    row for row in current
    if row.get("decision") == "RERUN" and is_current_canonical(row)
]
write_atomic(rerun_path, event_fields, reruns)

approved_events = [
    row for row in current
    if row.get("decision") == "APPROVED"
    and str(row.get("duplicate_rank") or "") == "1"
    and is_current_canonical(row)
]
approved_rows = []
base_fields = None
missing_sources = []
for event in approved_events:
    source = Path(event.get("source_result_file") or "")
    if not source.is_file():
        missing_sources.append(
            {
                "session_record_id": event.get("session_record_id", ""),
                "source_result_file": str(source),
            }
        )
        continue
    with source.open(newline="", encoding="utf-8-sig") as stream:
        reader = csv.DictReader(stream)
        fields = reader.fieldnames or []
        if base_fields is None:
            base_fields = fields
        elif fields != base_fields:
            raise RuntimeError(
                "Approved per-session result schemas do not match"
            )
        for source_row in reader:
            row = dict(source_row)
            row.update(
                {
                    "cell_label": event.get("cell_label", ""),
                    "video": event.get("video", ""),
                    "analysis_type": event.get("analysis_type", ""),
                    "camera": event.get("camera", ""),
                    "camera_id": event.get("camera_id", ""),
                    "video_year": event.get("video_year", ""),
                    "recording_date": event.get(
                        "recording_date", ""
                    ),
                    "recording_time": event.get(
                        "recording_time", ""
                    ),
                    "act": event.get("act", ""),
                    "postprocessing_qc_decision": "APPROVED",
                    "postprocessing_qc_decided_at": event.get(
                        "decided_at", ""
                    ),
                    "postprocessing_qc_reviewer": event.get("reviewer", ""),
                    "postprocessing_qc_reason": event.get("reason", ""),
                    "postprocessing_qc_session_record_id": event.get(
                        "session_record_id", ""
                    ),
                    "postprocessing_qc_session_key": event.get(
                        "session_key", ""
                    ),
                    "postprocessing_qc_duplicate_rank": event.get(
                        "duplicate_rank", ""
                    ),
                    "postprocessing_qc_duplicate_count": event.get(
                        "duplicate_count", ""
                    ),
                    "qc_record_id": event.get("session_record_id", ""),
                    "processing_batch_id": event.get(
                        "processing_batch_id", ""
                    ),
                    "processing_created_at": event.get(
                        "processing_created_at", ""
                    ),
                    "processing_execution_mode": event.get(
                        "processing_execution_mode", ""
                    ),
                    "source_result_file": event.get(
                        "source_result_file", ""
                    ),
                }
            )
            approved_rows.append(row)

if approved_rows:
    leading = ["cell_label", "video", "analysis_type", "video_year"]
    trailing = [
        "qc_record_id", "camera", "camera_id", "recording_date",
        "recording_time", "act", "processing_batch_id",
        "processing_created_at", "processing_execution_mode",
        "source_result_file",
    ]
    fields = (
        leading
        + approved_qc_fields
        + [
            field for field in (base_fields or [])
            if field not in leading and field not in trailing
        ]
        + trailing
    )
    write_atomic(approved_path, fields, approved_rows)
elif approved_path.exists():
    with approved_path.open(newline="", encoding="utf-8-sig") as stream:
        previous_fields = csv.DictReader(stream).fieldnames or []
    write_atomic(
        approved_path,
        previous_fields or [
            "cell_label", "video", "analysis_type", "video_year",
            *approved_qc_fields,
        ],
        [],
    )
else:
    write_atomic(
        approved_path,
        [
            "cell_label", "video", "analysis_type", "video_year",
            *approved_qc_fields,
        ],
        [],
    )

json.dump(
    {
        "history": history,
        "current": current,
        "approved_session_count": len(approved_events),
        "approved_row_count": len(approved_rows),
        "rerun_session_count": len(reruns),
        "missing_approved_sources": missing_sources,
        "history_path": str(history_path),
        "current_path": str(current_path),
        "approved_path": str(approved_path),
        "rerun_path": str(rerun_path),
    },
    sys.stdout,
)
'''
