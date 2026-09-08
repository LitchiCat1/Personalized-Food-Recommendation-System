"""醫療風險判定的測試。

這個模組決定「腎臟病患者能不能吃這道菜」，卻一直沒有直接的測試。今天才在
裡面找到腎臟病蛋白質判定方向相反的 bug——那種錯誤只有靠測試才擋得住，
所以每一條會擋人的規則都要有一個會失敗的理由。
"""

import os
import unittest

from services.disease_rule_service import load_allergen_taxonomy, load_disease_rules
from services.medical_risk_service import evaluate_medical_risk

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# 身高 170cm → 理想體重 W = 22 * 1.7^2 = 63.58 kg，E = W * 30 = 1907 kcal
# 單餐上限一律取每日的 1/3
PROFILE = {"height": 170, "weight": 65, "age": 30}
W = 22.0 * 1.7 ** 2
E = W * 30


def dish(**overrides) -> dict:
    """一道各項都寬鬆的餐點，測哪一條規則就只把那一項推高。"""
    base = {
        "label": "test_dish",
        "name_zh": "清蒸雞胸飯",
        "calories": 300,
        "protein": 10,
        "carbs": 35,
        "sugar": 2,
        "fat": 6,
        "saturated_fat": 1.0,
        "trans_fat": 0,
        "fiber": 4,
        "sodium": 200,
        "allergens": [],
        "is_fried": False,
        "gi": "low",
    }
    base.update(overrides)
    return base


