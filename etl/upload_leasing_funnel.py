import pandas as pd
import streamlit as st
from supabase import create_client

SUPABASE_URL = st.secrets["SUPABASE_URL"]
SUPABASE_KEY = st.secrets["SUPABASE_SERVICE_ROLE_KEY"]

supabase = create_client(SUPABASE_URL, SUPABASE_KEY)

csv_file = r"data/raw/leasing_funnel_performance.csv"
snapshot_date = "2026-06-11"

df = pd.read_csv(csv_file)
df.columns = [c.strip() for c in df.columns]


def clean_text(value):
    if pd.isna(value):
        return None
    value = str(value).strip()
    return value if value else None


def clean_int(value):
    if pd.isna(value):
        return 0
    number = pd.to_numeric(value, errors="coerce")
    return 0 if pd.isna(number) else int(number)


records = []

for _, row in df.iterrows():
    property_name = clean_text(row.get("Property"))

    if not property_name or "Signed Leases" in property_name:
        continue

    records.append({
        "snapshot_date": snapshot_date,
        "property": property_name,
        "inquiries": clean_int(row.get("Inquiries")),
        "completed_showings": clean_int(row.get("Completed Showings")),
        "rental_apps": clean_int(row.get("Rental Apps")),
        "decision_pending": clean_int(row.get("Decision Pending")),
        "approved": clean_int(row.get("Approved")),
        "signed_leases": clean_int(row.get("Signed Leases")),
    })

supabase.table("leasing_funnel").delete().eq("snapshot_date", snapshot_date).execute()
supabase.table("leasing_funnel").insert(records).execute()

print(f"Uploaded {len(records)} leasing funnel rows")