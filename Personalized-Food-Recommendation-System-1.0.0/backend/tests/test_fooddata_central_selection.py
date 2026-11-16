import copy
import unittest

from services.fooddata_central_selection_service import (
    FdcCandidateSelectionError,
    CONFIRMATION_SCHEMA_VERSION,
    SNAPSHOT_SCHEMA_VERSION,
    SELECTION_SCHEMA_VERSION,
    build_fdc_candidate_selection_prompt,
    build_fdc_candidate_snapshot,
    validate_fdc_candidate_selection,
    validate_fdc_candidate_confirmation,
)


ITEM = {
    "item_id": "rice-sausage", "item_revision": 0, "name_zh": "糯米腸", "food_state": "prepared",
    "preparation_method": "steamed", "components_scope": "food_only", "brand": "吉林",
    "variant": None, "confidence": 0.99, "estimated_weight_g": 120,
    "health_conditions": ["not-for-model"],
}
CANDIDATES = [{
    "fdcId": "12345", "description": "Rice, glutinous, cooked", "dataType": "Survey (FNDDS)",
    "brandOwner": None, "foodCategory": "Grains",
}]


def make_snapshot(items=None, candidates=None, revision=7):
    items = [ITEM] if items is None else items
    candidates = {item["item_id"]: CANDIDATES for item in items} if candidates is None else candidates
    return build_fdc_candidate_snapshot(items, candidates, scan_revision=revision)


def output(snapshot, outcome="suggested", candidate_id="12345", reason="name_and_state_match"):
    return {"schema_version": SELECTION_SCHEMA_VERSION, "snapshot_digest": snapshot["snapshot_digest"],
            "scan_revision": snapshot["scan_revision"], "items": [{
                "item_id": "rice-sausage", "outcome": outcome,
                "candidate_fdc_id": candidate_id, "reason_code": reason,
            }]}


def confirmation(snapshot, decision="confirm", candidate_id="12345"):
    return {"schema_version": CONFIRMATION_SCHEMA_VERSION,
            "snapshot_digest": snapshot["snapshot_digest"],
            "scan_revision": snapshot["scan_revision"],
            "items": [{"item_id": "rice-sausage", "decision": decision,
                       "candidate_fdc_id": candidate_id}]}


