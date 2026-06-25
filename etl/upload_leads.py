import pandas as pd
import streamlit as st
from supabase import create_client

SUPABASE_URL = st.secrets["SUPABASE_URL"]
SUPABASE_KEY = st.secrets["SUPABASE_SERVICE_ROLE_KEY"]

supabase = create_client(SUPABASE_URL, SUPABASE_KEY)

csv_file = r"data/raw/guest_card_interests.csv"
snapshot_date = "2026-06-11"

df = pd.read_csv(csv_file)
df.columns = [c.strip() for c in df.columns]

print(df["Monthly Income"].head(20))

print(df.columns.tolist())


def clean_text(value):
    if pd.isna(value):
        return None
    value = str(value).strip()
    return value if value else None


def clean_number(value):
    if pd.isna(value):
        return 0

    value = str(value).strip()
    value = value.replace("$", "")
    value = value.replace(",", "")
    value = value.replace('"', "")
    value = value.replace(" ", "")

    if value == "" or value.lower() == "nan":
        return 0

    number = pd.to_numeric(value, errors="coerce")
    return 0 if pd.isna(number) else float(number)


records = []

for _, row in df.iterrows():
    credit = clean_number(row.get("Credit Score")) or 0
    income = clean_number(row.get("Monthly Income")) or 0
    status = clean_text(row.get("Status")) or ""

    credit_pts = 0
    if credit >= 750:
        credit_pts = 40
    elif credit >= 700:
        credit_pts = 30
    elif credit >= 650:
        credit_pts = 20
    elif credit >= 600:
        credit_pts = 10

    income_pts = 0
    if income >= 8000:
        income_pts = 25
    elif income >= 6000:
        income_pts = 20
    elif income >= 4000:
        income_pts = 15
    elif income >= 3000:
        income_pts = 10

    status_pts = 0
    if status == "Converting":
        status_pts = 20
    elif status == "Decision Pending":
        status_pts = 15
    elif status == "Active":
        status_pts = 10
    elif status == "New":
        status_pts = 5

    lead_score = credit_pts + income_pts + status_pts

    records.append({
        "snapshot_date": snapshot_date,
        "property": clean_text(row.get("Property")),
        "name": clean_text(row.get("Name")),
        "status": status,
        "monthly_income": income,
        "max_rent": clean_number(row.get("Max Rent")),
        "credit_score": credit,
        "lead_score": lead_score,
    })

supabase.table("leads").delete().eq("snapshot_date", snapshot_date).execute()
supabase.table("leads").insert(records).execute()

print(f"Uploaded {len(records)} lead rows")