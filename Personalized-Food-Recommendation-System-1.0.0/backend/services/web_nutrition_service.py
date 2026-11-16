"""Bounded enrichment core for trusted server scan snapshots, not HTTP input.

The production registry is intentionally empty until source/service storage rights
and food compatibility have been reviewed. Public routes must additionally bind
the user, scan revision, quotas and saved profile authority before using this core.
"""

from copy import deepcopy
from datetime import datetime
import math
import threading
import time

from services.food_identity_service import requires_food_identity_confirmation
from services.nutrition_evidence_service import (
    NUTRIENTS, STATUSES, SCHEMA_VERSION, NutritionEvidenceError,
    build_nutrition_extraction_prompt, validate_and_build_nutrition_profiles,
)
from services.nutrition_extraction_model_service import NutritionExtractionModelError
from services.nutrition_profile_service import (
    NutritionProfileError, aggregate_nutrition_coverage, calculate_portion,
    profile_from_local_food,
)
from services.nutrition_source_adapter import (
    NutritionSourceAdapterError, build_reviewed_markdown_source,
)
from services.strict_json_service import parse_strict_model_json
from services.tavily_retrieval_service import TavilyRetrievalError, validate_reviewed_url
from services.vision_nutrition_service import find_vision_food_matches
from services.vision_food_service import VISION_FOOD_MIN_CONFIDENCE


MAX_ITEMS = 64
MAX_FOODS = 4
MAX_URLS = 6
MAX_SECONDS = 25
_JOBS = threading.BoundedSemaphore(2)
_IDENTITY_FIELDS = ("food_state", "preparation_method", "components_scope", "brand", "variant")
_NO_MATCH = {"no_local_mapping", "incompatible", "incomplete_profile"}


class WebNutritionError(ValueError):
    def __init__(self, code, message):
        self.code = code
        super().__init__(message)


def _require(condition, code, message):
    if not condition:
        raise WebNutritionError(code, message)


def _text(value, limit=128):
    return (isinstance(value, str) and 0 < len(value) <= limit and value.strip() == value
            and not any(ord(character) < 32 for character in value))


