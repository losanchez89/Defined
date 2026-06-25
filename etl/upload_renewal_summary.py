import pandas as pd
import streamlit as st
from supabase import create_client

SUPABASE_URL = st.secrets["SUPABASE_URL"]
SUPABASE_KEY = st.secrets["SUPABASE_SERVICE_ROLE_KEY"]

supabase = create_client(SUPABASE_URL, SUPABASE_KEY)

csv_file = r"data/raw/renewal_summary.csv"
snapshot_date = "2026-06-11"

df = pd.read_csv(csv_file)
df.columns = [c.strip() for c in df.columns]


def clean_text(value):
    if pd.isna(value):
        return None
    value = str(value).strip()
    return value if value else None


def clean_money(value):
    if pd.isna(value):
        return None
    value = str(value).replace("$", "").replace(",", "").replace('"', "").strip()
    if value == "" or value.lower() == "nan":
        return None
    number = pd.to_numeric(value, errors="coerce")
    return None if pd.isna(number) else float(number)


def clean_number(value):
    if pd.isna(value):
        return None
    number = pd.to_numeric(value, errors="coerce")
    return None if pd.isna(number) else float(number)


records = []

for _, row in df.iterrows():
    records.append({
        "snapshot_date": snapshot_date,
        "property": clean_text(row.get("Property")),
        "unit_id": clean_text(row.get("Unit ID")),
        "tenant_name": clean_text(row.get("Tenant Name")),
        "status": clean_text(row.get("Status")),
        "previous_rent": clean_money(row.get("Previous Rent")),
        "rent": clean_money(row.get("Rent")),
        "percent_difference": clean_number(row.get("Percent Difference")),
    })

supabase.table("renewal_summary").delete().eq("snapshot_date", snapshot_date).execute()
supabase.table("renewal_summary").insert(records).execute()

print(f"Uploaded {len(records)} renewal summary rows")