from datetime import date
import glob
import os
import pandas as pd

SNAPSHOT_DATE = date.today().isoformat()


def find_latest(prefix):
    """Busca el CSV/XLSX más reciente."""
    files = glob.glob(f"data/raw/{prefix}*.csv")
    files += glob.glob(f"data/raw/{prefix}*.xlsx")

    if not files:
        return None

    return max(files, key=os.path.getmtime)


def clean_text(value):
    if pd.isna(value):
        return None

    value = str(value).strip()

    return value if value else None


def clean_number(value):
    if pd.isna(value):
        return None

    value = str(value)

    value = (
        value.replace("$", "")
             .replace(",", "")
             .replace('"', "")
             .replace("(", "-")
             .replace(")", "")
             .strip()
    )

    if value == "" or value.lower() == "nan":
        return None

    number = pd.to_numeric(value, errors="coerce")

    return None if pd.isna(number) else float(number)


def clean_money(value):
    return clean_number(value)


def clean_int(value):
    number = clean_number(value)

    if number is None:
        return 0

    return int(number)


def clean_date(value):
    if pd.isna(value):
        return None

    parsed = pd.to_datetime(value, errors="coerce")

    if pd.isna(parsed):
        return None

    return parsed.strftime("%Y-%m-%d")


def clean_datetime(value):
    if pd.isna(value):
        return None

    parsed = pd.to_datetime(value, errors="coerce")

    if pd.isna(parsed):
        return None

    return parsed.strftime("%Y-%m-%d %H:%M:%S")


def clean_for_json(df):
    records = df.to_dict("records")

    clean = []

    for row in records:
        clean_row = {}

        for k, v in row.items():
            if pd.isna(v):
                clean_row[k] = None
            else:
                clean_row[k] = v

        clean.append(clean_row)

    return clean

def delete_snapshot(table, supabase, snapshot_date=SNAPSHOT_DATE):
    """
    Elimina los registros existentes de una tabla para una fecha de snapshot.
    """
    supabase.table(table) \
        .delete() \
        .eq("snapshot_date", snapshot_date) \
        .execute()


def upload_batches(table, records, supabase, batch_size=500):
    """
    Inserta registros en Supabase por lotes.
    """
    if not records:
        print(f"No records to upload to {table}")
        return

    for start in range(0, len(records), batch_size):
        batch = records[start:start + batch_size]

        supabase.table(table) \
            .insert(batch) \
            .execute()

        print(
            f"Uploaded {min(start + batch_size, len(records))}"
            f"/{len(records)} rows to {table}"
        )