import pandas as pd
import streamlit as st
from supabase import create_client

SUPABASE_URL = st.secrets["SUPABASE_URL"]
SUPABASE_KEY = st.secrets["SUPABASE_SERVICE_ROLE_KEY"]

supabase = create_client(SUPABASE_URL, SUPABASE_KEY)

csv_file = r"data/raw/showings.csv"
snapshot_date = "2026-06-11"

df = pd.read_csv(csv_file)
df.columns = [c.strip() for c in df.columns]


def clean_text(value):
    if pd.isna(value):
        return None
    value = str(value).strip()
    return value if value else None


def clean_datetime(value):
    if pd.isna(value):
        return None
    parsed = pd.to_datetime(value, errors="coerce")
    if pd.isna(parsed):
        return None
    return parsed.strftime("%Y-%m-%d %H:%M:%S")


records = []

for _, row in df.iterrows():
    records.append({
        "snapshot_date": snapshot_date,
        "property": clean_text(row.get("Property")),
        "unit": clean_text(row.get("Unit")),
        "status": clean_text(row.get("Status")),
        "showing_time": clean_datetime(row.get("Showing Time")),
        "prospect_name": clean_text(row.get("Prospect Name")),
        "agent": clean_text(row.get("Agent")),
    })


supabase.table("showings").delete().eq("snapshot_date", snapshot_date).execute()
supabase.table("showings").insert(records).execute()


# Create showings_agg table
df["Property"] = df["Property"].apply(clean_text)
df["Status"] = df["Status"].apply(clean_text)

status_lower = df["Status"].fillna("").str.lower()

df["_completed"] = (status_lower == "completed").astype(int)
df["_canceled"] = status_lower.str.contains("canceled", na=False).astype(int)
df["_scheduled"] = (status_lower == "scheduled").astype(int)

agg = df.groupby("Property").agg(
    calc_completed=("_completed", "sum"),
    calc_canceled=("_canceled", "sum"),
    calc_scheduled=("_scheduled", "sum"),
).reset_index()

agg_records = []

for _, row in agg.iterrows():
    agg_records.append({
        "snapshot_date": snapshot_date,
        "property": clean_text(row.get("Property")),
        "calc_completed": int(row.get("calc_completed", 0)),
        "calc_canceled": int(row.get("calc_canceled", 0)),
        "calc_scheduled": int(row.get("calc_scheduled", 0)),
    })

supabase.table("showings_agg").delete().eq("snapshot_date", snapshot_date).execute()
supabase.table("showings_agg").insert(agg_records).execute()

print(f"Uploaded {len(records)} showing rows")
print(f"Uploaded {len(agg_records)} showings agg rows")