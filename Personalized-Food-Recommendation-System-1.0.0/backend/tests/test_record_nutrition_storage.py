import copy
from concurrent.futures import ThreadPoolExecutor
import json
import os
import tempfile
import threading
import unittest

from repositories.sqlite_db import SqliteDatabase
from repositories.sqlite_schema import SCHEMA_VERSION, add_record_nutrition_contract, upgrade_schema
from repositories.storage import RECORD_COLUMNS, StorageRepository
from services.app_time_service import app_now
from services.history_service import build_history_response
from services.nutrition_profile_service import NUTRIENTS, UNITS, NutritionProfileError, build_nutrition_profile


def partial_record(identifier="partial"):
    cells = {field: None for field in NUTRIENTS}
    for field, value in {"calories": "300", "protein": "10", "carbs": "40", "fat": "10"}.items():
        cells[field] = {"value": value, "unit": UNITS[field], "comparison": "exact"}
    profile = build_nutrition_profile(cells, basis="per_100g", source_details={"source": "TFDA", "version": "fixture"})
    return {
        "user_id": "user-a", "client_record_id": identifier,
        "timestamp": app_now().isoformat(), "meal_type": "lunch", "source": "camera",
        "nutrition_contract_version": 2,
        "nutrition_context": {"revision": 0, "scan_id": "scan-fixture", "recognition_context": {"uncertainty_notes": ["occluded"]}},
        "foods": [
            {"item_id": "food-a", "name": "rice", "nutrition_profile": profile,
             "weight_g": 150, "portion_source": "user_adjusted", "included": True},
            {"item_id": "food-b", "name": "unknown sauce", "nutrition_profile": None,
             "weight_g": None, "portion_source": "unknown", "included": True},
        ],
    }