class NutritionSourceRegistry:
    """Only construct from reviewed server configuration, never a client payload."""

    def __init__(self, policies=()):
        _require(isinstance(policies, (list, tuple)) and len(policies) <= 64,
                 "invalid_policy", "Source policies must be a bounded sequence")
        self._policies = deepcopy(tuple(policies))
        identifiers, source_ids, urls = set(), set(), set()
        for policy in self._policies:
            _require(isinstance(policy, dict), "invalid_policy", "A source policy must be an object")
            identifier = policy.get("policy_id")
            _require(_text(identifier) and identifier not in identifiers, "invalid_policy", "Policy IDs must be unique")
            identifiers.add(identifier)
            spec = policy.get("source_spec")
            _require(isinstance(spec, dict) and _text(spec.get("source_id")), "invalid_policy", "An adapter specification is required")
            _require(spec["source_id"] not in source_ids, "invalid_policy", "Source IDs must be unique")
            source_ids.add(spec["source_id"])
            try:
                url = validate_reviewed_url(spec.get("source_url"))
            except TavilyRetrievalError:
                raise WebNutritionError("invalid_policy", "A policy URL is invalid") from None
            _require(url == spec["source_url"] and url not in urls, "invalid_policy", "Source URLs must be canonical and unique")
            urls.add(url)
            names = policy.get("accepted_names")
            _require(isinstance(names, (list, tuple)) and 0 < len(names) <= 16
                     and all(_text(name) for name in names), "invalid_policy", "Reviewed exact food aliases are required")
            target, source = policy.get("target_identity"), spec.get("food_identity")
            _require(isinstance(target, dict) and isinstance(source, dict), "invalid_policy", "Both food identities are required")
            enums = {"food_state": {"prepared", "raw", "dry"},
                     "preparation_method": {"boiled", "stir_fried", "pan_fried", "deep_fried", "roasted", "braised", "steamed", "mixed"},
                     "components_scope": {"food_only", "noodles_only", "whole_dish_with_broth", "with_sides"}}
            for field, values in enums.items():
                _require(isinstance(target.get(field), str) and target[field] in values
                         and target[field] == source.get(field), "invalid_policy", "Food state, preparation and scope must be explicitly reviewed")
            for field in ("brand", "variant"):
                _require(target.get(field) is None or _text(target[field]), "invalid_policy", "Brand and variant must be explicit or null")
            _require(policy.get("match_policy") in ("same_product", "reference_only"), "invalid_policy", "An explicit match policy is required")
            if policy["match_policy"] == "same_product":
                _require(all(target.get(field) == source.get(field) for field in ("brand", "variant")),
                         "invalid_policy", "Exact product matching cannot erase a source brand or variant")
            _require(_text(policy.get("compatibility_review"), 4096), "invalid_policy", "Compatibility review evidence is required")
            rights = policy.get("rights")
            _require(isinstance(rights, dict) and _text(rights.get("reference"), 4096), "invalid_policy", "A rights review reference is required")
            # A boolean permission is not enough to explain why a source may be
            # retained or reused. Keep the legal/operational evidence explicit so
            # a future production policy cannot silently turn a search result into
            # a shared nutrition snapshot.
            try:
                license_url = validate_reviewed_url(rights.get("license_url"))
            except TavilyRetrievalError:
                raise WebNutritionError("invalid_policy", "A source license URL is invalid") from None
            _require(license_url == rights.get("license_url"), "invalid_policy", "A source license URL must be canonical")
            _require(_text(rights.get("license_name"), 256), "invalid_policy", "A source license name is required")
            _require(_text(rights.get("attribution"), 1024), "invalid_policy", "A source attribution is required")
            _require(rights.get("reuse_scope") in ("single_request", "server_internal", "cross_user"),
                     "invalid_policy", "A source reuse scope is required")
            _require(rights.get("provider_cache_scope") in ("none", "server_internal", "cross_user_approved"),
                     "invalid_policy", "Provider cache scope is required")
            _require(not (rights.get("provider_cache_scope") == "cross_user_approved"
                          and rights.get("reuse_scope") != "cross_user"),
                     "invalid_policy", "Cross-user provider approval requires cross-user source reuse")
            _require(_text(rights.get("retention_policy"), 1024), "invalid_policy", "A retention policy is required")
            _require(_text(rights.get("withdrawal_policy"), 1024), "invalid_policy", "A withdrawal policy is required")
            _require(_text(rights.get("reviewer"), 256), "invalid_policy", "A rights reviewer is required")
            evidence_urls = rights.get("evidence_urls")
            _require(isinstance(evidence_urls, (list, tuple)) and 0 < len(evidence_urls) <= 8,
                     "invalid_policy", "Rights evidence URLs are required")
            normalized_evidence = []
            for evidence_url in evidence_urls:
                try:
                    normalized = validate_reviewed_url(evidence_url)
                except TavilyRetrievalError:
                    raise WebNutritionError("invalid_policy", "A rights evidence URL is invalid") from None
                _require(normalized == evidence_url, "invalid_policy", "Rights evidence URLs must be canonical")
                normalized_evidence.append(normalized)
            _require(len(set(normalized_evidence)) == len(normalized_evidence),
                     "invalid_policy", "Rights evidence URLs must be unique")
            try:
                reviewed = datetime.fromisoformat(rights.get("reviewed_at", ""))
                _require(reviewed.tzinfo is not None, "invalid_policy", "Rights review requires a timezone")
            except (TypeError, ValueError):
                raise WebNutritionError("invalid_policy", "Rights review timestamp is invalid") from None
            _require(all(isinstance(rights.get(flag), bool) for flag in
                         ("search_allowed", "extract_allowed", "snapshot_allowed", "reuse_allowed")),
                     "invalid_policy", "Rights permissions must be explicit booleans")

    def compatible(self, item):
        matches = []
        for policy in self._policies:
            if item["name_zh"] not in policy["accepted_names"]:
                continue
            if any(item.get(field) != policy["target_identity"].get(field) for field in _IDENTITY_FIELDS):
                continue
            if not all(policy["rights"][flag] for flag in
                       ("search_allowed", "extract_allowed", "snapshot_allowed", "reuse_allowed")):
                continue
            if (policy["rights"]["reuse_scope"] == "cross_user"
                    and policy["rights"]["provider_cache_scope"] != "cross_user_approved"):
                continue
            matches.append(deepcopy(policy))
        return matches


