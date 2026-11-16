"""Run the new enrichment regressions with all socket networking blocked."""

import argparse
from collections import Counter
import contextlib
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import socket
import sys
import tempfile
import time
import unittest
from unittest.mock import patch


PATTERNS = ("test_tavily_retrieval.py", "test_nutrition_source_adapter.py",
            "test_nutrition_extraction_model.py", "test_web_nutrition.py")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    output = args.output.resolve()
    root = Path(__file__).resolve().parents[1]
    backend = root / "backend"
    os.environ["NUTRILENS_SKIP_LOCAL_ENV"] = "1"
    os.environ["DATABASE_PATH"] = ""
    for key in ("DATABASE_URL", "MONGO_URI", "MONGODB_URI",
                "AI_BASE_URL", "AI_MODEL", "AI_API_KEYS", "AI_RELAY_KEYS_FILE", "TAVILY_API_KEY"):
        os.environ.pop(key, None)
    os.chdir(backend)
    sys.path.insert(0, str(backend))
    started = time.monotonic()
    def blocked(*_args, **_kwargs):
        raise AssertionError("Network access is forbidden in this offline verification")
    class BlockedSocket(socket.socket):
        def __new__(cls, *_args, **_kwargs):
            return blocked()
    with tempfile.TemporaryFile(mode="w+", encoding="utf-8") as logs:
        with contextlib.redirect_stdout(logs), contextlib.redirect_stderr(logs):
            with patch.object(socket, "socket", BlockedSocket), patch.object(socket, "create_connection", blocked), patch.object(socket, "getaddrinfo", blocked):
                suite = unittest.TestSuite(unittest.defaultTestLoader.discover(str(backend / "tests"), pattern=pattern) for pattern in PATTERNS)
                result = unittest.TextTestRunner(stream=logs, verbosity=1).run(suite)
        failures = [{"test": test.id(), "traceback": trace} for test, trace in result.failures + result.errors]
    report = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "scope": "bounded_tavily_enrichment_core_offline",
        "test_patterns": list(PATTERNS), "tests_run": result.testsRun,
        "passed": result.testsRun - len(result.skipped) - len(result.failures) - len(result.errors),
        "skipped": len(result.skipped), "skip_reasons": dict(Counter(reason for _test, reason in result.skipped)),
        "failures": len(result.failures), "errors": len(result.errors), "failure_details": failures,
        "successful": result.wasSuccessful(), "elapsed_seconds": round(time.monotonic() - started, 3),
        "isolation": {"network_socket_blocked": True, "skip_local_env": True,
                      "database_path": "", "external_db_and_relay_and_tavily_env_cleared": True},
        "production": {"automatic_enrichment_enabled": False, "reviewed_source_count": 0,
                       "route_connected": False, "persistent_cache_enabled": False},
        "limits": {"unique_foods": 4, "searches_per_food": 2, "extract_urls": 6,
                   "model_attempts": 1, "job_seconds": 25, "in_process_concurrency": 2},
        "limitations": ["Synthetic source policies do not grant rights for real websites",
                        "No new paid calls, user database access, UI or native-device verification",
                        "No public route, signed scan/profile repository or per-user durable budget",
                        "No cross-request cache/single-flight, source direct fetching or arbitrary HTML/PDF support",
                        "Cooperative deadline discards late output; no hard network cancellation guarantee",
                        "No weighed photo truth or recognition/nutrition accuracy claim"],
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, ensure_ascii=True, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({key: report[key] for key in ("tests_run", "passed", "skipped", "failures", "errors", "successful", "elapsed_seconds")}))
    for failure in failures:
        print(failure["test"])
        print(failure["traceback"])
    return 0 if result.wasSuccessful() else 1


if __name__ == "__main__":
    raise SystemExit(main())