class RecordNutritionStorageTests(unittest.TestCase):
    def repositories(self):
        memory = StorageRepository({}, [], [])
        sql = SqliteDatabase(":memory:")
        self.addCleanup(sql.close)
        sqlite = StorageRepository({}, [], [], sql=sql)
        return {"memory": memory, "sqlite": sqlite}

    def test_nullable_profiles_context_and_unresolved_denominator_round_trip(self):
        for backend, repository in self.repositories().items():
            with self.subTest(backend=backend):
                incoming = partial_record()
                original = copy.deepcopy(incoming)
                repository.insert_record(incoming)
                saved = repository.get_record_by_client_record_id("user-a", "partial")
                self.assertEqual(incoming, original)
                self.assertIsNone(saved["foods"][0]["nutrition_profile"]["per_100g"]["sodium"])
                self.assertIsNone(saved["foods"][1]["nutrition_profile"])
                self.assertEqual(saved["foods"][0]["nutrition_profile"]["source_details"]["version"], "fixture")
                self.assertEqual(saved["nutrition_context"]["scan_id"], "scan-fixture")
                self.assertEqual(saved["nutrition_context"]["recognition_context"]["uncertainty_notes"], ["occluded"])
                coverage = saved["nutrition_context"]["coverage"]["nutrients"]
                self.assertEqual(coverage["calories"]["known_sum"], 450)
                self.assertEqual(coverage["calories"]["eligible_items"], 2)
                self.assertEqual(coverage["calories"]["unresolved_items"], 1)
                self.assertEqual(coverage["sodium"]["status"], "unknown")
                self.assertNotIn("_id", saved)

    def test_weight_edits_recalculate_from_original_profile_all_backends(self):
        for backend, repository in self.repositories().items():
            with self.subTest(backend=backend):
                repository.insert_record(partial_record())
                existing = repository.get_record_by_client_record_id("user-a", "partial")
                existing["foods"][0]["weight_g"] = 50
                existing["total_calories"] = 9999
                repository.update_record(existing)
                saved = repository.get_record_by_client_record_id("user-a", "partial")
                self.assertEqual(saved["total_calories"], 150)
                self.assertEqual(saved["foods"][0]["nutrition_profile"]["per_100g"]["calories"], 300)

    def test_read_results_do_not_alias_stored_snapshots(self):
        for backend, repository in self.repositories().items():
            with self.subTest(backend=backend):
                repository.insert_record(partial_record())
                first = repository.get_records("user-a")[0]
                first["foods"][0]["nutrition_profile"]["source_details"]["version"] = "tampered"
                second = repository.get_records("user-a")[0]
                self.assertEqual(second["foods"][0]["nutrition_profile"]["source_details"]["version"], "fixture")

    def test_stale_revision_cannot_overwrite_a_newer_snapshot(self):
        for backend, repository in self.repositories().items():
            with self.subTest(backend=backend):
                repository.insert_record(partial_record())
                first_edit = repository.get_record_by_client_record_id("user-a", "partial")
                stale_edit = copy.deepcopy(first_edit)
                first_edit["nutrition_context"]["revision"] = 1
                first_edit["foods"][0]["weight_g"] = 50
                self.assertIsNotNone(repository.update_record(first_edit, expected_revision=0))
                stale_edit["nutrition_context"]["revision"] = 1
                stale_edit["foods"][0]["weight_g"] = 900
                self.assertIsNone(repository.update_record(stale_edit, expected_revision=0))
                saved = repository.get_record_by_client_record_id("user-a", "partial")
                self.assertEqual(saved["foods"][0]["weight_g"], 50)
                self.assertEqual(saved["nutrition_context"]["revision"], 1)

    def test_simultaneous_revision_updates_have_only_one_winner(self):
        repositories = self.repositories()
        for backend in ("memory", "sqlite"):
            with self.subTest(backend=backend):
                repository = repositories[backend]
                repository.insert_record(partial_record())
                barrier = threading.Barrier(2)

                def save(weight):
                    record = repository.get_record_by_client_record_id("user-a", "partial")
                    record["foods"][0]["weight_g"] = weight
                    record["nutrition_context"]["revision"] = 1
                    barrier.wait(timeout=5)
                    return repository.update_record(record, expected_revision=0)

                with ThreadPoolExecutor(max_workers=2) as executor:
                    futures = [executor.submit(save, weight) for weight in (50, 90)]
                    results = [future.result(timeout=10) for future in futures]
                self.assertEqual(sum(result is not None for result in results), 1)
                saved = repository.get_record_by_client_record_id("user-a", "partial")
                self.assertEqual(saved["nutrition_context"]["revision"], 1)
                self.assertIn(saved["foods"][0]["weight_g"], (50, 90))

    def test_legacy_zeros_preserved_and_marked_unknown(self):
        for backend, repository in self.repositories().items():
            with self.subTest(backend=backend):
                legacy = {"user_id": "user-a", "client_record_id": "old", "timestamp": app_now().isoformat(),
                          "foods": [{"name": "legacy", "calories": 100, "sodium": 0}], "total_sodium": 0}
                repository.insert_record(legacy)
                saved = repository.get_records("user-a")[0]
                self.assertEqual(saved["foods"][0]["sodium"], 0)
                self.assertEqual(saved["total_sodium"], 0)
                self.assertEqual(saved["nutrition_contract_version"], 1)
                self.assertEqual(saved["nutrition_context"]["status"], "legacy_unknown")

    def test_history_covers_unresolved_items_and_rejects_legacy_projection(self):
        for backend, repository in self.repositories().items():
            with self.subTest(backend=backend):
                repository.insert_record(partial_record())
                with self.assertRaises(NutritionProfileError) as caught:
                    repository.get_history("user-a", 7)
                self.assertEqual(caught.exception.code, "upgrade_required")
                history = repository.get_history("user-a", 7, nutrition_contract_version=2)
                self.assertEqual(history[0]["calories"], 450)
                row = history[0]["nutrition_coverage"]["nutrients"]["sodium"]
                self.assertEqual(row["eligible_items"], 2)
                self.assertEqual(row["status"], "unknown")

    def test_legacy_delete_cannot_remove_a_version_two_record(self):
        for backend, repository in self.repositories().items():
            with self.subTest(backend=backend):
                repository.insert_record(partial_record())
                with self.assertRaises(NutritionProfileError) as caught:
                    repository.delete_record("user-a", "partial", nutrition_contract_version=1)
                self.assertEqual(caught.exception.code, "upgrade_required")
                self.assertIsNotNone(repository.get_record_by_client_record_id("user-a", "partial"))
                self.assertIsNotNone(repository.delete_record("user-a", "partial", nutrition_contract_version=2))
                self.assertIsNone(repository.get_record_by_client_record_id("user-a", "partial"))

    def test_legacy_update_cannot_overwrite_a_version_two_record(self):
        for backend, repository in self.repositories().items():
            with self.subTest(backend=backend):
                repository.insert_record(partial_record())
                legacy_edit = {"user_id": "user-a", "client_record_id": "partial",
                               "timestamp": app_now().isoformat(),
                               "foods": [{"name": "old edit", "calories": 0, "sodium": 0}]}
                with self.assertRaises(NutritionProfileError) as caught:
                    repository.update_record(legacy_edit, nutrition_contract_version=1)
                self.assertEqual(caught.exception.code, "upgrade_required")
                current = repository.get_record_by_client_record_id("user-a", "partial")
                self.assertEqual(current["nutrition_contract_version"], 2)
                self.assertEqual(current["foods"][0]["name"], "rice")
                self.assertEqual(current["nutrition_context"]["coverage"]["nutrients"]["calories"]["known_sum"], 450)

    def test_today_and_history_have_no_five_hundred_record_cap(self):
        repository = StorageRepository({}, [], [])
        # Bypass insertion deduplication to exercise the complete range reader.
        for index in range(502):
            record = partial_record(str(index))
            repository.mem_records.append(record)
        self.assertEqual(len(repository.get_today_records("user-a")), 502)
        day = repository.get_history("user-a", 7, nutrition_contract_version=2)[0]
        self.assertEqual(day["record_count"], 502)
        self.assertEqual(day["nutrition_coverage"]["nutrients"]["calories"]["eligible_items"], 1004)

    def test_sqlite_file_reopen_keeps_canonical_snapshot(self):
        with tempfile.TemporaryDirectory() as folder:
            path = os.path.join(folder, "nutrition.db")
            first_sql = SqliteDatabase(path)
            first = StorageRepository({}, [], [], sql=first_sql)
            first.insert_record(partial_record())
            first_sql.close()
            reopened_sql = SqliteDatabase(path)
            try:
                reopened = StorageRepository({}, [], [], sql=reopened_sql)
                saved = reopened.get_record_by_client_record_id("user-a", "partial")
                self.assertEqual(saved["nutrition_contract_version"], 2)
                self.assertIsNone(saved["foods"][0]["nutrition_profile"]["per_100g"]["sodium"])
                self.assertEqual(saved["nutrition_context"]["coverage"]["nutrients"]["calories"]["eligible_items"], 2)
            finally:
                reopened_sql.close()

    def test_history_summary_keeps_known_average_and_unknown_coverage(self):
        repository = StorageRepository({}, [], [])
        repository.insert_record(partial_record())
        response = build_history_response(repository, "user-a", 7, nutrition_contract_version=2)
        summary = response["summary"]
        self.assertEqual(summary["avg_calories"], 450)
        self.assertEqual(summary["avg_known_sum"]["calories"], 450)
        self.assertEqual(summary["nutrition_coverage"]["nutrients"]["calories"]["status"], "partial")
        self.assertEqual(summary["nutrition_coverage"]["nutrients"]["sodium"]["status"], "unknown")
        self.assertIsNone(summary["nutrition_coverage"]["nutrients"]["sodium"]["total_upper_bound"])

    def test_empty_v2_history_never_claims_complete(self):
        repository = StorageRepository({}, [], [])
        summary = build_history_response(repository, "user-a", 7, nutrition_contract_version=2)["summary"]
        self.assertIsNone(summary["avg_known_sum"]["sodium"])
        self.assertEqual(summary["nutrition_coverage"]["nutrients"]["sodium"]["status"], "unknown")

    def test_mixed_legacy_history_keeps_unknown_in_summary(self):
        repository = StorageRepository({}, [], [])
        repository.insert_record(partial_record())
        repository.insert_record({"user_id": "user-a", "client_record_id": "legacy",
                                  "timestamp": app_now().isoformat(),
                                  "foods": [{"name": "old", "calories": 100, "sodium": 0}]})
        summary = build_history_response(repository, "user-a", 7, nutrition_contract_version=2)["summary"]
        self.assertEqual(summary["avg_known_sum"]["calories"], 550)
        row = summary["nutrition_coverage"]["nutrients"]["calories"]
        self.assertEqual(row["status"], "legacy_unknown")
        self.assertEqual(row["eligible_items"], 3)
        self.assertEqual(row["known_items"], 1)
        self.assertEqual(row["legacy_items"], 1)

    def test_legacy_history_rejection_only_applies_to_requested_user_and_range(self):
        for backend, repository in self.repositories().items():
            with self.subTest(backend=backend):
                record = partial_record()
                record["timestamp"] = "2000-01-01T12:00:00+08:00"
                repository.insert_record(record)
                self.assertEqual(repository.get_history("user-a", 7), [])
                self.assertEqual(repository.get_history("another-user", 100000), [])


