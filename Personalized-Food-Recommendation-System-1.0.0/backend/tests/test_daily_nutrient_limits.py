from hashlib import sha256
from itertools import combinations
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from repositories.sqlite_db import SqliteDatabase
from repositories.storage import StorageRepository
from services.daily_nutrient_limits_service import OVERRIDES_FIELD, daily_nutrient_limit_specs
from services.healthy_food_service import _fit_penalty
from services.nutrition_progress_service import (
    build_daily_nutrition_progress, build_nutrition_goal_types, calculate_daily_targets_with_basis,
)
from test_api_routes import ApiTestBase


class DailyLimitFormulaTests(unittest.TestCase):
    def test_upper_limit_is_not_a_protein_shortfall_and_zero_budget_is_known(self):
        class Records:
            def get_all_records(self, *_):
                return [{"total_protein": 1}]

        user = {"health_conditions": ["kidney_disease"],
                OVERRIDES_FIELD: {"kidney_disease": {"protein": 25}}}
        daily = build_daily_nutrition_progress(Records(), "user-a", user)
        self.assertEqual(daily["targets"]["protein"], 25)
        self.assertNotIn("protein", {row["nutrient"] for row in daily["shortfalls"]})
        self.assertEqual(_fit_penalty({"sodium": 100}, {"sodium": 0}), 18)
        self.assertEqual(_fit_penalty({"sodium": 100}, {"sodium": None}), 0)
        self.assertEqual(_fit_penalty({"sodium": 0}, {"sodium": 0}), 0)

    def test_defaults_equal_pre_change_results_for_all_32_selected_condition_sets(self):
        cases = [
            ({"height": 170, "weight": 70, "age": 40, "gender": "female", "activity_multiplier": 1.55},
             "c59b2e5c3ea63c25835299de8850282fc7422b22d44e0387dd4d23dde52e9e8f"),
            ({"height": 182, "weight": 100, "age": 66, "gender": "male", "activity_multiplier": 1.2,
              "target_weight": 85, "daily_calorie_target": 2700},
             "e6d084ab66f15184a54a445e558224113797e694ff2b77cd0d1b762add3ad58f"),
        ]
        conditions = ("diabetes", "gout", "hyperlipidemia", "hypertension", "kidney_disease")
        for profile, digest in cases:
            results = []
            for size in range(len(conditions) + 1):
                for subset in combinations(conditions, size):
                    user = {**profile, "health_conditions": list(subset), OVERRIDES_FIELD: {}}
                    daily = calculate_daily_targets_with_basis(user, include_limit_settings=True)
                    daily.pop("daily_nutrient_limit_settings")
                    results.append([daily, build_nutrition_goal_types(user)])
            self.assertEqual(sha256(json.dumps(results, sort_keys=True).encode()).hexdigest(), digest)

    def test_sodium_increases_and_multicondition_sources(self):
        user = {"health_conditions": ["hypertension"], OVERRIDES_FIELD: {"hypertension": {"sodium": 2100}}}
        daily = calculate_daily_targets_with_basis(user, include_limit_settings=True)
        self.assertEqual(daily["targets"]["sodium"], 2100)
        self.assertEqual(daily["basis"]["default_sodium_target"], 2000)
        user["health_conditions"].append("kidney_disease")
        daily = calculate_daily_targets_with_basis(user, include_limit_settings=True)
        settings = daily["daily_nutrient_limit_settings"]
        self.assertEqual(daily["targets"]["sodium"], 1500)
        self.assertEqual(settings["hypertension"]["sodium"]["effective_condition_ids"], ["kidney_disease"])
        self.assertEqual(settings["hypertension"]["sodium"]["value"], 2100)

    def test_inactive_overrides_remain_saved_and_report_actual_active_rules(self):
        user = {"health_conditions": ["gout", "hyperlipidemia", "kidney_disease"],
                OVERRIDES_FIELD: {"kidney_disease": {"fat": 1, "saturated_fat": 2}}}
        daily = calculate_daily_targets_with_basis(user, include_limit_settings=True)
        settings = daily["daily_nutrient_limit_settings"]["kidney_disease"]
        self.assertFalse(settings["fat"]["active"])
        self.assertEqual(settings["fat"]["value"], 1)
        self.assertEqual(settings["saturated_fat"]["effective_condition_ids"], ["hyperlipidemia"])
        self.assertNotEqual(daily["targets"]["fat"], 1)

    def test_daily_budget_at_exact_upper_limit_and_positive_intake_with_zero_limit(self):
        class Records:
            def get_all_records(self, *_):
                return [{"total_sodium": 1200}]

        for limit, status, over in ((1400, "near_limit", 0), (1200, "near_limit", 0),
                                    (1199, "over", 1), (0, "over", 1200)):
            with self.subTest(limit=limit):
                user = {"health_conditions": ["hypertension"],
                        OVERRIDES_FIELD: {"hypertension": {"sodium": limit}}}
                daily = build_daily_nutrition_progress(Records(), "user-a", user)
                self.assertEqual(daily["targets"]["sodium"], limit)
                self.assertEqual(daily["remaining"]["sodium"], max(0, limit - 1200))
                self.assertEqual(daily["status"]["sodium"], status)
                self.assertEqual(daily["over_by"]["sodium"], over)


