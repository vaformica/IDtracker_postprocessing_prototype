import csv
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

import numpy as np

from processor import (
    IDTRACKER_TRAJECTORY_SOURCES,
    OUTPUT_COLUMNS,
    SCRIPT_VERSION,
    analyze,
    continuous_path_segments,
    compute_social_candidates,
    compute_turtling_candidates,
    filter_jump_artifact_coordinates,
    main,
    validate_trajectory_source,
    write_plot_pdf,
)
from jump_audit import audit_manifest
from firebird_gui import (
    App,
    BATCH_SESSION_RESOLVER,
    COMBINE_RESULTS,
    TRAJECTORY_NAMES,
    automatic_download_paths,
    KNOWN_START_REVIEW_STEMS,
    make_missing_start_report,
    make_missing_trajectory_report,
    expand_remote_path,
    extract_pairs,
    find_interval_candidates,
    normalized_video_name,
    jump_audit_start_for_record,
    parse_video_fields,
    saved_start_decisions,
    settings_bundle_from_combined_rows,
    settings_bundle_from_jump_audit_rows,
    validate_settings_bundle,
    validate_start_report_updates,
)


class ProcessorTests(unittest.TestCase):
    def test_reusable_settings_validate_and_preserve_start_provenance(self):
        records = [
            {
                "qc_record_id": "QC_1",
                "video": "Camera_1_12345678_20260724_1200_ACT1.mp4",
                "cell_label": "A1",
                "analysis": "ba",
                "start": "1150",
                "archived_original_start": "1095",
                "status": "START APPROVED FROM JUMP AUDIT",
                "start_decision_source": "JUMP_AUDIT_APPROVED",
                "start_decision_provenance": "approved audit evidence",
            }
        ]
        decisions = saved_start_decisions(records)
        bundle = validate_settings_bundle(
            {
                "format": "IDTRACKER_POSTPROCESSING_SETTINGS",
                "schema_version": 1,
                "gui_settings": {
                    "window_frames": "7200",
                    "one_frame_jump": "200",
                    "use_social_disappearance": True,
                },
                "start_decisions": decisions,
                "jump_audit": {"summaries": [], "tracks": []},
            }
        )
        self.assertEqual(
            bundle["start_decisions"][0]["start_global_frame"], 1150
        )
        self.assertEqual(
            bundle["start_decisions"][0]["decision_source"],
            "JUMP_AUDIT_APPROVED",
        )

    def test_prior_combined_csv_restores_parameters_and_deduplicates_animals(self):
        common = {
            "qc_record_id": "QC_FIGHT",
            "video": "Camera_1_12345678_20260724_1200_FIGHT_ACT1.mp4",
            "cell_label": "A1",
            "analysis_type": "fight",
            "analysis_start_frame": "1150",
            "analysis_timespan_frames": "7200",
            "movement_threshold_px": "30",
            "wall_buffer_px": "30",
            "fungus_buffer_px": "30",
            "social_distance_threshold_px": "60",
            "jump_threshold_px": "200",
            "use_social_disappearance_in_calculations": "YES",
            "script_version": "0.5.5",
            "archived_original_start_frame": "1095",
            "start_frame_decision_source": "JUMP_AUDIT_APPROVED",
            "start_frame_decision_provenance": "approved audit evidence",
        }
        rows = [
            {**common, "idtracker_animal_id": "0"},
            {**common, "idtracker_animal_id": "1"},
        ]
        bundle = settings_bundle_from_combined_rows(rows, "prior.csv")
        self.assertEqual(bundle["gui_settings"]["one_frame_jump"], "200")
        self.assertTrue(
            bundle["gui_settings"]["use_social_disappearance"]
        )
        self.assertEqual(len(bundle["start_decisions"]), 1)
        self.assertEqual(
            bundle["start_decisions"][0]["start_global_frame"], 1150
        )

    def test_prior_jump_audit_restores_approved_video_decision(self):
        summaries = [
            {
                "video": "Camera_1_12345678_20260724_1200_ACT1.mp4",
                "analysis_type": "ba",
                "suggested_start_global_frame": "1150",
                "suggested_full_window_fits": "True",
                "last_synchronized_disturbance_frame": "1109",
                "jump_threshold_px": "200.0",
                "audit_version": "1.0",
                "decision": "APPROVED",
            }
        ]
        bundle = settings_bundle_from_jump_audit_rows(
            summaries, source_name="jump_audit_videos.csv"
        )
        self.assertEqual(
            bundle["jump_audit"]["summaries"][0][
                "suggested_start_global_frame"
            ],
            1150,
        )
        self.assertEqual(
            bundle["start_decisions"][0]["scope"], "VIDEO"
        )
        self.assertEqual(
            bundle["start_decisions"][0]["start_global_frame"], 1150
        )

    def test_saved_video_decision_applies_atomically_to_current_scan(self):
        app = App.__new__(App)
        app.all_records = [
            {
                "qc_record_id": "NEW_A1",
                "video": "Camera_1_12345678_20260724_1200_ACT1.mp4",
                "cell_label": "A1",
                "analysis": "ba",
                "start": "1095",
                "archived_original_start": "1095",
            },
            {
                "qc_record_id": "NEW_A2",
                "video": "Camera_1_12345678_20260724_1200_ACT1.mp4",
                "cell_label": "A2",
                "analysis": "ba",
                "start": "1095",
                "archived_original_start": "1095",
            },
        ]
        decision = {
            "scope": "VIDEO",
            "qc_record_id": "",
            "video": "Camera_1_12345678_20260724_1200_ACT1.mp4",
            "cell_label": "",
            "analysis": "ba",
            "start_global_frame": 1150,
            "archived_original_start_frame": "",
            "status": "START APPROVED FROM JUMP AUDIT",
            "decision_source": "JUMP_AUDIT_APPROVED",
            "decision_provenance": "approved audit evidence",
        }
        restored, unmatched = app._apply_loaded_start_decisions(
            [decision], "/tmp/previous_settings.json"
        )
        self.assertEqual(restored, 2)
        self.assertEqual(unmatched, [])
        self.assertEqual(
            {record["start"] for record in app.all_records}, {"1150"}
        )
        self.assertEqual(
            {
                record["archived_original_start"]
                for record in app.all_records
            },
            {"1095"},
        )
        self.assertTrue(
            all(
                "previous_settings.json"
                in record["start_decision_provenance"]
                for record in app.all_records
            )
        )

    def test_jump_audit_can_use_detected_start_without_approving_it(self):
        choice = jump_audit_start_for_record(
            {"start": "", "detected": "1538"}
        )
        self.assertEqual(
            choice, (1538, "POSITIVE_DETECTED_START_AUDIT_ONLY")
        )
        self.assertIsNone(
            jump_audit_start_for_record(
                {"start": "", "detected": "0"}
            )
        )
        self.assertIsNone(
            jump_audit_start_for_record(
                {"start": "", "detected": "1095,1538"}
            )
        )
        self.assertEqual(
            jump_audit_start_for_record(
                {"start": "1700", "detected": "1538"}
            ),
            (1700, "FINAL_APPROVED_START"),
        )

    def test_automatic_download_uses_one_timestamped_folder(self):
        with tempfile.TemporaryDirectory() as folder:
            home = Path(folder)
            (home / "Downloads").mkdir()
            paths = automatic_download_paths(
                "20260724_220000_123456", home=home
            )
            completed = (
                home
                / "Downloads"
                / "IDtracker_postprocessing_results"
                / "completed_run_20260724_220000_123456"
            )
            self.assertEqual(paths["completed_folder"], completed)
            self.assertEqual(
                paths["partial_csv"].name,
                "combined_results_20260724_220000_123456.csv",
            )
            self.assertEqual(paths["partial_pdfs"].name, "pdfs")
            self.assertEqual(
                paths["partial_folder"].name,
                ".completed_run_20260724_220000_123456.partial",
            )

    def test_gui_and_processor_accept_exactly_the_same_source_names(self):
        self.assertEqual(
            set(TRAJECTORY_NAMES),
            set(IDTRACKER_TRAJECTORY_SOURCES),
        )

    def resolve_session(self, root, candidate_names):
        root = Path(root)
        session = root / "session"
        trajectories = session / "trajectories"
        trajectories.mkdir(parents=True)
        (session / "session.json").write_text(
            json.dumps({"roi_list": []}), encoding="utf-8"
        )
        for name in candidate_names:
            candidate = trajectories / name
            candidate.parent.mkdir(parents=True, exist_ok=True)
            candidate.write_bytes(b"candidate")
        run = root / "run"
        run.mkdir()
        (run / "session_link.txt").write_text(
            str(session), encoding="utf-8"
        )
        metadata = run / "run_metadata.json"
        metadata.write_text("{}", encoding="utf-8")
        result = subprocess.run(
            [sys.executable, "-c", BATCH_SESSION_RESOLVER],
            input=json.dumps(
                [{"run_dir": str(run), "metadata_path": str(metadata)}]
            ),
            text=True,
            capture_output=True,
            check=True,
        )
        return json.loads(result.stdout)[0]

    def test_resolver_prefers_validated_then_without_gaps(self):
        with tempfile.TemporaryDirectory() as folder:
            resolved = self.resolve_session(
                folder,
                [
                    "trajectories.npy",
                    "trajectories_without_gaps.npy",
                    "without_gaps.npy",
                    "validated.npy",
                ],
            )
            self.assertEqual(
                Path(resolved["trajectory"]).name, "validated.npy"
            )
            self.assertEqual(
                resolved["trajectory_resolution_status"],
                "IDTRACKER_VALIDATED",
            )

    def test_resolver_selects_without_gaps_when_no_validated(self):
        with tempfile.TemporaryDirectory() as folder:
            resolved = self.resolve_session(
                folder, ["trajectories.npy", "without_gaps.npy"]
            )
            self.assertEqual(
                Path(resolved["trajectory"]).name, "without_gaps.npy"
            )
            self.assertEqual(
                resolved["trajectory_resolution_status"],
                "IDTRACKER_WITHOUT_GAPS",
            )

    def test_resolver_uses_raw_npy_fallback(self):
        with tempfile.TemporaryDirectory() as folder:
            resolved = self.resolve_session(
                folder, ["trajectories.npy", "trajectories.h5"]
            )
            self.assertEqual(
                Path(resolved["trajectory"]).name, "trajectories.npy"
            )
            self.assertEqual(
                resolved["trajectory_resolution_status"],
                "IDTRACKER_RAW_NPY",
            )
            self.assertEqual(
                {Path(path).name for path in resolved["raw_trajectory_candidates"]},
                {"trajectories.npy", "trajectories.h5"},
            )

    def test_resolver_blocks_ambiguous_top_priority_candidates(self):
        with tempfile.TemporaryDirectory() as folder:
            resolved = self.resolve_session(
                folder, ["validated.npy", "nested/validated.npy"]
            )
            self.assertEqual(resolved["trajectory"], "")
            self.assertEqual(
                resolved["trajectory_resolution_status"],
                "AMBIGUOUS_TRAJECTORY",
            )

    def test_processor_accepts_raw_trajectory_with_explicit_source(self):
        self.assertEqual(
            validate_trajectory_source(
                Path("/session/trajectories/trajectories.npy")
            ),
            "IDTRACKER_RAW_NPY",
        )

    def test_raw_trajectory_processing_reports_missing_data_policy(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "trajectories.npy"
            arr = np.zeros((40, 1, 2), dtype=float)
            arr[12, 0] = np.nan
            np.save(path, arr)
            row = analyze(path, Path(folder), 10, 10, 30)[0]
            self.assertEqual(
                row["trajectory_source_kind"], "IDTRACKER_RAW_NPY"
            )
            self.assertEqual(row["missing_coordinate_frames_in_window"], 1)
            self.assertIn("RAW_IDTRACKER_INPUT", row["warning"])

    def test_exact_global_crossing_and_window(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "without_gaps.npy"
            arr = np.zeros((8000, 1, 2), dtype=float)
            arr[62:, 0, 0] = np.arange(8000 - 62)
            np.save(path, arr)
            row = analyze(path, Path(folder), 62, 7200, 30)[0]
            self.assertEqual(row["analysis_end_frame_inclusive"], 7262)
            self.assertEqual(row["analysis_timespan_frames"], 7200)
            self.assertEqual(
                row["analysis_frame_observations_inclusive"], 7201
            )
            self.assertEqual(row["threshold_crossing_global_frame"], 92)
            self.assertEqual(row["latency_to_threshold_frames"], 30)
            self.assertEqual(
                row["total_distance_px_in_analysis_window"], 7200.0
            )

    def test_missing_entry_is_not_substituted(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "without_gaps.npy"
            arr = np.zeros((100, 1, 2), dtype=float)
            arr[10, 0] = np.nan
            arr[11:, 0, 0] = 100
            np.save(path, arr)
            row = analyze(path, Path(folder), 10, 50, 30)[0]
            self.assertEqual(row["result_status"], "NOT_CALCULATED")
            self.assertEqual(row["threshold_crossing_global_frame"], "")

    def test_zero_start_rejected(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "without_gaps.npy"
            np.save(path, np.zeros((100, 1, 2)))
            with self.assertRaisesRegex(ValueError, "greater than zero"):
                analyze(path, Path(folder), 0, 50, 30)

    def test_short_global_array_rejected(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "without_gaps.npy"
            np.save(path, np.zeros((100, 1, 2)))
            with self.assertRaisesRegex(ValueError, "interval-relative"):
                analyze(path, Path(folder), 60, 50, 30)

    def test_distance_does_not_bridge_missing_coordinate_gap(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "without_gaps.npy"
            arr = np.zeros((30, 1, 2), dtype=float)
            arr[10:16, 0, 0] = [0, 1, np.nan, 10, 11, 12]
            np.save(path, arr)
            row = analyze(path, Path(folder), 10, 5, 30)[0]
            self.assertEqual(
                row["total_distance_px_in_analysis_window"], 3.0
            )
            self.assertIn("excluded 2 adjacent-frame pair", row["warning"])
            self.assertIn(
                "still contains 1 missing coordinate frame", row["warning"]
            )
            self.assertEqual(
                row["trajectory_source_kind"], "IDTRACKER_WITHOUT_GAPS"
            )

    def test_jump_rejects_only_impossible_step_and_resumes_new_segment(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            trajectory = root / "without_gaps.npy"
            arr = np.zeros((30, 1, 2), dtype=float)
            arr[10:16, 0, 0] = [0, 10, 20, 200, 210, 220]
            np.save(trajectory, arr)
            row = analyze(
                trajectory,
                root,
                start=10,
                window=5,
                threshold=30,
                one_frame_jump_threshold_px=50,
            )[0]
            self.assertEqual(
                row["total_distance_px_in_analysis_window"],
                40.0,
            )
            self.assertEqual(row["one_frame_jump_threshold_px"], 50)
            self.assertEqual(row["one_frame_jumps_excluded"], 1)
            self.assertEqual(row["jump_threshold_px"], 50)
            self.assertEqual(
                row["jump_artifact_coordinate_frames_excluded"], 0
            )
            self.assertEqual(
                row["jump_qc_status"],
                "ONE_FRAME_JUMP_STEPS_EXCLUDED",
            )
            self.assertEqual(row["threshold_crossing_global_frame"], "")
            self.assertEqual(row["latency_to_threshold_frames"], "")
            self.assertEqual(row["result_status"], "THRESHOLD_NOT_REACHED")
            self.assertIn("ANTI_JUMP_STEP_QC", row["warning"])
            segments = continuous_path_segments(
                arr[10:16, 0, :], maximum_step_px=50
            )
            self.assertEqual(
                [offsets.tolist() for offsets, _xy in segments],
                [[0, 1, 2], [3, 4, 5]],
            )

    def test_default_jump_threshold_retains_steps_equal_to_200_pixels(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            trajectory = root / "without_gaps.npy"
            arr = np.zeros((30, 1, 2), dtype=float)
            arr[10:13, 0, 0] = [0, 200, 400]
            np.save(trajectory, arr)
            row = analyze(
                trajectory,
                root,
                start=10,
                window=2,
                threshold=30,
            )[0]
            self.assertEqual(row["jump_threshold_px"], 200)
            self.assertEqual(row["one_frame_jump_threshold_px"], 200)
            self.assertEqual(row["one_frame_jumps_excluded"], 0)
            self.assertEqual(
                row["jump_artifact_coordinate_frames_excluded"], 0
            )
            self.assertEqual(
                row["total_distance_px_in_analysis_window"], 400.0
            )

    def test_one_frame_step_equal_to_50_is_retained(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            trajectory = root / "without_gaps.npy"
            arr = np.zeros((30, 1, 2), dtype=float)
            arr[10:13, 0, 0] = [0, 50, 100]
            np.save(trajectory, arr)
            row = analyze(
                trajectory,
                root,
                start=10,
                window=2,
                threshold=30,
                one_frame_jump_threshold_px=50,
            )[0]
            self.assertEqual(
                row["total_distance_px_in_analysis_window"],
                100.0,
            )
            self.assertEqual(
                row["jump_artifact_coordinate_frames_excluded"], 0
            )
            self.assertEqual(row["threshold_crossing_global_frame"], 11)

    def test_returning_excursion_rejects_two_steps_but_keeps_coordinates(self):
        xy = np.asarray(
            [[0, 0], [10, 0], [200, 0], [201, 0], [11, 0], [12, 0]],
            dtype=float,
        )
        result = filter_jump_artifact_coordinates(
            xy, threshold_px=50, return_horizon_frames=120
        )
        self.assertEqual(
            np.flatnonzero(result["excluded_mask"]).tolist(),
            [],
        )
        np.testing.assert_array_equal(result["cleaned_xy"], xy)
        self.assertEqual(
            np.flatnonzero(result["rejected_step_mask"]).tolist(),
            [1, 3],
        )
        self.assertEqual(
            result["status"],
            "ONE_FRAME_JUMP_STEPS_EXCLUDED",
        )
        self.assertEqual(result["persistent_events"], 0)

    def test_jump_exclusion_is_not_social_disappearance_evidence(self):
        window = np.zeros((8, 2, 2), dtype=float)
        window[:, 1, 0] = 10
        window[3:5, 0, 0] = 200
        filtered = filter_jump_artifact_coordinates(
            window[:, 0, :], threshold_px=50
        )
        cleaned = window.copy()
        cleaned[:, 0, :] = filtered["cleaned_xy"]
        social = compute_social_candidates(
            cleaned,
            social_distance_threshold_px=60,
            eligible_missing_mask=~np.isfinite(window).all(axis=2),
        )
        self.assertEqual(
            int(social["disappearance_masks_by_animal"].sum()), 0
        )

    def test_video_wide_jump_audit_recommends_reviewable_start(self):
        with tempfile.TemporaryDirectory() as folder:
            records = []
            for index in range(4):
                path = Path(folder) / f"trajectory_{index}.npy"
                arr = np.zeros((9000, 1, 2), dtype=float)
                arr[:, 0, 0] = np.arange(9000) * 0.1
                if index < 3:
                    arr[1020:1022, 0, 1] = 200
                np.save(path, arr)
                records.append(
                    {
                        "video": "Camera_2_example.mp4",
                        "analysis": "ba",
                        "cell_label": f"A{index + 1}",
                        "qc_record_id": f"QC{index + 1}",
                        "trajectory": str(path),
                        "start": 760,
                    }
                )
            result = audit_manifest(
                {
                    "jump_threshold_px": 50,
                    "window_frames": 7200,
                    "records": records,
                }
            )
            summary = result["summaries"][0]
            self.assertEqual(
                summary["audit_status"],
                "VIDEO_WIDE_DISTURBANCE_START_RECOMMENDED",
            )
            self.assertEqual(
                summary["suggested_start_global_frame"], 1050
            )
            self.assertIs(summary["suggested_full_window_fits"], True)

    def test_cell_specific_jump_audit_does_not_suggest_video_start(self):
        with tempfile.TemporaryDirectory() as folder:
            records = []
            for index in range(4):
                path = Path(folder) / f"trajectory_{index}.npy"
                arr = np.zeros((9000, 1, 2), dtype=float)
                arr[:, 0, 0] = np.arange(9000) * 0.1
                if index == 0:
                    arr[1507, 0, 1] = 200
                np.save(path, arr)
                records.append(
                    {
                        "video": "Camera_2_example.mp4",
                        "analysis": "ba",
                        "cell_label": f"A{index + 1}",
                        "qc_record_id": f"QC{index + 1}",
                        "trajectory": str(path),
                        "start": 946,
                    }
                )
            summary = audit_manifest(
                {
                    "jump_threshold_px": 50,
                    "window_frames": 7200,
                    "records": records,
                }
            )["summaries"][0]
            self.assertEqual(
                summary["audit_status"],
                "CELL_OR_ANIMAL_SPECIFIC_RETURNING_JUMPS",
            )
            self.assertEqual(
                summary["suggested_start_global_frame"], ""
            )

    def test_wall_buffer_partitions_frames_and_distance(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            (root / "session.json").write_text(
                json.dumps(
                    {
                        "roi_list": [
                            "+ Polygon [[0, 0], [10, 0], [10, 10], [0, 10]]"
                        ]
                    }
                ),
                encoding="utf-8",
            )
            path = root / "without_gaps.npy"
            arr = np.zeros((30, 1, 2), dtype=float)
            arr[10:16, 0, :] = [
                [1, 5],
                [2, 5],
                [5, 5],
                [8, 5],
                [9, 5],
                [9, 9],
            ]
            np.save(path, arr)
            row = analyze(
                path,
                root,
                start=10,
                window=5,
                threshold=30,
                wall_buffer_px=2,
            )[0]
            self.assertEqual(row["frames_inside_wall_buffer"], 5)
            self.assertEqual(row["frames_outside_wall_buffer"], 1)
            self.assertAlmostEqual(row["distance_px_inside_wall_buffer"], 6)
            self.assertAlmostEqual(row["distance_px_outside_wall_buffer"], 6)
            self.assertEqual(row["spatial_partition_status"], "PASS")
            self.assertEqual(row["idtracker_animal_id"], 0)
            self.assertEqual(row["starting_side"], "NOT_APPLICABLE_NOT_FIGHT")
            self.assertEqual(
                row["fungus_partition_status"],
                "NOT_APPLICABLE_NOT_FIGHT",
            )

    def test_ba_post_wake_metrics_use_valid_steps_and_wall_midpoints(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            (root / "session.json").write_text(
                json.dumps(
                    {
                        "roi_list": [
                            "+ Polygon [[0, 0], [100, 0], [100, 100], [0, 100]]"
                        ]
                    }
                ),
                encoding="utf-8",
            )
            trajectory = root / "without_gaps.npy"
            arr = np.zeros((30, 1, 2), dtype=float)
            arr[10:16, 0, :] = [
                [5, 50], [15, 50], [35, 50],
                [45, 50], [95, 50], [85, 50],
            ]
            np.save(trajectory, arr)
            row = analyze(
                trajectory,
                root,
                start=10,
                window=5,
                threshold=30,
                wall_buffer_px=10,
                analysis_type="ba",
            )[0]
            self.assertEqual(row["threshold_crossing_global_frame"], 12)
            self.assertEqual(row["post_wake_analysis_status"], "CALCULATED")
            self.assertEqual(row["post_wake_valid_coordinate_frames"], 4)
            self.assertEqual(row["post_wake_valid_movement_steps"], 3)
            self.assertEqual(row["post_wake_missing_coordinate_frames"], 0)
            self.assertEqual(row["post_wake_jump_excluded_steps"], 0)
            self.assertAlmostEqual(row["post_wake_total_distance_px"], 70)
            self.assertAlmostEqual(
                row["post_wake_distance_px_per_valid_step"], 70 / 3
            )
            self.assertEqual(row["post_wake_frames_inside_wall_buffer"], 1)
            self.assertEqual(row["post_wake_frames_outside_wall_buffer"], 3)
            self.assertEqual(row["post_wake_steps_inside_wall_buffer"], 1)
            self.assertEqual(row["post_wake_steps_outside_wall_buffer"], 2)
            self.assertAlmostEqual(
                row["post_wake_distance_px_inside_wall_buffer"], 10
            )
            self.assertAlmostEqual(
                row["post_wake_distance_px_outside_wall_buffer"], 60
            )
            self.assertAlmostEqual(row["post_wake_open_area_proportion"], 0.75)
            self.assertAlmostEqual(
                row["post_wake_open_distance_px_per_available_step"], 20
            )
            self.assertAlmostEqual(
                row["post_wake_speed_px_per_open_step"], 30
            )
            self.assertEqual(row["post_wake_wall_analysis_status"], "PASS")
            self.assertEqual(row["post_wake_frames_on_fungus"], "")
            self.assertEqual(
                row["post_wake_fungus_analysis_status"],
                "NOT_APPLICABLE_NOT_FIGHT",
            )
            self.assertEqual(
                row["post_wake_open_off_fungus_analysis_status"],
                "NOT_APPLICABLE_NOT_FIGHT",
            )

    def test_post_wake_missing_and_jump_steps_are_not_bridged(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            trajectory = root / "without_gaps.npy"
            arr = np.zeros((30, 1, 2), dtype=float)
            arr[10:17, 0, :] = [
                [0, 0], [31, 0], [32, 0], [np.nan, np.nan],
                [33, 0], [300, 0], [301, 0],
            ]
            np.save(trajectory, arr)
            row = analyze(
                trajectory,
                root,
                start=10,
                window=6,
                threshold=30,
                one_frame_jump_threshold_px=200,
            )[0]
            self.assertEqual(row["threshold_crossing_global_frame"], 11)
            self.assertEqual(row["one_frame_jumps_excluded"], 1)
            self.assertEqual(row["post_wake_valid_coordinate_frames"], 5)
            self.assertEqual(row["post_wake_missing_coordinate_frames"], 1)
            self.assertEqual(row["post_wake_valid_movement_steps"], 2)
            self.assertEqual(row["post_wake_jump_excluded_steps"], 1)
            self.assertAlmostEqual(row["post_wake_total_distance_px"], 2)
            self.assertAlmostEqual(
                row["post_wake_distance_px_per_valid_step"], 1
            )

    def test_post_wake_metrics_are_blank_without_a_wake_frame(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            trajectory = root / "without_gaps.npy"
            arr = np.zeros((30, 1, 2), dtype=float)
            arr[10:16, 0, 0] = np.arange(6)
            np.save(trajectory, arr)
            no_crossing = analyze(
                trajectory, root, 10, 5, threshold=30
            )[0]
            self.assertEqual(
                no_crossing["post_wake_analysis_status"],
                "NOT_CALCULATED_THRESHOLD_NOT_REACHED",
            )
            self.assertEqual(no_crossing["post_wake_total_distance_px"], "")

            arr[10, 0, :] = np.nan
            np.save(trajectory, arr)
            invalid_baseline = analyze(
                trajectory, root, 10, 5, threshold=30
            )[0]
            self.assertEqual(
                invalid_baseline["post_wake_analysis_status"],
                "NOT_CALCULATED_INVALID_BASELINE",
            )
            self.assertEqual(
                invalid_baseline["post_wake_valid_movement_steps"], ""
            )

    def test_fight_side_and_fungus_partitions(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            (root / "session.json").write_text(
                json.dumps(
                    {
                        "roi_list": [
                            "+ Polygon [[0, 0], [20, 0], [20, 20], [0, 20]]",
                            "+ Polygon [[5, 5], [15, 5], [15, 15], [5, 15]]",
                        ]
                    }
                ),
                encoding="utf-8",
            )
            path = root / "without_gaps.npy"
            arr = np.zeros((30, 2, 2), dtype=float)
            arr[10:16, 0, :] = [
                [1, 10], [6, 10], [7, 10],
                [10, 10], [14, 10], [16, 10],
            ]
            arr[10:16, 1, :] = [
                [19, 10], [18, 10], [17, 10],
                [16, 10], [15, 10], [14, 10],
            ]
            np.save(path, arr)
            rows = analyze(
                path,
                root,
                start=10,
                window=5,
                threshold=30,
                wall_buffer_px=2,
                fungus_buffer_px=2,
                analysis_type="fight",
            )
            self.assertEqual(
                [row["idtracker_animal_id"] for row in rows], [0, 1]
            )
            self.assertEqual(
                [row["starting_side"] for row in rows], ["LEFT", "RIGHT"]
            )
            animal0 = rows[0]
            self.assertEqual(animal0["frames_on_fungus"], 4)
            self.assertEqual(animal0["frames_in_fungus_edge_buffer"], 3)
            self.assertEqual(animal0["frames_in_fungus_interior"], 1)
            self.assertAlmostEqual(animal0["distance_px_on_fungus"], 10)
            self.assertAlmostEqual(
                animal0["distance_px_in_fungus_edge_buffer"], 3
            )
            self.assertAlmostEqual(
                animal0["distance_px_in_fungus_interior"], 7
            )
            self.assertEqual(animal0["fungus_partition_status"], "PASS")
            self.assertEqual(animal0["social_distance_threshold_px"], 60)
            self.assertEqual(animal0["frames_within_social_distance"], 6)
            self.assertAlmostEqual(
                animal0[
                    "distance_moved_px_while_within_social_distance"
                ],
                15,
            )
            self.assertEqual(animal0["social_disappearance_frames"], 0)
            self.assertEqual(
                animal0["social_return_interaction_events"], 0
            )

    def test_fight_post_wake_fungus_and_joint_masks_are_direct_partitions(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            (root / "session.json").write_text(
                json.dumps(
                    {
                        "roi_list": [
                            "+ Polygon [[0, 0], [100, 0], [100, 100], [0, 100]]",
                            "+ Polygon [[40, 40], [60, 40], [60, 60], [40, 60]]",
                        ]
                    }
                ),
                encoding="utf-8",
            )
            trajectory = root / "without_gaps.npy"
            arr = np.zeros((30, 2, 2), dtype=float)
            arr[10:17, 0, :] = [
                [5, 50], [20, 50], [35, 50], [45, 50],
                [55, 50], [65, 50], [95, 50],
            ]
            arr[10:17, 1, :] = [90, 20]
            np.save(trajectory, arr)
            animal0 = analyze(
                trajectory,
                root,
                start=10,
                window=6,
                threshold=30,
                wall_buffer_px=10,
                analysis_type="fight",
            )[0]
            self.assertEqual(animal0["post_wake_analysis_status"], "CALCULATED")
            self.assertEqual(animal0["post_wake_valid_coordinate_frames"], 5)
            self.assertEqual(animal0["post_wake_valid_movement_steps"], 4)
            self.assertAlmostEqual(animal0["post_wake_total_distance_px"], 60)
            self.assertEqual(animal0["post_wake_frames_on_fungus"], 2)
            self.assertEqual(animal0["post_wake_frames_off_fungus"], 3)
            self.assertEqual(animal0["post_wake_steps_on_fungus"], 3)
            self.assertEqual(animal0["post_wake_steps_off_fungus"], 1)
            self.assertAlmostEqual(
                animal0["post_wake_distance_px_on_fungus"], 30
            )
            self.assertAlmostEqual(
                animal0["post_wake_distance_px_off_fungus"], 30
            )
            self.assertEqual(
                animal0["post_wake_frames_open_and_off_fungus"], 2
            )
            self.assertEqual(
                animal0["post_wake_steps_open_and_off_fungus"], 1
            )
            self.assertAlmostEqual(
                animal0["post_wake_distance_px_open_and_off_fungus"], 30
            )
            self.assertAlmostEqual(
                animal0["post_wake_open_off_fungus_proportion"], 0.4
            )
            self.assertAlmostEqual(
                animal0[
                    "post_wake_open_off_fungus_distance_px_per_available_step"
                ],
                7.5,
            )
            self.assertAlmostEqual(
                animal0[
                    "post_wake_speed_px_per_open_off_fungus_step"
                ],
                30,
            )
            self.assertEqual(
                animal0["post_wake_fungus_analysis_status"], "PASS"
            )
            self.assertEqual(
                animal0["post_wake_open_off_fungus_analysis_status"], "PASS"
            )

    def test_fight_start_side_is_unassigned_when_start_coordinate_missing(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            path = root / "without_gaps.npy"
            arr = np.zeros((30, 2, 2), dtype=float)
            arr[10, 0] = np.nan
            arr[10, 1] = [20, 10]
            np.save(path, arr)
            rows = analyze(
                path, root, 10, 5, 30, analysis_type="fight"
            )
            self.assertEqual(
                {row["starting_side"] for row in rows},
                {"UNASSIGNED_MISSING_START_COORDINATE"},
            )

    def test_social_distance_disappearance_and_return_events(self):
        window = np.zeros((10, 2, 2), dtype=float)
        window[:, 1, 0] = [
            50, 50, 80, 90, 50, np.nan, np.nan, 45, 100, 40
        ]
        result = compute_social_candidates(
            window, social_distance_threshold_px=60
        )
        self.assertEqual(int(result["within_mask"].sum()), 5)
        self.assertEqual(int(result["disappearance_mask"].sum()), 2)
        self.assertEqual(
            int(result["disappearance_masks_by_animal"][:, 0].sum()), 0
        )
        self.assertEqual(
            int(result["disappearance_masks_by_animal"][:, 1].sum()), 2
        )
        # Two visible >60 px excursions are bounded by <=60 px frames.
        # The missing-only gap is not counted as visible separation.
        self.assertEqual(result["return_events"], 2)
        self.assertEqual(result["status"], "CALCULATED_FIGHT_TWO_ANIMALS")

    def test_end_truncated_social_disappearance_is_not_inferred(self):
        window = np.zeros((5, 2, 2), dtype=float)
        window[:, 1, 0] = [40, 25, np.nan, np.nan, np.nan]
        result = compute_social_candidates(
            window, social_distance_threshold_px=60
        )
        self.assertEqual(int(result["disappearance_mask"].sum()), 0)

    def test_social_disappearance_imputation_switch_changes_spatial_calculations_only(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            (root / "session.json").write_text(
                json.dumps(
                    {
                        "roi_list": [
                            "+ Polygon [[0, 0], [30, 0], [30, 20], [0, 20]]",
                            "+ Polygon [[0, 0], [30, 0], [30, 20], [0, 20]]",
                        ]
                    }
                ),
                encoding="utf-8",
            )
            trajectory = root / "trajectories.npy"
            arr = np.zeros((30, 2, 2), dtype=float)
            arr[10:15, 0, :] = [
                [0, 5], [1, 5], [2, 5], [3, 5], [4, 5]
            ]
            arr[10:15, 1, :] = [
                [10, 5], [np.nan, np.nan], [np.nan, np.nan],
                [13, 5], [14, 5],
            ]
            np.save(trajectory, arr)
            off = analyze(
                trajectory, root, 10, 4, 30,
                analysis_type="fight",
                social_distance_threshold_px=60,
                use_social_disappearance_in_calculations=False,
            )
            on = analyze(
                trajectory, root, 10, 4, 30,
                analysis_type="fight",
                social_distance_threshold_px=60,
                use_social_disappearance_in_calculations=True,
            )
            animal_off = off[1]
            animal_on = on[1]
            self.assertEqual(animal_off["social_disappearance_frames"], 2)
            self.assertEqual(
                animal_off["total_distance_px_in_analysis_window"], 1
            )
            self.assertEqual(
                animal_on["total_distance_px_in_analysis_window"], 22
            )
            self.assertEqual(
                animal_on["social_disappearance_imputed_frames"], 2
            )
            self.assertEqual(
                animal_on[
                    "coordinate_frames_used_in_distance_and_location_calculations"
                ],
                5,
            )
            self.assertEqual(
                animal_on["frames_inside_wall_buffer"]
                + animal_on["frames_outside_wall_buffer"],
                5,
            )
            self.assertEqual(
                animal_on["frames_in_fungus_edge_buffer"]
                + animal_on["frames_in_fungus_interior"],
                animal_on["frames_on_fungus"],
            )
            self.assertEqual(
                animal_on["frames_on_fungus"],
                5,
            )
            self.assertEqual(
                animal_on["valid_coordinate_frames_in_window"], 3
            )
            self.assertEqual(
                animal_on["missing_coordinate_frames_in_window"], 2
            )
            self.assertEqual(
                animal_on[
                    "remaining_missing_coordinate_frames_after_social_substitution"
                ],
                0,
            )
            self.assertEqual(
                animal_on["threshold_crossing_global_frame"],
                animal_off["threshold_crossing_global_frame"],
            )
            self.assertIn(
                "SOCIAL_DISAPPEARANCE_IMPUTATION_USED",
                animal_on["warning"],
            )

    def test_pdf_plot_is_generated_for_identified_video_and_cell(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            (root / "session.json").write_text(
                json.dumps(
                    {
                        "roi_list": [
                            "+ Polygon [[0, 0], [20, 0], [20, 20], [0, 20]]",
                            "+ Polygon [[5, 5], [15, 5], [15, 15], [5, 15]]",
                        ]
                    }
                ),
                encoding="utf-8",
            )
            trajectory = root / "without_gaps.npy"
            arr = np.zeros((30, 2, 2), dtype=float)
            arr[10:16, 0, :] = [
                [2, 10], [4, 10], [6, 10],
                [8, 10], [10, 10], [12, 10],
            ]
            arr[10:16, 1, :] = [
                [18, 10], [16, 10], [14, 10],
                [12, 10], [10, 10], [8, 10],
            ]
            np.save(trajectory, arr)
            rows = analyze(
                trajectory, root, 10, 5, 4,
                fungus_buffer_px=2, analysis_type="fight",
            )
            pdf = root / "audit.pdf"
            write_plot_pdf(
                pdf,
                trajectory,
                root,
                rows,
                "fight",
                "Camera_1_12345678_20260724_1200_FIGHT_ACT1.mp4",
                "C2",
                "QC_TEST",
            )
            self.assertTrue(pdf.read_bytes().startswith(b"%PDF"))
            self.assertGreater(pdf.stat().st_size, 10_000)
            try:
                from pypdf import PdfReader
            except ImportError:
                return
            reader = PdfReader(pdf)
            self.assertIn(
                "IDtracker analysis-window metadata",
                reader.pages[-1].extract_text(),
            )
            all_text = "\n".join(
                page.extract_text() or "" for page in reader.pages
            )
            self.assertIn(f"Script: v{SCRIPT_VERSION}", all_text)
            self.assertIn("One-frame anti-jump threshold", all_text)
            self.assertIn("Social-distance and disappearance", all_text)
            self.assertIn("Translucent ROI-buffer audit map", all_text)

    def test_interval_candidate_extraction_is_key_limited(self):
        document = {
            "tracking_intervals": [[62, 7262]],
            "unrelated": {"interval": [1, 2]},
        }
        self.assertEqual(
            find_interval_candidates(document),
            [(62, 7262, "session_json.tracking_intervals[0]")],
        )

    def test_remote_tilde_expansion(self):
        self.assertEqual(
            expand_remote_path("~/approved", "/home/researcher"),
            "/home/researcher/approved",
        )

    def test_known_manual_review_name_accepts_optional_extension(self):
        stem = normalized_video_name(
            "/data/Camera_1_40169154_20260629_1319_ACT1.mp4"
        )
        self.assertIn(stem, KNOWN_START_REVIEW_STEMS)
        self.assertEqual(
            normalized_video_name(stem),
            stem,
        )

    def test_video_fields_are_split_for_sorting_and_filtering(self):
        fields = parse_video_fields(
            "/videos/Camera_1_40169154_20260702_1310_FIGHT_ACT1.mp4"
        )
        self.assertEqual(fields["camera"], "1")
        self.assertEqual(fields["camera_id"], "40169154")
        self.assertEqual(fields["recording_date"], "20260702")
        self.assertEqual(fields["video_year"], "2026")
        self.assertEqual(fields["recording_time"], "1310")
        self.assertEqual(fields["act"], "ACT1")

    def test_video_year_handles_prefixed_2025_video_name(self):
        fields = parse_video_fields(
            "/videos/S3_Camera_1_40292452_20250729_2122.mp4"
        )
        self.assertEqual(fields["video_year"], "2025")
        self.assertEqual(fields["recording_date"], "20250729")

    def test_turtling_candidate_requires_tight_repeated_turning(self):
        angles = np.linspace(0, 12 * np.pi, 150)
        tight = np.column_stack(
            [100 + 10 * np.cos(angles), 200 + 10 * np.sin(angles)]
        )
        result = compute_turtling_candidates(tight)
        self.assertGreater(int(result["mask"].sum()), 0)
        self.assertGreaterEqual(len(result["events"]), 1)
        self.assertIn("PROVISIONAL", result["status"])

        broad = np.column_stack(
            [100 + 100 * np.cos(angles), 200 + 100 * np.sin(angles)]
        )
        broad_result = compute_turtling_candidates(broad)
        self.assertEqual(int(broad_result["mask"].sum()), 0)

    def test_fight_turtling_on_fungus_is_excluded_from_outputs(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            (root / "session.json").write_text(
                json.dumps(
                    {
                        "roi_list": [
                            "+ Polygon [[0, 0], [500, 0], [500, 500], [0, 500]]",
                            "+ Polygon [[70, 170], [130, 170], [130, 230], [70, 230]]",
                        ]
                    }
                ),
                encoding="utf-8",
            )
            trajectory = root / "without_gaps.npy"
            arr = np.zeros((220, 2, 2), dtype=float)
            angles = np.linspace(0, 12 * np.pi, 150)
            arr[10:160, 0, :] = np.column_stack(
                [100 + 10 * np.cos(angles), 200 + 10 * np.sin(angles)]
            )
            arr[10:160, 1, :] = [400, 400]
            np.save(trajectory, arr)
            animal0 = analyze(
                trajectory,
                root,
                start=10,
                window=149,
                threshold=30,
                analysis_type="fight",
            )[0]
            self.assertEqual(animal0["turtling_candidate_frames"], 0)
            self.assertEqual(animal0["turtling_candidate_events"], 0)
            self.assertEqual(
                animal0[
                    "turtling_candidate_proportion_of_detected_frames"
                ],
                0.0,
            )

    def test_script_version_matches_version_file_and_is_written(self):
        self.assertEqual(
            SCRIPT_VERSION,
            (Path(__file__).resolve().parents[1] / "VERSION")
            .read_text(encoding="utf-8")
            .strip(),
        )
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            trajectory = root / "without_gaps.npy"
            np.save(trajectory, np.zeros((30, 1, 2), dtype=float))
            row = analyze(trajectory, root, 10, 5, 30)[0]
            self.assertEqual(row["script_version"], SCRIPT_VERSION)
            self.assertEqual(set(row), set(OUTPUT_COLUMNS))

    def test_final_start_is_simple_and_original_start_is_archived(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            trajectory = root / "without_gaps.npy"
            np.save(trajectory, np.zeros((100, 1, 2), dtype=float))
            row = analyze(
                trajectory,
                root,
                start=20,
                window=5,
                threshold=30,
                analysis_start_original_global_frame=10,
                analysis_start_source="JUMP_AUDIT_APPROVED",
                analysis_start_adjustment_provenance="reviewed example",
            )[0]
            self.assertEqual(row["analysis_start_frame"], 20)
            self.assertEqual(row["analysis_end_frame_inclusive"], 25)
            self.assertEqual(row["archived_original_start_frame"], 10)
            self.assertEqual(
                row["start_frame_decision_source"],
                "JUMP_AUDIT_APPROVED",
            )
            self.assertEqual(
                row["start_frame_decision_provenance"],
                "reviewed example",
            )

    def test_combined_csv_preserves_rows_and_provenance(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            sources = []
            for number in (1, 2):
                source = root / f"source_{number}.csv"
                with source.open("w", newline="", encoding="utf-8") as stream:
                    writer = csv.DictWriter(
                        stream,
                        fieldnames=["analysis_start_frame", "idtracker_animal_id"],
                    )
                    writer.writeheader()
                    writer.writerow(
                        {
                            "analysis_start_frame": 10 * number,
                            "idtracker_animal_id": 0,
                        }
                    )
                sources.append(source)
            destination = root / "combined.csv"
            request = {
                "destination": str(destination),
                "items": [
                    {
                        "source_result_file": str(source),
                        "qc_record_id": f"QC{index}",
                        "video": f"video{index}.mp4",
                        "cell_label": f"A{index}",
                        "analysis_type": "ba",
                        "camera": str(index),
                        "camera_id": f"ID{index}",
                        "video_year": "2026",
                        "recording_date": "20260724",
                        "recording_time": f"120{index}",
                        "act": f"ACT{index}",
                        "processing_batch_id": "20260724_120000",
                        "processing_created_at": "2026-07-24T12:00:00-04:00",
                        "processing_execution_mode": "SLURM_ARRAY",
                    }
                    for index, source in enumerate(sources, 1)
                ],
            }
            result = subprocess.run(
                [sys.executable, "-c", COMBINE_RESULTS],
                input=json.dumps(request),
                text=True,
                capture_output=True,
                check=True,
            )
            self.assertEqual(json.loads(result.stdout)["rows"], 2)
            with destination.open(newline="", encoding="utf-8") as stream:
                reader = csv.DictReader(stream)
                self.assertEqual(
                    reader.fieldnames[:4],
                    ["cell_label", "video", "analysis_type", "video_year"],
                )
                rows = list(reader)
            self.assertEqual([row["qc_record_id"] for row in rows], ["QC1", "QC2"])
            self.assertEqual(rows[0]["analysis_start_frame"], "10")
            self.assertEqual(rows[0]["recording_date"], "20260724")
            self.assertEqual(rows[0]["video_year"], "2026")
            self.assertEqual(rows[0]["recording_time"], "1201")
            self.assertEqual(
                rows[0]["processing_created_at"],
                "2026-07-24T12:00:00-04:00",
            )
            self.assertEqual(
                rows[0]["processing_execution_mode"],
                "SLURM_ARRAY",
            )
            request["overwrite"] = True
            second = subprocess.run(
                [sys.executable, "-c", COMBINE_RESULTS],
                input=json.dumps(request),
                text=True,
                capture_output=True,
                check=True,
            )
            self.assertEqual(json.loads(second.stdout)["rows"], 2)
            self.assertFalse(
                any(root.glob("combined.csv.partial.*"))
            )

    def test_slurm_worker_and_finalizer_promote_only_complete_batch(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            status_folder = root / "status"
            result_folder = root / "results"
            plot_stage = root / "pdfs_staged"
            plot_folder = root / "pdfs_latest"
            for directory in (status_folder, result_folder, plot_stage):
                directory.mkdir()
            fake_processor = root / "fake_processor.py"
            fake_processor.write_text(
                "\n".join(
                    [
                        "import argparse,csv",
                        "from pathlib import Path",
                        "p=argparse.ArgumentParser()",
                        "p.add_argument('--output', required=True)",
                        "p.add_argument('--plot-output', required=True)",
                        "a=p.parse_args()",
                        "Path(a.output).parent.mkdir(parents=True, exist_ok=True)",
                        "with Path(a.output).open('w', newline='', encoding='utf-8') as f:",
                        "    w=csv.DictWriter(f, fieldnames=['script_version','value'])",
                        "    w.writeheader(); w.writerow({'script_version':'0.4.0','value':'7'})",
                        "Path(a.plot_output).write_bytes(b'%PDF-1.4 fake')",
                    ]
                ),
                encoding="utf-8",
            )
            result_file = result_folder / "00000.csv"
            plot_file = plot_stage / "00000.pdf"
            manifest = {
                "script_version": SCRIPT_VERSION,
                "remote_python": sys.executable,
                "processor_path": str(fake_processor),
                "combine_script": str(
                    Path(__file__).resolve().parents[1]
                    / "combine_results.py"
                ),
                "status_folder": str(status_folder),
                "matplotlib_cache": str(root / "mpl"),
                "plot_stage": str(plot_stage),
                "plot_folder": str(plot_folder),
                "plot_previous": str(root / "pdfs_previous"),
                "combined_stage": str(root / "combined_staged.csv"),
                "combined_destination": str(root / "combined_latest.csv"),
                "completion_marker": str(root / "batch_complete.json"),
                "items": [
                    {
                        "processor_args": [
                            "--output", str(result_file),
                            "--plot-output", str(plot_file),
                        ],
                        "source_result_file": str(result_file),
                        "plot_output": str(plot_file),
                        "qc_record_id": "QC1",
                        "video": "video.mp4",
                        "cell_label": "A1",
                        "analysis_type": "fight",
                        "camera": "1",
                        "camera_id": "123",
                        "video_year": "2026",
                        "recording_date": "20260724",
                        "recording_time": "1200",
                        "act": "ACT1",
                        "processing_batch_id": "BATCH1",
                        "processing_created_at": "2026-07-24T12:00:00-04:00",
                        "processing_execution_mode": "SLURM_ARRAY",
                    }
                ],
            }
            manifest_path = root / "manifest.json"
            manifest_path.write_text(
                json.dumps(manifest), encoding="utf-8"
            )
            environment = dict(os.environ, SLURM_ARRAY_TASK_ID="0")
            subprocess.run(
                [
                    sys.executable,
                    str(
                        Path(__file__).resolve().parents[1]
                        / "slurm_worker.py"
                    ),
                    str(manifest_path),
                ],
                env=environment,
                check=True,
            )
            subprocess.run(
                [
                    sys.executable,
                    str(
                        Path(__file__).resolve().parents[1]
                        / "slurm_finalize.py"
                    ),
                    str(manifest_path),
                ],
                check=True,
            )
            self.assertTrue((root / "batch_complete.json").is_file())
            self.assertTrue((root / "combined_latest.csv").is_file())
            self.assertTrue((plot_folder / "00000.pdf").is_file())
            self.assertFalse(plot_stage.exists())

    def test_slurm_finalizer_failure_preserves_previous_complete_outputs(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            status_folder = root / "status"
            plot_stage = root / "pdfs_staged"
            plot_folder = root / "pdfs_latest"
            status_folder.mkdir()
            plot_stage.mkdir()
            plot_folder.mkdir()
            (plot_stage / "new.pdf").write_bytes(b"new")
            (plot_folder / "old.pdf").write_bytes(b"old")
            combined_destination = root / "combined_latest.csv"
            combined_destination.write_text("old complete\n", encoding="utf-8")
            manifest = {
                "script_version": SCRIPT_VERSION,
                "remote_python": sys.executable,
                "combine_script": str(
                    Path(__file__).resolve().parents[1]
                    / "combine_results.py"
                ),
                "status_folder": str(status_folder),
                "plot_stage": str(plot_stage),
                "plot_folder": str(plot_folder),
                "plot_previous": str(root / "pdfs_previous"),
                "combined_stage": str(root / "combined_staged.csv"),
                "combined_destination": str(combined_destination),
                "completion_marker": str(root / "batch_complete.json"),
                "items": [
                    {
                        "source_result_file": str(root / "missing.csv"),
                        "plot_output": str(plot_stage / "new.pdf"),
                        "qc_record_id": "QC_FAILED",
                    }
                ],
            }
            manifest_path = root / "manifest.json"
            manifest_path.write_text(
                json.dumps(manifest), encoding="utf-8"
            )
            result = subprocess.run(
                [
                    sys.executable,
                    str(
                        Path(__file__).resolve().parents[1]
                        / "slurm_finalize.py"
                    ),
                    str(manifest_path),
                ],
                text=True,
                capture_output=True,
            )
            self.assertNotEqual(result.returncode, 0)
            self.assertEqual(
                combined_destination.read_text(encoding="utf-8"),
                "old complete\n",
            )
            self.assertEqual(
                (plot_folder / "old.pdf").read_bytes(),
                b"old",
            )
            self.assertFalse((root / "batch_complete.json").exists())

    def test_missing_start_report_and_atomic_validation(self):
        base = {
            "qc_record_id": "QC1",
            "video": "video.mp4",
            "camera": "1",
            "camera_id": "123",
            "recording_date": "20260701",
            "recording_time": "1200",
            "act": "ACT1",
            "cell_label": "A1",
            "analysis": "ba",
            "detected": "0",
            "status": "START_ZERO — correction required",
            "start": "",
            "source": "source_toml.tracking_intervals[0]",
            "session": "/session",
            "toml": "/source.toml",
        }
        report = make_missing_start_report([base])
        self.assertEqual(len(report), 1)
        report[0]["enter_start_global_frame"] = "62"
        updates = validate_start_report_updates(report, [base])
        self.assertEqual(updates, [(base, 62)])
        duplicate = [dict(report[0]), dict(report[0])]
        with self.assertRaisesRegex(ValueError, "duplicate qc_record_id"):
            validate_start_report_updates(duplicate, [base])
        bad = [dict(report[0], enter_start_global_frame="0")]
        with self.assertRaisesRegex(ValueError, "greater than zero"):
            validate_start_report_updates(bad, [base])

    def test_missing_trajectory_report_names_specific_blocked_session(self):
        blocked = {
            "qc_record_id": "QC_BLOCKED",
            "video": "Camera_1_123_20260724_1200_FIGHT_ACT1.mp4",
            "camera": "1",
            "recording_date": "20260724",
            "recording_time": "1200",
            "act": "ACT1",
            "cell_label": "A1",
            "analysis": "fight",
            "trajectory_status": "NO_TRAJECTORY",
            "session": "/canonical/session",
            "raw_trajectory_candidates": ["/canonical/session/trajectories.npy"],
            "processable": False,
        }
        report = make_missing_trajectory_report([blocked])
        self.assertEqual(len(report), 1)
        self.assertEqual(
            report[0]["trajectory_status"], "NO_USABLE_TRAJECTORY"
        )
        self.assertEqual(report[0]["qc_record_id"], "QC_BLOCKED")


if __name__ == "__main__":
    unittest.main()
