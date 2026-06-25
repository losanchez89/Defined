from pathlib import Path
from datetime import date
import pandas as pd
from streamlit import status
from supabase_client import supabase
import os
import glob

DATA_DIR = Path("data/raw")
SNAPSHOT_DATE = date.today().isoformat()


def find_latest(prefix):
    files = glob.glob(f"data/raw/{prefix}*.csv")
    files += glob.glob(f"data/raw/{prefix}*.xlsx")
    if not files:
        return None

    return max(files, key=os.path.getmtime)

def fetch_all_supabase(table, snapshot_date, page_size=1000):
    rows = []
    start = 0

    while True:
        res = (
            supabase.table(table)
            .select("*")
            .eq("snapshot_date", snapshot_date)
            .range(start, start + page_size - 1)
            .execute()
        )

        batch = res.data or []
        rows.extend(batch)

        if len(batch) < page_size:
            break

        start += page_size

    return rows


def clean_money(value):
    if isinstance(value, pd.Series):
        return (
            value.astype(str)
            .str.replace("$", "", regex=False)
            .str.replace(",", "", regex=False)
            .str.replace("(", "-", regex=False)
            .str.replace(")", "", regex=False)
            .str.strip()
            .replace({"nan": None, "None": None, "": None})
            .apply(lambda x: pd.to_numeric(x, errors="coerce") if x is not None else None)
        )

    if pd.isna(value):
        return None

    value = str(value)
    value = value.replace("$", "")
    value = value.replace(",", "")
    value = value.replace("(", "-")
    value = value.replace(")", "")
    value = value.strip()

    if value == "" or value.lower() == "nan":
        return None

    return pd.to_numeric(value, errors="coerce")

def clean_for_json(df):
    records = df.to_dict("records")
    clean = []

    for row in records:
        new_row = {}
        for k, v in row.items():
            if pd.isna(v):
                new_row[k] = None
            else:
                new_row[k] = v
        clean.append(new_row)



def clean_for_json(df):
    records = df.to_dict("records")

    clean_records = []

    for row in records:
        clean_row = {}
        for k, v in row.items():
            if pd.isna(v):
                clean_row[k] = None
            else:
                clean_row[k] = v
        clean_records.append(clean_row)

    return clean_records


def upload_rent_roll():

    fp = find_latest("rent_roll")

    if not fp:
        print("No rent_roll CSV found")
        return

    print(f"Found rent_roll file: {fp}")

    # Buscar fila real de encabezados
    df_raw = pd.read_csv(fp, header=None, dtype=str)

    header_row = None

    for idx, row in df_raw.iterrows():
        row_text = " ".join(
            [str(v) for v in row.values if pd.notna(v)]
        )

        if "Property" in row_text and "Unit ID" in row_text:
            header_row = idx
            break

    if header_row is None:
        raise ValueError(
            "No se encontró la fila de encabezados del rent_roll"
        )

    print(f"Header row found at: {header_row}")

    df = pd.read_csv(
        fp,
        skiprows=header_row,
        dtype=str
    )

    # Eliminar filas vacías
    df = df[
        df["Property"].notna()
        & (df["Property"].astype(str).str.strip() != "")
    ]
    
    print(f"Rows after cleanup: {len(df)}")

    df["snapshot_date"] = SNAPSHOT_DATE

    rename = {
        "Property": "property",
        "Unit": "unit",
        "Unit ID": "unit_id",
        "Status": "status",
        "Tenant": "tenant",
        "Rent": "rent",
        "Market Rent": "market_rent",
        "Deposit": "deposit",
        "Past Due": "past_due",
        "Lease From": "lease_from",
        "Lease To": "lease_to",
        "BD/BA": "bd_ba",
        "Portfolio": "portfolio",
    }

    df = df.rename(columns=rename)

    keep_cols = [
        "snapshot_date",
        "property",
        "unit",
        "unit_id",
        "status",
        "tenant",
        "rent",
        "market_rent",
        "deposit",
        "past_due",
        "lease_from",
        "lease_to",
        "bd_ba",
        "portfolio",
    ]

    df = df[[c for c in keep_cols if c in df.columns]]

    for col in ["rent", "market_rent", "deposit", "past_due"]:
        if col in df.columns:
            df[col] = clean_money(df[col])

    for col in df.columns:
        if df[col].dtype == "object":
            df[col] = df[col].replace(
                {"": None, "nan": None, "None": None}
            )

    records = clean_for_json(df)

    print(f"Deleting snapshot {SNAPSHOT_DATE}")

    supabase.table("rent_roll") \
        .delete() \
        .eq("snapshot_date", SNAPSHOT_DATE) \
        .execute()

    print(f"Uploading {len(records)} rows...")

    for i in range(0, len(records), 500):
        supabase.table("rent_roll") \
            .insert(records[i:i + 500]) \
            .execute()

    print(
        f"Uploaded rent_roll: {len(records)} rows "
        f"for {SNAPSHOT_DATE}"
    )



