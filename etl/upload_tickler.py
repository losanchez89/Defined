import pandas as pd

from supabase_client import supabase
from etl.common import (
    SNAPSHOT_DATE,
    clean_date,
    clean_for_json,
    clean_money,
    clean_text,
    delete_snapshot,
    find_latest,
    upload_batches,
)


def upload_tickler():
    file_path = find_latest("tenant_tickler")

    if not file_path:
        print("No tenant_tickler file found in data/raw")
        return

    print(f"Found tenant_tickler file: {file_path}")

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
        "Date",
        "Event",
        "Tenant",
        "Unit",
        "Rent",
    ]

    missing_columns = [
        column
        for column in required_columns
        if column not in df.columns
    ]

    if missing_columns:
        raise ValueError(
            "Missing required tenant_tickler columns: "
            + ", ".join(missing_columns)
        )

    # Eliminar filas completamente vacías o sin propiedad.
    df = df[
        df["Property"].notna()
        & (
            df["Property"]
            .astype(str)
            .str.strip()
            != ""
        )
    ].copy()

    records = []

    for _, row in df.iterrows():
        records.append({
            "snapshot_date": SNAPSHOT_DATE,
            "property": clean_text(
                row.get("Property")
            ),
            "event_date": clean_date(
                row.get("Date")
            ),
            "event": clean_text(
                row.get("Event")
            ),
            "tenant": clean_text(
                row.get("Tenant")
            ),
            "unit": clean_text(
                row.get("Unit")
            ),
            "rent": clean_money(
                row.get("Rent")
            ),
        })

    records = clean_for_json(
        pd.DataFrame(records)
    )

    print(
        f"Replacing tenant_tickler snapshot "
        f"{SNAPSHOT_DATE} with {len(records)} rows..."
    )

    delete_snapshot(
        table="tenant_tickler",
        supabase=supabase,
    )

    upload_batches(
        table="tenant_tickler",
        records=records,
        supabase=supabase,
    )

    print(
        f"Uploaded tenant_tickler: "
        f"{len(records)} rows "
        f"for {SNAPSHOT_DATE}"
    )


if __name__ == "__main__":
    upload_tickler()