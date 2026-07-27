import pandas as pd

from supabase_client import supabase
from etl.common import (
    SNAPSHOT_DATE,
    clean_datetime,
    clean_for_json,
    clean_text,
    delete_snapshot,
    find_latest,
    upload_batches,
)


def upload_showings():
    file_path = find_latest("showings")

    if not file_path:
        print("No showings file found in data/raw")
        return

    print(f"Found showings file: {file_path}")

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
        "Guest Card Name",
        "Property",
        "Showing Unit",
        "Showing Time",
        "Assigned User",
        "Status",
    ]

    missing_columns = [
        column
        for column in required_columns
        if column not in df.columns
    ]

    if missing_columns:
        raise ValueError(
            "Missing required showings columns: "
            + ", ".join(missing_columns)
        )

    # Usar Property como valor principal y Property Name
    # como respaldo cuando Property esté vacío.
    property_series = (
        df["Property"]
        .fillna("")
        .astype(str)
        .str.strip()
    )

    if "Property Name" in df.columns:
        property_name_series = (
            df["Property Name"]
            .fillna("")
            .astype(str)
            .str.strip()
        )

        property_series = property_series.where(
            property_series != "",
            property_name_series,
        )

    # Guardar la propiedad normalizada para usarla tanto
    # en showings como en showings_agg.
    df["_normalized_property"] = property_series

    # Mantener únicamente filas que representan showings.
    df = df[
        df["_normalized_property"] != ""
    ].copy()

    records = []

    for _, row in df.iterrows():
        records.append({
            "snapshot_date": SNAPSHOT_DATE,
            "property": clean_text(
                row.get("_normalized_property")
            ),
            "unit": clean_text(
                row.get("Showing Unit")
            ),
            "status": clean_text(
                row.get("Status")
            ),
            "showing_time": clean_datetime(
                row.get("Showing Time")
            ),
            "prospect_name": clean_text(
                row.get("Guest Card Name")
            ),
            "agent": clean_text(
                row.get("Assigned User")
            ),
        })

    records = clean_for_json(
        pd.DataFrame(records)
    )

    print(
        f"Replacing showings snapshot "
        f"{SNAPSHOT_DATE} with {len(records)} rows..."
    )

    delete_snapshot(
        table="showings",
        supabase=supabase,
    )

    upload_batches(
        table="showings",
        records=records,
        supabase=supabase,
    )

    # Crear resumen de showings por propiedad.
    agg_df = df.copy()

    agg_df["Property"] = agg_df[
        "_normalized_property"
    ].apply(clean_text)

    agg_df["Status"] = agg_df[
        "Status"
    ].apply(clean_text)

    status_lower = (
        agg_df["Status"]
        .fillna("")
        .astype(str)
        .str.strip()
        .str.lower()
    )

    agg_df["_completed"] = (
        status_lower == "completed"
    ).astype(int)

    agg_df["_canceled"] = (
        status_lower.str.contains(
            "canceled",
            na=False,
        )
    ).astype(int)

    agg_df["_scheduled"] = (
        status_lower == "scheduled"
    ).astype(int)

    agg = (
        agg_df.groupby(
            "Property",
            dropna=False,
        )
        .agg(
            calc_completed=(
                "_completed",
                "sum",
            ),
            calc_canceled=(
                "_canceled",
                "sum",
            ),
            calc_scheduled=(
                "_scheduled",
                "sum",
            ),
        )
        .reset_index()
    )

    agg = agg[
        agg["Property"].notna()
        & (
            agg["Property"]
            .astype(str)
            .str.strip()
            != ""
        )
    ].copy()

    agg_records = []

    for _, row in agg.iterrows():
        agg_records.append({
            "snapshot_date": SNAPSHOT_DATE,
            "property": clean_text(
                row.get("Property")
            ),
            "calc_completed": int(
                row.get("calc_completed", 0)
            ),
            "calc_canceled": int(
                row.get("calc_canceled", 0)
            ),
            "calc_scheduled": int(
                row.get("calc_scheduled", 0)
            ),
        })

    agg_records = clean_for_json(
        pd.DataFrame(agg_records)
    )

    print(
        f"Replacing showings_agg snapshot "
        f"{SNAPSHOT_DATE} with "
        f"{len(agg_records)} rows..."
    )

    delete_snapshot(
        table="showings_agg",
        supabase=supabase,
    )

    upload_batches(
        table="showings_agg",
        records=agg_records,
        supabase=supabase,
    )

    print(
        f"Uploaded showings: {len(records)} rows "
        f"for {SNAPSHOT_DATE}"
    )

    print(
        f"Uploaded showings_agg: "
        f"{len(agg_records)} rows "
        f"for {SNAPSHOT_DATE}"
    )


if __name__ == "__main__":
    upload_showings()