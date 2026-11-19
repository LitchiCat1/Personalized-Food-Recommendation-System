"""Read-only configuration review for the smallest reviewed FDC preview scope.

This does not install policies, enable routes, grant rights or certify a running
deployment. Callers must distinguish repository defaults from observed runtime.
"""

from services.fdc_reviewed_selection_service import FdcReviewedSelectionService


REQUIRED_BACKEND_FLAGS = (
    "FDC_REVIEWED_SELECTION_ROUTE_ENABLED",
    "FDC_CONFIRMATION_ROUTE_ENABLED",
    "FDC_PROFILE_PREVIEW_ROUTE_ENABLED",
)
EXCLUDED_BACKEND_FLAGS = (
    "FDC_CANDIDATE_ROUTE_ENABLED", "FDC_DETAIL_ROUTE_ENABLED",
    "FDC_PROFILE_ACCEPT_ROUTE_ENABLED", "NUTRITION_ENRICHMENT_ROUTE_ENABLED",
)
REQUIRED_FRONTEND_FLAGS = (
    "EXPO_PUBLIC_FDC_REVIEWED_SELECTION_ENABLED",
    "EXPO_PUBLIC_FDC_CONFIRMATION_ENABLED",
    "EXPO_PUBLIC_FDC_PROFILE_PREVIEW_ENABLED",
)
EXCLUDED_FRONTEND_FLAGS = (
    "EXPO_PUBLIC_FDC_CANDIDATE_SEARCH_ENABLED",
    "EXPO_PUBLIC_NUTRITION_ENRICHMENT_ENABLED",
)


def review_fdc_preview_configuration(*, reviewed_sources, load_installed_policy,
                                     official_health, backend_flags, frontend_flags,
                                     sqlite_available, authentication_required,
                                     fdc_key_available):
    """Return blockers from explicit observations without reading environment.

    Flags and prerequisites are booleans (None means unobserved). A source loader
    must return the current policy, not an historical revision or an HTTP input.
    Even a successful result is a configuration review, not deployment consent.
    """
    blockers, sources = [], []

    def block(code, target):
        blockers.append({"code": code, "target": target})

    for target, value in (
            ("sqlite", sqlite_available), ("authentication", authentication_required),
            ("server_usda_key", fdc_key_available)):
        if value is not True:
            block("prerequisite_unverified" if value is None else "prerequisite_unavailable", target)

    for name in ("TFDA", "USDA FNDDS"):
        health = official_health.get(name) if isinstance(official_health, dict) else None
        if not isinstance(health, dict) or health.get("status") != "available":
            block("local_dataset_unavailable", name)

    for provided, required, excluded in (
            (backend_flags, REQUIRED_BACKEND_FLAGS, EXCLUDED_BACKEND_FLAGS),
            (frontend_flags, REQUIRED_FRONTEND_FLAGS, EXCLUDED_FRONTEND_FLAGS)):
        if not isinstance(provided, dict):
            provided = {}
        for name in required + excluded:
            value = provided.get(name)
            if type(value) is not bool:
                block("flag_unverified", name)
            elif name in required and not value:
                block("required_flag_disabled", name)
            elif name in excluded and value:
                block("outside_preview_scope", name)

    try:
        # Reuse actual selection's complete policy, admission and descriptor
        # checks. No repository/provider method runs during construction.
        selection = FdcReviewedSelectionService(
            scan_context_repository=None, snapshot_repository=None,
            source_repository=None, local_lookup_factory=None,
            official_health=official_health, reviewed_sources=reviewed_sources)
    except (ValueError, TypeError, KeyError) as error:
        block("invalid_reviewed_sources", getattr(error, "code", "invalid_policy"))
    else:
        if not reviewed_sources:
            block("no_reviewed_sources", "reviewed_fdc_configuration")
        for entry in reviewed_sources:
            policy = entry["policy"]
            if any(len(selection.registry.compatible({"name_zh": name, **policy["target_identity"]})) > 1
                   for name in policy["accepted_names"]):
                block("ambiguous_reviewed_sources", policy["source_spec"]["source_id"])
        for entry in reviewed_sources:
            policy = entry["policy"]
            source_id = policy["source_spec"]["source_id"]
            state, revision = "unverified", None
            try:
                current = load_installed_policy(source_id) if load_installed_policy else None
            except Exception:
                # Never echo a database path, SQL diagnostic or provider secret.
                block("source_lookup_failed", source_id)
            else:
                if load_installed_policy is None:
                    block("installation_unverified", source_id)
                elif current is None:
                    state = "not_installed"
                    block("source_not_installed", source_id)
                elif not isinstance(current, dict) or current.get("status") != "active":
                    state = "inactive"
                    block("source_inactive", source_id)
                elif (current.get("source_id") != source_id
                      or current.get("policy_id") != policy["policy_id"]
                      or type(current.get("revision")) is not int or current["revision"] < 0
                      or current.get("policy") != policy):
                    state = "drifted"
                    block("installed_policy_mismatch", source_id)
                else:
                    state, revision = "active_exact_match", current["revision"]
            sources.append({"source_id": source_id, "installation": state, "revision": revision})

    return {
        "schema_version": "FdcPreviewAdmissionReviewV1",
        "scope": "configuration_review_only_not_runtime_or_deployment_authorization",
        "decision": "blocked" if blockers else "configuration_ready",
        "deployment_authorized": False,
        "sources": sources, "blockers": blockers,
        "write_boundary": {
            "scan_snapshot_confirmation_and_preview_state": True,
            "nutrition_profile_accept": False, "meal_record": False,
            "cross_user_cache": False,
        },
        "provider_boundary": {
            "fixed_confirmed_fdc_detail": True,
            "fdc_search": False, "tavily": False, "model_nutrition_generation": False,
        },
    }
