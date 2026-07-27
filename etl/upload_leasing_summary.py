import pandas as pd

from supabase_client import supabase
from etl.common import (
    SNAPSHOT_DATE,
    clean_int,
    delete_snapshot,
    find_latest,
    upload_batches,
)


def upload_leasing_summary():
    file_path = find_latest("leasing_summary")

    if not file_path:
        print("No leasing_summary file found in data/raw")
        return

    print(f"Found leasing_summary file: {file_path}")

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
        "Unit Type",
        "Interests Received",
        "Showings Completed",
        "Applications Received",
        "Move Ins",
        "Move Outs",
        "Leased",
    ]

    missing_columns = [
        column
        for column in required_columns
        if column not in df.columns
    ]

    if missing_columns:
        raise ValueError(
            "Missing required leasing-summary columns: "
            + ", ".join(missing_columns)
        )

    # Tomar únicamente la fila consolidada Total.
    total_rows = df[
        df["Unit Type"]
        .astype(str)
        .str.strip()
        .str.lower()
        .eq("total")
    ]

    if total_rows.empty:
        raise ValueError(
            "Total row not found in leasing_summary.csv"
        )

    row = total_rows.iloc[0]

    record = {
        "snapshot_date": SNAPSHOT_DATE,
        "leased": clean_int(row.get("Leased")),
        "move_ins": clean_int(row.get("Move Ins")),
        "move_outs": clean_int(row.get("Move Outs")),
        "inquiries": clean_int(
            row.get("Interests Received")
        ),
        "showings": clean_int(
            row.get("Showings Completed")
        ),
        "applications": clean_int(
            row.get("Applications Received")
        ),
    }

    print("Leasing summary values:")
    print(f"  Inquiries: {record['inquiries']}")
    print(f"  Showings: {record['showings']}")
    print(f"  Applications: {record['applications']}")
    print(f"  Move Ins: {record['move_ins']}")
    print(f"  Move Outs: {record['move_outs']}")
    print(f"  Leased: {record['leased']}")

    print(
        f"Replacing leasing_summary snapshot "
        f"{SNAPSHOT_DATE}..."
    )

    delete_snapshot(
        table="leasing_summary",
        supabase=supabase,
    )

    upload_batches(
        table="leasing_summary",
        records=[record],
        supabase=supabase,
    )

    print(
        f"Uploaded leasing_summary: 1 row "
        f"for {SNAPSHOT_DATE}"
    )


if __name__ == "__main__":
    upload_leasing_summary()