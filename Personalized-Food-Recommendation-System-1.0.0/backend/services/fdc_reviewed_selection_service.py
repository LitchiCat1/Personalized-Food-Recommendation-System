"""Choose a unique reviewed reference, without making a user confirmation.

Configuration, installed source policy and persisted vision identity must agree.
This path performs no provider search, Detail fetch, profile or meal write.
"""

from copy import deepcopy
import math

from services.fdc_candidate_search_service import _eligible_for_search
from services.fdc_source_policy_service import validate_fdc_source_policy
from services.fooddata_central_selection_service import build_fdc_candidate_snapshot
from services.nutrition_source_admission_service import validate_source_admission
from services.web_nutrition_service import NutritionSourceRegistry


PRODUCTION_REVIEWED_FDC_SOURCES = ()
_LOCAL_STATUSES = {"matched", "source_conflict", "incomplete_profile",
                   "incompatible", "no_local_mapping"}


class FdcReviewedSelectionError(ValueError):
    def __init__(self, code, message):
        self.code = code
        super().__init__(message)


def _fail(code, message):
    raise FdcReviewedSelectionError(code, message)


def _weight(item):
    value = item.get("estimated_weight_g")
    if (isinstance(value, bool) or not isinstance(value, (int, float))
            or not math.isfinite(value) or not 0 < value <= 2000):
        return None
    return value


class FdcReviewedSelectionService:
    def __init__(self, *, scan_context_repository, snapshot_repository,
                 source_repository, local_lookup_factory, official_health,
                 reviewed_sources=PRODUCTION_REVIEWED_FDC_SOURCES):
        if not isinstance(reviewed_sources, (list, tuple)) or len(reviewed_sources) > 64:
            _fail("invalid_policy", "Reviewed sources must be a bounded server configuration")
        self.candidates = {}
        policies = []
        for entry in deepcopy(reviewed_sources):
            if not isinstance(entry, dict) or set(entry) != {"policy", "admission_review", "candidate"}:
                _fail("invalid_policy", "Reviewed source configuration is invalid")
            policy = validate_fdc_source_policy(
                validate_source_admission(entry["policy"], entry["admission_review"]))
            candidate, spec = entry["candidate"], policy["source_spec"]
            if (not isinstance(candidate, dict) or candidate.get("fdcId") != spec["fdc_id"]
                    or candidate.get("description") != spec["food_identity"]["name"]
                    or candidate.get("brandOwner") != spec["food_identity"]["brand"]):
                _fail("source_conflict", "Reviewed candidate metadata differs from its policy")
            # Reuse the existing strict metadata validator; these are reviewed
            # reference descriptors, never fabricated Search results.
            build_fdc_candidate_snapshot([
                {"item_id": "configuration-check", "item_revision": 0,
                 "name_zh": policy["accepted_names"][0], **policy["target_identity"]},
            ], {"configuration-check": [candidate]}, scan_revision=0)
            policies.append(policy)
            self.candidates[spec["source_id"]] = candidate
        self.registry = NutritionSourceRegistry(policies)
        self.scan_context_repository = scan_context_repository
        self.snapshot_repository = snapshot_repository
        self.source_repository = source_repository
        self.local_lookup_factory = local_lookup_factory
        self.official_health = official_health

    def select(self, *, authenticated_user_id, scan_id, scan_revision):
        """Persist only reference choices; the user must still explicitly confirm."""
        context = self.scan_context_repository.get_scan_context(
            user_id=authenticated_user_id, scan_id=scan_id,
            scan_revision=scan_revision, include_inactive=False)
        if context is None:
            _fail("scan_unavailable", "The server scan is unavailable")
        if any(not isinstance(self.official_health.get(source), dict)
               or self.official_health[source].get("status") != "available"
               for source in ("TFDA", "USDA FNDDS")):
            _fail("local_unavailable", "Official nutrition databases are not available")

        try:
            lookup = self.local_lookup_factory(authenticated_user_id)
        except Exception as error:
            raise FdcReviewedSelectionError("local_lookup_unavailable", "Local lookup is unavailable") from error
        mapping, selections = {}, []
        for item in context["items"]:
            item_id = item["item_id"]
            mapping[item_id] = []
            weight = _weight(item)
            reason = "identity_required"
            if _eligible_for_search(item):
                try:
                    local = lookup(item)
                except Exception as error:
                    raise FdcReviewedSelectionError("local_lookup_unavailable", "Local lookup failed") from error
                if not isinstance(local, dict) or local.get("status") not in _LOCAL_STATUSES:
                    _fail("invalid_local_result", "Local nutrition lookup returned an invalid result")
                reason = "local_priority" if local["status"] != "no_local_mapping" else "no_reviewed_source"
                if local["status"] == "no_local_mapping":
                    matches = []
                    for policy in self.registry.compatible(item):
                        current = self.source_repository.get_source_policy(policy["source_spec"]["source_id"])
                        if (current is not None and current.get("status") == "active"
                                and current.get("policy") == policy):
                            matches.append(policy)
                    if len(matches) > 1:
                        reason = "ambiguous_reviewed_source"
                    elif len(matches) == 1:
                        if weight is None:
                            reason = "weight_required"
                        else:
                            reason = "reviewed_match"
                            mapping[item_id] = [deepcopy(self.candidates[matches[0]["source_spec"]["source_id"]])]
            selections.append({"item_id": item_id, "weight_g": weight, "reason": reason})

        # This shares the existing immutable candidate/confirmation boundary.
        # A different raw Search snapshot cannot be overwritten or promoted.
        document = self.snapshot_repository.save_candidates(
            user_id=authenticated_user_id, scan_id=scan_id,
            scan_revision=scan_revision, candidates_by_item=mapping)
        return document, {
            "schema_version": "ReviewedFdcSelectionV1",
            "items": selections,
            "user_confirmation_required": True,
            "photo_confidence_changed": False,
        }
