import os
import glob
import pandas as pd
from supabase_client import supabase
from etl.common import SNAPSHOT_DATE, clean_date, clean_for_json, clean_money, clean_text, delete_snapshot, upload_batches


def _find_normal_lease_history():
    candidates = [
        f for f in glob.glob("data/raw/lease_history*.csv")
        if "non_revenue" not in os.path.basename(f).lower()
        and "non-revenue" not in os.path.basename(f).lower()
    ]
    return max(candidates, key=os.path.getmtime) if candidates else None


def upload_lease_history():
    fp = _find_normal_lease_history()
    if not fp:
        print("No lease_history CSV found")
        return

    print(f"Found lease_history file: {fp}")
    df = pd.read_csv(fp, dtype=str)
    df.columns = [c.strip() for c in df.columns]

    required = ["Unit Name", "Property", "Tenant Name", "Status", "Countersigned Date", "Renewal"]
    missing = [c for c in required if c not in df.columns]
    if missing:
        raise ValueError("Missing Lease History columns: " + ", ".join(missing))

    df = df[df["Property"].notna() & (df["Property"].astype(str).str.strip() != "")].copy()
    df["snapshot_date"] = SNAPSHOT_DATE
    df = df.rename(columns={
        "Unit Name": "unit_name", "Property": "property", "Tenant Name": "tenant_name",
        "Lease Start": "lease_start", "Lease End": "lease_end", "Rent": "rent",
        "Status": "status", "Countersigned Date": "countersigned_date",
        "Occupancy Name": "occupancy_name",
        "Renewal": "renewal",
    })

    for col in ["lease_start", "lease_end", "countersigned_date"]:
        if col in df.columns:
            df[col] = df[col].apply(clean_date)
    if "rent" in df.columns:
        df["rent"] = df["rent"].apply(clean_money)
    for col in ["unit_name", "property", "tenant_name", "status", "occupancy_name"]:
        if col in df.columns:
            df[col] = df[col].apply(clean_text)
    if "renewal" in df.columns:
        _renewal_text = df["renewal"].fillna("").astype(str).str.strip().str.lower()
        _renewal_map = {
            "yes": True, "true": True, "1": True,
            "no": False, "false": False, "0": False,
        }
        _invalid_renewal = sorted(set(_renewal_text) - set(_renewal_map))
        if _invalid_renewal:
            raise ValueError("Invalid Renewal values: " + ", ".join(repr(v) for v in _invalid_renewal))
        df["renewal"] = _renewal_text.map(_renewal_map)

    keep = ["snapshot_date", "unit_name", "property", "tenant_name", "lease_start", "lease_end",
            "rent", "status", "countersigned_date", "occupancy_name", "renewal"]
    for col in keep:
        if col not in df.columns:
            df[col] = None
    records = clean_for_json(df[keep])
    delete_snapshot("lease_history", supabase, SNAPSHOT_DATE)
    upload_batches("lease_history", records, supabase)
    print(f"Uploaded lease_history: {len(records)} rows for {SNAPSHOT_DATE}")


if __name__ == "__main__":
    upload_lease_history()