class NutritionSchemaMigrationTests(unittest.TestCase):
    def test_version_one_upgrade_preserves_legacy_row_and_is_idempotent(self):
        with tempfile.TemporaryDirectory() as folder:
            path = os.path.join(folder, "old.db")
            old = SqliteDatabase(path)
            old.execute("CREATE TABLE records (id INTEGER PRIMARY KEY, foods TEXT, total_sodium REAL)")
            old.execute("INSERT INTO records (foods,total_sodium) VALUES (?,?)", ('[{"name":"old","sodium":0}]', 0))
            old.set_user_version(1)
            old.close()
            sql = SqliteDatabase(path)
            try:
                backups = []
                self.assertEqual(upgrade_schema(sql, backup=backups.append), [2])
                self.assertEqual(sql.user_version(), SCHEMA_VERSION)
                self.assertEqual(backups, ["before-v2"])
                row = sql.query_one("SELECT * FROM records")
                self.assertEqual(row["total_sodium"], 0)
                self.assertIsNone(row["nutrition_context"])
                self.assertIsNone(row["nutrition_contract_version"])
                add_record_nutrition_contract(sql)
                self.assertEqual(upgrade_schema(sql, backup=backups.append), [])
                self.assertEqual(backups, ["before-v2"])
            finally:
                sql.close()


if __name__ == "__main__":
    unittest.main()
