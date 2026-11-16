import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch


SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "scanner_browser_e2e_server.py"
SPEC = importlib.util.spec_from_file_location("scanner_browser_e2e_server", SCRIPT)
harness = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(harness)


class ScannerBrowserE2eHarnessTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory(prefix="nutrilens-scanner-browser-e2e-")
        self.addCleanup(self.directory.cleanup)
        self.database = Path(self.directory.name).resolve() / "scanner.sqlite3"

    def test_fresh_path_and_explicit_resume_require_database_marker(self):
        self.assertEqual(harness.validate_database_path(str(self.database)), self.database)
        self.database.touch()
        with self.assertRaises(SystemExit):
            harness.validate_database_path(str(self.database))
        with self.assertRaises(SystemExit):
            harness.validate_database_path(str(self.database), resume=True)
        harness.TestClock(self.database)
        self.assertEqual(harness.validate_database_path(str(self.database), resume=True), self.database)

    def test_resume_rejects_marker_for_different_database_and_malformed_state(self):
        harness.TestClock(self.database)
        marker = harness.state_path(self.database)
        state = json.loads(marker.read_text(encoding="utf-8"))
        for changes in (
            {"database_path": str(self.database) + ".other"},
            {"kind": "unknown"}, {"clock_offset_seconds": -1},
            {"clock_offset_seconds": True}, {"clock_offset_seconds": float("inf")},
        ):
            with self.subTest(changes=changes):
                marker.write_text(json.dumps({**state, **changes}), encoding="utf-8")
                with self.assertRaises(SystemExit):
                    harness.read_test_state(self.database)
        marker.write_text("[]", encoding="utf-8")
        with self.assertRaises(SystemExit):
            harness.read_test_state(self.database)

    def test_ordinary_temporary_directory_and_outside_temp_are_rejected(self):
        with tempfile.TemporaryDirectory(prefix="unrelated-") as directory:
            with self.assertRaises(SystemExit):
                harness.validate_database_path(str(Path(directory) / "database.sqlite3"))
        with self.assertRaises(SystemExit):
            harness.validate_database_path(str(SCRIPT.parent / "database.sqlite3"))

    def test_clock_offset_survives_restart_and_continues_real_time(self):
        with patch.object(harness.time, "time", return_value=1000):
            clock = harness.TestClock(self.database)
            self.assertEqual(clock(), 1000)
            self.assertEqual(clock.advance(121), 121)
            self.assertEqual(clock(), 1121)
        with patch.object(harness.time, "time", return_value=1010):
            resumed = harness.TestClock(self.database, resume=True)
            self.assertEqual(resumed(), 1131)
            self.assertEqual(resumed.advance(1), 122)

    def test_invalid_advances_do_not_change_persisted_clock(self):
        clock = harness.TestClock(self.database)
        for value in (True, None, "121", 0, -1, float("nan"), float("inf"), 86401):
            with self.subTest(value=value):
                with self.assertRaises(ValueError):
                    clock.advance(value)
                self.assertEqual(harness.read_test_state(self.database)["clock_offset_seconds"], 0)

    def test_control_configuration_does_not_enable_accept_or_detail(self):
        with patch.dict(harness.os.environ, {"DATABASE_URL": "must-remove"}, clear=True):
            harness.configure_environment(self.database)
            self.assertNotIn("DATABASE_URL", harness.os.environ)
            self.assertEqual(harness.os.environ["NUTRILENS_SKIP_LOCAL_ENV"], "1")
            self.assertEqual(harness.os.environ["NUTRITION_SCAN_CONTEXT_TTL_SECONDS"], "120")
            for flag in ("FDC_PROFILE_ACCEPT_ROUTE_ENABLED", "FDC_DETAIL_ROUTE_ENABLED",
                         "NUTRITION_ENRICHMENT_ROUTE_ENABLED"):
                self.assertEqual(harness.os.environ[flag], "false")

    def test_nonloopback_host_is_rejected_before_database_creation(self):
        with patch.object(harness, "parse_args", return_value=type("Args", (), {
            "host": "0.0.0.0", "database_path": str(self.database), "resume": False,
        })()):
            with self.assertRaises(SystemExit):
                harness.main()
        self.assertFalse(self.database.exists())
        self.assertFalse(harness.state_path(self.database).exists())
