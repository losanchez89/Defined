import pandas as pd
import streamlit as st
from supabase import create_client

SUPABASE_URL = st.secrets["SUPABASE_URL"]
SUPABASE_KEY = st.secrets["SUPABASE_SERVICE_ROLE_KEY"]

supabase = create_client(SUPABASE_URL, SUPABASE_KEY)

csv_file = r"data/raw/rental_applications.csv"
snapshot_date = "2026-06-11"

df = pd.read_csv(csv_file)
df.columns = [c.strip() for c in df.columns]


def clean_text(value):
    if pd.isna(value):
        return None
    value = str(value).strip()
    return value if value else None


def clean_date(value):
    if pd.isna(value):
        return None
    parsed = pd.to_datetime(value, errors="coerce")
    return None if pd.isna(parsed) else parsed.strftime("%Y-%m-%d")


records = []

for _, row in df.iterrows():
    records.append({
        "snapshot_date": snapshot_date,
        "property": clean_text(row.get("Property")),
        "applicant": clean_text(row.get("Applicant")),
        "status": clean_text(row.get("Status")),
        "received": clean_date(row.get("Received")),
        "unit": clean_text(row.get("Unit")),
        "move_in_date": clean_date(row.get("Move In Date")),
    })

supabase.table("rental_applications").delete().eq("snapshot_date", snapshot_date).execute()
supabase.table("rental_applications").insert(records).execute()

print(f"Uploaded {len(records)} rental application rows")