#=================================================
# ===== WORK ORDERS=====================
#=================================================

def parse_date_col(s):
    return pd.to_datetime(s, errors="coerce").dt.strftime("%Y-%m-%d")


def upload_work_orders():
    fp = find_latest("work_order")
    if not fp:
        print("No work_order CSV found")
        return

    print(f"Found work_order file: {fp}")

    df = pd.read_csv(fp, dtype=str)
    df.columns = [c.strip() for c in df.columns]

    df["snapshot_date"] = SNAPSHOT_DATE

    rename = {
        "Property": "property",
        "Unit": "unit",
        "Status": "status",
        "Priority": "priority",
        "Amount": "amount",
        "Created At": "created_at_raw",
        "Completed On": "completed_on",
        "Work Order Issue": "work_order_issue",
        "Vendor": "vendor",
        "Work Order Type": "work_order_type",
    }

    df = df.rename(columns=rename)

    keep_cols = [
        "snapshot_date",
        "property",
        "unit",
        "status",
        "priority",
        "amount",
        "created_at_raw",
        "completed_on",
        "work_order_issue",
        "vendor",
        "work_order_type",
    ]

    df = df[[c for c in keep_cols if c in df.columns]]

    df["amount"] = df["amount"].apply(clean_money)

    created = pd.to_datetime(df["created_at_raw"], errors="coerce")
    completed = pd.to_datetime(df["completed_on"], errors="coerce")

    df["days_to_resolve"] = (completed - created).dt.days

    df["completed_on"] = completed.dt.strftime("%Y-%m-%d")

    records = clean_for_json(df)

    supabase.table("work_orders").delete().eq("snapshot_date", SNAPSHOT_DATE).execute()

    for i in range(0, len(records), 500):
        supabase.table("work_orders").insert(records[i:i+500]).execute()

    print(f"Uploaded work_orders: {len(records)} rows for {SNAPSHOT_DATE}")

#=================================================
#====Aged Receivables======================
#=================================================

def upload_aged_receivable():
    fp = find_latest("aged_receivable_detail")
    if not fp:
        fp = find_latest("aged_receivable")

    if not fp:
        print("No aged_receivable CSV found")
        return

    print(f"Found aged_receivable file: {fp}")

    df = pd.read_csv(fp, dtype=str)
    df.columns = [c.strip() for c in df.columns]

    df = df[
        df["Property"].notna()
        & (df["Property"].astype(str).str.strip() != "")
    ]

    df["snapshot_date"] = SNAPSHOT_DATE

    rename = {
        "Property": "property",
        "Payer Name": "payer_name",
        "Amount Receivable": "amount_receivable",
        "0-30": "d0_30",
        "31-60": "d31_60",
        "61-90": "d61_90",
        "91+": "d91_plus",
        "GL Account Name": "gl_account_name",
        "GL Account Number": "gl_account_number",
        "Total Amount": "total_amount",
        "Charge Date": "charge_date",
        "Posting Date": "posting_date",
    }

    df = df.rename(columns=rename)

    keep_cols = [
        "snapshot_date",
        "property",
        "payer_name",
        "amount_receivable",
        "d0_30",
        "d31_60",
        "d61_90",
        "d91_plus",
        "gl_account_name",
        "gl_account_number",
        "total_amount",
        "charge_date",
        "posting_date",
    ]

    df = df[[c for c in keep_cols if c in df.columns]]

    for col in [
        "amount_receivable",
        "d0_30",
        "d31_60",
        "d61_90",
        "d91_plus",
        "total_amount",
    ]:
        if col in df.columns:
            df[col] = clean_money(df[col])

    for col in ["charge_date", "posting_date"]:
        if col in df.columns:
            df[col] = pd.to_datetime(df[col], errors="coerce").dt.strftime("%Y-%m-%d")

    df = df.where(pd.notnull(df), None)
    records = df.to_dict("records")

    print(f"Deleting aged_receivable snapshot {SNAPSHOT_DATE}")
    supabase.table("aged_receivable").delete().eq("snapshot_date", SNAPSHOT_DATE).execute()

    print(f"Uploading {len(records)} aged_receivable rows...")
    for i in range(0, len(records), 500):
        supabase.table("aged_receivable").insert(records[i:i+500]).execute()

    print(f"Uploaded aged_receivable: {len(records)} rows for {SNAPSHOT_DATE}")

