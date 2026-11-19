"""Build a bounded, reviewable query plan for food-source searches."""

from copy import deepcopy
import hashlib
import json
import re

from services.food_identity_service import requires_food_identity_confirmation

SCHEMA_VERSION = "FdcSearchQueryPlanV1"
_MAX_NAME = 300
_MAX_QUERIES = 3
_MAX_QUERY = 128
_STATE = {"prepared", "raw", "dry", "unknown"}
_PREPARATION = {"boiled", "stir_fried", "pan_fried", "deep_fried", "roasted", "braised",
                "steamed", "mixed", "unknown"}
_SCOPE = {"food_only", "noodles_only", "whole_dish_with_broth", "with_sides", "unknown"}
_CONTROL = re.compile(r"[\x00-\x1f\x7f]")
_IDENTITY_FIELDS = ("name_zh", "food_state", "preparation_method", "components_scope", "brand", "variant")
_PLAN_KEYS = {"schema_version", "item_id", "item_revision", "scan_revision", "identity_digest", "original_name_zh",
              "queries", "query_source", "identity_expansion_allowed"}

# This is a server-owned alias registry, not a model-generated synonym list.
# Broad "rice sausage" is intentionally absent because live FDC replay showed
# it returns unrelated sausage-and-rice dishes and ordinary sausages.
_ALLOWLIST = {
    "青江菜": ("bok choy",),
    "糯米腸": ("glutinous rice sausage", "Taiwanese glutinous rice sausage"),
}


class FoodQueryNormalizationError(ValueError):
    def __init__(self, code, message):
        self.code = code
        super().__init__(message)


def _fail(code, message):
    raise FoodQueryNormalizationError(code, message)


def _text(value, maximum):
    if not (isinstance(value, str) and 0 < len(value) <= maximum and value.strip() == value
            and not _CONTROL.search(value)):
        return False
    try:
        value.encode("utf-8", "strict")
    except UnicodeError:
        return False
    return True


def _query(value):
    if not _text(value, _MAX_QUERY):
        _fail("invalid_request", "Search query is invalid")
    return value


def _item_id(value):
    if not _text(value, 128):
        _fail("invalid_request", "Server-owned item_id is required")
    return value


def _revision(value):
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        _fail("invalid_request", "scan_revision is invalid")
    return value


def _identity_digest(item):
    identity = {field: item.get(field) for field in _IDENTITY_FIELDS}
    identity["item_revision"] = item.get("item_revision")
    try:
        encoded = json.dumps(identity, ensure_ascii=False, sort_keys=True,
                             separators=(",", ":"), allow_nan=False).encode("utf-8")
    except (TypeError, ValueError, OverflowError, RecursionError) as error:
        _fail("invalid_request", "Food identity is not finite JSON")
    return hashlib.sha256(encoded).hexdigest()


def _validate_item(item, *, scan_revision):
    if not isinstance(item, dict) or not _item_id(item.get("item_id")):
        _fail("invalid_request", "Server-owned item identity is required")
    _revision(scan_revision)
    if type(item.get("item_revision")) is not int or item["item_revision"] < 0:
        _fail("invalid_request", "item_revision is invalid")
    if not _text(item.get("name_zh"), _MAX_NAME):
        _fail("invalid_request", "Original food name is required")
    for field, allowed in (("food_state", _STATE), ("preparation_method", _PREPARATION),
                           ("components_scope", _SCOPE)):
        value = item.get(field)
        if value is not None and value not in allowed:
            _fail("invalid_request", f"{field} is invalid")
    for field in ("brand", "variant"):
        value = item.get(field)
        if value is not None and not _text(value, _MAX_NAME):
            _fail("invalid_request", f"{field} is invalid")
    return item


def build_fdc_search_query_plan(item, *, scan_revision=None, english_aliases=None):
    """Return an explicit, non-authoritative query list; no model text is interpreted."""
    _validate_item(item, scan_revision=scan_revision)
    original = item["name_zh"]
    if requires_food_identity_confirmation(original):
        _fail("confirmation_required", "A specific food identity is required before FDC search")
    queries = [_query(original)]
    allowed_aliases = _ALLOWLIST.get(original, ())
    requested = allowed_aliases if english_aliases is None else english_aliases
    if not isinstance(requested, (list, tuple)):
        _fail("invalid_request", "English aliases must be a bounded list")
    if len(requested) > _MAX_QUERIES - 1:
        _fail("invalid_request", "English aliases exceed the query budget")
    seen_aliases = set()
    for alias in requested:
        alias = _query(alias)
        if alias not in allowed_aliases:
            _fail("invalid_request", "English alias is not server-allowlisted")
        folded = alias.casefold()
        if folded in seen_aliases or folded in {query.casefold() for query in queries}:
            _fail("invalid_request", "English aliases must be unique")
        seen_aliases.add(folded)
        queries.append(alias)
    # A missing identity context blocks expansion: broad aliases would be unsafe.
    complete = all(item.get(field) not in (None, "unknown")
                   for field in ("food_state", "preparation_method", "components_scope"))
    if not complete:
        queries = queries[:1]
    plan = {
        "schema_version": SCHEMA_VERSION,
        "item_id": item["item_id"],
        "item_revision": item["item_revision"],
        "scan_revision": scan_revision,
        "identity_digest": _identity_digest(item),
        "original_name_zh": original,
        "queries": queries,
        "query_source": ["original_name" if index == 0 else "server_allowlisted_alias"
                         for index in range(len(queries))],
        "identity_expansion_allowed": complete,
    }
    try:
        json.dumps(plan, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)
    except (TypeError, ValueError, OverflowError, RecursionError) as error:
        _fail("invalid_request", "Search query plan is not finite JSON")
    return deepcopy(plan)


def validate_fdc_search_query_plan(plan, *, item, scan_revision):
    """Reject a query plan that no longer belongs to the server-owned scan item."""
    if not isinstance(plan, dict) or set(plan) != _PLAN_KEYS or plan.get("schema_version") != SCHEMA_VERSION:
        _fail("invalid_plan", "Search query plan envelope is invalid")
    _validate_item(item, scan_revision=scan_revision)
    if plan.get("item_id") != item["item_id"] or plan.get("scan_revision") != scan_revision:
        _fail("plan_mismatch", "Search query plan is bound to another scan revision or item")
    if plan.get("identity_digest") != _identity_digest(item):
        _fail("plan_mismatch", "Search query plan identity has changed")
    queries = plan.get("queries")
    sources = plan.get("query_source")
    if not isinstance(queries, list) or not isinstance(sources, list) or len(queries) != len(sources):
        _fail("invalid_plan", "Search query plan query lists are invalid")
    if any(source not in {"original_name", "server_allowlisted_alias"} for source in sources):
        _fail("invalid_plan", "Search query plan source is invalid")
    expected = build_fdc_search_query_plan(item, scan_revision=scan_revision,
                                           english_aliases=queries[1:])
    if plan != expected:
        _fail("plan_mismatch", "Search query plan does not match the current server-owned item")
    return deepcopy(plan)


__all__ = ["SCHEMA_VERSION", "FoodQueryNormalizationError", "build_fdc_search_query_plan",
           "validate_fdc_search_query_plan"]
