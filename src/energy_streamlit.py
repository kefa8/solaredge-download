import argparse
import os
from pathlib import Path

import altair as alt
import pandas as pd
import streamlit as st
from dotenv import load_dotenv


BUCKET_ORDER = [
    f"{hour:02d}:{minute:02d}" for hour in range(24) for minute in (0, 15, 30, 45)
]
HOURLY_BUCKET_ORDER = [f"{hour:02d}:00" for hour in range(24)]
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
        Path("output").glob("energy_*.csv"), key=lambda p: p.stat().st_mtime
    )
    if candidates:
        return candidates[-1]

    return None


@st.cache_data(show_spinner=False)
def load_energy_csv(csv_path_str):
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
    frame["yield"] = pd.to_numeric(frame["yield"], errors="coerce")

    frame["year"] = frame["timestamp"].dt.year.astype(int)
    frame["month_num"] = frame["timestamp"].dt.month.astype(int)
    frame["month_name"] = frame["timestamp"].dt.strftime("%b")
    frame["week_of_year"] = frame["timestamp"].dt.isocalendar().week.astype(int)
    frame["time_bucket"] = frame["timestamp"].dt.strftime("%H:%M")

    return frame


@st.cache_data(show_spinner=False)
def build_aggregate(dataframe, group_mode, bucket_mode, years, months, weeks):
    filtered = dataframe[dataframe["year"].isin(years)].copy()

    if group_mode == "Month":
        filtered = filtered[filtered["month_name"].isin(months)].copy()
        filtered["group_label"] = filtered["month_name"]
        filtered["group_order"] = filtered["month_num"]
    else:
        filtered = filtered[filtered["week_of_year"].isin(weeks)].copy()
        filtered["group_label"] = filtered["week_of_year"].map(
            lambda value: f"W{value:02d}"
        )
        filtered["group_order"] = filtered["week_of_year"]

    filtered = filtered.dropna(subset=["production"]).copy()
    if filtered.empty:
        return filtered

    if bucket_mode == "Hourly":
        filtered["local_date"] = filtered["timestamp"].dt.date
        filtered["bucket"] = filtered["timestamp"].dt.strftime("%H:00")
        bucket_order = HOURLY_BUCKET_ORDER

        hourly_sums = (
            filtered.groupby(
                ["group_label", "group_order", "local_date", "bucket"],
                as_index=False,
            )["production"]
            .sum()
            .rename(columns={"production": "hourly_sum_wh"})
        )

        aggregated = (
            hourly_sums.groupby(
                ["group_label", "group_order", "bucket"], as_index=False
            )["hourly_sum_wh"]
            .mean()
            .rename(columns={"hourly_sum_wh": "avg_value_wh"})
        )
    else:
        filtered["bucket"] = filtered["time_bucket"]
        bucket_order = BUCKET_ORDER
        aggregated = (
            filtered.groupby(["group_label", "group_order", "bucket"], as_index=False)[
                "production"
            ]
            .mean()
            .rename(columns={"production": "avg_value_wh"})
        )

    aggregated["bucket"] = pd.Categorical(
        aggregated["bucket"], categories=bucket_order, ordered=True
    )
    aggregated["avg_value_kwh"] = (aggregated["avg_value_wh"] / 1000.0).round(3)
    aggregated = aggregated.sort_values(["group_order", "bucket"])
    return aggregated