#=================================================
#====Calls======================
#=================================================

def upload_calls():
    xlsx_file = r"data/raw/Users_Dashboard.xlsx"
    snapshot_date = date.today().strftime("%Y-%m-%d")

    if not os.path.exists(xlsx_file):
        print("No calls file found")
        return

    print(f"Found calls file: {xlsx_file}")

    raw = pd.read_excel(xlsx_file, sheet_name="Table_Table", header=None, dtype=str)

    period_start = pd.to_datetime(raw.iat[3, 1], errors="coerce")
    period_end = pd.to_datetime(raw.iat[3, 2], errors="coerce")

    df = raw.iloc[11:].reset_index(drop=True)

    df.columns = [
        "Name",
        "Ext",
        "Total Calls",
        "Avg Daily",
        "Inbound",
        "Outbound",
        "Missed with VM",
        "_extra",
    ]

    df = df[
        ["Name", "Ext", "Total Calls", "Avg Daily", "Inbound", "Outbound", "Missed with VM"]
    ]

    df = df[df["Name"].notna() & (df["Name"].astype(str).str.strip() != "")]
    df["Name"] = df["Name"].astype(str).str.strip()

    def clean_int(value):
        number = pd.to_numeric(value, errors="coerce")
        return 0 if pd.isna(number) else int(number)

    records = []

    for _, row in df.iterrows():
        inbound = clean_int(row.get("Inbound"))
        missed = clean_int(row.get("Missed with VM"))

        missed_pct = round((missed / inbound * 100), 2) if inbound > 0 else 0

        records.append({
            "snapshot_date": snapshot_date,
            "name": row.get("Name"),
            "ext": row.get("Ext"),
            "total_calls": clean_int(row.get("Total Calls")),
            "avg_daily": clean_int(row.get("Avg Daily")),
            "inbound": inbound,
            "outbound": clean_int(row.get("Outbound")),
            "missed_with_vm": missed,
            "missed_vm_pct": missed_pct,
            "period_start": period_start.strftime("%Y-%m-%d") if not pd.isna(period_start) else None,
            "period_end": period_end.strftime("%Y-%m-%d") if not pd.isna(period_end) else None,
        })

    supabase.table("calls").delete().eq("snapshot_date", snapshot_date).execute()

    if records:
        supabase.table("calls").insert(records).execute()

    print(f"Uploaded calls: {len(records)} rows for {snapshot_date}")

#=================================================
#====leads======================
#=================================================


def upload_leads():
    fp = find_latest("guest_card_interests")
    if not fp:
        print("No leads file found")
        return

    print(f"Found leads file: {fp}")
    df = pd.read_csv(fp)
    snapshot_date = date.today().strftime("%Y-%m-%d")

    df = df.rename(columns={
        "Property": "property",
        "Name": "name",
        "Status": "status",
        "Monthly Income": "monthly_income",
        "Max Rent": "max_rent",
        "Credit Score": "credit_score",
    })

    for col in ["monthly_income", "max_rent", "credit_score"]:
        df[col] = df[col].apply(clean_money)

    df["credit_score_mid"] = df["credit_score"]
    df["lead_score"] = (
        df["monthly_income"].fillna(0) / 1000
        + df["credit_score"].fillna(0) / 100
        - df["max_rent"].fillna(0) / 1000
    )

    df["snapshot_date"] = snapshot_date

    records = clean_for_json(
        df[[
            "snapshot_date",
            "property",
            "name",
            "status",
            "monthly_income",
            "max_rent",
            "credit_score",
            "credit_score_mid",
            "lead_score",
        ]]
    )

    supabase.table("leads").delete().eq("snapshot_date", snapshot_date).execute()

    if records:
        for i in range(0, len(records), 500):
            supabase.table("leads").insert(records[i:i+500]).execute()

    print(f"Uploaded leads: {len(records)} rows for {snapshot_date}")

