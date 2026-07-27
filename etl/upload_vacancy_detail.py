import pandas as pd

from supabase_client import supabase
from etl.common import (
    SNAPSHOT_DATE,
    clean_date,
    clean_for_json,
    clean_money,
    clean_number,
    clean_text,
    delete_snapshot,
    find_latest,
    upload_batches,
)


def upload_vacancy_detail():
    file_path = find_latest("unit_vacancy_detail")

    if not file_path:
        print("No unit_vacancy_detail file found in data/raw")
        return

    print(f"Found vacancy detail file: {file_path}")

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
        "Unit",
        "Unit ID",
        "Unit Status",
        "Days Vacant",
        "Last Rent",
        "Scheduled Rent",
        "Bed/Bath",
        "Rent Ready",
        "Available On",
    ]

    missing_columns = [
        column
        for column in required_columns
        if column not in df.columns
    ]

    if missing_columns:
        raise ValueError(
            "Missing required vacancy-detail columns: "
            + ", ".join(missing_columns)
        )

    # Mantener únicamente filas que representan unidades.
    df = df[
        df["Unit"].notna()
        & (df["Unit"].astype(str).str.strip() != "")
    ].copy()

    records = []

    for _, row in df.iterrows():
        records.append({
            "snapshot_date": SNAPSHOT_DATE,
            "property": clean_text(row.get("Property")),
            "unit": clean_text(row.get("Unit")),
            "unit_id": clean_text(row.get("Unit ID")),
            "unit_status": clean_text(
                row.get("Unit Status")
            ),
            "days_vacant": clean_number(
                row.get("Days Vacant")
            ),
            "last_rent": clean_money(
                row.get("Last Rent")
            ),
            "scheduled_rent": clean_money(
                row.get("Scheduled Rent")
            ),
            "bed_bath": clean_text(
                row.get("Bed/Bath")
            ),
            "rent_ready": clean_text(
                row.get("Rent Ready")
            ),
            "available_on": clean_date(
                row.get("Available On")
            ),
            "rr_status": clean_text(
                row.get("RR_Status")
            ),
            "rr_tenant": clean_text(
                row.get("RR_Tenant")
            ),
            "source": clean_text(
                row.get("Source")
            ),
        })

    records = clean_for_json(pd.DataFrame(records))

    print(
        f"Replacing vacancy_detail snapshot "
        f"{SNAPSHOT_DATE} with {len(records)} rows..."
    )

    delete_snapshot(
        table="vacancy_detail",
        supabase=supabase,
    )

    upload_batches(
        table="vacancy_detail",
        records=records,
        supabase=supabase,
    )

    print(
        f"Uploaded vacancy_detail: {len(records)} rows "
        f"for {SNAPSHOT_DATE}"
    )


if __name__ == "__main__":
    upload_vacancy_detail()