class FdcCandidateSelectionTests(unittest.TestCase):
    def test_snapshot_is_normalized_and_excludes_untrusted_fields(self):
        snapshot = make_snapshot()
        self.assertEqual(snapshot["schema_version"], SNAPSHOT_SCHEMA_VERSION)
        self.assertEqual(len(snapshot["snapshot_digest"]), 64)
        self.assertEqual(snapshot["items"][0]["candidates"][0]["fdcId"], "12345")
        self.assertNotIn("confidence", snapshot["items"][0])
        self.assertNotIn("estimated_weight_g", snapshot["items"][0])
        self.assertNotIn("foodNutrients", snapshot["items"][0]["candidates"][0])

    def test_snapshot_is_stable_and_input_mutation_does_not_change_it(self):
        items = [copy.deepcopy(ITEM)]
        candidates = {ITEM["item_id"]: copy.deepcopy(CANDIDATES)}
        snapshot = build_fdc_candidate_snapshot(items, candidates, scan_revision=7)
        digest = snapshot["snapshot_digest"]
        items[0]["name_zh"] = "其他食品"
        candidates[ITEM["item_id"]][0]["description"] = "tampered"
        self.assertEqual(snapshot["snapshot_digest"], digest)
        self.assertEqual(snapshot["items"][0]["recognition_identity"]["name_zh"], "糯米腸")

    def test_prompt_contains_snapshot_digest_and_only_identity_candidate_data(self):
        snapshot = make_snapshot()
        prompt = build_fdc_candidate_selection_prompt(snapshot)
        self.assertIn("糯米腸", prompt)
        self.assertIn("Rice, glutinous, cooked", prompt)
        self.assertIn(snapshot["snapshot_digest"], prompt)
        self.assertIn("FdcCandidateSelectionV2", prompt)
        self.assertNotIn("0.99", prompt)
        self.assertNotIn("120", prompt)
        self.assertNotIn("foodNutrients", prompt)
        self.assertNotIn("not-for-model", prompt)

    def test_model_suggestion_is_always_demoted_to_confirmation_required(self):
        snapshot = make_snapshot()
        result = validate_fdc_candidate_selection(output(snapshot), snapshot=snapshot,
                                                   expected_items=[ITEM], scan_revision=7)
        self.assertEqual(result, [{"item_id": "rice-sausage", "item_revision": 0,
                                   "status": "confirmation_required",
                                   "suggested_fdc_id": "12345", "reason_code": "name_and_state_match",
                                   "requires_user_confirmation": True}])

    def test_ambiguous_and_no_match_never_select_food_or_values(self):
        snapshot = make_snapshot()
        for candidate_output, expected_status in (
                (output(snapshot, "ambiguous", None, "identity_uncertain"), "ambiguous"),
                (output(snapshot, "no_match", None, "no_supported_match"), "not_found")):
            result = validate_fdc_candidate_selection(candidate_output, snapshot=snapshot,
                                                       expected_items=[ITEM], scan_revision=7)
            self.assertEqual(result[0]["status"], expected_status)
            self.assertIsNone(result[0]["suggested_fdc_id"])
            self.assertTrue(result[0]["requires_user_confirmation"])

    def test_snapshot_drift_fails_closed(self):
        snapshot = make_snapshot()
        for changed in ({**snapshot, "scan_revision": 8},
                        {**snapshot, "snapshot_digest": "0" * 64},
                        {**snapshot, "item_set_digest": "0" * 64}):
            with self.subTest(changed=changed):
                with self.assertRaises(FdcCandidateSelectionError) as error:
                    build_fdc_candidate_selection_prompt(changed)
                self.assertIn(error.exception.code, {"plan_mismatch", "invalid_request"})

    def test_validator_rejects_wrong_model_digest_revision_and_candidate(self):
        snapshot = make_snapshot()
        cases = [{**output(snapshot), "snapshot_digest": "0" * 64},
                 {**output(snapshot), "scan_revision": 8},
                 {**output(snapshot, candidate_id="99999")}]
        for payload in cases:
            with self.subTest(payload=payload):
                with self.assertRaises(FdcCandidateSelectionError) as error:
                    validate_fdc_candidate_selection(payload, snapshot=snapshot,
                                                       expected_items=[ITEM], scan_revision=7)
                self.assertEqual(error.exception.code, "invalid_output")

    def test_validator_rejects_changed_current_identity_or_revision(self):
        snapshot = make_snapshot()
        for changed_item, revision in (({**ITEM, "name_zh": "糯米腸(品牌)"}, 7),
                                       (ITEM, 8), ({**ITEM, "brand": "其他"}, 7)):
            with self.subTest(changed_item=changed_item, revision=revision):
                with self.assertRaises(FdcCandidateSelectionError) as error:
                    validate_fdc_candidate_selection(output(snapshot), snapshot=snapshot,
                                                       expected_items=[changed_item], scan_revision=revision)
                self.assertEqual(error.exception.code, "plan_mismatch")

    def test_all_expected_items_must_appear_exactly_once(self):
        snapshot = make_snapshot()
        for rows in ([], [output(snapshot)["items"][0], output(snapshot)["items"][0]],
                     [{**output(snapshot)["items"][0], "item_id": "unrequested"}]):
            payload = {**output(snapshot), "items": rows}
            with self.assertRaises(FdcCandidateSelectionError):
                validate_fdc_candidate_selection(payload, snapshot=snapshot,
                                                   expected_items=[ITEM], scan_revision=7)

    def test_strict_json_rejects_duplicate_keys_and_nonfinite_values(self):
        snapshot = make_snapshot()
        for text in (
                '{"schema_version":"FdcCandidateSelectionV2","snapshot_digest":"' + snapshot["snapshot_digest"]
                + '","scan_revision":7,"items":[],"schema_version":"bad"}',
                '{"schema_version":"FdcCandidateSelectionV2","snapshot_digest":"' + snapshot["snapshot_digest"]
                + '","scan_revision":7,"items":[],"x":NaN}',
        ):
            with self.assertRaises(FdcCandidateSelectionError) as error:
                validate_fdc_candidate_selection(text, snapshot=snapshot,
                                                   expected_items=[ITEM], scan_revision=7)
            self.assertEqual(error.exception.code, "invalid_output")

    def test_snapshot_rejects_unknown_candidate_fields_and_bad_identity(self):
        for candidate in ({**CANDIDATES[0], "foodNutrients": []},
                          {**CANDIDATES[0], "fdcId": "012345"},
                          {**CANDIDATES[0], "dataType": "Branded"}):
            with self.subTest(candidate=candidate):
                with self.assertRaises(FdcCandidateSelectionError) as error:
                    make_snapshot(candidates={ITEM["item_id"]: [candidate]})
                self.assertEqual(error.exception.code, "invalid_request")
        with self.assertRaises(FdcCandidateSelectionError):
            make_snapshot(items=[{"item_id": "x"}], candidates={"x": []})

    def test_unknown_or_missing_identity_context_cannot_be_suggested(self):
        item = {**ITEM, "food_state": "unknown"}
        snapshot = make_snapshot(items=[item], candidates={"rice-sausage": CANDIDATES})
        with self.assertRaises(FdcCandidateSelectionError) as error:
            validate_fdc_candidate_selection(output(snapshot), snapshot=snapshot,
                                               expected_items=[item], scan_revision=7)
        self.assertEqual(error.exception.code, "invalid_output")
        self.assertEqual(validate_fdc_candidate_selection(
            output(snapshot, "ambiguous", None, "identity_uncertain"), snapshot=snapshot,
            expected_items=[item], scan_revision=7)[0]["status"], "ambiguous")

    def test_explicit_user_confirmation_can_choose_presented_candidate_only(self):
        snapshot = make_snapshot()
        result = validate_fdc_candidate_confirmation(
            confirmation(snapshot), snapshot=snapshot, expected_items=[ITEM], scan_revision=7)
        self.assertEqual(result, [{
            "item_id": "rice-sausage", "status": "confirmed_pending_revision", "item_revision": 0,
            "confirmed_fdc_id": "12345",
            "snapshot_digest": snapshot["snapshot_digest"], "scan_revision": 7,
            "identity_digest": snapshot["items"][0]["identity_digest"],
            "requires_new_scan_revision": True, "requires_user_confirmation": False,
        }])

    def test_legacy_generic_snapshot_cannot_be_suggested_or_confirmed(self):
        for name in ("菜葉", "葉菜", "綠色葉菜", "炒菜葉", "清炒葉菜"):
            with self.subTest(name=name):
                item = {**ITEM, "name_zh": name}
                snapshot = make_snapshot([item])
                original = copy.deepcopy(snapshot)
                with self.assertRaises(FdcCandidateSelectionError) as suggested:
                    validate_fdc_candidate_selection(
                        output(snapshot), snapshot=snapshot, expected_items=[item], scan_revision=7)
                self.assertEqual(suggested.exception.code, "invalid_output")
                with self.assertRaises(FdcCandidateSelectionError) as confirmed:
                    validate_fdc_candidate_confirmation(
                        confirmation(snapshot), snapshot=snapshot, expected_items=[item], scan_revision=7)
                self.assertEqual(confirmed.exception.code, "confirmation_required")
                self.assertEqual(snapshot, original)
                self.assertEqual(item["confidence"], ITEM["confidence"])

    def test_generic_snapshot_remains_ambiguous_deferred_or_rejected(self):
        item = {**ITEM, "name_zh": "炒菜葉"}
        snapshot = make_snapshot([item])
        selected = validate_fdc_candidate_selection(
            output(snapshot, "ambiguous", None, "identity_uncertain"),
            snapshot=snapshot, expected_items=[item], scan_revision=7)
        self.assertEqual(selected[0]["status"], "ambiguous")
        for decision, status in (("defer", "confirmation_required"), ("reject", "rejected")):
            with self.subTest(decision=decision):
                result = validate_fdc_candidate_confirmation(
                    confirmation(snapshot, decision, None), snapshot=snapshot,
                    expected_items=[item], scan_revision=7)
                self.assertEqual(result[0]["status"], status)
                self.assertIsNone(result[0]["confirmed_fdc_id"])
                self.assertFalse(result[0]["requires_new_scan_revision"])

    def test_specific_leafy_names_and_synonyms_can_still_be_confirmed(self):
        for name in ("大陸妹", "福山萵苣", "青江菜", "小白菜", "清炒青江菜"):
            with self.subTest(name=name):
                item = {**ITEM, "name_zh": name}
                snapshot = make_snapshot([item])
                selected = validate_fdc_candidate_selection(
                    output(snapshot), snapshot=snapshot, expected_items=[item], scan_revision=7)
                confirmed = validate_fdc_candidate_confirmation(
                    confirmation(snapshot), snapshot=snapshot, expected_items=[item], scan_revision=7)
                self.assertEqual(selected[0]["suggested_fdc_id"], "12345")
                self.assertEqual(confirmed[0]["confirmed_fdc_id"], "12345")

    def test_reject_and_defer_never_authorize_a_candidate(self):
        snapshot = make_snapshot()
        for decision, status, needs_confirmation in (("reject", "rejected", False),
                                                      ("defer", "confirmation_required", True)):
            result = validate_fdc_candidate_confirmation(
                confirmation(snapshot, decision, None), snapshot=snapshot,
                expected_items=[ITEM], scan_revision=7)
            self.assertEqual(result[0]["status"], status)
            self.assertIsNone(result[0]["confirmed_fdc_id"])
            self.assertEqual(result[0]["requires_user_confirmation"], needs_confirmation)
            self.assertFalse(result[0]["requires_new_scan_revision"])

    def test_confirmation_rejects_forged_candidate_snapshot_or_identity(self):
        snapshot = make_snapshot()
        cases = [confirmation(snapshot, candidate_id="99999"),
                 {**confirmation(snapshot), "snapshot_digest": "0" * 64},
                 {**confirmation(snapshot), "scan_revision": 8},
                 {**confirmation(snapshot), "items": [{"item_id": "rice-sausage",
                                                        "decision": "reject",
                                                        "candidate_fdc_id": "12345"}]}]
        for payload in cases:
            with self.subTest(payload=payload):
                with self.assertRaises(FdcCandidateSelectionError) as error:
                    validate_fdc_candidate_confirmation(payload, snapshot=snapshot,
                                                        expected_items=[ITEM], scan_revision=7)
                self.assertEqual(error.exception.code, "invalid_confirmation")

    def test_confirmation_requires_every_item_exactly_once(self):
        snapshot = make_snapshot()
        payload = confirmation(snapshot)
        payload["items"] = []
        with self.assertRaises(FdcCandidateSelectionError) as error:
            validate_fdc_candidate_confirmation(payload, snapshot=snapshot,
                                                expected_items=[ITEM], scan_revision=7)
        self.assertEqual(error.exception.code, "invalid_confirmation")

    def test_confirmation_uses_strict_json(self):
        snapshot = make_snapshot()
        digest = snapshot["snapshot_digest"]
        for text in (
                '{"schema_version":"FdcCandidateConfirmationV1","snapshot_digest":"' + digest
                + '","scan_revision":7,"items":[],"schema_version":"bad"}',
                '{"schema_version":"FdcCandidateConfirmationV1","snapshot_digest":"' + digest
                + '","scan_revision":7,"items":[],"x":NaN}',
        ):
            with self.assertRaises(FdcCandidateSelectionError) as error:
                validate_fdc_candidate_confirmation(text, snapshot=snapshot,
                                                     expected_items=[ITEM], scan_revision=7)
            self.assertEqual(error.exception.code, "invalid_confirmation")

    def test_snapshot_and_confirmation_reject_item_revision_drift(self):
        snapshot = make_snapshot()
        changed = {**ITEM, "item_revision": 1}
        with self.assertRaises(FdcCandidateSelectionError) as error:
            validate_fdc_candidate_selection(output(snapshot), snapshot=snapshot,
                                              expected_items=[changed], scan_revision=7)
        self.assertEqual(error.exception.code, "plan_mismatch")
        with self.assertRaises(FdcCandidateSelectionError) as error:
            validate_fdc_candidate_confirmation(confirmation(snapshot), snapshot=snapshot,
                                                expected_items=[changed], scan_revision=7)
        self.assertEqual(error.exception.code, "plan_mismatch")


if __name__ == "__main__":
    unittest.main()
