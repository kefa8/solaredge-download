import csv
import datetime as dt
import time

API_BASE = "https://monitoring.solaredge.com/services/dashboard/energy/sites"


def login_playwright(session, username, password, headed=False):
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
        page.set_default_timeout(30000)
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