PRODUCTION_SOURCE_REGISTRY = NutritionSourceRegistry()


def make_local_nutrition_lookup(storage, database, user_id, build_custom_food_search_result):
    """Reuse official/custom compatibility and priority, without a new matcher."""
    def lookup(item):
        diagnostics = {}
        custom_originals = {}
        def adapt_custom(document):
            food = build_custom_food_search_result(document)
            custom_originals[food["key"]] = deepcopy(food)
            return food
        matches = find_vision_food_matches(storage, database, item, user_id,
                                          adapt_custom, diagnostics=diagnostics)
        result = {"status": diagnostics["status"], "diagnostics": diagnostics}
        if matches:
            food = matches[0]
            original = custom_originals.get(food["key"], database.get(food["key"]))
            _require(isinstance(original, dict), "invalid_local_result", "The selected original local table is unavailable")
            result["nutrition_profile"] = profile_from_local_food(original, source_details={
                "source": food.get("source"), "key": food.get("key"),
                "original_name": food.get("name_zh"), "local_lookup": deepcopy(diagnostics),
            })
        return result
    return lookup


def _validated_items(items):
    _require(isinstance(items, list) and 0 < len(items) <= MAX_ITEMS, "invalid_items", "A bounded nonempty scan item list is required")
    checked, seen = deepcopy(items), set()
    for item in checked:
        _require(isinstance(item, dict) and _text(item.get("item_id")) and item["item_id"] not in seen,
                 "invalid_items", "Scan item IDs must be unique")
        seen.add(item["item_id"])
        _require(_text(item.get("name_zh")), "invalid_items", "An original visual name is required")
        revision = item.get("item_revision")
        _require(isinstance(revision, int) and not isinstance(revision, bool) and revision >= 0,
                 "invalid_items", "An explicit item revision is required")
        for field in _IDENTITY_FIELDS:
            _require(item.get(field) is None or _text(item[field]), "invalid_items", "Food identity values must be text or null")
        _require(isinstance(item.get("validation_issues", []), list), "invalid_items", "Validation issues must be an array")
        try:
            calculate_portion(None, item.get("estimated_weight_g"), portion_source="vision_estimate")
        except NutritionProfileError:
            raise WebNutritionError("invalid_items", "The scan weight is invalid") from None
    return checked


def _identity_ready(item):
    confidence = item.get("confidence")
    return (not isinstance(confidence, bool) and isinstance(confidence, (int, float))
            and 0 <= confidence <= 1 and math.isfinite(confidence) and confidence >= VISION_FOOD_MIN_CONFIDENCE
            and not item.get("validation_issues")
            and not requires_food_identity_confirmation(item.get("name_zh")))


def _queries(item):
    # Compose only food identity fields, never health/user data or page commands.
    identity = " ".join(str(item[field]) for field in ("brand", "name_zh", "variant") if item.get(field))
    method = {"boiled": "水煮", "stir_fried": "炒", "pan_fried": "煎", "deep_fried": "油炸",
              "roasted": "烤", "braised": "滷", "steamed": "蒸", "mixed": "熟食"}.get(item.get("preparation_method"), "")
    return (f'{identity} {method} 營養標示 每100公克 熱量 蛋白質 鈉', f'{identity} 營養標示')


