# InsightPilot AI

InsightPilot AI is a chat-first business analytics and reporting project for a synthetic e-commerce dataset. The V1 design uses Python and PostgreSQL to calculate 25 approved metrics. A bounded LangGraph workflow will investigate questions using those metrics, and verified results will power interactive charts and downloadable PDF reports.

The project is in Phase 1. The FastAPI service and health endpoint are planned for Brick 1.2.

## Branch workflow

| Branch | Purpose |
| --- | --- |
| `main` | Production releases promoted from `development` by pull request after staging validation and release approval. |
| `development` | Integration branch for reviewed and tested changes. |
| `feature/<brick>` or `fix/<issue>` | Short-lived branches created from `development` and merged back by pull request. |

When the GitHub repository is connected, protect `main` and `development` by requiring pull requests and an approving review, blocking force pushes and deletion, and applying the rules to administrators. Require the applicable CI status checks once the workflows are available. [GitHub branch protection documentation](https://docs.github.com/en/repositories/configuring-branches-and-merges-in-your-repository/managing-protected-branches/about-protected-branches)

## Pull requests

Keep each pull request focused on one implementation brick or fix. Use the [pull request template](.github/pull_request_template.md) to record the change, checks actually run, and any checks still pending. Merge after review and the applicable CI checks pass.

Before committing, review `git status --short` and `git diff --cached --name-only`. Keep credentials in an ignored `.env` file. Keep runtime logs, generated reports, database dumps, and private data out of Git. Commit only deliberately selected synthetic fixtures.
