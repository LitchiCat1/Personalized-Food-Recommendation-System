"""Inspect FDC preview configuration without importing app or opening a writer.

No dotenv, credentials, network, schema initialization or installation. The
default is repository defaults; --configuration reads an explicit non-secret
snapshot, never implies that it describes a deployed process or built bundle.
"""

import argparse
import json
from pathlib import Path
import sqlite3
import sys


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from services.fdc_preview_admission_service import (
    EXCLUDED_BACKEND_FLAGS, EXCLUDED_FRONTEND_FLAGS, REQUIRED_BACKEND_FLAGS,
    REQUIRED_FRONTEND_FLAGS, review_fdc_preview_configuration,
)
from services.fdc_reviewed_selection_service import PRODUCTION_REVIEWED_FDC_SOURCES
from services.nutrition_database_service import load_official_nutrition_dataset
from services.strict_json_service import parse_strict_model_json


class ReadOnlySourcePolicies:
    def __init__(self, path):
        path = Path(path).resolve(strict=True)
        if not path.is_file():
            raise ValueError("An existing SQLite file is required")
        self.connection = sqlite3.connect(path.as_uri() + "?mode=ro", uri=True, timeout=2)
        self.connection.row_factory = sqlite3.Row
        self.connection.execute("PRAGMA query_only = ON")
        # One stable snapshot for the whole review; it is not an installation lock.
        self.connection.execute("BEGIN")

    def get(self, source_id):
        row = self.connection.execute(
            "SELECT source_id, policy_id, policy_revision, status, policy FROM nutrition_source_policies "
            "WHERE source_id = ?", (source_id,)).fetchone()
        if row is None:
            return None
        return {"source_id": row["source_id"], "policy_id": row["policy_id"], "revision": row["policy_revision"],
                "status": row["status"], "policy": parse_strict_model_json(row["policy"])}

    def close(self):
        self.connection.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--configuration", type=Path, help="Explicit non-secret configuration snapshot JSON")
    parser.add_argument("--database", type=Path, help="Explicit existing SQLite file; read-only")
    args = parser.parse_args()
    reader = None
    try:
        configuration = {}
        if args.configuration:
            raw = args.configuration.read_bytes()
            if len(raw) > 256 * 1024:
                raise ValueError("Configuration exceeds size budget")
            configuration = parse_strict_model_json(raw.decode("utf-8-sig"))
            allowed = {"reviewed_sources", "backend_flags", "frontend_flags",
                       "authentication_required", "fdc_key_available"}
            if not isinstance(configuration, dict) or set(configuration) != allowed:
                raise ValueError("Use the exact documented non-secret snapshot fields")
        if args.database:
            reader = ReadOnlySourcePolicies(args.database)
        health = {name: load_official_nutrition_dataset(ROOT / "backend", name)["health"]
                  for name in ("TFDA", "USDA FNDDS")}
        report = review_fdc_preview_configuration(
            reviewed_sources=configuration.get("reviewed_sources", PRODUCTION_REVIEWED_FDC_SOURCES),
            load_installed_policy=reader.get if reader else None, official_health=health,
            backend_flags=configuration.get("backend_flags", dict.fromkeys(
                REQUIRED_BACKEND_FLAGS + EXCLUDED_BACKEND_FLAGS, False)),
            frontend_flags=configuration.get("frontend_flags", dict.fromkeys(
                REQUIRED_FRONTEND_FLAGS + EXCLUDED_FRONTEND_FLAGS, False)),
            sqlite_available=True if reader else None,
            authentication_required=configuration.get("authentication_required"),
            fdc_key_available=configuration.get("fdc_key_available"),
        )
        report["observations"] = {
            "configuration": "supplied_snapshot_not_runtime" if args.configuration else "repository_defaults_not_runtime",
            "installed_sources": "explicit_read_only_sqlite_snapshot" if reader else "not_inspected",
            "local_datasets": "actual_repository_files", "credentials": "not_read",
            "deployed_frontend_bundle": "not_inspected", "running_backend_flags": "not_inspected",
        }
        print(json.dumps(report, ensure_ascii=True, indent=2, allow_nan=False))
        return 0 if report["decision"] == "configuration_ready" else 2
    except (OSError, ValueError, sqlite3.Error):
        print(json.dumps({"decision": "blocked", "error": "admission_input_unavailable_or_invalid",
                          "deployment_authorized": False}))
        return 2
    finally:
        if reader:
            reader.close()


if __name__ == "__main__":
    raise SystemExit(main())
