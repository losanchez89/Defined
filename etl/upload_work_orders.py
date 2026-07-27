import pandas as pd

from supabase_client import supabase
from etl.common import (
    SNAPSHOT_DATE,
    clean_for_json,
    clean_money,
    clean_text,
    delete_snapshot,
    find_latest,
    upload_batches,
)


def calculate_days_to_resolve(created_at, completed_on):
    created = pd.to_datetime(created_at, errors="coerce")
    completed = pd.to_datetime(completed_on, errors="coerce")

    if pd.isna(created) or pd.isna(completed):
        return None

    return int((completed - created).days)


def clean_date(value):
    parsed = pd.to_datetime(value, errors="coerce")

    if pd.isna(parsed):
        return None

    return parsed.strftime("%Y-%m-%d")


def upload_work_orders():
    file_path = find_latest("work_order")

    if not file_path:
        print("No work_order file found in data/raw")
        return

    print(f"Found work_order file: {file_path}")

    df = pd.read_csv(
        file_path,
        dtype=str,
        low_memory=False,
    )

    df.columns = [
        str(column).strip()
        for column in df.columns
    ]

    required_columns = [
        "Property",
        "Status",
        "Created At",
    ]

    missing_columns = [
        column
        for column in required_columns
        if column not in df.columns
    ]

    if missing_columns:
        raise ValueError(
            "Missing required work-order columns: "
            + ", ".join(missing_columns)
        )

    # Eliminamos filas completamente vacías o filas de resumen.
    df = df[
        df["Property"].notna()
        & (df["Property"].astype(str).str.strip() != "")
    ].copy()

    records = []

    for _, row in df.iterrows():
        records.append({
            "snapshot_date": SNAPSHOT_DATE,
            "property": clean_text(row.get("Property")),
            "unit": clean_text(row.get("Unit")),
            "status": clean_text(row.get("Status")),
            "priority": clean_text(row.get("Priority")),
            "amount": clean_money(row.get("Amount")),
            "created_at_raw": clean_text(row.get("Created At")),
            "completed_on": clean_date(row.get("Completed On")),
            "days_to_resolve": calculate_days_to_resolve(
                row.get("Created At"),
                row.get("Completed On"),
            ),
            "work_order_issue": clean_text(
                row.get("Work Order Issue")
            ),
            "vendor": clean_text(row.get("Vendor")),
            "work_order_type": clean_text(
                row.get("Work Order Type")
            ),
        })

    records = clean_for_json(pd.DataFrame(records))

    print(
        f"Replacing work_orders snapshot {SNAPSHOT_DATE} "
        f"with {len(records)} rows..."
    )

    delete_snapshot(
        table="work_orders",
        supabase=supabase,
    )

    upload_batches(
        table="work_orders",
        records=records,
        supabase=supabase,
    )

    print(
        f"Uploaded work_orders: {len(records)} rows "
        f"for {SNAPSHOT_DATE}"
    )


if __name__ == "__main__":
    upload_work_orders()