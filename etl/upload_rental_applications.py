import pandas as pd

from supabase_client import supabase
from etl.common import (
    SNAPSHOT_DATE,
    clean_date,
    clean_for_json,
    clean_text,
    delete_snapshot,
    find_latest,
    upload_batches,
)


def upload_rental_applications():
    file_path = find_latest("rental_applications")

    if not file_path:
        print("No rental_applications file found in data/raw")
        return

    print(f"Found rental_applications file: {file_path}")

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
        "Applicant(s)",
        "Received",
        "Desired Move In",
        "Status",
        "Property Name",
    ]

    missing_columns = [
        column
        for column in required_columns
        if column not in df.columns
    ]

    if missing_columns:
        raise ValueError(
            "Missing required rental-applications columns: "
            + ", ".join(missing_columns)
        )

    # Mantener únicamente filas que representan solicitudes reales.
    df = df[
        df["Applicant(s)"].notna()
        & (df["Applicant(s)"].astype(str).str.strip() != "")
    ].copy()

    records = []

    for _, row in df.iterrows():
        records.append({
            "snapshot_date": SNAPSHOT_DATE,

            # Property Name del reporte actual se carga en
            # la misma columna property de Supabase.
            "property": clean_text(
                row.get("Property Name")
            ),

            # Applicant(s) reemplaza el antiguo encabezado Applicant.
            "applicant": clean_text(
                row.get("Applicant(s)")
            ),

            "status": clean_text(
                row.get("Status")
            ),

            "received": clean_date(
                row.get("Received")
            ),

            # Applying For contiene el número corto de la unidad.
            # Si está vacío, usamos el campo Unit como respaldo.
            "unit": (
                clean_text(row.get("Applying For"))
                or clean_text(row.get("Unit"))
            ),

            # Desired Move In reemplaza el antiguo Move In Date.
            "move_in_date": clean_date(
                row.get("Desired Move In")
            ),
        })

    records = clean_for_json(pd.DataFrame(records))

    print(
        f"Replacing rental_applications snapshot "
        f"{SNAPSHOT_DATE} with {len(records)} rows..."
    )

    delete_snapshot(
        table="rental_applications",
        supabase=supabase,
    )

    upload_batches(
        table="rental_applications",
        records=records,
        supabase=supabase,
    )

    print(
        f"Uploaded rental_applications: {len(records)} rows "
        f"for {SNAPSHOT_DATE}"
    )


if __name__ == "__main__":
    upload_rental_applications()