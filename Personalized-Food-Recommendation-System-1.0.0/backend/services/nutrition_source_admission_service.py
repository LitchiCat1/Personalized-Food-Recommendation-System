"""Server-owned admission reviews, separate from retrieval and feature flags.

Reviews are configuration evidence, never HTTP input or an automatic grant of
rights. This release excludes sources that require physical deletion: source
withdrawal only revokes future access and cannot purge backups or SQLite pages.
"""

from copy import deepcopy
from datetime import datetime
import hashlib
import json


class NutritionSourceAdmissionError(ValueError):
    def __init__(self, code, message):
        self.code = code
        super().__init__(message)


def _fail(code, message):
    raise NutritionSourceAdmissionError(code, message)


def _text(value, limit=256):
    return (isinstance(value, str) and 0 < len(value) <= limit and value.strip() == value
            and not any(ord(char) < 32 or ord(char) == 127 for char in value))


def source_policy_digest(policy):
    try:
        encoded = json.dumps(policy, ensure_ascii=True, sort_keys=True,
                             separators=(",", ":"), allow_nan=False).encode("utf-8")
    except (TypeError, ValueError, OverflowError, RecursionError) as error:
        raise NutritionSourceAdmissionError("invalid_policy", "Policy must be finite JSON") from error
    if len(encoded) > 256 * 1024:
        _fail("invalid_policy", "Policy exceeds the admission size budget")
    return hashlib.sha256(encoded).hexdigest()


def validate_source_admission(policy, review):
    """Validate one reviewed policy without admitting it to any live registry."""
    # Local imports keep the generic registry and FDC validator independent.
    from services.fdc_source_policy_service import FdcSourcePolicyError, validate_fdc_source_policy
    from services.tavily_retrieval_service import TavilyRetrievalError, validate_reviewed_url
    from services.web_nutrition_service import NutritionSourceRegistry, WebNutritionError

    fields = {"source_id", "policy_sha256", "provider_kind", "publisher_rights_approved",
              "provider_terms_approved", "deletion_requirement", "cross_user_cache_approved",
              "reviewer", "reviewed_at", "evidence_urls"}
    if not isinstance(review, dict) or set(review) != fields:
        _fail("admission_review_required", "An exact server-owned admission review is required")
    try:
        NutritionSourceRegistry([policy])
    except WebNutritionError as error:
        raise NutritionSourceAdmissionError("invalid_policy", str(error)) from error
    spec, rights = policy["source_spec"], policy["rights"]
    if review["source_id"] != spec["source_id"]:
        _fail("source_mismatch", "Admission review belongs to another source")
    if review["policy_sha256"] != source_policy_digest(policy):
        _fail("policy_changed", "Admission review does not cover this policy version")
    provider = review["provider_kind"]
    if provider not in ("usda_fdc_api", "tavily_extract"):
        _fail("invalid_provider", "Admission provider is unsupported")
    if spec.get("provider_kind") not in (None, provider):
        _fail("provider_mismatch", "Admission and source providers differ")
    fdc_shaped = ("fdc_id" in spec or spec["source_id"].startswith("usda-fdc-")
                  or spec["source_url"].startswith("https://api.nal.usda.gov/")
                  or str(spec.get("table_id", "")).startswith("fdc-"))
    if provider == "usda_fdc_api":
        try:
            validate_fdc_source_policy(policy)
        except FdcSourcePolicyError as error:
            raise NutritionSourceAdmissionError(error.code, str(error)) from error
    elif fdc_shaped:
        _fail("provider_mismatch", "FDC policies cannot enter the Tavily retrieval path")
    if not _text(review["reviewer"]):
        _fail("invalid_review", "A named admission reviewer is required")
    try:
        stamp = datetime.fromisoformat(review["reviewed_at"])
    except (TypeError, ValueError):
        _fail("invalid_review", "Admission review time is invalid")
    if stamp.tzinfo is None or stamp.utcoffset() is None:
        _fail("invalid_review", "Admission review time must include a timezone")
    urls = review["evidence_urls"]
    if not isinstance(urls, list) or not 0 < len(urls) <= 8:
        _fail("invalid_review", "Admission evidence URLs are required")
    normalized_urls = []
    for url in urls:
        try:
            normalized = validate_reviewed_url(url)
        except TavilyRetrievalError as error:
            raise NutritionSourceAdmissionError("invalid_review", "Admission evidence URL is invalid") from error
        if normalized != url or url not in rights["evidence_urls"]:
            _fail("invalid_review", "Admission evidence must be bound to the policy rights review")
        normalized_urls.append(normalized)
    if len(set(normalized_urls)) != len(normalized_urls):
        _fail("invalid_review", "Admission evidence URLs must be unique")
    for field in ("publisher_rights_approved", "provider_terms_approved", "cross_user_cache_approved"):
        if type(review[field]) is not bool:
            _fail("invalid_review", "Admission decisions must be explicit booleans")
    if not review["publisher_rights_approved"]:
        _fail("publisher_rights_unapproved", "Original publisher rights are not approved")
    if not review["provider_terms_approved"]:
        _fail("provider_terms_unapproved", "Actual provider application scope is not approved")
    if review["deletion_requirement"] == "on_withdrawal":
        _fail("purge_unavailable", "This release cannot admit sources requiring physical deletion")
    if review["deletion_requirement"] != "not_required":
        _fail("retention_unreviewed", "Source deletion requirements are unreviewed")
    if not all(rights[field] for field in
               ("search_allowed", "extract_allowed", "snapshot_allowed", "reuse_allowed")):
        _fail("rights_not_allowed", "Policy does not allow the complete retrieval/storage flow")
    if rights["reuse_scope"] == "single_request":
        _fail("retention_not_allowed", "Durable enrichment cannot use a single-request policy")
    if rights["reuse_scope"] == "server_internal" and rights["provider_cache_scope"] != "server_internal":
        _fail("retention_not_allowed", "Internal persistence requires provider storage approval")
    if rights["reuse_scope"] == "cross_user" and (
            rights["provider_cache_scope"] != "cross_user_approved"
            or not review["cross_user_cache_approved"]):
        _fail("cross_user_unapproved", "Cross-user provider caching requires a separate approval")
    return deepcopy(policy)
