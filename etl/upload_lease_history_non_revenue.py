import glob
import os
import pandas as pd
from supabase_client import supabase
from etl.common import SNAPSHOT_DATE, clean_date, clean_for_json, clean_money, clean_text, delete_snapshot, upload_batches


def _find_non_revenue_lease_history():
    candidates = []
    for f in glob.glob("data/raw/lease_history*.csv"):
        name = os.path.basename(f).lower()
        if "non_revenue" in name or "non-revenue" in name:
            candidates.append(f)
    return max(candidates, key=os.path.getmtime) if candidates else None


def upload_lease_history_non_revenue():
    fp = _find_non_revenue_lease_history()
    if not fp:
        print("No lease_history_non_revenue CSV found")
        return

    print(f"Found lease_history_non_revenue file: {fp}")
    df = pd.read_csv(fp, dtype=str)
    df.columns = [c.strip() for c in df.columns]
    required = ["Unit Name", "Property", "Tenant Name", "Status", "Countersigned Date"]
    missing = [c for c in required if c not in df.columns]
    if missing:
        raise ValueError("Missing Lease History Non-Revenue columns: " + ", ".join(missing))

    df = df[df["Property"].notna() & (df["Property"].astype(str).str.strip() != "")].copy()
    df["snapshot_date"] = SNAPSHOT_DATE
    df = df.rename(columns={
        "Unit Name": "unit_name", "Property": "property", "Tenant Name": "tenant_name",
        "Lease Start": "lease_start", "Lease End": "lease_end", "Rent": "rent",
        "Status": "status", "Countersigned Date": "countersigned_date",
        "Occupancy Name": "occupancy_name",
    })
    for col in ["lease_start", "lease_end", "countersigned_date"]:
        if col in df.columns:
            df[col] = df[col].apply(clean_date)
    if "rent" in df.columns:
        df["rent"] = df["rent"].apply(clean_money)
    for col in ["unit_name", "property", "tenant_name", "status", "occupancy_name"]:
        if col in df.columns:
            df[col] = df[col].apply(clean_text)

    keep = ["snapshot_date", "unit_name", "property", "tenant_name", "lease_start", "lease_end",
            "rent", "status", "countersigned_date", "occupancy_name"]
    for col in keep:
        if col not in df.columns:
            df[col] = None
    records = clean_for_json(df[keep])
    delete_snapshot("lease_history_non_revenue", supabase, SNAPSHOT_DATE)
    upload_batches("lease_history_non_revenue", records, supabase)
    print(f"Uploaded lease_history_non_revenue: {len(records)} rows for {SNAPSHOT_DATE}")


if __name__ == "__main__":
    upload_lease_history_non_revenue()
