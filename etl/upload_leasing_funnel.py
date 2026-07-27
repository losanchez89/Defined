import pandas as pd

from supabase_client import supabase
from etl.common import (
    SNAPSHOT_DATE,
    clean_for_json,
    clean_int,
    clean_text,
    delete_snapshot,
    find_latest,
    upload_batches,
)


def upload_leasing_funnel():
    file_path = find_latest("leasing_funnel_performance")

    if not file_path:
        print(
            "No leasing_funnel_performance file found in data/raw"
        )
        return

    print(f"Found leasing funnel file: {file_path}")

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
        "Inquiries",
        "Completed Showings",
        "Rental Apps",
        "Decision Pending",
        "Approved",
        "Signed Leases",
    ]

    missing_columns = [
        column
        for column in required_columns
        if column not in df.columns
    ]

    if missing_columns:
        raise ValueError(
            "Missing required leasing-funnel columns: "
            + ", ".join(missing_columns)
        )

    records = []

    for _, row in df.iterrows():
        property_name = clean_text(
            row.get("Property")
        )

        # Mantener la misma lógica del archivo original:
        # excluir filas vacías y filas de resumen.
        if (
            not property_name
            or "Signed Leases" in property_name
        ):
            continue

        records.append({
            "snapshot_date": SNAPSHOT_DATE,
            "property": property_name,
            "inquiries": clean_int(
                row.get("Inquiries")
            ),
            "completed_showings": clean_int(
                row.get("Completed Showings")
            ),
            "rental_apps": clean_int(
                row.get("Rental Apps")
            ),
            "decision_pending": clean_int(
                row.get("Decision Pending")
            ),
            "approved": clean_int(
                row.get("Approved")
            ),
            "signed_leases": clean_int(
                row.get("Signed Leases")
            ),
        })

    records = clean_for_json(pd.DataFrame(records))

    print(
        f"Replacing leasing_funnel snapshot "
        f"{SNAPSHOT_DATE} with {len(records)} rows..."
    )

    delete_snapshot(
        table="leasing_funnel",
        supabase=supabase,
    )

    upload_batches(
        table="leasing_funnel",
        records=records,
        supabase=supabase,
    )

    print(
        f"Uploaded leasing_funnel: {len(records)} rows "
        f"for {SNAPSHOT_DATE}"
    )


if __name__ == "__main__":
    upload_leasing_funnel()