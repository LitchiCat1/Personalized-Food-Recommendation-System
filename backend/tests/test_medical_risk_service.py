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

        # 兩邊都從同一份宣告算出來，數字對齊時就不該報成衝突
        aligned = {
            "hypertension": {
                "personalized_limits": {
                    "sodium": {"basis": "absolute", "daily_amount": 1800.0, "meals_per_day": 3}
                },
                "risk_nutrients": {"sodium": {"block": 600.0}},
            }
        }
        self.assertEqual(derived_meal_limits(aligned, PROFILE)["hypertension"]["sodium"], 600.0)
        self.assertEqual(rule_threshold_conflicts(aligned, PROFILE), [])

    def test_the_diabetes_disagreements_are_reported_too(self):
        """先前的比對清單是手抄的，整組糖尿病都沒被檢查到。"""
        from services.medical_risk_service import rule_threshold_conflicts

        pairs = {
            (c["condition_id"], c["nutrient"])
            for c in rule_threshold_conflicts(self.rules, PROFILE)
        }
        self.assertIn(("diabetes", "sugar"), pairs)
        self.assertIn(("diabetes", "carbs"), pairs)


class DeclaredLimitTests(MedicalRiskTestCase):
    """單餐上限的公式宣告在規則檔，程式只負責求值。"""

    def test_every_condition_declares_its_personalized_limits(self):
        for condition_id in ("diabetes", "gout", "hyperlipidemia", "hypertension", "kidney_disease"):
            with self.subTest(condition=condition_id):
                self.assertTrue(self.rules[condition_id].get("personalized_limits"))

    def test_an_energy_share_converts_to_grams(self):
        from services.medical_risk_service import resolve_personalized_limit

        # 每日 1800 kcal 的 25% 當脂肪，1g 脂肪 9 kcal，分三餐
        limit = resolve_personalized_limit(
            {"basis": "daily_energy", "share": 0.25, "kcal_per_gram": 9.0, "meals_per_day": 3},
            1800, 60,
        )
        self.assertAlmostEqual(limit, (1800 * 0.25) / 9 / 3, places=6)

    def test_a_cap_is_applied_before_dividing_by_meals(self):
        from services.medical_risk_service import resolve_personalized_limit

        # 5% of 4000 kcal = 50g 糖，但每日上限 25g，所以單餐是 25/3
        limit = resolve_personalized_limit(
            {"basis": "daily_energy", "share": 0.05, "kcal_per_gram": 4.0,
             "cap": 25.0, "meals_per_day": 3},
            4000, 60,
        )
        self.assertAlmostEqual(limit, 25.0 / 3, places=6)

    def test_ideal_body_weight_basis(self):
        from services.medical_risk_service import resolve_personalized_limit

        limit = resolve_personalized_limit(
            {"basis": "ideal_body_weight", "per_kg": 0.8, "meals_per_day": 3}, 1800, 60
        )
        self.assertAlmostEqual(limit, (60 * 0.8) / 3, places=6)

    def test_an_unknown_basis_is_ignored_rather_than_guessed(self):
        from services.medical_risk_service import resolve_personalized_limit

        self.assertIsNone(resolve_personalized_limit({"basis": "vibes"}, 1800, 60))

    def test_the_rules_file_is_data_not_code(self):
        """不支援字串運算式：規則檔不該能執行任意運算。"""
        from services.medical_risk_service import resolve_personalized_limit

        self.assertIsNone(resolve_personalized_limit({"formula": "E / 3"}, 1800, 60))

    def test_changing_the_declaration_changes_what_gets_blocked(self):
        """證明程式真的讀了宣告，而不是還在用內建數字。"""
        import copy

        rules = copy.deepcopy(self.rules)
        rules["hypertension"]["personalized_limits"]["sodium"] = {
            "basis": "absolute", "daily_amount": 300.0, "meals_per_day": 3,
        }
        result = evaluate_medical_risk(
            dish(sodium=150), ["hypertension"], [], rules, self.taxonomy, user_profile=PROFILE
        )
        self.assertIn("sodium", {r.get("nutrient") for r in result["risks"] if r["severity"] == "block"})


class MealLevelLimitTests(MedicalRiskTestCase):
    """單餐上限要對「一餐」生效，不能只對「一道菜」生效。

    personalized_limits 是每日總量 ÷ 3，也就是一餐的額度，但
    evaluate_medical_risk 是逐道菜呼叫的。結果是一餐點兩道各 490mg 的菜全部
    通過（合計 980mg），單獨一道 510mg 的反而被擋——同一個上限，兩種結論。
    """

    def test_two_dishes_each_under_the_limit_still_pass_individually(self):
        for _ in range(2):
            result = evaluate_medical_risk(
                dish(sodium=490), ["hypertension"], [], self.rules, self.taxonomy, user_profile=PROFILE
            )
            self.assertTrue(result["is_safe"])

    def test_the_meal_total_of_those_same_dishes_is_flagged(self):
        from services.medical_risk_service import evaluate_meal_medical_risk

        result = evaluate_meal_medical_risk(
            [{"nutrients": dish(sodium=490)}, {"nutrients": dish(sodium=490)}],
            ["hypertension"], [], self.rules, self.taxonomy, user_profile=PROFILE,
        )
        self.assertTrue(result["has_caution"])
        sodium_risks = [r for r in result["risks"] if r["nutrient"] == "sodium"]
        self.assertEqual(len(sodium_risks), 1)
        self.assertEqual(sodium_risks[0]["value"], 980.0)
        self.assertEqual(sodium_risks[0]["scope"], "meal")

    def test_a_meal_within_the_limit_is_not_flagged(self):
        from services.medical_risk_service import evaluate_meal_medical_risk

        result = evaluate_meal_medical_risk(
            [{"nutrients": dish(sodium=300)}, {"nutrients": dish(sodium=300)}],
            ["hypertension"], [], self.rules, self.taxonomy, user_profile=PROFILE,
        )
        self.assertFalse(result["has_caution"])

    def test_a_user_without_conditions_gets_no_meal_warnings(self):
        from services.medical_risk_service import evaluate_meal_medical_risk

        result = evaluate_meal_medical_risk(
            [{"nutrients": dish(sodium=5000)}], [], [], self.rules, self.taxonomy, user_profile=PROFILE,
        )
        self.assertEqual(result["caution_reasons"], [])

    def test_the_meal_check_scales_by_portion_like_the_per_dish_check(self):
        from services.medical_risk_service import evaluate_meal_medical_risk

        # 每 100g 400mg 的菜，吃 200g 就是 800mg，已超過 666.7mg 的單餐上限
        result = evaluate_meal_medical_risk(
            [{"nutrients": dish(sodium=400), "portion_g": 200}],
            ["hypertension"], [], self.rules, self.taxonomy, user_profile=PROFILE,
        )
        self.assertTrue(result["has_caution"])

    def test_the_per_dish_message_says_it_is_one_dish_not_the_meal(self):
        """訊息寫「單餐」會讓人以為整餐都算過了。"""
        result = evaluate_medical_risk(
            dish(sodium=900), ["hypertension"], [], self.rules, self.taxonomy, user_profile=PROFILE
        )
        message = " ".join(result["block_reasons"])
        self.assertIn("這一道", message)
        self.assertNotIn("單餐鈉", message)