class MedicalRiskTestCase(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.rules = load_disease_rules(BASE_DIR)
        cls.taxonomy = load_allergen_taxonomy(BASE_DIR)

    def evaluate(self, candidate, conditions=(), allergens=()):
        return evaluate_medical_risk(
            candidate, list(conditions), list(allergens),
            self.rules, self.taxonomy, user_profile=PROFILE,
        )

    def blocked_nutrients(self, result) -> set:
        return {
            risk.get("nutrient")
            for risk in result["risks"]
            if risk.get("severity") == "block"
        }


class NoConditionsTests(MedicalRiskTestCase):
    def test_a_plain_dish_is_safe_when_nothing_is_configured(self):
        result = self.evaluate(dish())
        self.assertTrue(result["is_safe"])
        self.assertEqual(result["block_reasons"], [])

    def test_even_an_extreme_dish_passes_with_no_conditions(self):
        """沒有疾病條件時不該憑空擋人——那些門檻是疾病專屬的。"""
        result = self.evaluate(dish(calories=1500, sodium=3000, fat=90))
        self.assertTrue(result["is_safe"])


class AllergenTests(MedicalRiskTestCase):
    def test_a_declared_allergen_blocks_the_dish(self):
        result = self.evaluate(dish(name_zh="鮮蝦炒飯"), allergens=["shellfish"])
        self.assertFalse(result["is_safe"])

    def test_someone_elses_allergen_does_not_block_it(self):
        result = self.evaluate(dish(name_zh="鮮蝦炒飯"), allergens=["peanut"])
        self.assertTrue(result["is_safe"])


class TransFatTests(MedicalRiskTestCase):
    def test_trans_fat_is_blocked_for_every_condition(self):
        for condition in ("diabetes", "gout", "hyperlipidemia", "hypertension", "kidney_disease"):
            with self.subTest(condition=condition):
                result = self.evaluate(dish(trans_fat=0.5), conditions=[condition])
                self.assertIn("trans_fat", self.blocked_nutrients(result))

    def test_a_trace_amount_is_tolerated(self):
        """門檻是 0.1g；標示為 0 的食品實務上仍可能有微量。"""
        result = self.evaluate(dish(trans_fat=0.05), conditions=["hypertension"])
        self.assertNotIn("trans_fat", self.blocked_nutrients(result))


class HypertensionTests(MedicalRiskTestCase):
    def test_sodium_over_a_third_of_the_daily_limit_is_blocked(self):
        result = self.evaluate(dish(sodium=800), conditions=["hypertension"])
        self.assertIn("sodium", self.blocked_nutrients(result))

    def test_sodium_under_the_limit_passes(self):
        result = self.evaluate(dish(sodium=600), conditions=["hypertension"])
        self.assertNotIn("sodium", self.blocked_nutrients(result))

    def test_the_message_names_the_number_and_the_limit(self):
        result = self.evaluate(dish(sodium=900), conditions=["hypertension"])
        message = next(m for m in result["block_reasons"] if "鈉" in m)
        self.assertIn("900", message)
        # 生效的是 disease_rules.json 的 600mg（有 AHA／國健署引用），
        # 不是程式裡另外硬編碼的 2000/3。見 EffectiveLimitTests。
        self.assertIn("600", message)

    def test_calories_over_a_third_of_the_daily_energy_are_blocked(self):
        result = self.evaluate(dish(calories=int(E / 3) + 100), conditions=["hypertension"])
        self.assertIn("calories", self.blocked_nutrients(result))


class KidneyDiseaseTests(MedicalRiskTestCase):
    """腎臟病的蛋白質是「限量上限」，方向跟一般人的「至少吃到」相反。"""

    def test_high_protein_is_blocked_not_rewarded(self):
        result = self.evaluate(dish(protein=40), conditions=["kidney_disease"])
        self.assertIn("protein", self.blocked_nutrients(result))

    def test_low_protein_passes(self):
        result = self.evaluate(dish(protein=8), conditions=["kidney_disease"])
        self.assertNotIn("protein", self.blocked_nutrients(result))

    def test_the_protein_ceiling_follows_ideal_body_weight(self):
        limit = (W * 0.8) / 3.0
        self.assertNotIn(
            "protein",
            self.blocked_nutrients(self.evaluate(dish(protein=limit - 1), conditions=["kidney_disease"])),
        )
        self.assertIn(
            "protein",
            self.blocked_nutrients(self.evaluate(dish(protein=limit + 1), conditions=["kidney_disease"])),
        )

    def test_the_sodium_ceiling_is_stricter_than_for_hypertension(self):
        """腎臟病是 1500mg/日，高血壓是 2000mg/日。"""
        salty = dish(sodium=520)  # 介於 1500/3 與 2000/3 之間
        self.assertIn("sodium", self.blocked_nutrients(self.evaluate(salty, conditions=["kidney_disease"])))
        self.assertNotIn("sodium", self.blocked_nutrients(self.evaluate(salty, conditions=["hypertension"])))


class FriedFoodTests(MedicalRiskTestCase):
    def test_frying_is_forbidden_for_gout_and_hyperlipidemia(self):
        for condition in ("gout", "hyperlipidemia"):
            with self.subTest(condition=condition):
                result = self.evaluate(dish(name_zh="鹽酥雞", is_fried=True), conditions=[condition])
                self.assertTrue(
                    any(risk["type"] == "fried_food" and risk["severity"] == "block" for risk in result["risks"])
                )

    def test_frying_is_only_a_caution_for_the_other_conditions(self):
        for condition in ("diabetes", "hypertension", "kidney_disease"):
            with self.subTest(condition=condition):
                result = self.evaluate(dish(name_zh="炸雞排", is_fried=True), conditions=[condition])
                fried = [risk for risk in result["risks"] if risk["type"] == "fried_food"]
                self.assertTrue(fried)
                self.assertEqual({risk["severity"] for risk in fried}, {"caution"})


class HyperlipidemiaTests(MedicalRiskTestCase):
    def test_a_high_fat_meal_is_blocked(self):
        result = self.evaluate(dish(fat=60), conditions=["hyperlipidemia"])
        self.assertIn("fat", self.blocked_nutrients(result))

    def test_saturated_fat_has_its_own_stricter_ceiling(self):
        limit = (E * 0.07) / 9.0 / 3.0
        result = self.evaluate(dish(fat=10, saturated_fat=limit + 2), conditions=["hyperlipidemia"])
        self.assertIn("saturated_fat", self.blocked_nutrients(result))


class MultipleConditionsTests(MedicalRiskTestCase):
    def test_the_strictest_condition_wins(self):
        """同時有高血壓與腎臟病時，該用 1500mg 的那條。"""
        salty = dish(sodium=520)
        result = self.evaluate(salty, conditions=["hypertension", "kidney_disease"])
        self.assertIn("sodium", self.blocked_nutrients(result))

    def test_each_condition_reports_its_own_reason(self):
        result = self.evaluate(dish(sodium=900, protein=40), conditions=["hypertension", "kidney_disease"])
        conditions_named = {risk.get("condition_id") for risk in result["risks"] if risk["severity"] == "block"}
        self.assertEqual(conditions_named, {"hypertension", "kidney_disease"})


class EffectiveLimitTests(MedicalRiskTestCase):
    """同一個營養素有兩套門檻時，實際生效的是嚴的那個。

    `disease_rules.json` 是有引用、有審閱紀錄的治理檔案，`medical_risk_service`
    裡另外有一套依理想體重推算的公式。兩邊數字不一致時，較寬的那條等於死碼——
    審閱者看檔案簽核的數字，跟系統實際執行的可能不同。這裡把「較嚴者生效」
    釘住，讓任何一邊變動時測試會說話。
    """

    def test_hypertension_sodium_uses_the_configured_600_not_the_derived_667(self):
        self.assertNotIn("sodium", self.blocked_nutrients(
            self.evaluate(dish(sodium=590), conditions=["hypertension"])))
        self.assertIn("sodium", self.blocked_nutrients(
            self.evaluate(dish(sodium=610), conditions=["hypertension"])))

    def test_kidney_sodium_uses_the_derived_500_not_the_configured_600(self):
        self.assertIn("sodium", self.blocked_nutrients(
            self.evaluate(dish(sodium=520), conditions=["kidney_disease"])))

    def test_kidney_protein_uses_the_derived_ceiling_not_the_configured_40(self):
        self.assertIn("protein", self.blocked_nutrients(
            self.evaluate(dish(protein=25), conditions=["kidney_disease"])))

    def test_hyperlipidemia_fat_uses_the_derived_ceiling_not_the_configured_25(self):
        self.assertIn("fat", self.blocked_nutrients(
            self.evaluate(dish(fat=20), conditions=["hyperlipidemia"])))


class ProfileSensitivityTests(MedicalRiskTestCase):
    def test_a_shorter_person_gets_a_lower_ceiling(self):
        """門檻依理想體重換算，不是固定值。"""
        meal = dish(calories=560)
        tall = evaluate_medical_risk(
            meal, ["hypertension"], [], self.rules, self.taxonomy,
            user_profile={"height": 180, "weight": 75},
        )
        short = evaluate_medical_risk(
            meal, ["hypertension"], [], self.rules, self.taxonomy,
            user_profile={"height": 155, "weight": 48},
        )
        self.assertTrue(tall["is_safe"])
        self.assertFalse(short["is_safe"])


if __name__ == "__main__":
    unittest.main()


class ThresholdConflictReportTests(MedicalRiskTestCase):
    """兩套門檻不一致時要報出來，而不是靜靜地讓一邊失效。"""

    def test_the_known_disagreements_are_reported(self):
        from services.medical_risk_service import rule_threshold_conflicts

        conflicts = rule_threshold_conflicts(self.rules, PROFILE)
        pairs = {(c["condition_id"], c["nutrient"]) for c in conflicts}
        self.assertIn(("hypertension", "sodium"), pairs)
        self.assertIn(("kidney_disease", "protein"), pairs)

    def test_each_entry_says_which_side_is_ignored(self):
        from services.medical_risk_service import rule_threshold_conflicts

        for conflict in rule_threshold_conflicts(self.rules, PROFILE):
            self.assertIn(conflict["ignored_source"], {"configured", "derived"})
            self.assertEqual(
                conflict["effective_block"],
                min(conflict["configured_block"], conflict["derived_block"]),
            )

    def test_matching_thresholds_are_not_reported_as_conflicts(self):
        from services.medical_risk_service import derived_meal_limits, rule_threshold_conflicts

        derived = derived_meal_limits(PROFILE)
        aligned = {
            "hypertension": {
                "risk_nutrients": {"sodium": {"block": derived["hypertension"]["sodium"]}}
            }
        }
        self.assertEqual(rule_threshold_conflicts(aligned, PROFILE), [])
