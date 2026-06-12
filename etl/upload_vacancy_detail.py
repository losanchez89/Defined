import pandas as pd
import streamlit as st
from supabase import create_client

SUPABASE_URL = st.secrets["SUPABASE_URL"]
SUPABASE_KEY = st.secrets["SUPABASE_SERVICE_ROLE_KEY"]

supabase = create_client(SUPABASE_URL, SUPABASE_KEY)

csv_file = r"data/raw/unit_vacancy_detail.csv"
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
        "unit": clean_text(row.get("Unit")),
        "unit_id": clean_text(row.get("Unit ID")),
        "unit_status": clean_text(row.get("Unit Status")),
        "days_vacant": clean_number(row.get("Days Vacant")),
        "last_rent": clean_money(row.get("Last Rent")),
        "scheduled_rent": clean_money(row.get("Scheduled Rent")),
        "bed_bath": clean_text(row.get("Bed/Bath")),
        "rent_ready": clean_text(row.get("Rent Ready")),
        "available_on": clean_date(row.get("Available On")),
        "rr_status": clean_text(row.get("RR_Status")),
        "rr_tenant": clean_text(row.get("RR_Tenant")),
        "source": clean_text(row.get("Source")),
    })

supabase.table("vacancy_detail").delete().eq("snapshot_date", snapshot_date).execute()
supabase.table("vacancy_detail").insert(records).execute()

print(f"Uploaded {len(records)} vacancy detail rows")