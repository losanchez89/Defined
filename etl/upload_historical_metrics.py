import pandas as pd
import streamlit as st
from supabase import create_client

SUPABASE_URL = st.secrets["SUPABASE_URL"]
SUPABASE_KEY = st.secrets["SUPABASE_SERVICE_ROLE_KEY"]

supabase = create_client(SUPABASE_URL, SUPABASE_KEY)

snapshot_date = "2026-06-11"


def fetch_table(table):
    result = (
        supabase.table(table)
        .select("*")
        .eq("snapshot_date", snapshot_date)
        .execute()
    )
    return pd.DataFrame(result.data)


rent_roll = fetch_table("rent_roll")
aged = fetch_table("aged_receivable")
leasing = fetch_table("leasing_summary")

total_units = len(rent_roll)

occupied_units = len(
    rent_roll[rent_roll["status"].isin(["Current", "Notice-Unrented", "Evict"])]
)

vacant_units = len(
    rent_roll[rent_roll["status"].isin(["Vacant-Unrented", "Vacant-Rented"])]
)

physical_occupancy = (
    occupied_units / total_units * 100 if total_units > 0 else 0
)

economic_occupied = len(
    rent_roll[rent_roll["status"].isin(["Current", "Vacant-Rented", "Notice-Unrented"])]
)

economic_occupancy = (
    economic_occupied / total_units * 100 if total_units > 0 else 0
)

sum_of_rent = pd.to_numeric(rent_roll["rent"], errors="coerce").fillna(0).sum()

total_ar = pd.to_numeric(
    aged["amount_receivable"], errors="coerce"
).fillna(0).sum()

collection_rate = (
    max(0, min(100, ((sum_of_rent - total_ar) / sum_of_rent * 100)))
    if sum_of_rent > 0
    else 0
)

leasing_row = leasing.iloc[0] if len(leasing) > 0 else {}

record = {
    "date": snapshot_date,
    "physical_occupancy": round(physical_occupancy, 2),
    "economic_occupancy": round(economic_occupancy, 2),
    "total_units": int(total_units),
    "occupied_units": int(occupied_units),
    "vacant_units": int(vacant_units),
    "sum_of_rent": float(sum_of_rent),
    "inquiries": int(leasing_row.get("inquiries", 0)),
    "showings": int(leasing_row.get("showings", 0)),
    "leased": int(leasing_row.get("leased", 0)),
    "collection_rate": float(round(collection_rate, 2)),
}

supabase.table("historical_metrics").delete().eq("date", snapshot_date).execute()
supabase.table("historical_metrics").insert(record).execute()

print("Uploaded historical metrics")
print(record)
