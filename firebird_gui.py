#!/usr/bin/env python3
"""Review-first GUI for minimal Firebird IDtracker.ai reprocessing."""
from __future__ import annotations

import csv
import io
import json
import queue
import re
import shlex
import shutil
import subprocess
import threading
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
    match = re.match(
        r"^Camera_(?P<camera>\d+)_(?P<camera_id>\d+)_"
        r"(?P<date>\d{8})_(?P<time>\d{4})(?P<remainder>.*)$",
        stem,
        flags=re.IGNORECASE,
    )
    act_match = re.search(r"(ACT\d+)", stem, flags=re.IGNORECASE)
    return {
        "video_name": stem,
        "camera": match.group("camera") if match else "",
        "camera_id": match.group("camera_id") if match else "",
        "recording_date": match.group("date") if match else "",
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
A positive global start was entered directly or imported from the editable CSV."""


def make_missing_start_report(records):
    return [
        {
            "qc_record_id": record["qc_record_id"],
            "video": record["video"],
            "camera": record["camera"],
            "camera_id": record["camera_id"],
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
        self.last_combined_remote = ""
        self.last_plot_remote = ""
        self.current_batch_token = ""
        self.auto_download_started_for = ""
        self.all_records = []
        self.filtered_records = []
        self.sort_column = "video_name"
        self.sort_reverse = False

        self.notebook = ttk.Notebook(self)
        self.notebook.pack(fill="both", expand=True, padx=10, pady=8)
        self.setup_tab = ttk.Frame(self.notebook)
        self.sessions_tab = ttk.Frame(self.notebook)
        self.logs_tab = ttk.Frame(self.notebook)
        self.notebook.add(self.setup_tab, text="Setup & Run")
        self.notebook.add(self.sessions_tab, text="Sessions")
        self.notebook.add(self.logs_tab, text="Logs & Diagnostics")

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
        self.use_social_disappearance = tk.BooleanVar(value=False)
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
        controls.columnconfigure(4, weight=1)
        ttk.Button(
            controls,
            text="Edit selected start frame",
            command=self.edit_start,
        ).grid(row=3, column=0, columnspan=2, sticky="w", padx=8, pady=(6, 8))
        self.process_button = ttk.Button(
            controls, text="Process checked sessions", command=self.process
        )
        self.process_button.grid(
            row=3, column=2, columnspan=2, sticky="w", padx=8, pady=(6, 8)
        )

        results = ttk.LabelFrame(
            self.setup_tab,
            text="3. Results from the latest completed processing run",
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

        columns = (
            "use", "trajectory_status", "status", "start", "video_name", "camera",
            "recording_date", "recording_time", "act", "cell_label",
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
            "camera": 70, "recording_date": 95, "recording_time": 70,
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
                elif kind == "log":
                    self._append_log(payload)
                elif kind == "show_logs":
                    self.notebook.select(self.logs_tab)
                elif kind == "scan_done":
                    self.scan_running = False
                    self.scan_button.configure(state="normal")
                elif kind == "processing_done":
                    self.processing_running = False
                    self.process_button.configure(state="normal")
                    self.download_button.configure(state="normal")
                    self.plot_download_button.configure(state="normal")
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
                records.append(
                    {"session": session, "trajectory": trajectory, "detected": detected,
                     "source": source, "start": approved, "status": status, "use": "No",
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
            record["start"] = str(value)
            record["status"] = "START MANUALLY APPROVED"
        self.apply_filters()
        self.log(
            f"Imported {len(updates)} manually approved global starts from {source}"
        )
        messagebox.showinfo(
            "Start times imported",
            f"Applied {len(updates)} positive global start values atomically.",
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
                    "video_name", "camera", "camera_id", "recording_date",
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
            "start", "camera", "recording_date", "recording_time"
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
            "recording_date", "recording_time", "act", "cell_label",
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
            record["start"] = str(value)
            record["status"] = "START MANUALLY APPROVED"
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
        downloads = Path.home() / "Downloads"
        local_root = (
            downloads if downloads.is_dir() else Path.home()
        ) / "IDtracker_postprocessing_results"
        local_csv = local_root / f"combined_results_{token}.csv"
        local_pdfs = local_root / f"combined_results_{token}_pdfs"
        partial_csv = local_root / f".combined_results_{token}.csv.partial"
        partial_pdfs = local_root / f".combined_results_{token}_pdfs.partial"

        def action():
            local_root.mkdir(parents=True, exist_ok=True)
            if (
                local_csv.exists()
                or local_pdfs.exists()
                or partial_csv.exists()
                or partial_pdfs.exists()
            ):
                raise FileExistsError(
                    "Refusing to overwrite an existing automatic download: "
                    f"{local_csv} or {local_pdfs}"
                )
            try:
                self.log(
                    f"Automatically staging completed CSV on Mac: {local_csv}"
                )
                self.ssh().download(
                    remote_csv, str(partial_csv), timeout=900
                )
                self.log(
                    f"Automatically staging completed PDF folder on Mac: "
                    f"{local_pdfs}"
                )
                self.ssh().download_directory(
                    remote_pdfs, str(partial_pdfs), timeout=1800
                )
                partial_pdfs.replace(local_pdfs)
                partial_csv.replace(local_csv)
            except Exception:
                if partial_csv.exists():
                    partial_csv.unlink()
                if partial_pdfs.exists():
                    shutil.rmtree(partial_pdfs)
                if local_pdfs.exists() and not local_csv.exists():
                    shutil.rmtree(local_pdfs)
                raise
            self.log(
                f"Automatic Mac download completed: {local_csv}; {local_pdfs}"
            )
            self.work.put(("auto_download_complete", str(local_root)))
            self.work.put((
                "status",
                f"Completed results saved on Mac in {local_root}",
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
            use_social_disappearance = bool(
                self.use_social_disappearance.get()
            )
            if (
                window <= 0
                or threshold <= 0
                or wall_buffer < 0
                or fungus_buffer < 0
                or social_distance <= 0
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
                "distance threshold must be positive.",
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
            f"Inclusive end − start: {window} frames\nThreshold: {threshold:g} pixels\n"
            f"Wall buffer: {wall_buffer:g} pixels\n"
            f"Fungus inward buffer for fights: {fungus_buffer:g} pixels\n"
            f"Fight social distance: {social_distance:g} pixels\n"
            f"Use social disappearance in distance/location calculations: "
            f"{'YES' if use_social_disappearance else 'NO'}\n"
            + skip_message
            +
            "The best available IDtracker trajectory is used: validated and "
            "without-gaps files are preferred, with raw trajectories used as "
            "fallbacks. This prototype does not add interpolation; missing "
            "coordinates and excluded distance steps are reported. Previous complete "
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

        def action():
            script = PROCESSOR.read_text(encoding="utf-8")
            remote_home = self.ssh().run('printf "%s" "$HOME"').strip()
            output_root = expand_remote_path(self.output_root.get(), remote_home)
            remote_python = expand_remote_path(self.remote_python.get(), remote_home)
            self.log(
                f"Processing started for {len(chosen)} checked session(s); "
                f"inclusive span={window}, wake threshold={threshold:g} px, "
                f"wall buffer={wall_buffer:g} px, "
                f"fungus buffer={fungus_buffer:g} px, "
                f"social distance={social_distance:g} px, "
                f"social disappearance calculation switch="
                f"{'ON' if use_social_disappearance else 'OFF'}."
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
                        "--analysis-type", shlex.quote(record["analysis"]),
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
                        "recording_date": record["recording_date"],
                        "recording_time": record["recording_time"],
                        "act": record["act"],
                        "processing_batch_id": batch_token,
                        "processing_created_at": processing_created_at,
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
                action()
            except Exception:
                self.work.put(("processing_results_failed", None))
                raise
            finally:
                self.work.put(("processing_done", None))

        self._background(guarded_processing)


if __name__ == "__main__":
    App().mainloop()
