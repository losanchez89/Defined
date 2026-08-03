from __future__ import annotations

import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
RAW_DIR = BASE_DIR / "data" / "raw"
LOG_DIR = BASE_DIR / "logs"

CREDENTIALS_FILE = BASE_DIR / "credentials.json"
TOKEN_FILE = BASE_DIR / "token.json"

GMAIL_CREDENTIALS_JSON = os.getenv("GMAIL_CREDENTIALS_JSON", "").strip()
GMAIL_TOKEN_JSON = os.getenv("GMAIL_TOKEN_JSON", "").strip()

GMAIL_SCOPES = ["https://www.googleapis.com/auth/gmail.readonly"]

# Búsqueda amplia; el descargador filtra estrictamente por la fecha de Bolivia.
GMAIL_SEARCH_QUERY = (
    'newer_than:2d '
    '(subject:Streamlit '
    'OR subject:leasing '
    'OR subject:delinquency '
    'OR subject:"Scheduled Reports from RingCentral" '
    'OR from:analytics.portal@ringcentral.com)'
)

ALLOWED_EXTENSIONS = {".csv", ".xlsx", ".xls"}

REPORT_FILE_MAPPING = {
    "work order": "work_order.csv",
    "tenant tickler": "tenant_tickler.csv",
    "unit vacancy detail": "unit_vacancy_detail.csv",
    "showings": "showings.csv",
    "guest card interest": "guest_card_interests.csv",
    "delinquency": "delinquency.csv",
    "leasing summary": "leasing_summary.csv",
    "owner directory": "owner_directory.csv",
    "rent roll": "rent_roll.csv",
    "aged receivable detail": "aged_receivable_detail.csv",
    "leasing funnel performance": "leasing_funnel_performance.csv",
    "renewal summary": "renewal_summary.csv",
    "rental applications": "rental_applications.csv",
    "scheduled reports from ringcentral": "Users_Dashboard.xlsx",
}

RINGCENTRAL_URL_FRAGMENT = "analytics.ringcentral.com/reports/"
