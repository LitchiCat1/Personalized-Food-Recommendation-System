"""Explicit source installation and read-only startup configuration loading.

Candidate files are never discovered here. A startup load grants no deployment
permission and must not repair, update or reactivate installed policies.
"""

from copy import deepcopy
from pathlib import Path

from services.fdc_reviewed_selection_service import FdcReviewedSelectionService
from services.nutrition_source_admission_service import source_policy_digest
from services.strict_json_service import MAX_MODEL_JSON_BYTES, parse_strict_model_json


class FdcReviewedSourceLifecycleError(ValueError):
    def __init__(self, code, message):
        self.code = code
        super().__init__(message)


def validate_reviewed_fdc_sources(reviewed_sources):
    """Validate explicit server entries without loading or installing anything."""
    entries = deepcopy(reviewed_sources)
    # The actual selector validates admission digests, fixed FDC identities and
    # descriptors. No repository or provider is used during construction.
    selection = FdcReviewedSelectionService(
        scan_context_repository=None, snapshot_repository=None,
        source_repository=None, local_lookup_factory=None,
        official_health={}, reviewed_sources=entries)
    for entry in entries:
        policy = entry["policy"]
        if any(len(selection.registry.compatible({"name_zh": name, **policy["target_identity"]})) > 1
               for name in policy["accepted_names"]):
            raise FdcReviewedSourceLifecycleError("ambiguous_reviewed_sources", "Reviewed source identities overlap")
    return tuple(entries)


def install_reviewed_fdc_source(*, source_repository, reviewed_source, expected_policy_sha256):
    """Install one explicitly selected, hash-pinned entry; no update semantics."""
    entry, = validate_reviewed_fdc_sources([reviewed_source])
    policy = entry["policy"]
    if expected_policy_sha256 != source_policy_digest(policy):
        raise FdcReviewedSourceLifecycleError("policy_changed", "Explicit installation digest differs")
    result = source_repository.install_source_policy_if_absent(policy)
    source = result["source"]
    return {"schema_version": "ReviewedFdcSourceInstallV1", "action": result["action"],
            "source_id": source["source_id"], "revision": source["revision"],
            "policy_sha256": source_policy_digest(source["policy"]),
            "deployment_authorized": False}


def load_installed_reviewed_fdc_sources(*, reviewed_sources, load_installed_policy, sqlite_available,
                                      configuration_path=None):
    """Return an all-or-none configured set and diagnostics, without writes.

    The callback must read current state, including withdrawal. Selection and
    preview still recheck current policy after this point; this is no lease.
    """
    report = {"schema_version": "ReviewedFdcSourceLoadV1", "decision": "blocked",
              "sources": [], "blockers": [], "deployment_authorized": False}
    try:
        if configuration_path is not None:
            path = Path(configuration_path)
            if not path.is_absolute() or reviewed_sources:
                raise ValueError("Use one explicit absolute source configuration")
            with path.open("rb") as stream:
                raw = stream.read(MAX_MODEL_JSON_BYTES + 1)
            if len(raw) > MAX_MODEL_JSON_BYTES:
                raise ValueError("Source configuration exceeds size budget")
            configuration = parse_strict_model_json(raw.decode("utf-8-sig"))
            if set(configuration) != {"reviewed_sources"}:
                raise ValueError("Use exactly the reviewed_sources field")
            reviewed_sources = configuration["reviewed_sources"]
        entries = validate_reviewed_fdc_sources(reviewed_sources)
    except (OSError, ValueError, TypeError, KeyError):
        report["blockers"].append({"code": "invalid_reviewed_configuration"})
        return (), report
    if not entries:
        report["decision"] = "empty"
        return (), report
    if sqlite_available is not True or load_installed_policy is None:
        report["blockers"].append({"code": "sqlite_unavailable"})
        return (), report
    for entry in entries:
        policy = entry["policy"]
        source_id = policy["source_spec"]["source_id"]
        state, revision = "source_lookup_failed", None
        try:
            current = load_installed_policy(source_id)
            if current is None:
                state = "source_not_installed"
            elif not isinstance(current, dict) or current.get("status") != "active":
                state = "source_inactive"
            elif (current.get("source_id") != source_id
                  or current.get("policy_id") != policy["policy_id"]
                  or type(current.get("revision")) is not int or current["revision"] < 0
                  or current.get("policy") != policy):
                state = "installed_policy_mismatch"
            else:
                state, revision = "active_exact_match", current["revision"]
        except Exception:
            # Diagnostics must not expose paths, SQL details or credentials.
            pass
        report["sources"].append({"source_id": source_id, "state": state, "revision": revision})
        if state != "active_exact_match":
            report["blockers"].append({"source_id": source_id, "code": state})
    if report["blockers"]:
        return (), report
    report["decision"] = "ready"
    return entries, report