def main():
    load_dotenv(override=True)
    st.set_page_config(page_title="Solar Energy Time-of-Day Averages", layout="wide")
    st.title("SolarEdge Time-of-Day Average Generation")

    cli_input_path = parse_cli_input_path()
    env_input_path = os.getenv("ENERGY_DATA_FILE")
    input_path = resolve_input_path(cli_input_path, env_input_path)

    st.caption(
        "Input precedence: --input argument, ENERGY_DATA_FILE in .env, then latest output/energy_*.csv"
    )

    if input_path is None:
        st.error(
            "No input CSV found. Set ENERGY_DATA_FILE in .env or pass --input path/to/file.csv"
        )
        return

    if not input_path.exists():
        st.error(f"Input CSV not found: {input_path}")
        return

    st.write(f"Using input file: `{input_path}`")

    try:
        data = load_energy_csv(str(input_path.resolve()))
    except Exception as exc:
        st.error(f"Failed to load data: {exc}")
        return

    if data.empty:
        st.warning("No valid rows available after timestamp parsing.")
        return

    available_years = sorted(data["year"].unique().tolist())
    available_months = [
        month for month in MONTH_NAMES if month in set(data["month_name"].unique())
    ]
    available_weeks = sorted(data["week_of_year"].unique().tolist())

    with st.sidebar:
        st.header("Controls")
        group_mode = st.radio("Aggregate by", ["Month", "Week of year"], index=0)
        bucket_mode = st.radio("Time bucket", ["15-minute", "Hourly"], index=1)
        selected_years = st.multiselect(
            "Years", options=available_years, default=available_years
        )

        if group_mode == "Month":
            selected_months = st.multiselect(
                "Months", options=available_months, default=available_months
            )
            selected_weeks = available_weeks
        else:
            selected_weeks = st.multiselect(
                "ISO weeks", options=available_weeks, default=available_weeks
            )
            selected_months = available_months

    if not selected_years:
        st.warning("Select at least one year.")
        return

    if group_mode == "Month" and not selected_months:
        st.warning("Select at least one month.")
        return

    if group_mode == "Week of year" and not selected_weeks:
        st.warning("Select at least one ISO week.")
        return

    aggregated = build_aggregate(
        data,
        group_mode,
        bucket_mode,
        selected_years,
        selected_months,
        selected_weeks,
    )

    if group_mode == "Month":
        ordered_group_labels = selected_months
    else:
        ordered_group_labels = [f"W{value:02d}" for value in selected_weeks]

    aggregated["group_label"] = pd.Categorical(
        aggregated["group_label"], categories=ordered_group_labels, ordered=True
    )
    aggregated = aggregated.sort_values(["group_label", "bucket"])

    if aggregated.empty:
        st.warning("No rows found for the selected filters.")
        return

    bucket_order = HOURLY_BUCKET_ORDER if bucket_mode == "Hourly" else BUCKET_ORDER
    chart_source = aggregated.copy()
    chart_source["bucket"] = chart_source["bucket"].astype(str)

    st.subheader(f"Average production (kWh) by {bucket_mode.lower()} bucket")
    chart = (
        alt.Chart(chart_source)
        .mark_bar()
        .encode(
            x=alt.X("bucket:N", sort=bucket_order, title="Time bucket"),
            y=alt.Y("avg_value_kwh:Q", title="Average production (kWh)"),
            color=alt.Color(
                "group_label:N", title=group_mode, sort=ordered_group_labels
            ),
            xOffset=alt.XOffset("group_label:N", sort=ordered_group_labels),
            tooltip=[
                alt.Tooltip("group_label:N", title="Group"),
                alt.Tooltip("bucket:N", title="Time bucket"),
                alt.Tooltip(
                    "avg_value_kwh:Q", title="Avg production (kWh)", format=".3f"
                ),
            ],
        )
    )
    st.altair_chart(chart, use_container_width=True)

    col1, col2 = st.columns(2)
    col1.metric("Input rows", f"{len(data):,}")
    col2.metric("Aggregated rows", f"{len(aggregated):,}")

    st.subheader("Aggregated data preview")
    st.dataframe(
        aggregated[["group_label", "bucket", "avg_value_kwh"]].rename(
            columns={
                "group_label": "group",
                "bucket": "time_bucket",
                "avg_value_kwh": "avg_production_kwh",
            }
        ),
        use_container_width=True,
    )


if __name__ == "__main__":
    main()
