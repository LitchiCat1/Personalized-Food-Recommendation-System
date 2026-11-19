"""Installation and restart must not undo source withdrawal or policy changes."""

from contextlib import redirect_stdout
from copy import deepcopy
import importlib.util
import io
import json
import os
from pathlib import Path
import sqlite3
import subprocess
import sys
import tempfile
import threading
import unittest
from unittest.mock import Mock, patch

from repositories.nutrition_profile_repository import NutritionProfileSourceRepository, NutritionRepositoryError
from repositories.sqlite_db import SqliteDatabase
from services.fdc_reviewed_selection_service import FdcReviewedSelectionService, PRODUCTION_REVIEWED_FDC_SOURCES
from services.fdc_reviewed_source_lifecycle_service import (
    FdcReviewedSourceLifecycleError, install_reviewed_fdc_source,
    load_installed_reviewed_fdc_sources,
)
from services.nutrition_source_admission_service import source_policy_digest
from test_fdc_reviewed_selection import ITEM, reviewed_source


ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location("fdc_source_manager", ROOT / "tools" / "manage_reviewed_fdc_source.py")
tool = importlib.util.module_from_spec(spec)
spec.loader.exec_module(tool)
SOURCE_ID = "usda-fdc-171688"


class FdcReviewedSourceLifecycleTests(unittest.TestCase):
    def setUp(self):
        network = patch("socket.socket.connect", side_effect=AssertionError("Network forbidden"))
        network.start()
        self.addCleanup(network.stop)
        self.folder = tempfile.TemporaryDirectory(prefix="nutrilens-source-lifecycle-")
        self.addCleanup(self.folder.cleanup)
        self.path = Path(self.folder.name) / "source.db"
        self.sql = SqliteDatabase(str(self.path))
        self.addCleanup(lambda: self.sql.close() if self.sql else None)
        self.repository = NutritionProfileSourceRepository(self.sql)
        self.entry = reviewed_source()
        self.digest = source_policy_digest(self.entry["policy"])

    def install(self, entry=None, repository=None, digest=None):
        return install_reviewed_fdc_source(
            source_repository=repository or self.repository,
            reviewed_source=self.entry if entry is None else entry,
            expected_policy_sha256=self.digest if digest is None else digest)

    def load(self, entries=None, loader=None, sqlite_available=True, configuration_path=None):
        return load_installed_reviewed_fdc_sources(
            reviewed_sources=[self.entry] if entries is None else entries,
            configuration_path=configuration_path,
            load_installed_policy=loader or (lambda source_id: self.repository.get_source_policy(
                source_id, include_withdrawn=True)), sqlite_available=sqlite_available)

    def reopen(self):
        if self.sql is not None:
            self.sql.close()
        self.sql = SqliteDatabase(str(self.path))
        self.repository = NutritionProfileSourceRepository(self.sql, initialize_schema=False)

    def counts(self):
        return tuple(self.sql.query_one(f"SELECT COUNT(*) AS n FROM {table}")["n"] for table in
                     ("nutrition_source_policies", "nutrition_source_policy_versions", "nutrition_profiles"))

    def test_install_is_explicit_digest_bound_and_idempotent_across_two_reopens(self):
        self.assertEqual(self.load()[1]["decision"], "blocked")
        first = self.install()
        self.assertEqual(first["action"], "installed")
        self.assertEqual(first["revision"], 0)
        self.assertEqual(first["policy_sha256"], self.digest)
        original = self.repository.get_source_policy(SOURCE_ID)
        for _ in range(2):
            self.reopen()
            entries, report = self.load()
            self.assertEqual(entries, (self.entry,))
            self.assertEqual(report["decision"], "ready")
            self.assertFalse(report["deployment_authorized"])
            self.assertEqual(self.install()["action"], "already_installed")
            self.assertEqual(self.repository.get_source_policy(SOURCE_ID), original)
            self.assertEqual(self.counts(), (1, 1, 0))

    def test_invalid_admission_descriptor_or_explicit_digest_cannot_write(self):
        for mutate in (
                lambda entry: entry["policy"]["accepted_names"].append("unreviewed"),
                lambda entry: entry["admission_review"].update(publisher_rights_approved=False),
                lambda entry: entry["candidate"].update(fdcId="1750340")):
            entry = deepcopy(self.entry)
            mutate(entry)
            with self.assertRaises(ValueError):
                self.install(entry=entry)
            self.assertEqual(self.counts(), (0, 0, 0))
        with self.assertRaises(FdcReviewedSourceLifecycleError):
            self.install(digest="0" * 64)
        self.assertEqual(self.counts(), (0, 0, 0))

    def test_memory_installation_is_rejected_and_empty_default_does_not_query(self):
        with self.assertRaises(NutritionRepositoryError) as caught:
            self.install(repository=NutritionProfileSourceRepository())
        self.assertEqual(caught.exception.code, "unsupported_database")
        loader = Mock(side_effect=AssertionError("Must not discover database sources"))
        entries, report = self.load(entries=PRODUCTION_REVIEWED_FDC_SOURCES, loader=loader,
                                    sqlite_available=False)
        self.assertEqual((entries, report["decision"]), ((), "empty"))
        loader.assert_not_called()

    def test_startup_load_is_read_only_and_does_not_discover_other_installed_sources(self):
        self.install()
        fuji = reviewed_source("1750340")
        self.install(entry=fuji, digest=source_policy_digest(fuji["policy"]))
        self.sql.close()
        self.sql = None
        before = self.path.read_bytes()
        reader = tool.ReadOnlySourcePolicies(self.path)
        try:
            entries, report = self.load(loader=reader.get)
            self.assertEqual(entries, (self.entry,))
            self.assertEqual(len(report["sources"]), 1)
            with self.assertRaises(sqlite3.OperationalError):
                reader.connection.execute("DELETE FROM nutrition_source_policies")
        finally:
            reader.close()
        self.assertEqual(self.path.read_bytes(), before)

    def test_explicit_configuration_file_is_read_only_and_cannot_install_or_reactivate(self):
        configuration = Path(self.folder.name) / "sources.json"
        configuration.write_text(json.dumps({"reviewed_sources": [self.entry]}), encoding="utf-8")
        self.assertEqual(self.load(entries=(), configuration_path=configuration)[1]["decision"], "blocked")
        self.assertEqual(self.counts(), (0, 0, 0))
        self.install()
        self.sql.close()
        self.sql = None
        before = self.path.read_bytes()
        reader = tool.ReadOnlySourcePolicies(self.path)
        try:
            entries, report = self.load(entries=(), loader=reader.get, configuration_path=configuration)
            self.assertEqual((entries, report["decision"]), ((self.entry,), "ready"))
        finally:
            reader.close()
        self.assertEqual(self.path.read_bytes(), before)
        self.reopen()
        self.repository.withdraw_source_policy(SOURCE_ID, expected_revision=0)
        self.assertEqual(self.load(entries=(), configuration_path=configuration)[1]["decision"], "blocked")
        self.assertEqual(self.counts(), (1, 2, 0))

    def test_invalid_configuration_files_fail_closed_without_paths_or_sql_writes(self):
        configuration = Path(self.folder.name) / "private-sources.json"
        cases = [None, b"{", b'{"reviewed_sources": [], "reviewed_sources": []}',
                 b'{"reviewed_sources": [], "extra": true}', b'{"reviewed_sources": null}',
                 b'{"reviewed_sources": [NaN]}', b"\xff", b" " * (256 * 1024 + 1)]
        loader = Mock(side_effect=AssertionError("Invalid configuration must not query SQLite"))
        for content in cases:
            with self.subTest(content_type=type(content).__name__, size=0 if content is None else len(content)):
                if content is not None:
                    configuration.write_bytes(content)
                entries, report = self.load(entries=(), loader=loader, configuration_path=configuration)
                self.assertEqual((entries, report["decision"]), ((), "blocked"))
                self.assertEqual(report["blockers"], [{"code": "invalid_reviewed_configuration"}])
                self.assertNotIn(str(configuration), json.dumps(report))
        for path in ("relative.json", self.folder.name):
            self.assertEqual(self.load(entries=(), loader=loader, configuration_path=path)[1]["decision"], "blocked")
        configuration.write_text(json.dumps({"reviewed_sources": [self.entry]}), encoding="utf-8")
        self.assertEqual(self.load(loader=loader, configuration_path=configuration)[1]["decision"], "blocked")
        loader.assert_not_called()
        self.assertEqual(self.counts(), (0, 0, 0))

    def test_withdrawal_is_not_reactivated_by_install_or_restart(self):
        self.install()
        self.repository.withdraw_source_policy(SOURCE_ID, expected_revision=0)
        for _ in range(2):
            self.reopen()
            self.assertEqual(self.load()[0], ())
            self.assertEqual(self.load()[1]["sources"][0]["state"], "source_inactive")
            with self.assertRaises(NutritionRepositoryError) as caught:
                self.install()
            self.assertEqual(caught.exception.code, "source_withdrawn")
            current = self.repository.get_source_policy(SOURCE_ID, include_withdrawn=True)
            self.assertEqual((current["status"], current["revision"]), ("withdrawn", 1))
            self.assertEqual(self.counts(), (1, 2, 0))
        with self.assertRaises(NutritionRepositoryError):
            self.repository.withdraw_source_policy(SOURCE_ID, expected_revision=0)

    def test_drift_is_not_overwritten_or_reloaded_even_with_a_new_valid_admission(self):
        self.install()
        updated = deepcopy(self.entry)
        updated["policy"]["compatibility_review"] += " Updated review text."
        updated_digest = source_policy_digest(updated["policy"])
        updated["admission_review"]["policy_sha256"] = updated_digest
        with self.assertRaises(NutritionRepositoryError) as caught:
            self.install(entry=updated, digest=updated_digest)
        self.assertEqual(caught.exception.code, "policy_changed")
        self.assertEqual(self.counts(), (1, 1, 0))
        self.repository.save_source_policy(updated["policy"], expected_revision=0)
        self.reopen()
        self.assertEqual(self.load()[0], ())
        self.assertEqual(self.load()[1]["sources"][0]["state"], "installed_policy_mismatch")
        with self.assertRaises(NutritionRepositoryError):
            self.install()
        self.assertEqual(self.repository.get_source_policy(SOURCE_ID)["revision"], 1)

    def test_failed_history_insert_rolls_back_current_policy_and_can_retry(self):
        execute = self.sql.execute

        def fail_history(statement, params=()):
            if "INSERT INTO nutrition_source_policy_versions" in statement:
                raise sqlite3.IntegrityError("injected history failure")
            return execute(statement, params)

        with patch.object(self.sql, "execute", side_effect=fail_history):
            with self.assertRaises(sqlite3.IntegrityError):
                self.install()
        self.assertEqual(self.counts(), (0, 0, 0))
        self.assertEqual(self.install()["action"], "installed")

    def test_two_connections_install_one_policy_and_one_history_revision(self):
        second_sql = SqliteDatabase(str(self.path))
        self.addCleanup(second_sql.close)
        second = NutritionProfileSourceRepository(second_sql, initialize_schema=False)
        barrier = threading.Barrier(2)
        actions, errors = [], []

        def run(repository):
            try:
                barrier.wait(timeout=5)
                actions.append(self.install(repository=repository)["action"])
            except Exception as error:
                errors.append(error)

        threads = [threading.Thread(target=run, args=(repository,))
                   for repository in (self.repository, second)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=15)
            self.assertFalse(thread.is_alive())
        self.assertEqual(errors, [])
        self.assertCountEqual(actions, ["installed", "already_installed"])
        self.assertEqual(self.counts(), (1, 1, 0))

    def test_install_and_withdrawal_race_cannot_leave_source_active(self):
        self.install()
        second_sql = SqliteDatabase(str(self.path))
        self.addCleanup(second_sql.close)
        second = NutritionProfileSourceRepository(second_sql, initialize_schema=False)
        barrier = threading.Barrier(2)
        errors = []

        def reinstall():
            barrier.wait(timeout=5)
            try:
                self.install(repository=second)
            except NutritionRepositoryError as error:
                if error.code != "source_withdrawn":
                    errors.append(error)

        def withdraw():
            barrier.wait(timeout=5)
            try:
                self.repository.withdraw_source_policy(SOURCE_ID, expected_revision=0)
            except Exception as error:
                errors.append(error)

        threads = [threading.Thread(target=target) for target in (reinstall, withdraw)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=15)
            self.assertFalse(thread.is_alive())
        self.assertEqual(errors, [])
        self.assertEqual(self.repository.get_source_policy(SOURCE_ID, include_withdrawn=True)["status"], "withdrawn")
        self.assertEqual(self.counts(), (1, 2, 0))

    def test_loaded_selection_still_rechecks_withdrawal_without_process_restart(self):
        self.install()
        entries, _report = self.load()
        scan = Mock()
        scan.get_scan_context.return_value = {"items": [ITEM]}
        snapshots = Mock()
        service = FdcReviewedSelectionService(
            scan_context_repository=scan, snapshot_repository=snapshots,
            source_repository=self.repository, local_lookup_factory=lambda _owner: lambda _item: {"status": "no_local_mapping"},
            official_health={name: {"status": "available"} for name in ("TFDA", "USDA FNDDS")},
            reviewed_sources=entries)
        request = dict(authenticated_user_id="user-a", scan_id="scan-reviewed", scan_revision=0)
        self.assertEqual(service.select(**request)[1]["items"][0]["reason"], "reviewed_match")
        self.repository.withdraw_source_policy(SOURCE_ID, expected_revision=0)
        self.assertEqual(service.select(**request)[1]["items"][0]["reason"], "no_reviewed_source")
        self.assertEqual(snapshots.save_candidates.call_args.kwargs["candidates_by_item"][ITEM["item_id"]], [])

    def test_invalid_unavailable_ambiguous_or_partially_installed_configuration_loads_nothing(self):
        self.install()
        for entries in ([self.entry, self.entry], [self.entry, reviewed_source("1750340")], None, {}):
            with self.subTest(entries_type=type(entries).__name__):
                actual = load_installed_reviewed_fdc_sources(
                    reviewed_sources=entries, load_installed_policy=lambda source_id: self.repository.get_source_policy(source_id),
                    sqlite_available=True)
                self.assertEqual(actual[0], ())
                self.assertEqual(actual[1]["decision"], "blocked")
        for available in (False, None, "true", 1):
            self.assertEqual(self.load(sqlite_available=available)[0], ())
        alternate = deepcopy(self.entry)
        policy = alternate["policy"]
        policy["policy_id"] = "other-apple"
        policy["source_spec"].update(source_id="usda-fdc-12345", fdc_id="12345",
                                     source_url="https://api.nal.usda.gov/fdc/v1/food/12345", table_id="fdc-12345-per-100g")
        alternate["candidate"]["fdcId"] = "12345"
        alternate["admission_review"].update(source_id="usda-fdc-12345", policy_sha256=source_policy_digest(policy))
        loader = Mock(side_effect=AssertionError("Invalid configuration cannot query SQLite"))
        self.assertEqual(self.load(entries=[self.entry, alternate], loader=loader)[0], ())
        loader.assert_not_called()

    def test_malformed_rows_and_lookup_errors_fail_closed_without_sensitive_diagnostics(self):
        self.install()
        current = self.repository.get_source_policy(SOURCE_ID)
        for changes in ({"source_id": "other"}, {"policy_id": "other"}, {"revision": True},
                        {"revision": -1}, {"policy": {}}, {"status": "unknown"}):
            with self.subTest(changes=changes):
                self.assertEqual(self.load(loader=lambda _source_id: dict(current, **changes))[0], ())
        entries, report = self.load(loader=Mock(side_effect=RuntimeError("private-path-and-secret")))
        self.assertEqual(entries, ())
        self.assertNotIn("private-path-and-secret", json.dumps(report))

    def cli(self, *extra):
        configuration = Path(self.folder.name) / "configuration.json"
        configuration.write_text(json.dumps({"reviewed_sources": [self.entry]}), encoding="utf-8")
        output = io.StringIO()
        with patch("sys.argv", ["manage_reviewed_fdc_source.py", "--configuration", str(configuration),
                                "--database", str(self.path), *extra]), redirect_stdout(output):
            code = tool.main()
        return code, json.loads(output.getvalue())

    def test_cli_defaults_to_read_only_then_explicit_install_and_restart_load(self):
        code, report = self.cli()
        self.assertEqual((code, report["decision"]), (2, "blocked"))
        self.assertEqual(self.counts(), (0, 0, 0))
        code, report = self.cli("--install-source", SOURCE_ID, "--policy-sha256", self.digest)
        self.assertEqual((code, report["action"]), (0, "installed"))
        self.reopen()
        self.assertEqual(self.cli()[1]["decision"], "ready")
        self.assertEqual(self.cli("--install-source", SOURCE_ID, "--policy-sha256", self.digest)[1]["action"], "already_installed")
        self.repository.withdraw_source_policy(SOURCE_ID, expected_revision=0)
        self.assertEqual(self.cli("--install-source", SOURCE_ID, "--policy-sha256", self.digest)[0], 2)
        self.assertEqual(self.cli()[1]["decision"], "blocked")
        self.assertEqual(self.counts(), (1, 2, 0))

    def test_fresh_app_processes_load_installed_source_and_disable_after_withdrawal(self):
        self.install()
        configuration = Path(self.folder.name) / "startup.json"
        configuration.write_text(json.dumps({"reviewed_sources": [self.entry]}), encoding="utf-8")
        environment = dict(os.environ, NUTRILENS_SKIP_LOCAL_ENV="1", DATABASE_PATH=str(self.path),
                           PYTHONPATH=str(ROOT / "backend"), AUTH_REQUIRED="true",
                           FDC_REVIEWED_SELECTION_ROUTE_ENABLED="true", AUTO_BACKUP_HOURS="0",
                           FDC_REVIEWED_SOURCES_FILE=str(configuration))
        for key in ("DATABASE_URL", "MONGO_URI", "MONGODB_URI", "AI_BASE_URL", "AI_MODEL", "AI_API_KEYS",
                    "AI_RELAY_KEYS_FILE", "TAVILY_API_KEY", "USDA_FDC_API_KEY", "FDC_API_KEY"):
            environment.pop(key, None)
        script = """
import json, socket, sys
from pathlib import Path
def reject_network(*args, **kwargs):
    raise AssertionError('Network forbidden')
socket.socket.connect = reject_network
import app
print(json.dumps({'decision': app.fdc_reviewed_source_load_report['decision'],
                  'enabled': app.fdc_reviewed_selection_route_enabled,
                  'source_ids': list(app.fdc_reviewed_selection_service.candidates)}))
app.sql_db.close()
"""

        def launch():
            child = subprocess.run([sys.executable, "-c", script, str(configuration)], cwd=ROOT,
                                   env=environment, text=True, encoding="utf-8", errors="replace",
                                   capture_output=True, timeout=40)
            self.assertEqual(child.returncode, 0, child.stderr + child.stdout)
            lines = child.stdout.strip().splitlines()
            diagnostic = json.loads(next(line.split("[INFO] FDC preview startup: ", 1)[1]
                                         for line in lines if line.startswith("[INFO] FDC preview startup: ")))
            result = json.loads(lines[-1])
            self.assertEqual(diagnostic["source_load"]["decision"], result["decision"])
            self.assertEqual(diagnostic["reviewed_selection"], result["enabled"])
            self.assertIs(diagnostic["fdc_key_available"], False)
            self.assertNotIn(str(configuration), json.dumps(diagnostic))
            return result

        for _ in range(2):
            self.assertEqual(launch(), {"decision": "ready", "enabled": True, "source_ids": [SOURCE_ID]})
        self.assertEqual(self.counts(), (1, 1, 0))
        self.repository.withdraw_source_policy(SOURCE_ID, expected_revision=0)
        self.assertEqual(launch(), {"decision": "blocked", "enabled": False, "source_ids": []})
        self.assertEqual(self.counts(), (1, 2, 0))
        configuration.write_text('{"reviewed_sources": []}', encoding="utf-8")
        self.assertEqual(launch(), {"decision": "empty", "enabled": False, "source_ids": []})

    def test_cli_rejects_missing_inputs_digest_or_schema_without_creating_or_initializing(self):
        for extra in (("--install-source", SOURCE_ID), ("--policy-sha256", self.digest),
                      ("--install-source", SOURCE_ID, "--policy-sha256", "0" * 64),
                      ("--install-source", "usda-fdc-1750340", "--policy-sha256", self.digest)):
            self.assertEqual(self.cli(*extra)[0], 2)
            self.assertEqual(self.counts(), (0, 0, 0))
        self.sql.close()
        self.sql = None
        original_path = self.path
        self.path = original_path.parent / "absent.db"
        self.assertEqual(self.cli()[0], 2)
        self.assertFalse(self.path.exists())
        self.path = original_path.parent / "empty.db"
        sqlite3.connect(self.path).close()
        before = self.path.read_bytes()
        self.assertEqual(self.cli("--install-source", SOURCE_ID, "--policy-sha256", self.digest)[0], 2)
        self.assertEqual(self.path.read_bytes(), before)


if __name__ == "__main__":
    unittest.main()
