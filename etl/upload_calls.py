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


def upload_calls():
    file_path = find_latest("Users_Dashboard")

    if not file_path:
        print("No Users_Dashboard file found in data/raw")
        return

    print(f"Found calls file: {file_path}")

    # Los datos de usuarios están en la hoja Table_Table.
    raw = pd.read_excel(
        file_path,
        sheet_name="Table_Table",
        header=None,
        dtype=str,
    )

    # Las fechas generales del reporte están en la fila 3.
    period_start = clean_text(raw.iloc[3, 1])
    period_end = clean_text(raw.iloc[3, 2])

    # Los encabezados están divididos entre las filas 9 y 10.
    # Los registros comienzan en la fila 11.
    df = raw.iloc[11:, :7].copy()

    df.columns = [
        "Name",
        "Ext",
        "Total Calls",
        "Avg Daily",
        "Inbound",
        "Outbound",
        "Missed with VM",
    ]

    # Mantener solamente filas con nombre de usuario.
    df = df[
        df["Name"].notna()
        & (df["Name"].astype(str).str.strip() != "")
    ].copy()

    # Eliminar posibles filas de totales.
    df = df[
        ~df["Name"]
        .astype(str)
        .str.strip()
        .str.lower()
        .isin(["total", "totals"])
    ].copy()

    records = []

    for _, row in df.iterrows():
        records.append({
            "snapshot_date": SNAPSHOT_DATE,
            "name": clean_text(row.get("Name")),
            "ext": clean_text(row.get("Ext")),
            "total_calls": clean_int(row.get("Total Calls")),
            "avg_daily": clean_int(row.get("Avg Daily")),    
            "inbound": clean_int(row.get("Inbound")),
            "outbound": clean_int(row.get("Outbound")),
            "missed_with_vm": clean_int(
                row.get("Missed with VM")
            ),
            "period_start": period_start,
            "period_end": period_end,
        })

    records = clean_for_json(pd.DataFrame(records))

    print(f"Report period: {period_start} to {period_end}")

    print(
        f"Replacing calls snapshot {SNAPSHOT_DATE} "
        f"with {len(records)} rows..."
    )

    delete_snapshot(
        table="calls",
        supabase=supabase,
    )

    upload_batches(
        table="calls",
        records=records,
        supabase=supabase,
    )

    print(
        f"Uploaded calls: {len(records)} rows "
        f"for {SNAPSHOT_DATE}"
    )


if __name__ == "__main__":
    upload_calls()