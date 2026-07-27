import pandas as pd

from supabase_client import supabase
from etl.common import (
    SNAPSHOT_DATE,
    clean_for_json,
    clean_money,
    clean_number,
    clean_text,
    delete_snapshot,
    find_latest,
    upload_batches,
)


def upload_renewal_summary():
    """
    Carga el archivo renewal_summary más reciente a Supabase.

    AppFolio puede exportar varias filas para una misma unidad y residente,
    correspondientes a intentos o cambios dentro del proceso de renovación.

    El ETL conserva un solo registro actual por:
        Property + Unit ID + Tenant Name

    Para elegirlo, prioriza:
        1. La fecha Lease Start más reciente.
        2. La fecha Lease End más reciente.
        3. El estado más definitivo, cuando las fechas son iguales.
    """

    file_path = find_latest("renewal_summary")

    if not file_path:
        print("No renewal_summary file found in data/raw")
        return

    print(f"Found renewal summary file: {file_path}")

    df = pd.read_csv(
        file_path,
        dtype=str,
        low_memory=False,
    )

    # Limpiar nombres de columnas.
    df.columns = [
        str(column).strip()
        for column in df.columns
    ]

    required_columns = [
        "Property",
        "Unit ID",
        "Tenant Name",
        "Status",
        "Lease Start",
        "Lease End",
    ]

    missing_columns = [
        column
        for column in required_columns
        if column not in df.columns
    ]

    if missing_columns:
        raise ValueError(
            "Missing required renewal-summary columns: "
            + ", ".join(missing_columns)
        )

    print(f"Original renewal rows: {len(df)}")

    # Limpiar campos de texto principales.
    text_columns = [
        "Unit Name",
        "Property",
        "Tenant Name",
        "Status",
        "Term",
        "Unit ID",
        "Lease Start Month",
    ]

    for column in text_columns:
        if column in df.columns:
            df[column] = (
                df[column]
                .fillna("")
                .astype(str)
                .str.strip()
            )

    # Eliminar filas vacías, subtotales o sin identificación.
    df = df[
        (df["Property"] != "")
        & (df["Unit ID"] != "")
        & (df["Tenant Name"] != "")
    ].copy()

    print(f"Valid renewal rows: {len(df)}")

    # Convertir fechas.
    date_columns = [
        "Lease Start",
        "Lease End",
        "Previous Lease Start",
        "Previous Lease End",
    ]

    for column in date_columns:
        if column in df.columns:
            df[f"_{column}_date"] = pd.to_datetime(
                df[column],
                errors="coerce",
            )

    rows_before_deduplication = len(df)

    # Prioridad usada únicamente cuando existen registros con las mismas
    # fechas para el mismo residente y unidad.
    status_priority = {
        "Canceled by User": 1,
        "Pending": 2,
        "Did Not Renew": 3,
        "Renewed": 4,
    }

    df["_status_priority"] = (
        df["Status"]
        .map(status_priority)
        .fillna(0)
        .astype(int)
    )

    # Ordenar para que el último registro sea:
    # - la renovación con Lease Start más reciente;
    # - luego Lease End más reciente;
    # - luego el estado más definitivo.
    df = df.sort_values(
        by=[
            "Property",
            "Unit ID",
            "Tenant Name",
            "_Lease Start_date",
            "_Lease End_date",
            "_status_priority",
        ],
        ascending=[
            True,
            True,
            True,
            True,
            True,
            True,
        ],
        na_position="first",
    )

    # Conservar el proceso de renovación más reciente por residente.
    df = df.drop_duplicates(
        subset=[
            "Property",
            "Unit ID",
            "Tenant Name",
        ],
        keep="last",
    ).copy()

    helper_columns = [
        "_status_priority",
        "_Lease Start_date",
        "_Lease End_date",
        "_Previous Lease Start_date",
        "_Previous Lease End_date",
    ]

    df = df.drop(
        columns=[
            column
            for column in helper_columns
            if column in df.columns
        ]
    ).reset_index(drop=True)

    rows_removed = (
        rows_before_deduplication
        - len(df)
    )

    print(
        f"Duplicate/history rows removed: "
        f"{rows_removed}"
    )

    print(
        f"Final unique renewal rows: "
        f"{len(df)}"
    )

    print("\nFinal status distribution:")

    status_counts = (
        df["Status"]
        .replace("", "NULL")
        .value_counts(dropna=False)
    )

    for status, total in status_counts.items():
        print(f"  {status}: {total}")

    records = []

    for _, row in df.iterrows():
        records.append({
            "snapshot_date": SNAPSHOT_DATE,
            "property": clean_text(
                row.get("Property")
            ),
            "unit_id": clean_text(
                row.get("Unit ID")
            ),
            "tenant_name": clean_text(
                row.get("Tenant Name")
            ),
            "status": clean_text(
                row.get("Status")
            ),
            "previous_rent": clean_money(
                row.get("Previous Rent")
            ),
            "rent": clean_money(
                row.get("Rent")
            ),
            "percent_difference": clean_number(
                row.get("Percent Difference")
            ),
        })

    records = clean_for_json(
        pd.DataFrame(records)
    )

    print(
        f"\nReplacing renewal_summary snapshot "
        f"{SNAPSHOT_DATE} with {len(records)} rows."
    )

    delete_snapshot(
        table="renewal_summary",
        supabase=supabase,
    )

    upload_batches(
        table="renewal_summary",
        records=records,
        supabase=supabase,
    )

    print(
        f"Uploaded renewal_summary: "
        f"{len(records)} rows for {SNAPSHOT_DATE}"
    )


if __name__ == "__main__":
    upload_renewal_summary()