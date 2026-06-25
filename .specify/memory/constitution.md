<!--
SYNC IMPACT REPORT
==================
Version change: (none) → 1.0.0   [initial ratification]
Bump rationale: First formal constitution for the project. MAJOR baseline.

Principles defined (6):
  I.   Security First (NON-NEGOTIABLE)
  II.  Public Data, Public-by-Design
  III. Data Quality is a Release Gate (NON-NEGOTIABLE)
  IV.  Test-First for Pure Logic
  V.   Layered Ownership & Pragmatic Simplicity
  VI.  Reproducible, Observable Deploys

Added sections:
  - Security Requirements
  - Development Workflow & Quality Gates
  - Governance

Templates reviewed for alignment:
  ✅ .specify/templates/plan-template.md  — "Constitution Check" reads this file
        dynamically (no edit needed)
  ✅ .specify/templates/spec-template.md  — no constitution-specific gates (no edit)
  ✅ .specify/templates/tasks-template.md — task categories already cover testing,
        security, observability (no edit)

Deferred / follow-up TODOs: none.
-->

# Brazil Economy Observatory Constitution

End-to-end ELT pipeline for Brazilian public economic data: Airflow ingests, dbt
transforms and tests, Superset publishes, OpenMetadata catalogs — running 24/7 on a
free-tier cloud VM. These principles govern every change. They are deliberately
testable: a reviewer (human or agent) MUST be able to check compliance objectively.

## Core Principles

### I. Security First (NON-NEGOTIABLE)

Cybersecurity is the project's highest priority and overrides convenience.

- Secrets (passwords, tokens, Fernet/JWT keys) MUST NEVER be committed, logged,
  printed, or echoed. They live only in gitignored env files and are passed via
  environment, never as literals in commands, code, or output.
- Defense in depth and least privilege: every externally reachable surface MUST be
  read-only by default (public dashboard, catalog proxy), writes/signup blocked,
  and database roles scoped to the minimum needed.
- Operational scripts MUST NOT delete entities or data; they create, update, and
  validate only.
- New surfaces MUST be validated anonymously (as an unauthenticated visitor) to
  confirm no write path or private data is exposed.
- Exposed or leaked secrets MUST be treated as compromised and rotated.

**Rationale**: the system is internet-facing and serves public data; a single leaked
credential or writable surface is the dominant risk, so it is gated, not advised.

### II. Public Data, Public-by-Design

- Every byte ingested MUST come from open government APIs (BACEN, CVM, IBGE). No
  private, paid, or personal data enters the warehouse.
- No PII is collected or stored; governance metadata MUST reflect this honestly.
- The public dashboard and catalog require no login and expose read access only.

**Rationale**: a public-data-only scope keeps the legal/privacy surface near zero and
lets the project be transparent end-to-end.

### III. Data Quality is a Release Gate (NON-NEGOTIABLE)

- Transformation runs as `dbt build` (models + tests) in dependency order; a failing
  test MUST stop bad data from propagating downstream to the charts.
- `dbt source freshness` MUST flag any upstream API that stopped publishing, per its
  per-source SLA (daily / weekly / monthly).
- Ingestion MUST be incremental and idempotent: re-running any day produces the same
  result (upsert only the new observations).
- New metrics or marts MUST ship with the dbt tests that protect them
  (`not_null`/`unique` keys, plus value tests like `non_negative`/`in_range`).

**Rationale**: silent data corruption is worse than a visible failure; tests are the
contract that keeps published numbers trustworthy.

### IV. Test-First for Pure Logic

- Pure ingestion/business logic (month math, CVM row normalization, idempotent
  backfill) MUST live in `include/brazil_economy` and be unit-tested with `pytest`
  in isolation — no Airflow, no network.
- CI MUST pass before merge: `ruff check` + `ruff format --check`, DAG import
  validation, `pytest`, and `dbt parse`. A red CI blocks the merge.
- Prefer writing or updating the test alongside (ideally before) the logic it covers.

