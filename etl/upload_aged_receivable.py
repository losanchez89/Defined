import pandas as pd
import streamlit as st
from supabase import create_client

SUPABASE_URL = st.secrets["SUPABASE_URL"]
SUPABASE_KEY = st.secrets["SUPABASE_SERVICE_ROLE_KEY"]

supabase = create_client(SUPABASE_URL, SUPABASE_KEY)

csv_file = r"data/raw/aged_receivable_detail.csv"
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
    if pd.isna(number):
        return None
    return float(number)

def clean_number(value):
    if pd.isna(value):
        return None

    value = str(value).replace("$", "").replace(",", "").replace('"', "").strip()

    if value == "" or value.lower() == "nan":
        return None

    number = pd.to_numeric(value, errors="coerce")
    return None if pd.isna(number) else float(number)


records = []

for _, row in df.iterrows():
    records.append({
        "snapshot_date": snapshot_date,
        "property": clean_text(row.get("Property")),
        "payer_name": clean_text(row.get("Payer Name")),
        "amount_receivable": clean_money(row.get("Amount Receivable")),
        "d0_30": clean_money(row.get("0-30")),
        "d31_60": clean_money(row.get("31-60")),
        "d61_90": clean_money(row.get("61-90")),
        "d91_plus": clean_money(row.get("91+")),
        "gl_account_name": clean_text(row.get("GL Account Name")),
        "gl_account_number": clean_text(row.get("GL Account Number")),
        "total_amount": clean_number(row.get("Total Amount")),
        "charge_date": clean_text(row.get("Charge Date")),
        "posting_date": clean_text(row.get("Posting Date")),
    })

supabase.table("aged_receivable").delete().eq("snapshot_date", snapshot_date).execute()
supabase.table("aged_receivable").insert(records).execute()

print(f"Uploaded {len(records)} aged receivable rows")