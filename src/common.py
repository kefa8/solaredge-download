import csv
import datetime as dt
import hashlib
import json
import os
from pathlib import Path
import sys
import time

import requests

API_BASE = "https://monitoring.solaredge.com/services/dashboard/energy/sites"


def get_timeout_seconds(default=30):
    value = os.getenv("TIMEOUT_SECONDS", str(default))
    try:
        timeout_seconds = float(value)
    except ValueError:
        print(
            f"Invalid TIMEOUT_SECONDS={value!r}; using default {default} seconds",
            file=sys.stderr,
        )
        return default

    if timeout_seconds <= 0:
        print(
            f"TIMEOUT_SECONDS must be > 0; using default {default} seconds",
            file=sys.stderr,
        )
        return default

    return timeout_seconds


def login_playwright(session, username, password, headed=False, timeout_seconds=30):
    try:
        from playwright.sync_api import sync_playwright
    except Exception:
        return False

    with sync_playwright() as p:
        print("Launching Playwright browser...")
        browser = p.chromium.launch(headless=not headed)
        context = browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            viewport={"width": 1280, "height": 720},
        )
        page = context.new_page()
        page.set_default_timeout(int(timeout_seconds * 1000))
        page.goto(
            "https://monitoring.solaredge.com/mfe/auth/", wait_until="domcontentloaded"
        )
        page.get_by_role("button", name="Log in").click()
        print("Filling credentials...")
        page.get_by_role("textbox", name="Email address").fill(username)
        page.get_by_role("textbox", name="Password").fill(password)
        page.locator("form").filter(has_text="With existing account").get_by_role(
            "button", name="Sign in"
        ).click()
        print("Waiting for auth cookies...")
        authed = False
        for _ in range(60):
            cookies = context.cookies()
            if any(
                cookie.get("name") == "se_monitoring_auth"
                and "solaredge.com" in (cookie.get("domain") or "")
                for cookie in cookies
            ):
                authed = True
                break
            time.sleep(1)
        if not authed:
            browser.close()
            return False

        for cookie in context.cookies():
            session.cookies.set(
                cookie["name"],
                cookie["value"],
                domain=cookie.get("domain"),
                path=cookie.get("path", "/"),
            )

        browser.close()

    return (
        session.cookies.get("se_monitoring_auth", domain="monitoring.solaredge.com")
        is not None
    )


def date_range_chunks(start_date, end_date, chunk_days):
    current = start_date
    while current <= end_date:
        chunk_end = min(current + dt.timedelta(days=chunk_days - 1), end_date)
        yield current, chunk_end
        current = chunk_end + dt.timedelta(days=1)


def parse_date(value):
    return dt.datetime.strptime(value, "%Y-%m-%d").date()


def write_csv(rows, output_path):
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(
            handle, fieldnames=["timestamp", "production", "yield", "siteId"]
        )
        writer.writeheader()
        writer.writerows(rows)


def get_chunk_cache_path(
    cache_root,
    site_id,
    chart_time_unit,
    start_date,
    end_date,
    measurement_types,
):
    key = "|".join(
        [
            str(site_id),
            chart_time_unit,
            start_date,
            end_date,
            measurement_types,
        ]
    )
    key_hash = hashlib.sha256(key.encode("utf-8")).hexdigest()[:16]
    filename = f"{start_date}_{end_date}_{key_hash}.json"
    return Path(cache_root) / f"site_{site_id}" / chart_time_unit / filename


def load_chunk_cache(
    cache_root,
    site_id,
    chart_time_unit,
    start_date,
    end_date,
    measurement_types,
):
    cache_path = get_chunk_cache_path(
        cache_root,
        site_id,
        chart_time_unit,
        start_date,
        end_date,
        measurement_types,
    )
    if not cache_path.exists():
        return None

    try:
        with cache_path.open("r", encoding="utf-8") as handle:
            return json.load(handle)
    except (OSError, json.JSONDecodeError) as exc:
        print(f"Ignoring unreadable cache file {cache_path}: {exc}", file=sys.stderr)
        return None


def save_chunk_cache(
    cache_root,
    site_id,
    chart_time_unit,
    start_date,
    end_date,
    measurement_types,
    payload,
):
    cache_path = get_chunk_cache_path(
        cache_root,
        site_id,
        chart_time_unit,
        start_date,
        end_date,
        measurement_types,
    )
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    with cache_path.open("w", encoding="utf-8") as handle:
        json.dump(payload, handle)


def fetch_with_retries(fetch_fn, max_attempts=3, initial_backoff_seconds=1):
    for attempt in range(1, max_attempts + 1):
        try:
            return fetch_fn()
        except requests.RequestException as exc:
            if attempt == max_attempts:
                raise

            backoff_seconds = initial_backoff_seconds * (2 ** (attempt - 1))
            print(
                (
                    f"Request failed (attempt {attempt}/{max_attempts}): {exc}. "
                    f"Retrying in {backoff_seconds} seconds..."
                ),
                file=sys.stderr,
            )
            time.sleep(backoff_seconds)
