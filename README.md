# InsightPilot AI

InsightPilot AI is a chat-first business analytics and reporting project for a synthetic e-commerce dataset. The V1 design uses Python and PostgreSQL to calculate 25 approved metrics. A bounded LangGraph workflow will investigate questions using those metrics, and verified results will power interactive charts and downloadable PDF reports.

## Run locally

On Windows, use Ubuntu WSL for development. Open the repository from WSL, such as `/mnt/d/insightpilotAI`, and use [uv](https://docs.astral.sh/uv/getting-started/installation/) installed inside WSL. Keep the virtual environment on the Linux filesystem for this checkout. Set `UV_PROJECT_ENVIRONMENT` in each shell you use for the project.

```sh
export PATH="$HOME/.local/bin:$PATH"
export UV_PROJECT_ENVIRONMENT="$HOME/.local/share/insightpilot-ai/venv"
uv sync --locked
uv run --locked python -m app
```

uv uses Python 3.12 from `.python-version` and syncs dependencies from `uv.lock`.

`GET http://127.0.0.1:8000/api/v1/health` returns `{"status":"ok"}` when the API is running. This liveness check covers the API process. Interactive API docs are available at `/docs` in development.

Copy `.env.example` to `.env` to configure local settings. `INSIGHTPILOT_ENVIRONMENT` defaults to `development` and also accepts `test`, `staging`, and `production`. Process environment variables override `.env` values.

The standalone API binds to `127.0.0.1:8000` by default. Set `INSIGHTPILOT_BIND_PORT` to change its port when running outside Compose.

## Run the Docker stack

From Ubuntu WSL, set `INSIGHTPILOT_POSTGRES_PASSWORD` in `.env` before the first startup. Compose publishes the API on localhost. Set `INSIGHTPILOT_API_PORT` in `.env` to use a different host port if `8000` is occupied.

```sh
docker compose up --build --wait
docker compose run --rm app alembic upgrade head
curl --fail http://127.0.0.1:8000/api/v1/health
curl --fail http://127.0.0.1:8000/api/v1/ready
```

Liveness checks the API process. Readiness verifies PostgreSQL and Redis connections and returns HTTP 503 if either dependency is unavailable. The RQ worker listens on the `default` queue. PostgreSQL and Redis use named volumes that persist across `docker compose down` and subsequent startups.

## Runtime logs

The API and worker emit JSON logs to stdout. Set `INSIGHTPILOT_LOG_LEVEL` to `DEBUG`, `INFO`, `WARNING`, `ERROR`, or `CRITICAL`. API responses include a server-generated `X-Request-ID` that matches the request log. Each request record includes the status and duration. Events and fields use an allowlist so request contents, credentials, job arguments, and tracebacks stay out of logs.

Use `docker compose logs app worker` to inspect events. Docker rotates logs for each service at 10 MB and retains up to three files per container.

## Verify changes

```sh
uv run --locked pytest -q
uv run --locked ruff check .
uv run --locked ruff format --check .
```

Run `uv run --locked pytest -q --postgres` in WSL to include the migration and database tests on disposable PostgreSQL. GitHub Actions runs that suite, validates the lockfile, scans Git history for secrets, and builds and starts all four services. Run the same isolated Compose and migration smoke test with `bash scripts/smoke_compose.sh`. The smoke test uses port `18016` by default and accepts `INSIGHTPILOT_API_PORT` if you need another port.

## Data model

The [PostgreSQL schema and migration plan](docs/schema.md) covers the 12 V1 tables, their constraints, and the accounting rules for sales and returns.

After applying migrations, `POST /api/v1/session` starts or resumes the anonymous session for the browser that holds its cookie. The default lifetime is 90 days and can be set with `INSIGHTPILOT_SESSION_LIFETIME_DAYS`. Staging and production use a secure cookie over HTTPS. Session history is tied to the browser profile that holds the unexpired cookie.

Set `INSIGHTPILOT_ALLOWED_ORIGINS` to a JSON array of exact browser origins for HTTPS deployments or a custom Compose host port. Local development defaults to `http://localhost:8000` and `http://127.0.0.1:8000`. Session bootstrap and history deletion require a trusted `Origin`. The bootstrap response supplies the session-bound token to send as `X-CSRF-Token` when deleting history.

## Branch workflow

| Branch | Purpose |
| --- | --- |
| `main` | Production releases promoted from `development` by pull request after staging validation and release approval. |
| `development` | Integration branch for reviewed and tested changes. |
| `feature/<brick>` or `fix/<issue>` | Short-lived branches created from `development` and merged back by pull request. |

GitHub requires pull requests and passing CI on `main` and `development`. The solo maintainer can merge pull requests into `development` after CI passes. Production releases into `main` also need an approving review. Both branches block force pushes and branch deletion, with protection enforced for administrators. [GitHub branch protection documentation](https://docs.github.com/en/repositories/configuring-branches-and-merges-in-your-repository/managing-protected-branches/about-protected-branches)

## Pull requests

Keep each pull request focused on one implementation brick or fix. Use the [pull request template](.github/pull_request_template.md) to record the change, checks actually run, and any checks still pending. Review the diff and the CI results before merging.

Before committing, review `git status --short` and `git diff --cached --name-only`. Keep credentials in an ignored `.env` file. Keep runtime logs, generated reports, database dumps, and private data out of Git. Commit only deliberately selected synthetic fixtures.
