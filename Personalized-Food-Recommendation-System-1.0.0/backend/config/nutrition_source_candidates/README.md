# Reviewed Source Candidates

These files are server-owned review artifacts. They are not loaded by the app,
do not populate `PRODUCTION_SOURCE_REGISTRY` or the production SQLite policy
repository, and do not enable feature flags.

The batch76 lifecycle implementation adds an explicit digest-pinned installer
and read-only startup loader. Batch78 deployed only generic171688 preview using
an explicit external server configuration and installed revision0. The optional
FDC_REVIEWED_SOURCES_FILE must be an absolute server-owned path to the same
one-field document accepted by the installer. The default source tuple remains
empty; startup never discovers this directory or repairs/reactivates withdrawn
or drifted sources. `tools/manage_reviewed_fdc_source.py` defaults to read-only
inspection of an explicit configuration/database; installation requires both
`--install-source` and `--policy-sha256`. See the deployment guide for its exact
one-field configuration format. Installing a policy does not enable a route.

The batch75 admission review selected generic171688 as the smallest prospective
preview scope, leaving Fuji1750340 out of the initial activation set. Neither was
installed in production by these batches. `python tools/review_fdc_preview_admission.py` checks repository
defaults and actual local dataset health; it deliberately reports blocked.
An explicit non-secret configuration snapshot and existing SQLite file can be
checked with `--configuration` and `--database`, but even configuration_ready
is not runtime verification, an installer or deployment authorization. See
`docs/Local_Server_Deployment.md` for the exact preview-only flag matrix and
the distinction between nutrition reads and persisted workflow state.

`usda-fdc-171688.json` separately covers generic raw apple with skin. Its real
2026-11-16 Detail capture has the full Food Distribution Program annotation,
110 nutrient rows and nine selected nutrient values. Older shortened 171688
phone fixtures remain synthetic even where their numbers coincide. The scan
name remains apple; no cultivar is inferred. `variant=with_skin` describes
visible edible skin, not cultivar. Unknown skin, peeled/cooked/dried foods,
juice, branded food and unknown preparation/scope are excluded. The existing
raw+mixed enum convention applies only to visibly unheated apple. The generic
and Fuji policies are distinct and do not match each other's identities.

The actual generic response passed isolated SQLite preview/accept/two reopens,
idempotency, ownership and withdrawal checks. Preserve the complete source
description in both source_identity and reviewed aliases: profile persistence
checks the original source name as well as the display identity. This is not
an automatic scanner flow, mobile save or production installation.

`usda-fdc-1750340.json` covers only raw Fuji apple with skin, using the existing
live Detail replay and official FDC rights evidence. It is separate from the
synthetic apple 171688 used for phone flow testing. Unknown variety, generic
apple, peeled/cooked products and brand-specific foods are excluded. Missing
saturated/trans fat stays unknown. The current preparation enum uses `mixed`
with `food_state=raw`; this is an explicit compatibility convention for an
unheated whole food, not a claim about its recipe.

`validate_source_admission(policy, admission_review)` checks the complete policy
SHA-256, original publisher and provider approvals, evidence references, storage
scope and deletion requirement. Changing an alias, nutrient selector or rights
statement requires a fresh review and digest. The digest binds configuration;
it is not a digital signature or proof that a publisher granted permission.

This release excludes any source with an unknown deletion requirement or an
obligation to physically delete on withdrawal. Existing withdrawal revokes
future access; retained snapshots, SQLite pages/WAL and backups are not purged.
Do not describe it as erasure. No purge subsystem is required for excluded
sources.

For a future Tavily production policy, use
`build_production_web_registry(policies, admission_reviews=reviews)`. It rejects
missing reviews, unapproved publisher/provider terms, unsupported retention and
unapproved cross-user caches. Only the Tavily path belongs there. FDC policies
use the dedicated fixed-ID API flow and the existing SQLite source repository;
the candidate file is not a request to install one. Keep real source validation,
remaining save acceptance and the final deployment/flag review separate.

The food shown to the user keeps its recognition name. A database source name
is provenance, not a finding that the photographed food has that variety. An
unknown-variety apple should use a separately reviewed compatible generic
record; do not add a generic alias to this Fuji-only policy to force a match.
The existing captured Fuji response has now passed temporary SQLite
preview/accept/reopen/withdrawal verification. This is not generic-source
admission, image recognition, mobile meal saving, or production activation.
