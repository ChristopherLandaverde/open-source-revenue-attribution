# Open Source Revenue Attribution

Self-hostable, auditable B2B revenue attribution. See which marketing touchpoints are
**associated** with pipeline and closed revenue under a clearly named attribution model,
and inspect the math behind every number.

Attribution here is a reporting model. It shows how a stated rule assigns credit; it does
not estimate causal impact or incrementality.

**Status:** M0 (repository and setup proof). One model (first-touch), a tiny synthetic
sample dataset, and one server-rendered report. See [docs/prd.md](docs/prd.md) for product
scope and [docs/project-management-plan.md](docs/project-management-plan.md) for milestones.

## Quick start (fresh clone to running app with sample data)

Requires Python 3.12, [uv](https://docs.astral.sh/uv/), and Docker (for Postgres).

```sh
git clone https://github.com/ChristopherLandaverde/open-source-revenue-attribution.git
cd open-source-revenue-attribution
uv sync
cp .env.example .env
docker compose up -d --wait db
uv run python manage.py migrate
uv run python manage.py load_sample_data
uv run python manage.py runserver
```

Open http://127.0.0.1:8000/ for the first-touch sample report. Switch between
"Pipeline" and "Won revenue" to swap the results table in place (HTMX).

### Without Docker (SQLite)

Use the same steps, but skip `docker compose` and set the SQLite URL in `.env`:

```sh
sed -i 's|^DATABASE_URL=.*|DATABASE_URL=sqlite:///db.sqlite3|' .env
```

## Checks

```sh
uv run ruff check . && uv run ruff format --check .
uv run python manage.py check
uv run python manage.py makemigrations --check --dry-run
uv run pytest
```

Tests always use in-memory SQLite (`config/settings_test.py`) and need no `.env` or Docker.
CI (`.github/workflows/ci.yml`) runs the same commands.

## Layout

| Path | What |
|---|---|
| `attribution/` | Pure-Python attribution models and types. No Django imports (enforced by a test). |
| `reports/` | Django app: sample records, `load_sample_data` command, report view. |
| `config/` | Django project settings (read from environment / `.env`). |
| `sample_data/` | Synthetic sample dataset with hand-calculated expected results. |
| `templates/`, `static/` | Django templates, plain CSS with design tokens, vendored HTMX and RudderStack SDK. |
| `docs/` | PRD, project management plan, market research. |

## License

MIT. See [LICENSE](LICENSE).
