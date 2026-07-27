import pandas as pd
import streamlit as st
from supabase import create_client


SUPABASE_URL = st.secrets["SUPABASE_URL"]
SUPABASE_KEY = st.secrets["SUPABASE_SERVICE_ROLE_KEY"]

supabase = create_client(SUPABASE_URL, SUPABASE_KEY)


def clean_int(value):
    number = pd.to_numeric(value, errors="coerce")
    return 0 if pd.isna(number) else int(number)


def duration_to_seconds(value):
    if value is None or pd.isna(value):
        return 0.0

    try:
        duration = pd.to_timedelta(str(value))
        return round(duration.total_seconds(), 3)
    except (TypeError, ValueError):
        return 0.0


def upload_daily_calls_summary():
    xlsx_file = r"data/raw/daily_calls.xlsx"

    df = pd.read_excel(
        xlsx_file,
        sheet_name="KPI_KPI",
        dtype=str,
    )

    required_columns = {
        "KPI Name",
        "Numbers",
        "Start Date",
        "End Date",
    }

    missing_columns = required_columns.difference(df.columns)

    if missing_columns:
        raise ValueError(
            "Faltan columnas en KPI_KPI: "
            + ", ".join(sorted(missing_columns))
        )

    start_date = pd.to_datetime(
        df["Start Date"].iloc[0],
        errors="coerce",
    )

    end_date = pd.to_datetime(
        df["End Date"].iloc[0],
        errors="coerce",
    )

    if pd.isna(start_date) or pd.isna(end_date):
        raise ValueError(
            "No se pudo obtener la fecha del reporte diario."
        )

    if start_date.date() != end_date.date():
        raise ValueError(
            "El archivo daily_calls.xlsx no corresponde a un solo día. "
            f"Período detectado: {start_date.date()} a {end_date.date()}."
        )

    call_date = end_date.strftime("%Y-%m-%d")

    kpis = dict(
        zip(
            df["KPI Name"].astype(str).str.strip(),
            df["Numbers"],
        )
    )

    total_calls = clean_int(kpis.get("# Total Calls"))
    inbound = clean_int(kpis.get("# Inbound"))
    outbound = clean_int(kpis.get("# Outbound"))
    missed = clean_int(kpis.get("# Missed with VM"))

    answered = max(inbound - missed, 0)

    avg_duration_seconds = duration_to_seconds(
        kpis.get("Avg. Handle Time")
    )

    record = {
        "call_date": call_date,
        "total_calls": total_calls,
        "inbound": inbound,
        "outbound": outbound,
        "missed": missed,
        "answered": answered,
        "avg_duration_seconds": avg_duration_seconds,
    }

    (
        supabase.table("daily_calls_summary")
        .delete()
        .eq("call_date", call_date)
        .execute()
    )

    (
        supabase.table("daily_calls_summary")
        .insert(record)
        .execute()
    )

    print(
        "Uploaded daily_calls_summary: "
        f"{call_date} | "
        f"Total={total_calls} | "
        f"Inbound={inbound} | "
        f"Outbound={outbound} | "
        f"Missed={missed}"
    )


if __name__ == "__main__":
    upload_daily_calls_summary()