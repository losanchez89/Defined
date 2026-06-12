import pandas as pd
import streamlit as st
from supabase import create_client

SUPABASE_URL = st.secrets["SUPABASE_URL"]
SUPABASE_KEY = st.secrets["SUPABASE_SERVICE_ROLE_KEY"]

supabase = create_client(SUPABASE_URL, SUPABASE_KEY)

csv_file = r"data/raw/rent_roll.csv"

df = pd.read_csv(csv_file)
df.columns = [c.strip() for c in df.columns]

snapshot_date = "2026-06-11"


def clean_text(value):
    if pd.isna(value):
        return None
    value = str(value).strip()
    return value if value else None


def clean_money(value):
    if pd.isna(value):
        return None

    value = str(value)
    value = value.replace("$", "")
    value = value.replace(",", "")
    value = value.replace('"', "")
    value = value.strip()

    if value == "" or value.lower() == "nan":
        return None

    number = pd.to_numeric(value, errors="coerce")

    if pd.isna(number):
        return None

    return float(number)


def clean_date(value):
    if pd.isna(value):
        return None

    value = str(value).strip()

    if value == "" or value.lower() == "nan":
        return None

    parsed = pd.to_datetime(value, errors="coerce")

    if pd.isna(parsed):
        return None

    return parsed.strftime("%Y-%m-%d")


records = []

for _, row in df.iterrows():
    records.append({
        "snapshot_date": snapshot_date,
        "property": clean_text(row.get("Property")),
        "unit": clean_text(row.get("Unit")),
        "unit_id": clean_text(row.get("Unit ID")),
        "status": clean_text(row.get("Status")),
        "tenant": clean_text(row.get("Tenant")),
        "rent": clean_money(row.get("Rent")),
        "market_rent": clean_money(row.get("Market Rent")),
        "deposit": clean_money(row.get("Deposit")),
        "past_due": clean_money(row.get("Past Due")),
        "lease_from": clean_date(row.get("Lease From")),
        "lease_to": clean_date(row.get("Lease To")),
        "bd_ba": clean_text(row.get("BD/BA")),
    })

# Optional: delete existing snapshot before inserting again
supabase.table("rent_roll").delete().eq("snapshot_date", snapshot_date).execute()

supabase.table("rent_roll").insert(records).execute()

print(f"Uploaded {len(records)} rent roll rows")