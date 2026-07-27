import pandas as pd

from supabase_client import supabase
from etl.common import (
    SNAPSHOT_DATE,
    clean_for_json,
    clean_number,
    clean_text,
    delete_snapshot,
    find_latest,
    upload_batches,
)


def calculate_lead_score(credit_score, monthly_income, status):
    credit = credit_score or 0
    income = monthly_income or 0
    status = status or ""

    credit_points = 0

    if credit >= 750:
        credit_points = 40
    elif credit >= 700:
        credit_points = 30
    elif credit >= 650:
        credit_points = 20
    elif credit >= 600:
        credit_points = 10

    income_points = 0

    if income >= 8000:
        income_points = 25
    elif income >= 6000:
        income_points = 20
    elif income >= 4000:
        income_points = 15
    elif income >= 3000:
        income_points = 10

    status_points = 0

    if status == "Converting":
        status_points = 20
    elif status == "Decision Pending":
        status_points = 15
    elif status == "Active":
        status_points = 10
    elif status == "New":
        status_points = 5

    return credit_points + income_points + status_points


def upload_leads():
    file_path = find_latest("guest_card_interests")

    if not file_path:
        print("No guest_card_interests file found in data/raw")
        return

    print(f"Found leads file: {file_path}")

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
        "Name",
        "Status",
        "Monthly Income",
        "Credit Score",
        "Property",
    ]

    missing_columns = [
        column
        for column in required_columns
        if column not in df.columns
    ]

    if missing_columns:
        raise ValueError(
            "Missing required leads columns: "
            + ", ".join(missing_columns)
        )

    # Mantener únicamente filas que representan prospectos.
    df = df[
        df["Name"].notna()
        & (df["Name"].astype(str).str.strip() != "")
    ].copy()

    records = []

    for _, row in df.iterrows():
        credit_score = clean_number(
            row.get("Credit Score")
        )

        monthly_income = clean_number(
            row.get("Monthly Income")
        )

        status = clean_text(row.get("Status")) or ""

        lead_score = calculate_lead_score(
            credit_score=credit_score,
            monthly_income=monthly_income,
            status=status,
        )

        records.append({
            "snapshot_date": SNAPSHOT_DATE,
            "property": clean_text(row.get("Property")),
            "name": clean_text(row.get("Name")),
            "status": status,
            "monthly_income": monthly_income or 0,
            "max_rent": clean_number(row.get("Max Rent")) or 0,
            "credit_score": credit_score or 0,
            "lead_score": lead_score,
        })

    records = clean_for_json(pd.DataFrame(records))

    print(
        f"Replacing leads snapshot {SNAPSHOT_DATE} "
        f"with {len(records)} rows..."
    )

    delete_snapshot(
        table="leads",
        supabase=supabase,
    )

    upload_batches(
        table="leads",
        records=records,
        supabase=supabase,
    )

    print(
        f"Uploaded leads: {len(records)} rows "
        f"for {SNAPSHOT_DATE}"
    )


if __name__ == "__main__":
    upload_leads()