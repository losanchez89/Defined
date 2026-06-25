import pandas as pd
import streamlit as st
from supabase import create_client

SUPABASE_URL = st.secrets["SUPABASE_URL"]
SUPABASE_KEY = st.secrets["SUPABASE_SERVICE_ROLE_KEY"]

supabase = create_client(SUPABASE_URL, SUPABASE_KEY)

xlsx_file = r"data/raw/Users_Dashboard.xlsx"
snapshot_date = "2026-06-11"

raw = pd.read_excel(xlsx_file, sheet_name="Table_Table", header=None, dtype=str)

period_start = pd.to_datetime(raw.iat[3, 1], errors="coerce")
period_end = pd.to_datetime(raw.iat[3, 2], errors="coerce")

df = raw.iloc[11:].reset_index(drop=True)

df.columns = [
    "Name",
    "Ext",
    "Total Calls",
    "Avg Daily",
    "Inbound",
    "Outbound",
    "Missed with VM",
    "_extra",
]

df = df[
    ["Name", "Ext", "Total Calls", "Avg Daily", "Inbound", "Outbound", "Missed with VM"]
]

df = df[df["Name"].notna() & (df["Name"].astype(str).str.strip() != "")]
df["Name"] = df["Name"].astype(str).str.strip()


def clean_int(value):
    number = pd.to_numeric(value, errors="coerce")
    return 0 if pd.isna(number) else int(number)


records = []

for _, row in df.iterrows():
    inbound = clean_int(row.get("Inbound"))
    missed = clean_int(row.get("Missed with VM"))

    missed_pct = round((missed / inbound * 100), 2) if inbound > 0 else 0

    records.append({
        "snapshot_date": snapshot_date,
        "name": row.get("Name"),
        "ext": row.get("Ext"),
        "total_calls": clean_int(row.get("Total Calls")),
        "avg_daily": clean_int(row.get("Avg Daily")),
        "inbound": inbound,
        "outbound": clean_int(row.get("Outbound")),
        "missed_with_vm": missed,
        "missed_vm_pct": missed_pct,
        "period_start": period_start.strftime("%Y-%m-%d") if not pd.isna(period_start) else None,
        "period_end": period_end.strftime("%Y-%m-%d") if not pd.isna(period_end) else None,
    })

supabase.table("calls").delete().eq("snapshot_date", snapshot_date).execute()
supabase.table("calls").insert(records).execute()

print(f"Uploaded {len(records)} calls rows")