# Agent Guide for solaredge

This repository is a small Python utility for logging in to SolarEdge Monitoring
and fetching 15-minute energy data. There are no build systems, tests, or linters
configured, so follow the conventions in the existing script and keep changes
minimal and focused.

## Repository Layout
- `src/fetch_energy.py`: main CLI script (login + data extraction + CSV output).
- `src/fetch_energy_daily.py`: daily energy variant (daily chart-time-unit).
- `.env`: credentials (never commit or print).
- `plan.md`: human notes about the approach.

## Build / Lint / Test Commands
There is no build system, no test runner, and no lint/format tooling configured.

Use these commands instead:
- Create the venv + install deps: `uv sync`
- Run the script: `uv run python src/fetch_energy.py --start-date YYYY-MM-DD --end-date YYYY-MM-DD`
- Run with headed browser (for debugging): `uv run python -u src/fetch_energy.py --start-date YYYY-MM-DD --end-date YYYY-MM-DD --headed`
- Install Playwright browsers: `uv run playwright install`

Single-test equivalents:
- Not applicable (no tests exist). If tests are added, document how to run a
  single test in this file.

## Runtime Requirements
- Python 3.11+ (tested on 3.13).
- Dependencies: `requests`, `python-dotenv`, and `playwright`.
- Network access to `monitoring.solaredge.com` and `login.solaredge.com`.

## Configuration (Environment)
Read from `.env` with `load_dotenv(override=True)`.

Required:
- `USERNAME` (email address)
- `PASSWORD`

Never log secrets or raw cookies. Avoid adding any debug prints for credentials,
cookie values, or tokens.

## Login Behavior
- Login is performed using Playwright (`login_playwright`) which automates a
  headless browser to handle the SolarEdge authentication flow.
- Use `--headed` flag to run with a visible browser window for debugging.
- Auth cookies are extracted from the browser session and reused in `requests`
  for subsequent API calls.

## Data Fetch Behavior
- Endpoint: `/services/dashboard/energy/sites/{siteId}`
- Query params must use `chart-time-unit=quarter-hours` for 15-minute data.
- Quarter-hour data requires daily requests (one day per request). The script
  enforces `chunk-days=1`.
- Output: CSV with columns `timestamp`, `production`, `yield`, `siteId`.

## Code Style Guidelines
Follow the existing style in `fetch_energy.py`:

Formatting
- 4-space indentation, no tabs.
- Max line length is not enforced, but keep lines readable.
- Use parentheses for multi-line statements rather than backslashes.

Imports
- Standard library imports first, then third-party imports.
- One import per line (current file follows this).
- Avoid unused imports.

Naming
- `snake_case` for functions, variables, and module-level helpers.
- `UPPER_SNAKE_CASE` for constants.
- Keep function names descriptive and verb-based (`fetch_energy`, `login_playwright`).

Types
- No explicit type hints currently in this codebase.
- If adding types, keep them light and consistent across new code.

Error Handling
- Use explicit checks + `return False` for login failures.
- Use `raise_for_status()` for HTTP errors in fetch paths.
- Print user-facing errors to stderr and return non-zero exit codes in `main`.
- Avoid catching broad exceptions unless needed to convert to a simple failure.

I/O and Output
- Use CSV writing with `csv.DictWriter` and explicit fieldnames.
- Ensure output directory exists before writing.
- Keep progress logging concise; do not print secrets.

External Requests
- Use `requests.Session()` for cookies and keep `timeout` on requests.
- Avoid changing auth flow or endpoints without verifying with devtools capture.

## Agent Workflow Notes
- Prefer minimal changes and preserve the existing CLI interface.
- Keep commands and docs updated in this file if you add tools or tests.

## Cursor / Copilot Rules
- No Cursor rules found (`.cursorrules` or `.cursor/rules/`).
- No Copilot instructions found (`.github/copilot-instructions.md`).

## Common Tasks
Fetch a small sample:
- `uv run python -u src/fetch_energy.py --start-date 2026-03-01 --end-date 2026-03-03 --headed`

Fetch a larger range (daily requests):
- `uv run python -u src/fetch_energy.py --start-date 2026-03-01 --end-date 2026-03-31`

## Adding Tests (If Needed Later)
- Add a lightweight test runner (pytest recommended).
- Include commands here for full suite and single-test execution.
- Keep tests offline by default; mock network calls where practical.
