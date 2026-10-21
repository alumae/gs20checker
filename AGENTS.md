# Repository Guidelines

## Project Structure & Module Organization

Develop a simple Python web application using Flask. The app checks publication venues against a validated Google Scholar catalogue; see `README.md` for setup and catalogue collection.

Use an `app/` package with a `create_app()` factory in `app/__init__.py`. Keep routes in `app/routes.py`, Jinja templates in `app/templates/`, static assets in `app/static/`, and tests in `tests/`. Keep runtime dependencies in root-level `requirements.txt`; use `requirements-dev.txt` to include runtime dependencies, pytest, and Ruff. Configure tooling in `pyproject.toml` and document setup in `README.md`.

## Build, Test, and Development Commands

Use the existing `flask` conda environment for development. Agents are authorized to install and upgrade Python packages in this environment as needed, without additional confirmation. Record project dependency changes in the appropriate requirements files.

- `conda activate flask`: activate the development environment.

Run these commands after installing dependencies:

- `python -m pip install -r requirements-dev.txt`: install runtime and development dependencies.
- `flask --app app run --debug`: run the local development server.
- `pytest`: run automated tests.
- `ruff check .`: lint Python code.
- `ruff format .`: format Python code.

Run `python build.py` to validate the catalogue and copy static assets for Vercel. Local Flask development does not require this build step. Vercel installs `[project].dependencies` from `pyproject.toml` using uv; keep this list aligned with `requirements.txt` when changing runtime dependencies.

## Coding Style & Naming Conventions

Follow PEP 8 with four-space indentation. Use `snake_case` for modules and functions, `PascalCase` for classes, and uppercase constants. Use Ruff for formatting and linting. Keep route handlers small and move reusable logic into separate modules as needed.

## Testing Guidelines

Use pytest and Flask’s test client, with fixtures creating an application in testing mode. Name test files `test_*.py` and functions `test_*`. Cover successful routes, input validation, failure cases, and bug regressions. No initial coverage threshold is required. Report checks actually run and any validation gaps.

## Commit & Pull Request Guidelines

Git history is currently unavailable. Use concise, imperative commit subjects, such as `Add checker route`, and keep commits focused.

Pull requests should describe the problem, the changes, and validation performed. Link relevant issues when available; include screenshots for visual changes and configuration notes when setup changes.

## Deployment & Configuration

Vercel Pro imports this repository from GitHub, using Python 3.12, `wsgi.py`, and `vercel.json`. Follow `DEPLOYMENT.md` for dashboard setup and release checks. Commit the catalogue and source assets; the build generates `public/static/`. Keep uploads and results request-local and in memory. Hosted requests have stricter size and duration limits. Read secrets from environment variables; exclude `.env` files, `.vercel/`, credentials, and generated workbooks from Git. Keep debug mode local. Validate streaming, cancellation, concurrent uploads, and the full sample workbook before releasing a staged production deployment.