#=================================================
#====leasing_funnel_performance======================
#=================================================

def upload_leasing_funnel():
    fp = find_latest("leasing_funnel_performance")
    if not fp:
        print("No leasing_funnel file found")
        return

    print(f"Found leasing_funnel file: {fp}")
    df = pd.read_csv(fp)
    snapshot_date = date.today().strftime("%Y-%m-%d")

    df = df.rename(columns={
        "Property": "property",
        "Inquiries": "inquiries",
        "Completed Showings": "completed_showings",
        "Rental Apps": "rental_apps",
        "Decision Pending": "decision_pending",
        "Approved": "approved",
        "Signed Leases": "signed_leases",
    })

    for col in ["inquiries", "completed_showings", "rental_apps", "decision_pending", "approved", "signed_leases"]:
        df[col] = pd.to_numeric(df[col], errors="coerce").fillna(0).astype(int)

    df["snapshot_date"] = snapshot_date

    records = df[[
        "snapshot_date", "property", "inquiries", "completed_showings",
        "rental_apps", "decision_pending", "approved", "signed_leases"
    ]].where(pd.notna(df), None).to_dict("records")

    supabase.table("leasing_funnel").delete().eq("snapshot_date", snapshot_date).execute()

    if records:
        supabase.table("leasing_funnel").insert(records).execute()

    print(f"Uploaded leasing_funnel: {len(records)} rows for {snapshot_date}")

#=================================================
#====leasing_summary======================
#=================================================

def upload_leasing_summary():
    fp = find_latest("leasing_summary")
    if not fp:
        print("No leasing_summary file found")
        return

    print(f"Found leasing_summary file: {fp}")
    df = pd.read_csv(fp)
    snapshot_date = date.today().strftime("%Y-%m-%d")

    df.columns = [c.strip().lower().replace(" ", "_") for c in df.columns]

    summary = {
        "snapshot_date": snapshot_date,
        "leased": int(pd.to_numeric(df.get("leased", pd.Series([0])).sum(), errors="coerce") or 0),
        "move_ins": int(pd.to_numeric(df.get("move_ins", pd.Series([0])).sum(), errors="coerce") or 0),
        "move_outs": int(pd.to_numeric(df.get("move_outs", pd.Series([0])).sum(), errors="coerce") or 0),
        "inquiries": int(pd.to_numeric(df.get("inquiries", pd.Series([0])).sum(), errors="coerce") or 0),
        "showings": int(pd.to_numeric(df.get("showings", pd.Series([0])).sum(), errors="coerce") or 0),
        "applications": int(pd.to_numeric(df.get("applications", pd.Series([0])).sum(), errors="coerce") or 0),
    }

    supabase.table("leasing_summary").delete().eq("snapshot_date", snapshot_date).execute()
    supabase.table("leasing_summary").insert(summary).execute()

    print(f"Uploaded leasing_summary for {snapshot_date}")

#=================================================
#====unit_vacancy_detail======================
#=================================================

