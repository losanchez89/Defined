import pandas as pd
import streamlit as st
from supabase import create_client

SUPABASE_URL = st.secrets["SUPABASE_URL"]
SUPABASE_KEY = st.secrets["SUPABASE_SERVICE_ROLE_KEY"]

supabase = create_client(SUPABASE_URL, SUPABASE_KEY)

csv_file = r"data/raw/leasing_summary.csv"
snapshot_date = "2026-06-11"

df = pd.read_csv(csv_file)
df.columns = [c.strip() for c in df.columns]


def clean_int(value):
    if pd.isna(value):
        return 0
    number = pd.to_numeric(value, errors="coerce")
    return 0 if pd.isna(number) else int(number)


# Tomamos la primera fila válida del summary
total_row = df[df["Unit Type"] == "Total"]

if len(total_row) == 0:
    raise Exception("Total row not found")

row = total_row.iloc[0]

record = {
    "snapshot_date": snapshot_date,
    "leased": clean_int(row.get("Leased")),
    "move_ins": clean_int(row.get("Move Ins")),
    "move_outs": clean_int(row.get("Move Outs")),
    "inquiries": clean_int(row.get("Interests Received")),
    "showings": clean_int(row.get("Showings Completed")),
    "applications": clean_int(row.get("Applications Received")),
}

supabase.table("leasing_summary").delete().eq("snapshot_date", snapshot_date).execute()
supabase.table("leasing_summary").insert(record).execute()

print("Uploaded leasing summary row")
print(record)