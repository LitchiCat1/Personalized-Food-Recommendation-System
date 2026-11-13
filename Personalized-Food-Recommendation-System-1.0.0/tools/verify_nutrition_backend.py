"""Run isolated backend regressions and write a credential-free result manifest."""

import argparse
from collections import Counter
import contextlib
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import sys
import tempfile
import time
import unittest


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    args.output = args.output.resolve()
    root = Path(__file__).resolve().parents[1]
    backend = root / "backend"
    os.environ["NUTRILENS_SKIP_LOCAL_ENV"] = "1"
    os.environ["DATABASE_PATH"] = ""
    for key in ("DATABASE_URL", "MONGO_URI", "MONGODB_URI", "NUTRILENS_TEST_DATABASE_URL",
                "AI_BASE_URL", "AI_MODEL", "AI_API_KEYS", "AI_RELAY_KEYS_FILE"):
        os.environ.pop(key, None)
    os.chdir(backend)
    sys.path.insert(0, str(backend))
    started = time.monotonic()
    with tempfile.TemporaryFile(mode="w+", encoding="utf-8") as logs:
        with contextlib.redirect_stdout(logs), contextlib.redirect_stderr(logs):
            suite = unittest.defaultTestLoader.discover(str(backend / "tests"))
            result = unittest.TextTestRunner(stream=logs, verbosity=1).run(suite)
        failures = [{"test": test.id(), "traceback": trace} for test, trace in result.failures + result.errors]
    report = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "scope": "isolated_backend_regression",
        "tests_run": result.testsRun,
        "passed": result.testsRun - len(result.skipped) - len(result.failures) - len(result.errors),
        "skipped": len(result.skipped),
        "skip_reasons": dict(Counter(reason for _test, reason in result.skipped)),
        "failures": len(result.failures), "errors": len(result.errors),
        "failure_details": failures,
        "successful": result.wasSuccessful(),
        "elapsed_seconds": round(time.monotonic() - started, 3),
        "isolation": {"skip_local_env": True, "database_path": "", "external_db_and_relay_env_cleared": True},
        "limitations": ["Real PostgreSQL integration tests require a separate configured test database",
                        "Mongo behavior uses offline test doubles; no live Mongo server",
                        "No new paid model or Tavily calls; no mobile UI or recognition accuracy evaluation"],
    }
    args.output.resolve().parent.mkdir(parents=True, exist_ok=True)
    args.output.resolve().write_text(json.dumps(report, ensure_ascii=True, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({key: report[key] for key in ("tests_run", "passed", "skipped", "failures", "errors", "successful", "elapsed_seconds")}))
    if failures:
        for failure in failures:
            print(failure["test"])
            print(failure["traceback"])
    return 0 if result.wasSuccessful() else 1


if __name__ == "__main__":
    raise SystemExit(main())
