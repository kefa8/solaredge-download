import argparse
import os
from pathlib import Path

import altair as alt
import pandas as pd
import streamlit as st
from dotenv import load_dotenv

from common import (
    week_display_label,
    year_length,
)


MONTH_NAMES = [
    "Jan",
    "Feb",
    "Mar",
    "Apr",
    "May",
    "Jun",
    "Jul",
    "Aug",
    "Sep",
    "Oct",
    "Nov",
    "Dec",
]
WEEK_NUMBERS = list(range(0, 52))
REFERENCE_YEAR = 2025


def parse_cli_input_path():
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("--input", default=None)
    args, _ = parser.parse_known_args()
    return args.input


def resolve_input_path(cli_input_path, env_input_path):
    if cli_input_path:
        return Path(cli_input_path)

    if env_input_path:
        return Path(env_input_path)

    candidates = sorted(
        Path("output").glob("energy_daily_*.csv"), key=lambda p: p.stat().st_mtime
    )
    if candidates:
        return candidates[-1]

    return None


@st.cache_data(show_spinner=False)
def load_energy_daily_csv(csv_path_str):
    csv_path = Path(csv_path_str)
    frame = pd.read_csv(csv_path)

    required = {"timestamp", "production", "yield", "siteId"}
    missing = required - set(frame.columns)
    if missing:
        missing_list = ", ".join(sorted(missing))
        raise ValueError(f"Missing required columns: {missing_list}")

    cleaned_timestamp = (
        frame["timestamp"]
        .astype("string")
        .str.replace(r"(Z|[+-]\d{2}:\d{2})$", "", regex=True)
    )
    frame["timestamp"] = pd.to_datetime(cleaned_timestamp, errors="coerce")
    frame = frame.dropna(subset=["timestamp"]).copy()

    frame["production"] = pd.to_numeric(frame["production"], errors="coerce")
    frame = frame.dropna(subset=["production"]).copy()

    frame["daily_kwh"] = frame["production"] / 1000.0
    frame["month_num"] = frame["timestamp"].dt.month.astype(int)
    frame["month_name"] = frame["timestamp"].dt.strftime("%b")

    frame["year"] = frame["timestamp"].dt.year.astype(int)
    frame["doy"] = frame["timestamp"].dt.day_of_year
    frame["year_len"] = frame["year"].map(year_length)

    # Fractional position through year (0.0–1.0), then bin into 52 weeks
    frame["frac"] = (frame["doy"] - 1) / frame["year_len"]
    frame["week_num"] = (frame["frac"] * 52).astype(int)  # 0–51, perfectly consistent

    return frame


@st.cache_data(show_spinner=False)
def build_monthly_average(dataframe):
    aggregated = (
        dataframe.groupby(["month_num", "month_name"], as_index=False)["daily_kwh"]
        .mean()
        .rename(columns={"daily_kwh": "avg_daily_kwh"})
    )

    template = pd.DataFrame(
        {
            "month_num": list(range(1, 13)),
            "month_name": MONTH_NAMES,
        }
    )
    output = template.merge(aggregated, on=["month_num", "month_name"], how="left")
    output["avg_daily_kwh"] = output["avg_daily_kwh"].fillna(0.0).round(3)
    return output


@st.cache_data(show_spinner=False)
def build_weekly_average(dataframe):
    aggregated = (
        dataframe.groupby("week_num", as_index=False)["daily_kwh"]
        .mean()
        .rename(columns={"daily_kwh": "avg_daily_kwh"})
    )

    template = pd.DataFrame({"week_num": WEEK_NUMBERS})
    output = template.merge(aggregated, on="week_num", how="left")
    output["avg_daily_kwh"] = output["avg_daily_kwh"].fillna(0.0).round(3)
    output["week_label"] = output["week_num"].map(lambda x: week_display_label(x, REFERENCE_YEAR))
    return output


def main():
    load_dotenv(override=True)
    st.set_page_config(page_title="Solar Daily Average Generation", layout="wide")
    st.title("SolarEdge Average Daily Generation")

    cli_input_path = parse_cli_input_path()
    env_input_path = os.getenv("ENERGY_DAILY_DATA_FILE") or os.getenv(
        "ENERGY_DATA_FILE"
    )
    input_path = resolve_input_path(cli_input_path, env_input_path)

    st.caption(
        "Input precedence: --input argument, ENERGY_DAILY_DATA_FILE/ENERGY_DATA_FILE in .env, then latest output/energy_daily_*.csv"
    )

    if input_path is None:
        st.error(
            "No input CSV found. Set ENERGY_DAILY_DATA_FILE in .env or pass --input path/to/file.csv"
        )
        return

    if not input_path.exists():
        st.error(f"Input CSV not found: {input_path}")
        return

    st.write(f"Using input file: `{input_path}`")

    try:
        data = load_energy_daily_csv(str(input_path.resolve()))
    except Exception as exc:
        st.error(f"Failed to load data: {exc}")
        return

    if data.empty:
        st.warning("No valid rows available after parsing.")
        return

    group_mode = st.radio(
        "Aggregate view", ["Monthly", "Weekly"], index=0, horizontal=True
    )

    if group_mode == "Monthly":
        aggregated = build_monthly_average(data)
        st.subheader("Average daily generation by month (kWh)")
        chart = (
            alt.Chart(aggregated)
            .mark_bar()
            .encode(
                x=alt.X("month_name:N", sort=MONTH_NAMES, title="Month"),
                y=alt.Y("avg_daily_kwh:Q", title="Average daily generation (kWh)"),
                tooltip=[
                    alt.Tooltip("month_name:N", title="Month"),
                    alt.Tooltip("avg_daily_kwh:Q", title="Avg daily kWh", format=".3f"),
                ],
            )
        )
        preview = aggregated[["month_name", "avg_daily_kwh"]].rename(
            columns={"month_name": "month"}
        )
    else:
        aggregated = build_weekly_average(data)
        week_labels = [week_display_label(value, REFERENCE_YEAR) for value in WEEK_NUMBERS]
        st.subheader("Average daily generation by Week (kWh)")
        chart = (
            alt.Chart(aggregated)
            .mark_bar()
            .encode(
                x=alt.X("week_label:N", sort=week_labels, title="Week"),
                y=alt.Y("avg_daily_kwh:Q", title="Average daily generation (kWh)"),
                tooltip=[
                    alt.Tooltip("week_label:N", title="Week"),
                    alt.Tooltip("avg_daily_kwh:Q", title="Avg daily kWh", format=".3f"),
                ],
            )
        )
        preview = aggregated[["week_label", "avg_daily_kwh"]].rename(
            columns={"week_label": "week"}
        )

    st.altair_chart(chart, use_container_width=True)

    col1, col2 = st.columns(2)
    col1.metric("Input rows", f"{len(data):,}")
    col2.metric("Chart bars", f"{len(aggregated):,}")

    st.subheader("Aggregated data preview")
    st.dataframe(preview, use_container_width=True)


if __name__ == "__main__":
    main()
