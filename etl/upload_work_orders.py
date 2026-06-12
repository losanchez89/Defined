import pandas as pd
import streamlit as st
from supabase import create_client

SUPABASE_URL = st.secrets["SUPABASE_URL"]
SUPABASE_KEY = st.secrets["SUPABASE_SERVICE_ROLE_KEY"]

supabase = create_client(SUPABASE_URL, SUPABASE_KEY)

csv_file = r"data/raw/work_order.csv"
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
        "unit": clean_text(row.get("Unit")),
        "status": clean_text(row.get("Status")),
        "priority": clean_text(row.get("Priority")),
        "amount": clean_money(row.get("Amount")),
        "created_at_raw": clean_text(row.get("Created At")),
        "completed_on": clean_text(row.get("Completed On")),
        "days_to_resolve": clean_number(row.get("Days to Resolve")),
        "work_order_issue": clean_text(row.get("Work Order Issue")),
        "vendor": clean_text(row.get("Vendor")),
        "work_order_type": clean_text(row.get("Work Order Type")),
    })

supabase.table("work_orders").delete().eq("snapshot_date", snapshot_date).execute()
supabase.table("work_orders").insert(records).execute()

print(f"Uploaded {len(records)} work order rows")