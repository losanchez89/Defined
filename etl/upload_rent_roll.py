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


def upload_rent_roll():
    file_path = find_latest("rent_roll")

    if not file_path:
        print("No rent_roll file found in data/raw")
        return

    print(f"Found rent_roll file: {file_path}")

    # AppFolio puede incluir líneas adicionales antes de los encabezados.
    raw = pd.read_csv(file_path, header=None, dtype=str)

    header_row = None

    for index, row in raw.iterrows():
        row_text = " ".join(
            str(value)
            for value in row.values
            if pd.notna(value)
        )

        if "Property" in row_text and "Unit ID" in row_text:
            header_row = index
            break

    if header_row is None:
        raise ValueError(
            "No se encontró la fila de encabezados del rent roll."
        )

    print(f"Header row found at: {header_row}")

    df = pd.read_csv(
        file_path,
        skiprows=header_row,
        dtype=str,
    )

    df.columns = [str(column).strip() for column in df.columns]

    # Conservamos solamente filas que representan unidades reales.
    if "Unit ID" in df.columns:
        df = df[
            df["Unit ID"].notna()
            & (df["Unit ID"].astype(str).str.strip() != "")
        ]
    else:
        df = df[
            df["Property"].notna()
            & (df["Property"].astype(str).str.strip() != "")
        ]

    records = []

    for _, row in df.iterrows():
        records.append({
            "snapshot_date": SNAPSHOT_DATE,
            "property": clean_text(row.get("Property")),
            "unit": clean_text(row.get("Unit")),
            "unit_id": clean_text(row.get("Unit ID")),
            "status": clean_text(row.get("Status")),
            "tenant": clean_text(row.get("Tenant")),
            "rent": clean_money(row.get("Rent")),
            "market_rent": clean_money(row.get("Market Rent")),
            "deposit": clean_money(row.get("Deposit")),
            "past_due": clean_money(row.get("Past Due")),
            "lease_from": clean_date(row.get("Lease From")),
            "lease_to": clean_date(row.get("Lease To")),
            "bd_ba": clean_text(row.get("BD/BA")),
            "portfolio": clean_text(row.get("Portfolio")),
        })

    records = clean_for_json(pd.DataFrame(records))

    print(
        f"Replacing rent_roll snapshot {SNAPSHOT_DATE} "
        f"with {len(records)} rows..."
    )

    delete_snapshot(
        table="rent_roll",
        supabase=supabase,
    )

    upload_batches(
        table="rent_roll",
        records=records,
        supabase=supabase,
    )

    print(
        f"Uploaded rent_roll: {len(records)} rows "
        f"for {SNAPSHOT_DATE}"
    )


if __name__ == "__main__":
    upload_rent_roll()