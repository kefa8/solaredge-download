import argparse
import os
import sys
from pathlib import Path

import requests
from dotenv import load_dotenv

from common import (
    API_BASE,
    date_range_chunks,
    fetch_with_retries,
    get_timeout_seconds,
    load_chunk_cache,
    login_playwright,
    parse_date,
    save_chunk_cache,
    write_csv,
)


def fetch_energy(session, site_id, start_date, end_date, timeout_seconds):
    url = f"{API_BASE}/{site_id}"
    params = {
        "start-date": start_date,
        "end-date": end_date,
        "chart-time-unit": "quarter-hours",
        "measurement-types": "production,yield",
    }
    headers = {
        "Accept": "application/json, text/plain, */*",
        "Referer": "https://monitoring.solaredge.com/one",
    }
    resp = session.get(url, params=params, headers=headers, timeout=timeout_seconds)
    resp.raise_for_status()
    return resp.json()


def main():
    load_dotenv(override=True)

    parser = argparse.ArgumentParser(
        description="Fetch SolarEdge 15-minute energy data."
    )
    parser.add_argument("--site-id", default=os.getenv("SITE_ID"))
    parser.add_argument("--start-date", required=True, help="YYYY-MM-DD")
    parser.add_argument("--end-date", required=True, help="YYYY-MM-DD")
    parser.add_argument("--chunk-days", type=int, default=1)
    parser.add_argument("--output", default=None)
    parser.add_argument("--headed", action="store_true")
    parser.add_argument("--no-cache", action="store_true")
    args = parser.parse_args()

    username = os.getenv("USERNAME")
    password = os.getenv("PASSWORD")
    timeout_seconds = get_timeout_seconds()

    if not username or not password:
        print("Missing USERNAME or PASSWORD in .env", file=sys.stderr)
        return 1

    start_date = parse_date(args.start_date)
    end_date = parse_date(args.end_date)
    if end_date < start_date:
        print("end-date must be >= start-date", file=sys.stderr)
        return 1

    if args.chunk_days != 1:
        print("quarter-hours data requires daily requests; using chunk-days=1")
        args.chunk_days = 1

    output_path = Path(
        args.output
        or f"output/energy_{args.site_id}_{start_date.isoformat()}_{end_date.isoformat()}.csv"
    )

    session = requests.Session()
    cache_root = Path("output/.cache")
    chart_time_unit = "quarter-hours"
    measurement_types = "production,yield"
    print("Logging in with Playwright...")
    logged_in = login_playwright(
        session,
        username,
        password,
        headed=args.headed,
        timeout_seconds=timeout_seconds,
    )
    if not logged_in:
        print("Login failed.", file=sys.stderr)
        return 1

    rows = []
    for chunk_start, chunk_end in date_range_chunks(
        start_date, end_date, args.chunk_days
    ):
        chunk_start_str = chunk_start.isoformat()
        chunk_end_str = chunk_end.isoformat()
        data = None
        if not args.no_cache:
            data = load_chunk_cache(
                cache_root,
                args.site_id,
                chart_time_unit,
                chunk_start_str,
                chunk_end_str,
                measurement_types,
            )
        if data is None:
            print(f"Fetching {chunk_start_str} to {chunk_end_str}...")
            try:
                data = fetch_with_retries(
                    lambda: fetch_energy(
                        session,
                        args.site_id,
                        chunk_start_str,
                        chunk_end_str,
                        timeout_seconds,
                    ),
                    max_attempts=3,
                )
            except requests.RequestException as exc:
                print(
                    (
                        f"Failed to fetch {chunk_start_str} to {chunk_end_str} "
                        f"after 3 attempts: {exc}"
                    ),
                    file=sys.stderr,
                )
                return 1

            if not args.no_cache:
                save_chunk_cache(
                    cache_root,
                    args.site_id,
                    chart_time_unit,
                    chunk_start_str,
                    chunk_end_str,
                    measurement_types,
                    data,
                )
        else:
            print(f"Using cached chunk {chunk_start_str} to {chunk_end_str}...")

        measurements = data.get("chart", {}).get("measurements", [])
        for item in measurements:
            rows.append(
                {
                    "timestamp": item.get("measurementTime"),
                    "production": item.get("production"),
                    "yield": item.get("yield"),
                    "siteId": args.site_id,
                }
            )

    write_csv(rows, output_path)
    print(f"Wrote {len(rows)} rows to {output_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