def upload_vacancy_detail():
    fp = find_latest("unit_vacancy_detail")
    if not fp:
        print("No vacancy_detail file found")
        return

    print(f"Found vacancy_detail file: {fp}")
    df = pd.read_csv(fp)
    snapshot_date = date.today().strftime("%Y-%m-%d")

    df = df.rename(columns={
        "Property": "property",
        "Unit": "unit",
        "Unit ID": "unit_id",
        "Unit Status": "unit_status",
        "Days Vacant": "days_vacant",
        "Last Rent": "last_rent",
        "Scheduled Rent": "scheduled_rent",
        "Bed/Bath": "bed_bath",
        "Rent Ready": "rent_ready",
        "Available On": "available_on",
    })

    for col in ["days_vacant", "last_rent", "scheduled_rent"]:
        df[col] = df[col].apply(clean_money)

    df["available_on"] = pd.to_datetime(df["available_on"], errors="coerce").dt.strftime("%Y-%m-%d")
    df["snapshot_date"] = snapshot_date
    df["source"] = "unit_vacancy_detail"

    for col in ["rr_status", "rr_tenant"]:
        if col not in df.columns:
            df[col] = None

    records = clean_for_json(
        df[[
            "snapshot_date",
            "property",
            "unit",
            "unit_id",
            "unit_status",
            "days_vacant",
            "last_rent",
            "scheduled_rent",
            "bed_bath",
            "rent_ready",
            "available_on",
            "rr_status",
            "rr_tenant",
            "source",
        ]]
    )

    supabase.table("vacancy_detail").delete().eq("snapshot_date", snapshot_date).execute()

    if records:
        for i in range(0, len(records), 500):
            supabase.table("vacancy_detail").insert(records[i:i+500]).execute()

    print(f"Uploaded vacancy_detail: {len(records)} rows for {snapshot_date}")

#=================================================
#====renewal_summary======================
#=================================================

def upload_renewal_summary():
    fp = find_latest("renewal_summary")
    if not fp:
        print("No renewal_summary file found")
        return

    print(f"Found renewal_summary file: {fp}")
    df = pd.read_csv(fp, dtype=str)
    df.columns = [c.strip() for c in df.columns]

    df["snapshot_date"] = SNAPSHOT_DATE

    df = df.rename(columns={
        "Property": "property",
        "Unit ID": "unit_id",
        "Tenant Name": "tenant_name",
        "Status": "status",
        "Previous Rent": "previous_rent",
        "Rent": "rent",
        "Percent Difference": "percent_difference",
    })

    for col in ["previous_rent", "rent", "percent_difference"]:
        if col in df.columns:
            df[col] = df[col].apply(clean_money)

    records = clean_for_json(
        df[[
            "snapshot_date",
            "property",
            "unit_id",
            "tenant_name",
            "status",
            "previous_rent",
            "rent",
            "percent_difference",
        ]]
    )

    supabase.table("renewal_summary").delete().eq("snapshot_date", SNAPSHOT_DATE).execute()

    for i in range(0, len(records), 500):
        supabase.table("renewal_summary").insert(records[i:i+500]).execute()

    print(f"Uploaded renewal_summary: {len(records)} rows for {SNAPSHOT_DATE}")

#=================================================
#====rental_applications======================
#=================================================

def upload_rental_applications():
    fp = find_latest("rental_applications")
    if not fp:
        print("No rental_applications file found")
        return

    print(f"Found rental_applications file: {fp}")
    df = pd.read_csv(fp, dtype=str)
    df.columns = [c.strip() for c in df.columns]

    df["snapshot_date"] = SNAPSHOT_DATE

    df = df.rename(columns={
        "Property Name": "property",
        "Applicant(s)": "applicant",
        "Status": "status",
        "Received": "received",
        "Unit": "unit",
        "Desired Move In": "move_in_date",
    })

    for col in ["received", "move_in_date"]:
        if col in df.columns:
            df[col] = pd.to_datetime(df[col], errors="coerce").dt.strftime("%Y-%m-%d")

    records = clean_for_json(
        df[[
            "snapshot_date",
            "property",
            "applicant",
            "status",
            "received",
            "unit",
            "move_in_date",
        ]]
    )

    supabase.table("rental_applications").delete().eq("snapshot_date", SNAPSHOT_DATE).execute()

    for i in range(0, len(records), 500):
        supabase.table("rental_applications").insert(records[i:i+500]).execute()

    print(f"Uploaded rental_applications: {len(records)} rows for {SNAPSHOT_DATE}")

#=================================================
#====tenant_tickler======================
#=================================================