def _split_selection(payload, expected_ids):
    if isinstance(payload, str):
        payload = parse_strict_model_json(payload)
    _require(isinstance(payload, dict) and set(payload) == {"schema_version", "items"}
             and payload["schema_version"] == SCHEMA_VERSION and isinstance(payload["items"], list)
             and len(payload["items"]) <= MAX_ITEMS,
             "invalid_output", "The model response envelope is invalid")
    found = {}
    keys = {"item_id", "status", "source_id", "table_id", "column_id", "nutrients"}
    for item in payload["items"]:
        _require(isinstance(item, dict) and set(item) == keys and _text(item.get("item_id"))
                 and item["item_id"] not in found, "invalid_output", "The model item set is invalid")
        _require(isinstance(item["status"], str) and item["status"] in STATUSES
                 and isinstance(item["nutrients"], dict) and set(item["nutrients"]) == set(NUTRIENTS),
                 "invalid_output", "The model item schema is invalid")
        for selection in item["nutrients"].values():
            _require(selection is None or isinstance(selection, dict) and set(selection) == {"row_id"}
                     and _text(selection["row_id"]), "invalid_output", "A nutrient must select a row or remain null")
        for key in ("source_id", "table_id", "column_id"):
            _require(item[key] is None or _text(item[key]), "invalid_output", "Source selections must be IDs or null")
        found[item["item_id"]] = item
    _require(set(found) == set(expected_ids), "invalid_output", "The model must return every requested item exactly once")
    return found


