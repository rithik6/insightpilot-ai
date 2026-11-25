# InsightPilot AI project status and handoff

This document records the implemented state of InsightPilot AI, the work awaiting review, and the exact next development starting point. It accompanies the master plan at `C:\Users\HP\Downloads\InsightPilot_AI_Codex_Master_Plan.md`.

## Product and environment

InsightPilot AI is a chat-first business analytics application for a fictional e-commerce business. V1 will calculate exactly 25 approved deterministic metrics from PostgreSQL, use a bounded LangGraph investigation flow, show verified visual insights in web chat, and produce stored PDF reports.

The project uses Python 3.12, FastAPI, PostgreSQL 17, Redis/RQ, SQLAlchemy, Alembic, pytest, Ruff, Docker Compose, and GitHub Actions. Development runs in Ubuntu WSL from `/mnt/d/insightpilotAI`. The personal GitHub remote is `https://github.com/rithik6/insightpilot-ai.git`.

## Source-control state

| Item | Current state |
| --- | --- |
| `main` | Repository foundation at `043256c` |
| `development` | Phases 1 to 3 merged at `bb961ab` |
| Current branch | `feature/metric-spec`, based on `development` |
| Current feature work | Phase 4.1 metric specification and hand-calculated fixture |
| Generated CSVs | Local and ignored by Git under `data/generated/synthetic-v1/` |
| Phase 3 status | Merged into `development` through pull request #10 |

Use a focused `feature/` or `fix/` branch for each brick. Run the checks in this document, review the diff for secrets and generated files, then commit, push, open a pull request into `development`, and merge after CI passes. Promote `development` to `main` after staging validation and release approval.

## Completed foundation

### Phase 1 — Repository and runtime foundation

| Brick | Delivered state | Verification |
| --- | --- | --- |
| 1.1 Repository and workflow | Branches, `.gitignore`, `.env.example`, PR template, and branch documentation | Git history and GitHub workflow established |
| 1.2 FastAPI foundation | Application factory, settings, health endpoint, safe errors, and API docs | Startup and health tests |
| 1.3 Docker services | App, PostgreSQL, Redis, and RQ worker with pinned images, health checks, persistent volumes, and resource limits | `scripts/smoke_compose.sh` |
| 1.4 Structured logging | JSON stdout logs, request IDs, field allowlist, configurable levels, and log rotation | Logging tests and Compose configuration |
| 1.5 Tests and CI | pytest, Ruff, lockfile check, Compose smoke test, and Git history secret scan | GitHub Actions on PRs and protected branches |

### Phase 2 — Database and anonymous sessions

| Brick | Delivered state | Verification |
| --- | --- | --- |
| 2.1 Schema review | Six business tables, six application tables, accounting rules, UTC policy, and indexes | [Schema document](schema.md) |
| 2.2 SQLAlchemy and Alembic | ORM models and initial PostgreSQL migration with named constraints and indexes | Disposable PostgreSQL migration and constraint tests |
| 2.3 Browser sessions | Opaque browser token, SHA-256 token storage, expiry, and cookie policy | Same-browser session tests |
| 2.4 Session security | Ownership checks, expiry behavior, CSRF, trusted origins, and cross-session denial | Session isolation integration tests |
| 2.5 Database integration | Repositories, request transaction boundaries, connection cleanup, and readiness checks | Disposable PostgreSQL integration tests |

Business data is stored in `customers`, `products`, `orders`, `order_items`, `returns`, and `inventory_daily`. Application data is stored in `anonymous_sessions`, `conversations`, `analysis_runs`, `messages`, `reports`, and `llm_usage`.

## Phase 3 — Synthetic data and controlled import

Phase 3 merged into `development` at `bb961ab` through pull request #10. CI passed on the pull request and again on `development` after the merge.

### Reviewed synthetic snapshot

The generator creates six deterministic UTF-8 CSV files from a seed. Default seed `42` covers January 1, 2024 through December 31, 2025 in UTC.

| File | Rows | Content |
| --- | ---: | --- |
| `customers.csv` | 10,000 | Registration date and optional segment |
| `products.csv` | 200 | Catalog SKU, name, and category |
| `orders.csv` | 100,000 | Customer, timestamp, region, and order status |
| `order_items.csv` | 192,838 | Quantity, historical price, discount, and unit cost |
| `returns.csv` | 13,835 | Return event, refund, date, and status |
| `inventory_daily.csv` | 146,200 | Daily closing stock by product |

The reviewed snapshot contains 463,073 rows in total. It uses fictional customer IDs and catalog labels. The generated review workbook and CSV archive are local ignored artifacts in `data/generated/outputs/`.

Known scenarios are documented in [the synthetic-data guide](synthetic-data.md).

- Holiday demand in November and December
- West-region campaign discounts in July and August 2025
- September 16, 2025 order spike
- Elevated Studio Headphones returns
- Desk Lamp stockout from August 11 through August 24, 2025
- Low Travel Organizer margin
- Repeat buyers, cohorts, and cross-month return events

### Validation and import behavior

The controlled validator checks headers, UTF-8 CSV records, IDs, money precision, timestamps with offsets, dates, text fields, keys, product SKUs, foreign keys, order dates, return dates, qualifying statuses, discount caps, refund caps, return quantity caps, and line-item presence. It reports sanitized file-and-line errors.

```sh
uv run --locked python -m app.db.import_synthetic data/generated/synthetic-v1
```

The `--replace` option loads the data into a migrated PostgreSQL database. It uses a transaction-scoped advisory lock, deletes business tables in reverse dependency order, bulk-loads in dependency order, verifies row counts and cross-row rules, then commits. Any failure rolls back. Application tables are outside the replacement.

