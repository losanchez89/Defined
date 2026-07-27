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


def upload_aged_receivable():
    file_path = find_latest("aged_receivable_detail")

    if not file_path:
        print("No aged_receivable_detail file found in data/raw")
        return

    print(f"Found aged receivable file: {file_path}")

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
        "Payer Name",
        "Amount Receivable",
    ]

    missing_columns = [
        column
        for column in required_columns
        if column not in df.columns
    ]

    if missing_columns:
        raise ValueError(
            "Missing required aged-receivable columns: "
            + ", ".join(missing_columns)
        )

    df = df[
        df["Property"].notna()
        & (df["Property"].astype(str).str.strip() != "")
    ].copy()

    records = []

    for _, row in df.iterrows():
        records.append({
            "snapshot_date": SNAPSHOT_DATE,
            "property": clean_text(row.get("Property")),
            "payer_name": clean_text(row.get("Payer Name")),
            "amount_receivable": clean_money(
                row.get("Amount Receivable")
            ),
            "d0_30": clean_money(row.get("0-30")),
            "d31_60": clean_money(row.get("31-60")),
            "d61_90": clean_money(row.get("61-90")),
            "d91_plus": clean_money(row.get("91+")),
            "gl_account_name": clean_text(
                row.get("GL Account Name")
            ),
            "gl_account_number": clean_text(
                row.get("GL Account Number")
            ),
            "total_amount": clean_money(
                row.get("Total Amount")
            ),
            "charge_date": clean_date(
                row.get("Charge Date")
            ),
            "posting_date": clean_date(
                row.get("Posting Date")
            ),
        })

    records = clean_for_json(pd.DataFrame(records))

    print(
        f"Replacing aged_receivable snapshot {SNAPSHOT_DATE} "
        f"with {len(records)} rows..."
    )

    delete_snapshot(
        table="aged_receivable",
        supabase=supabase,
    )

    upload_batches(
        table="aged_receivable",
        records=records,
        supabase=supabase,
    )

    print(
        f"Uploaded aged_receivable: {len(records)} rows "
        f"for {SNAPSHOT_DATE}"
    )


if __name__ == "__main__":
    upload_aged_receivable()