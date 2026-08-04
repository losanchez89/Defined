import os

import pandas as pd
import streamlit as st
from supabase import create_client


SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_SERVICE_ROLE_KEY")

# Respaldo para ejecución local con .streamlit/secrets.toml
if not SUPABASE_URL:
    SUPABASE_URL = st.secrets["SUPABASE_URL"]

if not SUPABASE_KEY:
    SUPABASE_KEY = st.secrets["SUPABASE_SERVICE_ROLE_KEY"]

if not SUPABASE_URL or not SUPABASE_KEY:
    raise RuntimeError(
        "Faltan SUPABASE_URL o SUPABASE_SERVICE_ROLE_KEY."
    )

supabase = create_client(SUPABASE_URL, SUPABASE_KEY)


def find_header_row(raw: pd.DataFrame) -> int:
    """
    Busca automáticamente la fila donde comienza la tabla de usuarios.
    """
    for index, row in raw.iterrows():
        values = row.astype(str).str.strip().tolist()

        if "Name" in values and "Ext" in values:
            return index

    raise ValueError(
        "No se encontró la fila de encabezados en la hoja Table_Table."
    )


def get_call_date(xlsx_file: str) -> str:
    """
    Obtiene y valida la fecha del reporte diario.
    """
    kpi = pd.read_excel(
        xlsx_file,
        sheet_name="KPI_KPI",
        dtype=str,
    )

    required_columns = {"Start Date", "End Date"}
    missing_columns = required_columns.difference(kpi.columns)

    if missing_columns:
        raise ValueError(
            "Faltan columnas en KPI_KPI: "
            + ", ".join(sorted(missing_columns))
        )

    start_date = pd.to_datetime(
        kpi["Start Date"].iloc[0],
        errors="coerce",
    )

    end_date = pd.to_datetime(
        kpi["End Date"].iloc[0],
        errors="coerce",
    )

    if pd.isna(start_date) or pd.isna(end_date):
        raise ValueError(
            "No se pudo obtener la fecha del reporte diario."
        )

    if start_date.date() != end_date.date():
        raise ValueError(
            "El archivo daily_calls.xlsx no corresponde a un solo día. "
            f"Período detectado: {start_date.date()} a {end_date.date()}."
        )

    return end_date.strftime("%Y-%m-%d")


def upload_daily_calls_users() -> None:
    xlsx_file = r"data/raw/daily_calls.xlsx"

    call_date = get_call_date(xlsx_file)

    raw = pd.read_excel(
        xlsx_file,
        sheet_name="Table_Table",
        header=None,
        dtype=str,
    )

    header_row = find_header_row(raw)

    # RingCentral usa dos filas de encabezado:
    # fila 9: Name, Ext, Total Calls, Total Calls, ...
    # fila 10: NaN, NaN, Sum, Avg Daily, Sum, ...
    # Los datos comienzan en la fila siguiente.
    df = raw.iloc[header_row + 2:, :7].copy()

    # Asignamos nombres propios por posición para evitar el encabezado duplicado
    # "Total Calls".
    df.columns = [
        "name",
        "ext",
        "total_calls",
        "avg_daily",
        "inbound",
        "outbound",
        "missed_vm",
    ]

    # Eliminar filas completamente vacías.
    df = df.dropna(how="all")

    # Limpiar nombres.
    df["name"] = (
        df["name"]
        .fillna("")
        .astype(str)
        .str.strip()
        .str.replace(r"\s+", " ", regex=True)
    )

    # Conservar únicamente filas de usuarios.
    df = df[
        (df["name"] != "")
        & (df["name"].str.lower() != "nan")
        & (df["name"].str.lower() != "total")
    ].copy()

    # Limpiar extensiones.
    df["ext"] = (
        df["ext"]
        .fillna("")
        .astype(str)
        .str.strip()
        .str.replace(r"\.0$", "", regex=True)
    )

    # Convertir métricas a valores numéricos.
    numeric_columns = [
        "total_calls",
        "avg_daily",
        "inbound",
        "outbound",
        "missed_vm",
    ]

    for column in numeric_columns:
        df[column] = pd.to_numeric(
            df[column],
            errors="coerce",
        ).fillna(0)

    # Detectar nombres duplicados dentro del mismo reporte.
    duplicates = df[df.duplicated(subset=["name"], keep=False)]

    if not duplicates.empty:
        print("\nDuplicate users detected:")
        print(
            duplicates[
                [
                    "name",
                    "ext",
                    "total_calls",
                    "avg_daily",
                    "inbound",
                    "outbound",
                    "missed_vm",
                ]
            ].to_string(index=False)
        )

    # La tabla usa PRIMARY KEY (call_date, ext), por lo que cada extensión
    # debe aparecer una sola vez dentro del lote. Si RingCentral repite una
    # extensión, consolidamos sus métricas antes de insertar.
    df = df[df["ext"].astype(str).str.strip() != ""].copy()

    duplicate_ext = df[df.duplicated(subset=["ext"], keep=False)]
    if not duplicate_ext.empty:
        print("\nDuplicate extensions detected:")
        print(
            duplicate_ext[
                [
                    "name",
                    "ext",
                    "total_calls",
                    "avg_daily",
                    "inbound",
                    "outbound",
                    "missed_vm",
                ]
            ].to_string(index=False)
        )

    df = (
        df.groupby("ext", as_index=False)
        .agg(
            {
                "name": "first",
                "total_calls": "sum",
                "avg_daily": "sum",
                "inbound": "sum",
                "outbound": "sum",
                "missed_vm": "sum",
            }
        )
    )

    records = []

    for _, row in df.iterrows():
        records.append(
            {
                "call_date": call_date,
                "name": row["name"],
                "ext": row["ext"],
                "total_calls": int(row["total_calls"]),
                "inbound": int(row["inbound"]),
                "outbound": int(row["outbound"]),
                "missed_vm": int(row["missed_vm"]),
                "avg_daily": float(row["avg_daily"]),
            }
        )

    if not records:
        raise ValueError(
            "No se encontraron usuarios válidos para cargar."
        )

    # Reemplazar completamente los datos de esa fecha.
    supabase.table("daily_calls_users") \
        .delete() \
        .eq("call_date", call_date) \
        .execute()

    # Insertar en bloques para mantener estable la carga.
    batch_size = 500
    for start in range(0, len(records), batch_size):
        supabase.table("daily_calls_users") \
            .insert(records[start:start + batch_size]) \
            .execute()

    print(
        f"Uploaded daily_calls_users: "
        f"{len(records)} rows for {call_date}"
    )


if __name__ == "__main__":
    upload_daily_calls_users()
