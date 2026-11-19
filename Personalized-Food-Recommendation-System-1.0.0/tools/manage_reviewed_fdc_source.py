"""Inspect explicit FDC configuration, or install one digest-pinned source.

No app import, dotenv, credential or provider access. Default inspection opens
only an explicit existing SQLite file read-only. Installation requires both
--install-source and --policy-sha256; it never updates existing source policies.
"""

import argparse
import json
from pathlib import Path
import sqlite3
import sys


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))
sys.path.insert(0, str(ROOT / "tools"))

from repositories.nutrition_profile_repository import NutritionProfileSourceRepository
from repositories.sqlite_db import SqliteDatabase
from services.fdc_reviewed_source_lifecycle_service import (
    install_reviewed_fdc_source, load_installed_reviewed_fdc_sources, validate_reviewed_fdc_sources,
)
from services.nutrition_source_admission_service import source_policy_digest
from services.strict_json_service import parse_strict_model_json
from review_fdc_preview_admission import ReadOnlySourcePolicies


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--configuration", type=Path, required=True,
                        help="Server-owned JSON with exactly one reviewed_sources array")
    parser.add_argument("--database", type=Path, required=True, help="Existing initialized SQLite file")
    parser.add_argument("--install-source", help="Explicit source ID to install (writes SQLite)")
    parser.add_argument("--policy-sha256", help="Explicit reviewed policy digest required for installation")
    args = parser.parse_args()
    reader = sql = None
    try:
        if bool(args.install_source) != bool(args.policy_sha256):
            raise ValueError("Installation requires an explicit source and digest")
        raw = args.configuration.read_bytes()
        if len(raw) > 256 * 1024:
            raise ValueError("Configuration exceeds size budget")
        configuration = parse_strict_model_json(raw.decode("utf-8-sig"))
        if not isinstance(configuration, dict) or set(configuration) != {"reviewed_sources"}:
            raise ValueError("Use exactly the reviewed_sources field")
        entries = validate_reviewed_fdc_sources(configuration["reviewed_sources"])
        selected = None
        if args.install_source:
            selected = next((entry for entry in entries
                             if entry["policy"]["source_spec"]["source_id"] == args.install_source), None)
            if selected is None or source_policy_digest(selected["policy"]) != args.policy_sha256:
                raise ValueError("Source and digest must match the explicit configuration")
        path = args.database.resolve(strict=True)
        reader = ReadOnlySourcePolicies(path)
        if selected is None:
            _entries, report = load_installed_reviewed_fdc_sources(
                reviewed_sources=entries, load_installed_policy=reader.get, sqlite_available=True)
        else:
            # Require existing source tables before opening a writer; never
            # initialize a missing database/schema through this command.
            reader.connection.execute("SELECT source_id FROM nutrition_source_policies LIMIT 0")
            reader.connection.execute("SELECT source_id FROM nutrition_source_policy_versions LIMIT 0")
            reader.close()
            reader = None
            sql = SqliteDatabase(str(path))
            repository = NutritionProfileSourceRepository(sql, initialize_schema=False)
            report = install_reviewed_fdc_source(
                source_repository=repository, reviewed_source=selected,
                expected_policy_sha256=args.policy_sha256)
        print(json.dumps(report, ensure_ascii=True, indent=2, allow_nan=False))
        return 2 if report.get("decision") == "blocked" else 0
    except (OSError, ValueError, TypeError, KeyError, sqlite3.Error) as error:
        print(json.dumps({"decision": "blocked", "error": getattr(error, "code", "source_input_unavailable_or_invalid"),
                          "deployment_authorized": False}))
        return 2
    finally:
        if reader:
            reader.close()
        if sql:
            sql.close()


if __name__ == "__main__":
    raise SystemExit(main())
