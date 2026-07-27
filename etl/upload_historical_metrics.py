import pandas as pd

from supabase_client import supabase
from etl.common import SNAPSHOT_DATE


def fetch_snapshot(table, snapshot_date, page_size=1000):
    """
    Obtiene todas las filas de una tabla para una fecha específica.

    Se usa paginación porque Supabase normalmente devuelve
    un máximo de 1,000 filas por consulta.
    """
    rows = []
    start = 0

    while True:
        response = (
            supabase.table(table)
            .select("*")
            .eq("snapshot_date", snapshot_date)
            .range(start, start + page_size - 1)
            .execute()
        )

        batch = response.data or []
        rows.extend(batch)

        if len(batch) < page_size:
            break

        start += page_size

    return pd.DataFrame(rows)


def numeric_series(df, column):
    """
    Devuelve una columna numérica segura.

    Si la columna no existe, devuelve una serie de ceros
    con el mismo índice del DataFrame.
    """
    if column not in df.columns:
        return pd.Series(0.0, index=df.index)

    return pd.to_numeric(
        df[column],
        errors="coerce",
    ).fillna(0)


def upload_historical_metrics():
    snapshot_date = SNAPSHOT_DATE

    print(
        f"Building historical metrics for "
        f"{snapshot_date}..."
    )

    # ==========================================================
    # RENT ROLL
    # ==========================================================
    rent_roll = fetch_snapshot(
        table="rent_roll",
        snapshot_date=snapshot_date,
    )

    if rent_roll.empty:
        raise ValueError(
            f"No rent_roll rows found for {snapshot_date}. "
            "Run upload_rent_roll first."
        )

    required_rent_roll_columns = [
        "status",
        "rent",
        "past_due",
    ]

    missing_rent_roll_columns = [
        column
        for column in required_rent_roll_columns
        if column not in rent_roll.columns
    ]

    if missing_rent_roll_columns:
        raise ValueError(
            "Missing required rent_roll columns: "
            + ", ".join(missing_rent_roll_columns)
        )

    status = (
        rent_roll["status"]
        .fillna("")
        .astype(str)
        .str.strip()
    )

    total_units = len(rent_roll)

    occupied_statuses = [
        "Current",
        "Notice-Unrented",
        "Evict",
    ]

    occupied_units = int(
        status.isin(occupied_statuses).sum()
    )

    vacant_units = int(
        total_units - occupied_units
    )

    physical_occupancy = (
        occupied_units / total_units * 100
        if total_units > 0
        else 0
    )

    current_units = int(
        (status == "Current").sum()
    )

    notice_unrented_units = int(
        (status == "Notice-Unrented").sum()
    )

    vacant_rented_units = int(
        (status == "Vacant-Rented").sum()
    )

    economic_occupied_units = (
        current_units
        + notice_unrented_units
        + vacant_rented_units
    )

    economic_occupancy = (
        economic_occupied_units
        / total_units
        * 100
        if total_units > 0
        else 0
    )

    rent_values = numeric_series(
        rent_roll,
        "rent",
    )

    sum_of_rent = float(
        rent_values.sum()
    )

    # ==========================================================
    # COLLECTION RATE
    # Misma fórmula que usa actualmente el dashboard:
    # solo residentes Current y Past Due sin créditos negativos.
    # ==========================================================
    current_mask = status == "Current"

    current_rent = float(
        rent_values[current_mask].sum()
    )

    past_due_values = numeric_series(
        rent_roll,
        "past_due",
    ).clip(lower=0)

    current_past_due = float(
        past_due_values[current_mask].sum()
    )

    collection_rate = (
        (
            current_rent - current_past_due
        )
        / current_rent
        * 100
        if current_rent > 0
        else 0
    )

    collection_rate = max(
        0.0,
        min(100.0, collection_rate),
    )

    # ==========================================================
    # LEASING SUMMARY
    # ==========================================================
    leasing_summary = fetch_snapshot(
        table="leasing_summary",
        snapshot_date=snapshot_date,
    )

    inquiries = 0
    showings = 0
    leased = 0

    if not leasing_summary.empty:
        inquiries = int(
            numeric_series(
                leasing_summary,
                "inquiries",
            ).sum()
        )

        showings = int(
            numeric_series(
                leasing_summary,
                "showings",
            ).sum()
        )

        leased = int(
            numeric_series(
                leasing_summary,
                "leased",
            ).sum()
        )

    # ==========================================================
    # HISTORICAL METRICS RECORD
    # Se mantienen exactamente las columnas existentes.
    # ==========================================================
    record = {
        "date": snapshot_date,
        "physical_occupancy": round(
            float(physical_occupancy),
            2,
        ),
        "economic_occupancy": round(
            float(economic_occupancy),
            2,
        ),
        "total_units": int(total_units),
        "occupied_units": int(occupied_units),
        "vacant_units": int(vacant_units),
        "sum_of_rent": float(sum_of_rent),
        "inquiries": int(inquiries),
        "showings": int(showings),
        "leased": int(leased),
        "collection_rate": round(
            float(collection_rate),
            2,
        ),
    }

    print("Historical metrics calculated:")
    print(
        f"  Total Units: {record['total_units']}"
    )
    print(
        f"  Occupied Units: "
        f"{record['occupied_units']}"
    )
    print(
        f"  Vacant Units: "
        f"{record['vacant_units']}"
    )
    print(
        f"  Physical Occupancy: "
        f"{record['physical_occupancy']}%"
    )
    print(
        f"  Economic Occupancy: "
        f"{record['economic_occupancy']}%"
    )
    print(
        f"  Sum of Rent: "
        f"${record['sum_of_rent']:,.2f}"
    )
    print(
        f"  Collection Rate: "
        f"{record['collection_rate']}%"
    )
    print(
        f"  Inquiries: {record['inquiries']}"
    )
    print(
        f"  Showings: {record['showings']}"
    )
    print(
        f"  Leased: {record['leased']}"
    )

    # historical_metrics utiliza "date", no "snapshot_date".
    print(
        f"Replacing historical_metrics record "
        f"for {snapshot_date}..."
    )

    (
        supabase.table("historical_metrics")
        .delete()
        .eq("date", snapshot_date)
        .execute()
    )

    (
        supabase.table("historical_metrics")
        .insert(record)
        .execute()
    )

    print(
        f"Uploaded historical_metrics: "
        f"1 row for {snapshot_date}"
    )


if __name__ == "__main__":
    upload_historical_metrics()