def upload_tickler():
    fp = find_latest("tenant_tickler")
    if not fp:
        print("No tenant_tickler file found")
        return

    print(f"Found tenant_tickler file: {fp}")
    df = pd.read_csv(fp, dtype=str)
    df.columns = [c.strip() for c in df.columns]

    df["snapshot_date"] = SNAPSHOT_DATE

    df = df.rename(columns={
        "Property": "property",
        "Date": "event_date",
        "Event": "event",
        "Tenant": "tenant",
        "Unit": "unit",
        "Rent": "rent",
    })

    df["event_date"] = pd.to_datetime(df["event_date"], errors="coerce").dt.strftime("%Y-%m-%d")
    df["rent"] = df["rent"].apply(clean_money)

    records = clean_for_json(
        df[[
            "snapshot_date",
            "property",
            "event_date",
            "event",
            "tenant",
            "unit",
            "rent",
        ]]
    )

    supabase.table("tenant_tickler").delete().eq("snapshot_date", SNAPSHOT_DATE).execute()

    for i in range(0, len(records), 500):
        supabase.table("tenant_tickler").insert(records[i:i+500]).execute()

    print(f"Uploaded tenant_tickler: {len(records)} rows for {SNAPSHOT_DATE}")

#=================================================
#====Building historical_metrics======================
#=================================================

def upload_historical_metrics():
    print("Building historical_metrics...")

    snapshot_date = SNAPSHOT_DATE

    # Rent Roll
    df_rr = pd.DataFrame(
        fetch_all_supabase("rent_roll", snapshot_date)
    )

    total_units = len(df_rr)

    occupied_statuses = [
        "Current",
        "Notice-Unrented",
        "Evict",
    ]

    occupied_units = len(
        df_rr[df_rr["status"].isin(occupied_statuses)]
    )

    vacant_units = total_units - occupied_units

    physical_occupancy = (
        occupied_units / total_units * 100
        if total_units > 0 else 0
    )

    sum_of_rent = pd.to_numeric(
        df_rr["rent"],
        errors="coerce"
    ).fillna(0).sum()

    status = df_rr["status"].fillna("").astype(str).str.strip()

    current_units = (status == "Current").sum()
    notice_unrented_units = (status == "Notice-Unrented").sum()
    vacant_rented_units = (status == "Vacant-Rented").sum()

    economic_occupancy = (
        (current_units + vacant_rented_units + notice_unrented_units)
        / total_units * 100
        if total_units > 0 else 0
    )

    # Aged Receivable
    # Collection Rate — same formula as All Hands
    df_current = df_rr[
        df_rr["status"].fillna("").astype(str).str.strip() == "Current"
    ].copy()

    current_rent = pd.to_numeric(
        df_current["rent"],
        errors="coerce"
    ).fillna(0).sum()

    current_past_due = pd.to_numeric(
        df_current["past_due"],
        errors="coerce"
    ).fillna(0).clip(lower=0).sum()

    collection_rate = (
        (current_rent - current_past_due) / current_rent * 100
        if current_rent > 0 else 0
    )

    collection_rate = max(0.0, min(100.0, collection_rate))

    # Leasing Summary
    ls = supabase.table("leasing_summary") \
        .select("*") \
        .eq("snapshot_date", snapshot_date) \
        .execute()

    df_ls = pd.DataFrame(ls.data)

    inquiries = 0
    showings = 0
    leased = 0

    if not df_ls.empty:
        inquiries = int(df_ls["inquiries"].fillna(0).sum())
        showings = int(df_ls["showings"].fillna(0).sum())
        leased = int(df_ls["leased"].fillna(0).sum())

    record = {
        "date": snapshot_date,
        "physical_occupancy": round(physical_occupancy, 2),
        "economic_occupancy": round(economic_occupancy, 2),
        "total_units": int(total_units),
        "occupied_units": int(occupied_units),
        "vacant_units": int(vacant_units),
        "sum_of_rent": float(sum_of_rent),
        "inquiries": inquiries,
        "showings": showings,
        "leased": leased,
        "collection_rate": round(collection_rate, 2),
    }

    supabase.table("historical_metrics") \
        .delete() \
        .eq("date", snapshot_date) \
        .execute()

    supabase.table("historical_metrics") \
        .insert(record) \
        .execute()

    print(
        f"Uploaded historical_metrics for {snapshot_date}"
    )

if __name__ == "__main__":
    upload_rent_roll()
    upload_work_orders()
    upload_aged_receivable()
    upload_calls()
    upload_leads()
    upload_leasing_funnel()
    upload_leasing_summary()
    upload_vacancy_detail()
    upload_renewal_summary()
    upload_rental_applications()
    upload_tickler()
    upload_historical_metrics()

