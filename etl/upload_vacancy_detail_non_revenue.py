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


def upload_vacancy_detail_non_revenue():

    # IMPORTANTE:
    # Buscar específicamente el reporte Non-Revenue
    file_path = find_latest("unit_vacancy_detail_non_revenue")

    if not file_path:
        print(
            "No unit_vacancy_detail_non_revenue file found in data/raw"
        )
        return

    print(
        f"Found vacancy detail non-revenue file: {file_path}"
    )

    df = pd.read_csv(
        file_path,
        dtype=str,
        low_memory=False,
    )

    # Limpiar nombres de columnas
    df.columns = [
        str(column).strip()
        for column in df.columns
    ]

    # Columnas mínimas necesarias
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
            "Missing required non-revenue vacancy columns: "
            + ", ".join(missing_columns)
        )

    # Mantener únicamente filas que representan unidades
    df = df[
        df["Unit"].notna()
        & (df["Unit"].astype(str).str.strip() != "")
    ].copy()

    records = []

    for _, row in df.iterrows():

        records.append({
            "snapshot_date": SNAPSHOT_DATE,

            "property": clean_text(
                row.get("Property")
            ),

            "unit": clean_text(
                row.get("Unit")
            ),

            "unit_id": clean_text(
                row.get("Unit ID")
            ),

            "tags": clean_text(
                row.get("Tags")
            ),

            "bed_bath": clean_text(
                row.get("Bed/Bath")
            ),

            "sqft": clean_number(
                row.get("Sqft")
            ),

            "unit_status": clean_text(
                row.get("Unit Status")
            ),

            "rent_ready": clean_text(
                row.get("Rent Ready")
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

            "new_rent": clean_money(
                row.get("New Rent")
            ),

            "last_move_in": clean_date(
                row.get("Last Move In")
            ),

            "last_move_out": clean_date(
                row.get("Last Move Out")
            ),

            "available_on": clean_date(
                row.get("Available On")
            ),

            "next_move_in": clean_date(
                row.get("Next Move In")
            ),

            "description": clean_text(
                row.get("Description")
            ),
        })

    records = clean_for_json(
        pd.DataFrame(records)
    )

    print(
        f"Replacing vacancy_detail_non_revenue snapshot "
        f"{SNAPSHOT_DATE} with {len(records)} rows..."
    )

    # Eliminar solamente el snapshot de hoy
    delete_snapshot(
        table="vacancy_detail_non_revenue",
        supabase=supabase,
    )

    # Subir nuevos registros
    upload_batches(
        table="vacancy_detail_non_revenue",
        records=records,
        supabase=supabase,
    )

    print(
        f"Uploaded vacancy_detail_non_revenue: "
        f"{len(records)} rows for {SNAPSHOT_DATE}"
    )


if __name__ == "__main__":
    upload_vacancy_detail_non_revenue()