**Rationale**: the testable core is small and deterministic; isolating it from
orchestration makes regressions cheap to catch and the pipeline safe to refactor.

### V. Layered Ownership & Pragmatic Simplicity

- Clear ownership boundaries: **Airflow owns ingestion** (lands immutable `raw`);
  **dbt owns everything downstream** (`staging` views, `marts` tables) with
  dependencies resolved via `ref()`/`source()`, never hand-ordered SQL.
- Scheduling is data-aware: each ingestion DAG publishes an Airflow Asset on success
  and `dbt_transform` is scheduled on those Assets — the pipeline advances when data
  is ready, not on a guessed clock.
- Choose the simplest thing that fits the single-VM, free-tier footprint (e.g.
  LocalExecutor over Celery/K8s; one Postgres with separate databases). Added
  complexity MUST be justified against this constraint (YAGNI).

**Rationale**: explicit boundaries and minimal moving parts keep a 24/7 system
maintainable by one person on free-tier hardware.

### VI. Reproducible, Observable Deploys

- One Docker Compose definition powers DEV, QA, and PROD; only `.env` differs. Promotion
  flows DEV → QA (`develop`) → PROD (`main`) and MUST be automated via GitHub Actions.
- Every DAG MUST alert on failure (webhook, Slack-compatible), degrading to a log line
  when no webhook is configured.
- Configuration, dashboards, and catalog governance are docs-/code-as-source-of-truth
  (e.g. `superset/bootstrap_dashboard.py`, dbt `schema.yml`), so any environment can be
  rebuilt from the repo.

**Rationale**: reproducibility from code plus failure visibility is what makes an
unattended 24/7 pipeline trustworthy.

## Security Requirements

- Secrets are generated per-environment by `make env` into a gitignored `.env`; the
  OpenMetadata env, Cloudflare creds, and JWT signing keys are gitignored too.
- The VM exposes no inbound web ports: public HTTPS is served through a Cloudflare
  Tunnel (`cloudflared` dials out only) at `*.geraldoschuetze.com`.
- Public web surfaces enforce a strict Content-Security-Policy and read-only access;
  the OpenMetadata catalog is fronted by a read-only nginx proxy.
- OpenMetadata JWT signing keys are generated on the VM per environment; bundled demo
  keys MUST NOT be used.
- Static/public assets MUST set hardening headers (HSTS, `X-Content-Type-Options`,
  `X-Frame-Options`, `Referrer-Policy`, `Permissions-Policy`) and avoid inline JS/CSS.

## Development Workflow & Quality Gates

- Feature work follows the Spec Kit flow: `/speckit-specify` → (`/speckit-clarify`) →
  `/speckit-plan` → `/speckit-tasks` → `/speckit-implement`, with the plan's
  "Constitution Check" verifying these principles before implementation.
- Branch model: develop locally, push to `develop` (validates on QA), merge to `main`
  (deploys to PROD). CI gates every push.
- CI/CD does not run dbt; dbt changes are completed on the VM per the deploy runbook.
- Commits on this project are authored by Geraldo Junior and MUST NOT include any
  `Co-Authored-By` trailer.
- Reviews (human or agent) MUST verify compliance with this constitution; unjustified
  violations block the change.

## Governance

- This constitution supersedes other practices where they conflict; the user's explicit
  instructions still take precedence over it.
- Amendments MUST be made via `/speckit-constitution`, versioned by semantic versioning:
  - **MAJOR**: backward-incompatible governance/principle removal or redefinition.
  - **MINOR**: a new principle/section or materially expanded guidance.
  - **PATCH**: clarifications, wording, or non-semantic refinements.
- Every amendment updates the version line and Sync Impact Report, and re-checks the
  dependent `.specify/templates/*` for alignment.
- Compliance is reviewed at plan time (Constitution Check) and at code review.

**Version**: 1.0.0 | **Ratified**: 2026-06-25 | **Last Amended**: 2026-06-25