class DailyLimitApiTests(ApiTestBase):
    def _profile(self, **changes):
        return self.client.post("/user", json={"user_id": "user-a", "height": 170, "weight": 70, "age": 40,
            "health_conditions": ["hypertension"], **changes}, headers=self.auth_headers())

    def _records(self):
        return self.client.get("/records/user-a", headers=self.auth_headers()).get_json()

    def test_metadata_uses_same_specs_as_the_editor(self):
        metadata = self.client.get("/medical-metadata").get_json()
        specs = metadata["daily_nutrient_limit_specs"]
        self.assertEqual(specs, daily_nutrient_limit_specs())
        for condition in specs.values():
            for setting in condition.values():
                self.assertEqual(setting["step"], 1)
                self.assertEqual(setting["precision"], int(setting["unit"] == "g"))
        with self.mock_auth():
            response = self._profile(**{OVERRIDES_FIELD: {"hypertension": {"carbs": 123.4}}})
            self.assertEqual(response.status_code, 200)
            setting = response.get_json()["user"]["daily_nutrient_limit_settings"]["hypertension"]["carbs"]
            self.assertEqual((setting["value"], setting["step"], setting["precision"]), (123.4, 1, 1))

    def test_legacy_writes_and_unselection_preserve_until_explicit_clear(self):
        with self.mock_auth():
            first = self._profile(**{OVERRIDES_FIELD: {"hypertension": {"sodium": 0}}})
            self.assertEqual(first.status_code, 200)
            settings = first.get_json()["user"]["daily_nutrient_limit_settings"]
            self.assertEqual(settings["hypertension"]["sodium"]["value"], 0)
            self.assertEqual(self._records()["nutrition_targets"]["sodium"], 0)
            self.assertEqual(self._records()["nutrition_target_basis"]["default_sodium_target"], 2000)
            self.assertEqual(self._profile().get_json()["user"][OVERRIDES_FIELD], {"hypertension": {"sodium": 0}})
            patch_profile = self.client.post("/user", json={"user_id": "user-a", "name": "Updated name"},
                                             headers=self.auth_headers())
            self.assertEqual(patch_profile.get_json()["user"][OVERRIDES_FIELD], {"hypertension": {"sodium": 0}})
            unselected = self._profile(health_conditions=[]).get_json()["user"]
            self.assertEqual(unselected[OVERRIDES_FIELD], {"hypertension": {"sodium": 0}})
            self.assertEqual(unselected["daily_nutrient_limit_settings"], {})
            inactive_records = self._records()
            self.assertEqual(inactive_records["nutrition_targets"]["sodium"], 2000)
            self.assertNotIn("default_sodium_target", inactive_records["nutrition_target_basis"])
            reselected = self._profile().get_json()["user"]
            self.assertEqual(reselected["daily_nutrient_limit_settings"]["hypertension"]["sodium"]["value"], 0)
            self.assertEqual(self._records()["nutrition_targets"]["sodium"], 0)
            self.assertEqual(self._profile(**{OVERRIDES_FIELD: {}}).get_json()["user"][OVERRIDES_FIELD], {})

    def test_saving_another_condition_keeps_dormant_setting_and_validates_it(self):
        with self.mock_auth():
            overrides = {"hypertension": {"sodium": 1234}, "diabetes": {"sugar": 13.5}}
            response = self._profile(health_conditions=["diabetes"], **{OVERRIDES_FIELD: overrides})
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.get_json()["user"][OVERRIDES_FIELD], overrides)
            self.assertEqual(self._records()["nutrition_targets"]["sodium"], 2000)
            invalid = self._profile(health_conditions=["diabetes"], **{OVERRIDES_FIELD: {
                **overrides, "hypertension": {"sodium": -1},
            }})
            self.assertEqual(invalid.status_code, 400)
            self.assertEqual(self._profile().get_json()["user"][OVERRIDES_FIELD], overrides)
            self.assertEqual(self._records()["nutrition_targets"]["sodium"], 1234)

    def test_invalid_and_foreign_writes_do_not_replace_prior_settings(self):
        with self.mock_auth():
            first = self._profile(**{OVERRIDES_FIELD: {"hypertension": {"sodium": 1200}}})
            self.assertEqual(first.status_code, 200)
            for raw in (None, {"unknown": {"sodium": 20}}, {"hypertension": {"fiber": 1}},
                        {"hypertension": {"sodium": True}}, {"hypertension": {"sodium": 1200.5}},
                        {"hypertension": {"sodium": 10001}}, {"hypertension": {"sodium": float("nan")}}):
                with self.subTest(raw=raw):
                    self.assertEqual(self._profile(**{OVERRIDES_FIELD: raw}).status_code, 400)
        with self.mock_auth("user-b"):
            self.assertEqual(self._profile(**{OVERRIDES_FIELD: {}}).status_code, 403)
            self.assertEqual(self.client.get("/user/user-a", headers=self.auth_headers()).status_code, 403)
        with self.mock_auth():
            self.assertEqual(self._records()["nutrition_targets"]["sodium"], 1200)

    def test_sqlite_reload_keeps_override_without_changing_clinical_meal_limits(self):
        with TemporaryDirectory() as directory:
            path = str(Path(directory) / "test.db")
            with self.mock_auth():
                for reopen in (False, True):
                    sql = SqliteDatabase(path)
                    try:
                        storage = StorageRepository({}, [], [], sql=sql)
                        with patch.object(self.app_module, "storage", storage):
                            if not reopen:
                                self.assertEqual(self._profile().status_code, 200)
                                baseline = self._records()["meal_nutrient_limits"]
                                self.assertEqual(self._profile(**{OVERRIDES_FIELD: {"hypertension": {"sodium": 1234}}}).status_code, 200)
                            else:
                                read = self.client.get("/user/user-a", headers=self.auth_headers()).get_json()
                                self.assertEqual(read[OVERRIDES_FIELD], {"hypertension": {"sodium": 1234}})
                                self.assertEqual(read["daily_nutrient_limit_settings"], {})
                                self.assertEqual(self._records()["nutrition_targets"]["sodium"], 2000)
                                self.assertEqual(self._profile().status_code, 200)
                            self.assertEqual(self._records()["nutrition_targets"]["sodium"], 1234)
                            self.assertEqual(self._records()["meal_nutrient_limits"], baseline)
                            read = self.client.get("/user/user-a", headers=self.auth_headers()).get_json()
                            self.assertEqual(read[OVERRIDES_FIELD], {"hypertension": {"sodium": 1234}})
                            if not reopen:
                                self.assertEqual(self._profile(health_conditions=[]).status_code, 200)
                    finally:
                        sql.close()