```sh
docker compose run --rm --build \
  --volume "$PWD/data/generated/synthetic-v1:/synthetic:ro" \
  app python -m app.db.import_synthetic /synthetic --replace
```

### Phase 3 verification evidence

| Check | Result |
| --- | --- |
| Same-seed replay | All six default CSVs matched byte for byte |
| Database cross-check | Disposable PostgreSQL 17 loaded and reconciled all 463,073 rows |
| Integrity rules | No broken foreign keys, duplicate keys, invalid money, invalid timestamps, or business-rule violations |
| Accounting reconciliation | All 24 monthly sales, refund, COGS, gross-profit, and margin totals matched the review calculations |
| Idempotency | Two full loads produced identical counts |
| Rollback | A forced post-copy failure preserved the prior snapshot |
| Error handling | Invalid CSV fixtures returned sanitized file-and-line errors |
| Baseline timing | Monthly reconciliation 382 ms, September spike query 0.56 ms, stockout query 0.05 ms in one local PostgreSQL 17 run |
| Last Phase 3 test suite | 63 tests passed with `pytest -q --postgres` |

The timing figures describe a disposable local database run and act as a future comparison baseline.

## Phase 4 — Analytics foundation

### 4.1 Metric specification

The [metric specification](metrics.md) is on `feature/metric-spec`, pending review and merge.

- Shared rules cover terms, UTC periods, dataset coverage, filters, dimensions, rounding, result statuses, evidence records, and the read-only execution boundary.
- Base calculations B1 for sale totals and B2 for approved return totals include reference SQL. B3 for customer purchases and B4 for inventory days are outlined for later metrics.
- Metrics 01 to 10 are fully specified. Metrics 11 to 25 have planned definitions, dependencies, and the questions Phase 9.1 must settle.
- The dependency graph has no cycles because each metric depends only on base calculations or lower-numbered metrics.
- The `tests/fixtures/metrics-v1/` CSVs pass the snapshot validator. Their expected values were calculated by hand and reproduced by running the B1 and B2 SQL on disposable PostgreSQL 17.
- Six decisions to confirm are listed at the end of the specification.

## Current application scope

The foundation, PostgreSQL schema, anonymous sessions, controlled importer, and metric specification exist. The public application does not yet have the analytics engine, LangGraph investigator, chat UI, chart rendering, or PDF generation.

The importer is a controlled developer operation. Browser users cannot upload or replace business data through FastAPI.

## Verification required after each brick

Run these commands from `/mnt/d/insightpilotAI` after every code, migration, dependency, or runtime change.

```sh
export UV_PROJECT_ENVIRONMENT="$HOME/.local/share/insightpilot-ai/venv"
uv lock --check
uv run --locked --no-sync pytest -q --postgres
uv run --locked --no-sync ruff check .
uv run --locked --no-sync ruff format --check .
git diff --check
```

Run the complete service check after any Compose, dependency, environment, migration, or application-runtime change.

```sh
bash scripts/smoke_compose.sh
```

For a manual API check, run `uv run --locked python -m app` and request `http://127.0.0.1:8000/api/v1/health`. The expected body is `{"status":"ok"}`. The Compose smoke test also checks health and readiness.

For metrics and import work, add focused fixture tests and a disposable PostgreSQL test. For UI work, add route tests and desktop/mobile browser checks. For PDF work, render and inspect the generated document.

## Where to begin next

### Immediate repository step

Finish Phase 4.1 before writing analytics code.

1. Review the [metric specification](metrics.md) and confirm or change its listed decisions.
2. Run the verification checklist and review the diff for secrets and generated files.
3. Commit on `feature/metric-spec`, push, open a pull request into `development`, wait for CI, and merge it.

### Next product brick — Phases 4.2 and 4.3

Implement the shared read-only calculations from the specification.

- B1 sale totals and B2 approved return totals as parameterized SQL with the allowlisted group keys
- Dataset coverage, zero-filled groups, and the `OK`, `NOT_APPLICABLE`, and `INSUFFICIENT_DATA` statuses
- Derived values for net sales, adjusted COGS, gross profit, discounted sales, gross margin, discount rate, and period comparison
- `Decimal` arithmetic with the documented rounding

Test against `tests/fixtures/metrics-v1/` using the expected tables in the specification, including a disposable PostgreSQL test. Phase 4.4 then registers metrics 01 to 10 and their evidence records.

## Remaining roadmap

| Phase | Focus | Start condition |
| --- | --- | --- |
| 4 | Exact metrics and read-only analytics | Phase 3 merged and development snapshot available |
| 5 | LLM gateway, costs, timing, budgets, and failures | Deterministic analytics available |
| 6 | LangGraph, approved tools, guardrails, and evidence | Gateway and analytics tests available |
| 7 | Chat UI, session history, and interactive charts | Saved investigation evidence available |
| 8 | HTML/PDF reports and stored downloads | Verified result snapshots available |
| 9 | Remaining metrics, evaluation, recovery, staging, and release | Application layers complete |

## Working rules

- Use WSL as the main development environment.
- Keep secrets only in ignored `.env` files.
- Use PostgreSQL as the source of truth after import.
- Keep generated data and report artifacts out of Git.
- Use UTC dates and half-open reporting periods.
- Count only `completed` and `fulfilled` orders for sales metrics.
- Apply approved refunds and cost reversals on `returned_at`.
- Aggregate margin numerators and denominators before calculating total margin.
- Keep analytics SQL read-only and registry-controlled.
- Record the actual verification result in every pull request.