def enrich_nutrition(items, *, official_health, lookup_local, registry, tavily,
                     select_cells, deadline, clock=time.monotonic, limiter=None):
    """Run one bounded automatic search/extract/validate pass, with no persistence.

    Callers supply server-owned scan items and a reviewed registry. Unknown input
    is not an authorization token. No route, background job or v1 downgrade is
    introduced here; no persistent cache, user quota or replay guarantee is implied.
    """
    items = _validated_items(items)
    _require(isinstance(registry, NutritionSourceRegistry), "invalid_policy", "A server source registry is required")
    try:
        valid_deadline = not isinstance(deadline, bool) and isinstance(deadline, (int, float)) and math.isfinite(deadline)
    except OverflowError:
        valid_deadline = False
    _require(valid_deadline,
             "invalid_deadline", "A monotonic deadline is required")
    deadline = min(deadline, clock() + MAX_SECONDS)
    results = {item["item_id"]: {"item_id": item["item_id"], "item_revision": item["item_revision"],
               "original_visual_name": item["name_zh"], "status": "pending", "origin": None,
               "recognition_context": {field: deepcopy(item.get(field)) for field in
                    ("name_zh", "confidence", "weight_confidence", "estimated_weight_g", *_IDENTITY_FIELDS)},
               "nutrition_profile": None} for item in items}
    events, groups = [], {}
    health_ok = (isinstance(official_health, dict) and all(
        isinstance(official_health.get(source), dict) and official_health[source].get("status") == "available"
        for source in ("TFDA", "USDA FNDDS")))
    for item in items:
        result = results[item["item_id"]]
        if not _identity_ready(item):
            result["status"] = "needs_identity"
            continue
        try:
            local = lookup_local(deepcopy(item))
            _require(isinstance(local, dict) and local.get("status") in _NO_MATCH | {"matched", "source_conflict"},
                     "invalid_local_result", "The local lookup returned an invalid status")
            result["local_lookup"] = deepcopy(local.get("diagnostics", {"status": local["status"]}))
            if local["status"] == "matched":
                profile = local.get("nutrition_profile")
                _require(isinstance(profile, dict), "invalid_local_result", "A local match requires a canonical profile")
                calculate_portion(profile, item.get("estimated_weight_g"), portion_source="vision_estimate")
                result.update(status="accepted", origin="local", nutrition_profile=deepcopy(profile))
                continue
        except (WebNutritionError, NutritionProfileError):
            result["status"] = "local_error"
            continue
        if local["status"] == "source_conflict":
            result["status"] = "source_conflict"
            continue
        if not health_ok:
            result["status"] = "local_unavailable"
            continue
        policies = registry.compatible(item)
        if not policies:
            result["status"] = "needs_source_review"
            continue
        if len(policies) != 1:
            result["status"] = "ambiguous_source"
            continue
        key = tuple(item.get(field) for field in ("name_zh", *_IDENTITY_FIELDS))
        if key not in groups and len(groups) >= MAX_FOODS:
            result["status"] = "budget_exceeded"
            continue
        groups.setdefault(key, {"items": [], "policies": policies})["items"].append(item)

    def terminal_pending(status):
        for result in results.values():
            if result["status"] == "pending":
                result["status"] = status

    def remaining():
        if clock() >= deadline:
            raise TavilyRetrievalError("timeout", "The enrichment deadline expired")

    acquired = False
    limiter = _JOBS if limiter is None else limiter
    try:
        if groups:
            remaining()
            acquired = limiter.acquire(blocking=False)
            if not acquired:
                terminal_pending("busy")
            else:
                selected_urls, url_groups = [], {}
                for key, group in groups.items():
                    allowed = tuple(policy["source_spec"]["source_url"] for policy in group["policies"][:MAX_URLS])
                    found = []
                    for query in _queries(group["items"][0]):
                        remaining()
                        events.append({"operation": "search", "status": "attempted"})
                        try:
                            response = tavily.search(query, allowed_urls=allowed, deadline=deadline)
                        except TavilyRetrievalError as error:
                            if error.code in ("timeout", "authentication_failed", "rate_limited", "budget_exceeded"):
                                raise
                            events[-1]["status"] = error.code
                            for item in group["items"]:
                                results[item["item_id"]]["status"] = "upstream_error"
                            break
                        events[-1].update(status="completed", request_id=response["request_id"], usage=response.get("usage"))
                        found = [url for url in response["urls"] if url in allowed]
                        if found:
                            break
                    if not found and all(results[item["item_id"]]["status"] == "pending" for item in group["items"]):
                        for item in group["items"]:
                            results[item["item_id"]]["status"] = "not_found"
                    for url in found:
                        if url not in selected_urls:
                            if len(selected_urls) >= MAX_URLS:
                                continue
                            selected_urls.append(url)
                        url_groups.setdefault(url, []).append(key)
                    if found and not any(url in url_groups for url in found):
                        for item in group["items"]:
                            results[item["item_id"]]["status"] = "budget_exceeded"
                if selected_urls:
                    remaining()
                    events.append({"operation": "extract", "status": "attempted", "requested_urls": len(selected_urls)})
                    extracted = tavily.extract(tuple(selected_urls), deadline=deadline)
                    events[-1].update(status="completed", request_id=extracted["request_id"],
                                      usage=extracted.get("usage"), successful_urls=len(extracted["documents"]))
                    blocks, policy_by_source, expected = [], {}, {}
                    for document in extracted["documents"]:
                        for key in url_groups[document["url"]]:
                            group = groups[key]
                            policy = next(policy for policy in group["policies"] if policy["source_spec"]["source_url"] == document["url"])
                            try:
                                block = build_reviewed_markdown_source(document, spec=policy["source_spec"],
                                                                      eligible_item_ids=[item["item_id"] for item in group["items"]])
                            except NutritionSourceAdapterError as error:
                                events.append({"operation": "adapter", "source_id": policy["source_spec"]["source_id"], "status": error.code})
                                continue
                            previous = next((source for source in blocks if source["source_id"] == block["source_id"]), None)
                            if previous is None:
                                blocks.append(block)
                            else:
                                for old, new in zip(previous["tables"], block["tables"]):
                                    old["eligible_item_ids"] = list(dict.fromkeys(old["eligible_item_ids"] + new["eligible_item_ids"]))
                            policy_by_source[block["source_id"]] = policy
                            for item in group["items"]:
                                expected[item["item_id"]] = {field: item.get(field) for field in ("item_id", "name_zh", *_IDENTITY_FIELDS)}
                                expected[item["item_id"]]["name"] = item["name_zh"]
                    for group in groups.values():
                        for item in group["items"]:
                            if results[item["item_id"]]["status"] == "pending" and item["item_id"] not in expected:
                                results[item["item_id"]]["status"] = "no_usable_source"
                    if expected:
                        remaining()
                        try:
                            prompt = build_nutrition_extraction_prompt(list(expected.values()), blocks)
                            events.append({"operation": "model", "status": "attempted"})
                            payload = select_cells(prompt, deadline=deadline)
                            remaining()
                            selections = _split_selection(payload, expected)
                            events[-1]["status"] = "completed"
                        except NutritionExtractionModelError:
                            raise
                        except (NutritionEvidenceError, ValueError) as error:
                            terminal_pending("timeout" if getattr(error, "code", None) == "timeout" else "invalid_output")
                        else:
                            for item_id, selection in selections.items():
                                try:
                                    entry = validate_and_build_nutrition_profiles(
                                        {"schema_version": SCHEMA_VERSION, "items": [selection]},
                                        expected_items=[expected[item_id]], source_blocks=blocks)[0]
                                except NutritionEvidenceError as error:
                                    results[item_id]["status"] = "source_conflict" if error.code == "source_conflict" else "invalid_output"
                                    events.append({"operation": "validation", "item_id": item_id, "status": error.code})
                                    continue
                                if entry["status"] != "candidate":
                                    results[item_id]["status"] = entry["status"]
                                    continue
                                policy = policy_by_source[selection["source_id"]]
                                profile = entry["nutrition_profile"]
                                if not profile["has_required_point_values"]:
                                    results[item_id]["status"] = "incomplete_core"
                                    continue
                                original = next(item for item in items if item["item_id"] == item_id)
                                try:
                                    calculate_portion(profile, original.get("estimated_weight_g"), portion_source="vision_estimate")
                                except NutritionProfileError as error:
                                    results[item_id]["status"] = "invalid_portion"
                                    events.append({"operation": "validation", "item_id": item_id, "status": error.code})
                                    continue
                                profile["source_details"].update(match_policy=policy["match_policy"], policy_id=policy["policy_id"],
                                    rights_reference=policy["rights"]["reference"], compatibility_review=policy["compatibility_review"])
                                results[item_id].update(status="accepted", origin="web", nutrition_profile=profile)
    except (TavilyRetrievalError, NutritionExtractionModelError) as error:
        terminal_pending(error.code if error.code in ("timeout", "budget_exceeded", "invalid_output") else "upstream_error")
        events.append({"operation": "provider", "status": error.code})
    finally:
        if acquired:
            limiter.release()
    terminal_pending("no_usable_source")
    coverage_items = []
    for item in items:
        result = results[item["item_id"]]
        profile = result["nutrition_profile"]
        result["portion"] = calculate_portion(profile, item.get("estimated_weight_g"), portion_source="vision_estimate")
        if profile is not None:
            result["status"] = ("needs_portion" if item.get("estimated_weight_g") is None else
                                "partial" if profile["nutrition_status"] != "complete" else "accepted")
        coverage_items.append({"item_id": item["item_id"], "profile": profile,
                               "weight_g": item.get("estimated_weight_g"), "portion_source": "vision_estimate"})
    try:
        coverage = aggregate_nutrition_coverage(coverage_items)
    except NutritionProfileError as error:
        if error.code != "numeric_range":
            raise
        # Only use the slower isolation pass for an out-of-range batch. Retain
        # each rejected item's denominator and all earlier representable sums.
        safe_items = []
        for item in coverage_items:
            try:
                aggregate_nutrition_coverage([*safe_items, item])
            except NutritionProfileError as item_error:
                if item_error.code != "numeric_range":
                    raise
                item["profile"] = None
                result = results[item["item_id"]]
                result.update(status="numeric_range", origin=None, nutrition_profile=None,
                              portion=calculate_portion(None, item["weight_g"], portion_source="vision_estimate"))
                events.append({"operation": "validation", "item_id": item["item_id"], "status": "numeric_range"})
            safe_items.append(item)
        coverage = aggregate_nutrition_coverage(safe_items)
    return {"schema_version": "WebNutritionEnrichmentV1", "items": list(results.values()),
            "nutrition_coverage": coverage, "events": events,
            "production_enabled": False}
