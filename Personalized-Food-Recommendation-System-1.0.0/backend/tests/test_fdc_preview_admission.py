"""Deployment review must not mistake candidates or partial flags for readiness."""

from copy import deepcopy
from contextlib import redirect_stdout
import importlib.util
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

from repositories.nutrition_profile_repository import NutritionProfileSourceRepository
from repositories.sqlite_db import SqliteDatabase
from services.fdc_preview_admission_service import (
    EXCLUDED_BACKEND_FLAGS, EXCLUDED_FRONTEND_FLAGS, REQUIRED_BACKEND_FLAGS,
    REQUIRED_FRONTEND_FLAGS, review_fdc_preview_configuration,
)
from services.fdc_reviewed_selection_service import PRODUCTION_REVIEWED_FDC_SOURCES
from services.fdc_reviewed_source_lifecycle_service import load_installed_reviewed_fdc_sources
from services.nutrition_source_admission_service import source_policy_digest
from test_fdc_reviewed_selection import reviewed_source


ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location("fdc_admission_tool", ROOT / "tools" / "review_fdc_preview_admission.py")
tool = importlib.util.module_from_spec(spec)
spec.loader.exec_module(tool)


class FdcPreviewAdmissionTests(unittest.TestCase):
    def setUp(self):
        network = patch("socket.socket.connect", side_effect=AssertionError("Network forbidden"))
        network.start()
        self.addCleanup(network.stop)
        self.entry = reviewed_source()
        self.current = {"source_id": "usda-fdc-171688", "policy_id": self.entry["policy"]["policy_id"], "revision": 0,
                        "status": "active", "policy": deepcopy(self.entry["policy"])}
        self.arguments = dict(
            reviewed_sources=[self.entry], load_installed_policy=Mock(return_value=self.current),
            official_health={name: {"status": "available"} for name in ("TFDA", "USDA FNDDS")},
            backend_flags={**dict.fromkeys(REQUIRED_BACKEND_FLAGS, True),
                           **dict.fromkeys(EXCLUDED_BACKEND_FLAGS, False)},
            frontend_flags={**dict.fromkeys(REQUIRED_FRONTEND_FLAGS, True),
                            **dict.fromkeys(EXCLUDED_FRONTEND_FLAGS, False)},
            sqlite_available=True, authentication_required=True, fdc_key_available=True,
        )

    def review(self, **changes):
        return review_fdc_preview_configuration(**dict(self.arguments, **changes))

    def codes(self, report):
        return {block["code"] for block in report["blockers"]}

    def test_smallest_preview_scope_does_not_require_raw_search_detail_or_write_routes(self):
        report = self.review()
        self.assertEqual(report["decision"], "configuration_ready")
        self.assertFalse(report["deployment_authorized"])
        self.assertFalse(report["write_boundary"]["nutrition_profile_accept"])
        self.assertFalse(report["write_boundary"]["meal_record"])
        self.assertTrue(report["write_boundary"]["scan_snapshot_confirmation_and_preview_state"])
        self.assertEqual(report["sources"][0]["installation"], "active_exact_match")

    def test_production_configuration_stays_empty_and_candidates_are_not_installations(self):
        self.assertEqual(PRODUCTION_REVIEWED_FDC_SOURCES, ())
        self.assertIn("no_reviewed_sources", self.codes(self.review(reviewed_sources=())))
        self.assertIn("source_not_installed", self.codes(self.review(load_installed_policy=lambda _: None)))
        self.assertIn("installation_unverified", self.codes(self.review(load_installed_policy=None)))

    def test_every_required_flag_and_every_out_of_scope_flag_is_checked(self):
        for side, required, excluded in (
                ("backend_flags", REQUIRED_BACKEND_FLAGS, EXCLUDED_BACKEND_FLAGS),
                ("frontend_flags", REQUIRED_FRONTEND_FLAGS, EXCLUDED_FRONTEND_FLAGS)):
            for name in required + excluded:
                with self.subTest(name=name):
                    changed = dict(self.arguments[side], **{name: name in excluded})
                    report = self.review(**{side: changed})
                    self.assertEqual(report["decision"], "blocked")
                    self.assertIn(name, {block["target"] for block in report["blockers"]})
            for value in (None, "false", "true", 0, 1):
                with self.subTest(side=side, value=value):
                    self.assertIn("flag_unverified", self.codes(self.review(**{
                        side: dict(self.arguments[side], **{required[0]: value})})))

    def test_prerequisites_and_both_actual_local_datasets_are_required(self):
        for name in ("sqlite_available", "authentication_required", "fdc_key_available"):
            for value in (None, False, 1, "true"):
                with self.subTest(name=name, value=value):
                    self.assertEqual(self.review(**{name: value})["decision"], "blocked")
        for name in ("TFDA", "USDA FNDDS"):
            health = deepcopy(self.arguments["official_health"])
            health[name]["status"] = "unavailable"
            self.assertIn("local_dataset_unavailable", self.codes(self.review(official_health=health)))

    def test_policy_drift_withdrawal_duplicates_invalid_reviews_and_lookup_errors_fail_closed(self):
        for mutate in (
                lambda entry: entry["policy"]["accepted_names"].append("unreviewed"),
                lambda entry: entry["admission_review"].update(publisher_rights_approved=False),
                lambda entry: entry["candidate"].update(fdcId="1750340")):
            entry = deepcopy(self.entry)
            mutate(entry)
            self.assertIn("invalid_reviewed_sources", self.codes(self.review(reviewed_sources=[entry])))
        self.assertIn("invalid_reviewed_sources", self.codes(self.review(reviewed_sources=[self.entry, self.entry])))
        for changes, code in (({"status": "withdrawn"}, "source_inactive"),
                              ({"revision": True}, "installed_policy_mismatch"),
                              ({"source_id": "other"}, "installed_policy_mismatch"),
                              ({"policy_id": "other"}, "installed_policy_mismatch"),
                              ({"policy_id": None}, "installed_policy_mismatch"),
                              ({"policy": {}}, "installed_policy_mismatch")):
            with self.subTest(changes=changes):
                loader = Mock(return_value=dict(self.current, **changes))
                self.assertIn(code, self.codes(self.review(load_installed_policy=loader)))
        report = self.review(load_installed_policy=Mock(side_effect=RuntimeError("secret-path-and-key")))
        self.assertIn("source_lookup_failed", self.codes(report))
        self.assertNotIn("secret-path-and-key", json.dumps(report))

    def test_two_valid_installed_sources_cannot_claim_a_unique_match_for_the_same_identity(self):
        alternate = deepcopy(self.entry)
        policy = alternate["policy"]
        policy["policy_id"] = "other-reviewed-apple"
        policy["source_spec"].update(
            source_id="usda-fdc-12345", fdc_id="12345",
            source_url="https://api.nal.usda.gov/fdc/v1/food/12345", table_id="fdc-12345-per-100g")
        alternate["candidate"]["fdcId"] = "12345"
        alternate["admission_review"].update(source_id="usda-fdc-12345", policy_sha256=source_policy_digest(policy))
        loader = lambda source_id: {"source_id": source_id, "policy_id": (
                                    self.entry["policy"]["policy_id"] if source_id == "usda-fdc-171688" else policy["policy_id"]),
                                    "revision": 0, "status": "active",
                                    "policy": self.entry["policy"] if source_id == "usda-fdc-171688" else policy}
        self.assertIn("ambiguous_reviewed_sources", self.codes(self.review(
            reviewed_sources=[self.entry, alternate], load_installed_policy=loader)))

    def test_distinct_generic_and_fuji_sources_do_not_ambiguously_match(self):
        fuji = reviewed_source("1750340")
        loader = lambda source_id: {"source_id": source_id, "policy_id": (
                                    self.entry["policy"]["policy_id"] if source_id == "usda-fdc-171688" else fuji["policy"]["policy_id"]),
                                    "revision": 0, "status": "active",
                                    "policy": self.entry["policy"] if source_id == "usda-fdc-171688" else fuji["policy"]}
        self.assertEqual(self.review(reviewed_sources=[self.entry, fuji], load_installed_policy=loader)["decision"],
                         "configuration_ready")

    def test_sqlite_reader_never_initializes_schema_or_changes_database(self):
        with tempfile.TemporaryDirectory(prefix="nutrilens-admission-") as directory:
            path = Path(directory) / "review.db"
            sql = SqliteDatabase(str(path))
            sources = NutritionProfileSourceRepository(sql)
            sources.save_source_policy(self.entry["policy"])
            sql.close()
            before = path.read_bytes()
            reader = tool.ReadOnlySourcePolicies(path)
            try:
                self.assertEqual(self.review(load_installed_policy=reader.get)["decision"], "configuration_ready")
                with self.assertRaises(tool.sqlite3.OperationalError):
                    reader.connection.execute("DELETE FROM nutrition_source_policies")
            finally:
                reader.close()
            self.assertEqual(path.read_bytes(), before)
            with self.assertRaises(FileNotFoundError):
                tool.ReadOnlySourcePolicies(Path(directory) / "absent.db")
            self.assertFalse((Path(directory) / "absent.db").exists())

    def test_withdrawn_real_sqlite_policy_and_missing_schema_are_not_accepted(self):
        with tempfile.TemporaryDirectory(prefix="nutrilens-admission-") as directory:
            path = Path(directory) / "review.db"
            sql = SqliteDatabase(str(path))
            sources = NutritionProfileSourceRepository(sql)
            sources.save_source_policy(self.entry["policy"])
            sources.withdraw_source_policy("usda-fdc-171688", expected_revision=0)
            sql.close()
            reader = tool.ReadOnlySourcePolicies(path)
            try:
                self.assertIn("source_inactive", self.codes(self.review(load_installed_policy=reader.get)))
            finally:
                reader.close()
            empty = Path(directory) / "empty.db"
            connection = tool.sqlite3.connect(empty)
            connection.close()
            before = empty.read_bytes()
            reader = tool.ReadOnlySourcePolicies(empty)
            try:
                self.assertIn("source_lookup_failed", self.codes(self.review(load_installed_policy=reader.get)))
            finally:
                reader.close()
            self.assertEqual(empty.read_bytes(), before)

    def test_sqlite_policy_id_drift_is_rejected_by_both_review_and_startup_without_writes(self):
        with tempfile.TemporaryDirectory(prefix="nutrilens-admission-") as directory:
            path = Path(directory) / "review.db"
            sql = SqliteDatabase(str(path))
            sources = NutritionProfileSourceRepository(sql)
            sources.save_source_policy(self.entry["policy"])
            sql._conn.execute("UPDATE nutrition_source_policies SET policy_id = ? WHERE source_id = ?",
                              ("wrong-installed-policy", "usda-fdc-171688"))
            sql.close()
            before = path.read_bytes()
            reader = tool.ReadOnlySourcePolicies(path)
            try:
                report = self.review(load_installed_policy=reader.get)
                self.assertEqual(report["decision"], "blocked")
                self.assertIn("installed_policy_mismatch", self.codes(report))
                entries, startup = load_installed_reviewed_fdc_sources(
                    reviewed_sources=[self.entry], load_installed_policy=reader.get, sqlite_available=True)
                self.assertEqual(entries, ())
                self.assertEqual(startup["decision"], "blocked")
            finally:
                reader.close()
            self.assertEqual(path.read_bytes(), before)

    def test_cli_defaults_are_not_misreported_as_deployed_or_runtime_settings(self):
        output = io.StringIO()
        with patch.object(tool.sys, "argv", ["review_fdc_preview_admission.py"]), redirect_stdout(output):
            result = tool.main()
        report = json.loads(output.getvalue())
        self.assertEqual(result, 2)
        self.assertEqual(report["decision"], "blocked")
        self.assertEqual(report["observations"]["configuration"], "repository_defaults_not_runtime")
        self.assertEqual(report["observations"]["running_backend_flags"], "not_inspected")
        self.assertEqual(report["observations"]["local_datasets"], "actual_repository_files")
        self.assertEqual(report["observations"]["credentials"], "not_read")

    def test_cli_explicit_snapshot_and_database_are_read_only_and_not_deployment_consent(self):
        with tempfile.TemporaryDirectory(prefix="nutrilens-admission-") as directory:
            path = Path(directory) / "review.db"
            sql = SqliteDatabase(str(path))
            sources = NutritionProfileSourceRepository(sql)
            sources.save_source_policy(self.entry["policy"])
            sql.close()
            before = path.read_bytes()
            configuration = {key: self.arguments[key] for key in (
                "reviewed_sources", "backend_flags", "frontend_flags",
                "authentication_required", "fdc_key_available")}
            snapshot = Path(directory) / "configuration.json"
            snapshot.write_text(json.dumps(configuration), encoding="utf-8")
            arguments = ["review_fdc_preview_admission.py", "--configuration", str(snapshot), "--database", str(path)]
            output = io.StringIO()
            with patch.object(tool.sys, "argv", arguments), redirect_stdout(output):
                result = tool.main()
            report = json.loads(output.getvalue())
            self.assertEqual(result, 0)
            self.assertEqual(report["decision"], "configuration_ready")
            self.assertFalse(report["deployment_authorized"])
            self.assertEqual(report["observations"]["configuration"], "supplied_snapshot_not_runtime")
            self.assertEqual(before, path.read_bytes())
            configuration["secret"] = "not-a-real-key"
            snapshot.write_text(json.dumps(configuration), encoding="utf-8")
            output = io.StringIO()
            with patch.object(tool.sys, "argv", arguments), redirect_stdout(output):
                self.assertEqual(tool.main(), 2)
            self.assertNotIn("not-a-real-key", output.getvalue())
