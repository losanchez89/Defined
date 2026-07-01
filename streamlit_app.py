import streamlit as st

st.title("Defined")
"""
Property Management Executive Dashboard — Streamlit
Defined Property Management
"""

import io
import logging
import os
import re
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo


import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import plotly.io as pio
import streamlit as st
import yaml
from supabase_client import supabase

# ── Logging setup ─────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.WARNING,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
log = logging.getLogger("dfm")

# ── Global Plotly theme: Inter font, clean white background ───────────────
pio.templates["dfm"] = pio.templates["plotly_white"]
pio.templates["dfm"].layout.font       = dict(family="Inter, system-ui, -apple-system, sans-serif", size=11, color="#374151")
pio.templates["dfm"].layout.hoverlabel = dict(bgcolor="#1E293B", font_color="#F8FAFC", font_size=12, bordercolor="#1E293B")
pio.templates["dfm"].layout.paper_bgcolor = "#FFFFFF"
pio.templates["dfm"].layout.plot_bgcolor  = "#FFFFFF"
pio.templates.default = "dfm"

# ============================================================================
# CORE FUNCTIONS  (inlined from box_score_generator)
# ============================================================================

def find_csv_file(directory, prefix):
    """
    Finds the most recent CSV file matching prefix (sorted by filename descending).
    Files use date suffixes (e.g. tenant_tickler-20260531.csv), so the
    alphabetically-last name is always the newest.
    """
    files = sorted(Path(directory).glob(f"{prefix}*.csv"), key=lambda p: p.name)
    return str(files[-1]) if files else None


def detect_header_row(df_raw, search_terms=['Property', 'Unit']):
    """
    Detecta la fila donde empieza el encabezado real.
    AppFolio a menudo tiene líneas vacías al principio.

    Args:
        df_raw: DataFrame sin procesar
        search_terms: Términos a buscar en las columnas

    Returns:
        Índice de la fila del encabezado
    """
    for idx, row in df_raw.iterrows():
        row_str = ' '.join([str(val) for val in row.values if pd.notna(val)])
        if any(term in row_str for term in search_terms):
            return idx
    return 0


def clean_property_name(name):
    """
    Normaliza el nombre de propiedad eliminando direcciones y códigos postales.

    Ejemplos:
        "Gardendale Park - 8350 Gardendale St Paramount, CA 90723" -> "Gardendale Park"
        "Hughes Ave 3701 - 103..." -> "Hughes Ave 3701"
        "Pacific St 1022 - 1022 Pacific St Santa Monica, CA 90405" -> "Pacific St 1022"

    Args:
        name: Nombre de propiedad crudo

    Returns:
        Nombre de propiedad limpio
    """
    if pd.isna(name) or name == '':
        return ''

    name = str(name).strip()

    # Si contiene " - ", tomar la parte antes del guion
    if ' - ' in name:
        name = name.split(' - ')[0].strip()

    # Eliminar códigos postales (5 dígitos al final)
    name = re.sub(r'\s+\d{5}$', '', name)

    # Eliminar estados y ciudades comunes al final (CA, Los Angeles, etc.)
    name = re.sub(r',\s*(CA|California|Los Angeles|Santa Monica|West Hollywood|Paramount)\s*$', '', name, flags=re.IGNORECASE)

    return name.strip()


def clean_money_column(series):
    """
    Convierte una columna de dinero a float con limpieza agresiva.
    Elimina símbolos $, comas, comillas, espacios y cualquier otro carácter no numérico.

    Args:
        series: Serie de pandas con valores de dinero

    Returns:
        Serie convertida a float
    """
    # Convertir a string primero para asegurar procesamiento
    cleaned = series.astype(str)

    # Limpieza agresiva: eliminar $, comas, comillas, espacios usando regex
    cleaned = cleaned.str.replace(r'[$,"\s]', '', regex=True)

    # Convertir a float, NaN se convierte en 0
    cleaned = pd.to_numeric(cleaned, errors='coerce').fillna(0)

    # Asegurar que sea float explícitamente
    cleaned = cleaned.astype(float)

    return cleaned


def load_rent_roll(directory):
    """
    Carga y limpia el archivo rent_roll.

    Args:
        directory: Directorio donde buscar el archivo

    Returns:
        DataFrame limpio del rent roll
    """
    print("📂 Cargando Rent Roll...")

    file_path = find_csv_file(directory, 'rent_roll')
    if not file_path:
        print("   ⚠️  No se encontró el archivo rent_roll-*.csv")
        return None

    print(f"   Archivo encontrado: {os.path.basename(file_path)}")

    # Leer archivo sin procesar
    df_raw = pd.read_csv(file_path, header=None, dtype=str)

    # Detectar fila del encabezado
    header_row = detect_header_row(df_raw)
    print(f"   Encabezado detectado en fila {header_row + 1}")

    # Leer con el encabezado correcto
    df = pd.read_csv(file_path, skiprows=header_row)

    # Eliminar filas de resumen usando Unit ID (las unidades sin número como JTM Land
    # tienen Unit en blanco pero sí tienen Unit ID válido)
    df = df[df['Unit ID'].notna() & (df['Unit ID'].astype(str).str.strip() != '')]

    # LIMPIEZA AGRESIVA DE MARKET RENT (CRÍTICO - ANTES DE CUALQUIER CÁLCULO)
    print("   Limpiando Market Rent (limpieza agresiva)...")
    if 'Market Rent' in df.columns:
        df['Market Rent'] = clean_money_column(df['Market Rent'])
        # Verificar que sea float
        df['Market Rent'] = df['Market Rent'].astype(float)
        print(f"   ✓ Market Rent convertido a float: {df['Market Rent'].dtype}")

    # Limpiar nombres de propiedades
    print("   Limpiando nombres de propiedades...")
    df['Property'] = df['Property'].apply(clean_property_name)

    # Limpiar otras columnas numéricas de dinero
    print("   Limpiando otras columnas numéricas...")
    if 'Rent' in df.columns:
        df['Rent'] = clean_money_column(df['Rent'])
    if 'Deposit' in df.columns:
        df['Deposit'] = clean_money_column(df['Deposit'])

    print(f"   ✓ Rent Roll cargado: {len(df)} unidades")
    return df


def load_funnel(directory):
    """
    Carga y limpia el archivo leasing_funnel_performance.

    Args:
        directory: Directorio donde buscar el archivo

    Returns:
        DataFrame limpio del funnel
    """
    print("📂 Cargando Leasing Funnel...")

    file_path = find_csv_file(directory, 'leasing_funnel_performance')
    if not file_path:
        print("   ⚠️  No se encontró el archivo leasing_funnel_performance-*.csv")
        return None

    print(f"   Archivo encontrado: {os.path.basename(file_path)}")

    # Leer archivo sin procesar
    df_raw = pd.read_csv(file_path, header=None, dtype=str)

    # Detectar fila del encabezado
    header_row = detect_header_row(df_raw)
    print(f"   Encabezado detectado en fila {header_row + 1}")

    # Leer con el encabezado correcto
    df = pd.read_csv(file_path, skiprows=header_row)

    # Filtrar filas basura ANTES de limpiar nombres (evitar "Signed Leases", headers, subtotals)
    print("   Filtrando filas inválidas...")
    initial_rows = len(df)

    # Filtrar filas donde Property contiene "Signed Leases" (case-insensitive)
    if 'Property' in df.columns:
        df = df[~df['Property'].astype(str).str.contains('Signed Leases', case=False, na=False)]

        # Limpiar nombres de propiedades para detectar vacíos
        df['Property_cleaned'] = df['Property'].apply(clean_property_name)

        # Filtrar filas donde el nombre limpio está vacío
        df = df[df['Property_cleaned'] != '']

        # Usar el nombre limpio como Property
        df['Property'] = df['Property_cleaned']
        df = df.drop(columns=['Property_cleaned'])

    rows_removed = initial_rows - len(df)
    if rows_removed > 0:
        print(f"   ✓ Filas basura eliminadas: {rows_removed} (quedan {len(df)} filas válidas)")

    # Agrupar por Property y SUMAR: cada fila representa una unidad vacante distinta
    # dentro del mismo edificio. AppFolio reporta actividad por unidad, no por edificio.
    print("   Agrupando datos por Property (suma de unidades)...")
    funnel_cols = ['Inquiries', 'Completed Showings', 'Rental Apps',
                   'Decision Pending', 'Approved', 'Signed Leases']

    # Convertir columnas numéricas
    for col in funnel_cols:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors='coerce').fillna(0)

    available_cols = [c for c in funnel_cols if c in df.columns]
    df_funnel = df.groupby('Property')[available_cols].sum().reset_index()

    print(f"   ✓ Funnel cargado: {len(df_funnel)} propiedades")
    return df_funnel


def load_showings(directory):
    """
    Carga el archivo showings-*.csv y calcula por propiedad:
    - Completed: Status == "Completed"
    - Canceled: Status contiene "Canceled" (case-insensitive; incluye "Prospect Canceled")
    - Upcoming/Scheduled: Status == "Scheduled" (case-insensitive)

    Args:
        directory: Directorio donde buscar el archivo

    Returns:
        DataFrame con columnas ['Property', 'Calc_Completed', 'Calc_Canceled', 'Calc_Scheduled'],
        o vacío si no se encuentra el archivo.
    """
    print("📂 Cargando Showings (raw)...")

    empty_cols = ['Property', 'Calc_Completed', 'Calc_Canceled', 'Calc_Scheduled']
    file_path = find_csv_file(directory, 'showings')
    if not file_path:
        print("   ⚠️  No se encontró el archivo showings*.csv")
        return pd.DataFrame(columns=empty_cols)

    print(f"   Archivo encontrado: {os.path.basename(file_path)}")

    # Leer archivo sin procesar (puede tener metadata al inicio)
    df_raw = pd.read_csv(file_path, header=None, dtype=str)

    # Detectar fila del encabezado
    header_row = detect_header_row(df_raw, search_terms=['Property', 'Status'])
    print(f"   Encabezado detectado en fila {header_row + 1}")

    # Leer con el encabezado correcto
    df = pd.read_csv(file_path, skiprows=header_row)

    if 'Property' not in df.columns or 'Status' not in df.columns:
        print("   ⚠️  Columnas 'Property' o 'Status' no encontradas en showings CSV")
        return pd.DataFrame(columns=empty_cols)

    # Limpiar nombres de propiedades para join consistente
    print("   Limpiando nombres de propiedades...")
    df['Property'] = df['Property'].apply(clean_property_name)

    # Filtrar a semana actual usando "Showing Time" (si existe)
    today = pd.Timestamp.now().normalize()
    start_date = today - pd.Timedelta(days=6)
    if 'Showing Time' in df.columns:
        try:
            showing_dt = pd.to_datetime(df['Showing Time'], errors='coerce')
            status_lower_pre = df['Status'].astype(str).str.strip().str.lower()
            # Scheduled (futuro) se mantiene siempre; Completed/Canceled solo si están en la semana actual
            is_scheduled = status_lower_pre == 'scheduled'
            in_current_week = (showing_dt >= start_date) & (showing_dt <= today + pd.Timedelta(days=90))
            df = df[is_scheduled | in_current_week].reset_index(drop=True)
            log.info("Showings filtrados: %d registros en semana actual + próximos agendados", len(df))
        except Exception as e:
            log.warning("Showings date filter failed, usando todos los datos: %s", e)

    status_lower = df['Status'].astype(str).str.strip().str.lower()

    # Completed: Status == "Completed"
    completed = (status_lower == 'completed')
    # Canceled: Status contiene "canceled" (incluye "Prospect Canceled")
    canceled = status_lower.str.contains('canceled', na=False)
    # Upcoming/Scheduled: Status == "Scheduled"
    scheduled = (status_lower == 'scheduled')

    df['_completed'] = completed.astype(int)
    df['_canceled'] = canceled.astype(int)
    df['_scheduled'] = scheduled.astype(int)

    # Agrupar por Property y sumar conteos
    df_showings_metrics = df.groupby('Property').agg(
        Calc_Completed=('_completed', 'sum'),
        Calc_Canceled=('_canceled', 'sum'),
        Calc_Scheduled=('_scheduled', 'sum')
    ).reset_index()

    print(f"   ✓ Showings cargados: {len(df_showings_metrics)} propiedades (Completed/Canceled/Scheduled)")
    return df_showings_metrics


def calculate_metrics(df_rent_roll, df_funnel=None):
    """
    Calcula todas las métricas del Box Score agrupando por Property.
    """
    print("🔢 Calculando métricas por Property...")

    base_cols = [
        "Property", "Total Units", "Current", "Current %",
        "Economic Occ %", "Physical Occ %",
        "Vacant-Unrented", "Vacant-Unrented %",
        "Vacant-Rented", "Vacant-Rented %",
        "Notice-Unrented", "Notice-Unrented %",
        "Notice-Rented", "Notice-Rented %",
        "Evict", "Revenue Gap ($)",
        "Inquiries", "Completed Showings", "Rental Apps",
        "Decision Pending", "Approved", "Signed Leases",
        "Lease Conversion %",
    ]

    if df_rent_roll is None or len(df_rent_roll) == 0:
        print("⚠️ Rent Roll vacío")
        return pd.DataFrame(columns=base_cols)

    df_rent_roll = df_rent_roll.copy()

    # Normalizar nombres por si vienen de Supabase en lowercase o CSV en Title Case
    df_rent_roll = df_rent_roll.rename(columns={
        "property": "Property",
        "unit": "Unit",
        "unit_id": "Unit ID",
        "status": "Status",
        "tenant": "Tenant",
        "rent": "Rent",
        "market_rent": "Market Rent",
        "deposit": "Deposit",
        "past_due": "Past Due",
        "lease_from": "Lease From",
        "lease_to": "Lease To",
        "bd_ba": "BD/BA",
        "portfolio": "Portfolio",
    })

    if "Property" not in df_rent_roll.columns:
        print("⚠️ Rent Roll sin columna Property")
        print("RENT ROLL COLS:", df_rent_roll.columns.tolist())
        return pd.DataFrame(columns=base_cols)

    if "Status" not in df_rent_roll.columns:
        print("⚠️ Rent Roll sin columna Status")
        df_rent_roll["Status"] = ""
    else:
        df_rent_roll["Status"] = df_rent_roll["Status"].astype(str).str.strip()

    for col in ["Rent", "Market Rent", "Deposit", "Past Due"]:
        if col in df_rent_roll.columns:
            df_rent_roll[col] = pd.to_numeric(df_rent_roll[col], errors="coerce").fillna(0)

    if "Market Rent" not in df_rent_roll.columns:
        df_rent_roll["Market Rent"] = 0

    grouped = df_rent_roll.groupby("Property", dropna=False)
    results = []

    for property_name, group in grouped:
        total_units = len(group)
        status_counts = group["Status"].value_counts(dropna=False)

        current = int(status_counts.get("Current", 0))
        vacant_unrented = int(status_counts.get("Vacant-Unrented", 0))
        vacant_rented = int(status_counts.get("Vacant-Rented", 0))
        notice_unrented = int(status_counts.get("Notice-Unrented", 0))
        notice_rented = int(status_counts.get("Notice-Rented", 0))
        evict = int(status_counts.get("Evict", 0))

        current_pct = (current / total_units * 100) if total_units > 0 else 0
        vacant_unrented_pct = (vacant_unrented / total_units * 100) if total_units > 0 else 0
        vacant_rented_pct = (vacant_rented / total_units * 100) if total_units > 0 else 0
        notice_unrented_pct = (notice_unrented / total_units * 100) if total_units > 0 else 0
        notice_rented_pct = (notice_rented / total_units * 100) if total_units > 0 else 0

        economic_occ = (
            (current + vacant_rented + notice_unrented) / total_units * 100
            if total_units > 0 else 0
        )
        physical_occ = (
            (current + notice_unrented + evict) / total_units * 100
            if total_units > 0 else 0
        )

        revenue_gap_mask = group["Status"].isin(["Vacant-Unrented", "Evict"])
        revenue_gap = float(group.loc[revenue_gap_mask, "Market Rent"].sum())

        results.append({
            "Property": property_name,
            "Total Units": total_units,
            "Current": current,
            "Current %": current_pct,
            "Economic Occ %": economic_occ,
            "Physical Occ %": physical_occ,
            "Vacant-Unrented": vacant_unrented,
            "Vacant-Unrented %": vacant_unrented_pct,
            "Vacant-Rented": vacant_rented,
            "Vacant-Rented %": vacant_rented_pct,
            "Notice-Unrented": notice_unrented,
            "Notice-Unrented %": notice_unrented_pct,
            "Notice-Rented": notice_rented,
            "Notice-Rented %": notice_rented_pct,
            "Evict": evict,
            "Revenue Gap ($)": revenue_gap,
        })

    df_metrics = pd.DataFrame(results)
    if df_metrics.empty:
        print("⚠️ df_metrics vacío")
        return pd.DataFrame(columns=base_cols)

    funnel_cols = [
        "Inquiries", "Completed Showings", "Rental Apps",
        "Decision Pending", "Approved", "Signed Leases",
    ]

    if df_funnel is not None and len(df_funnel) > 0:
        df_funnel = df_funnel.copy().rename(columns={
            "property": "Property",
            "inquiries": "Inquiries",
            "completed_showings": "Completed Showings",
            "rental_apps": "Rental Apps",
            "decision_pending": "Decision Pending",
            "approved": "Approved",
            "signed_leases": "Signed Leases",
        })
        if "Property" in df_funnel.columns:
            print("   Integrando datos del Funnel...")
            df_metrics = df_metrics.merge(df_funnel, on="Property", how="left")
        else:
            print("   ⚠️ Funnel skipped: missing Property column")
    else:
        print("   ⚠️ Funnel skipped: empty funnel")

    for col in funnel_cols:
        if col not in df_metrics.columns:
            df_metrics[col] = 0
        else:
            df_metrics[col] = pd.to_numeric(df_metrics[col], errors="coerce").fillna(0)

    df_metrics["Lease Conversion %"] = (
        df_metrics["Signed Leases"] / df_metrics["Inquiries"].replace(0, pd.NA) * 100
    ).fillna(0).replace([float("inf"), float("-inf")], 0)

    df_metrics = df_metrics.sort_values("Property").reset_index(drop=True)
    print(f"   ✓ Métricas calculadas para {len(df_metrics)} propiedades")
    return df_metrics

def calculate_totals_row(df_metrics):
    """
    Calcula la fila de totales del portafolio.
    Para porcentajes usa promedios ponderados, para conteos usa suma simple.

    Args:
        df_metrics: DataFrame con métricas por propiedad

    Returns:
        Serie con los totales
    """
    print("📊 Calculando totales del portafolio...")

    if df_metrics is None or len(df_metrics) == 0:
        return pd.Series({"Total Units": 0}), 0.0, 0.0

    totals = {}
    total_units = df_metrics['Total Units'].sum() if 'Total Units' in df_metrics.columns else 0

    # Conteos: suma simple
    count_cols = ['Total Units', 'Current', 'Vacant-Unrented', 'Vacant-Rented',
                  'Notice-Unrented', 'Notice-Rented', 'Evict']
    for col in count_cols:
        if col in df_metrics.columns:
            totals[col] = df_metrics[col].sum()

    # Revenue Gap: suma simple
    if 'Revenue Gap ($)' in df_metrics.columns:
        totals['Revenue Gap ($)'] = df_metrics['Revenue Gap ($)'].sum()

    # Porcentajes: promedios ponderados
    if total_units > 0:
        totals['Current %'] = (df_metrics['Current'].sum() / total_units * 100)
        totals['Economic Occ %'] = (
            (df_metrics['Current'] + df_metrics['Vacant-Rented'] + df_metrics['Notice-Unrented']).sum()
            / total_units * 100
        )
        totals['Physical Occ %'] = (
            (df_metrics['Current'] + df_metrics['Notice-Unrented'] + df_metrics['Evict']).sum()
            / total_units * 100
        )
        totals['Vacant-Unrented %'] = (df_metrics['Vacant-Unrented'].sum() / total_units * 100)
        totals['Vacant-Rented %'] = (df_metrics['Vacant-Rented'].sum() / total_units * 100)
        totals['Notice-Unrented %'] = (df_metrics['Notice-Unrented'].sum() / total_units * 100)
        totals['Notice-Rented %'] = (df_metrics['Notice-Rented'].sum() / total_units * 100)
    else:
        for pct_col in ['Current %', 'Economic Occ %', 'Physical Occ %',
                       'Vacant-Unrented %', 'Vacant-Rented %',
                       'Notice-Unrented %', 'Notice-Rented %']:
            totals[pct_col] = 0

    # Funnel: suma simple
    funnel_cols = ['Inquiries', 'Completed Showings', 'Rental Apps',
                   'Decision Pending', 'Approved', 'Signed Leases']
    for col in funnel_cols:
        if col in df_metrics.columns:
            totals[col] = df_metrics[col].sum()

    # Lease Conversion %: calcular sobre totales
    if 'Inquiries' in totals and totals['Inquiries'] > 0:
        totals['Lease Conversion %'] = (totals.get('Signed Leases', 0) / totals['Inquiries'] * 100)
    else:
        totals['Lease Conversion %'] = 0

    # Asegurar que no haya NaN o Inf en los totales
    for key, value in totals.items():
        if pd.isna(value) or value == float('inf') or value == float('-inf'):
            totals[key] = 0

    # Property name para la fila de totales
    totals['Property'] = "PRESENT WEEK'S TOTALS"

    # Extraer porcentajes de ocupación del portafolio para histórico
    portfolio_economic_occ = totals.get('Economic Occ %', 0)
    portfolio_physical_occ = totals.get('Physical Occ %', 0)

    print("   ✓ Totales calculados")
    return pd.Series(totals), portfolio_economic_occ, portfolio_physical_occ


def _norm_key(s):
    """
    Normalized matching key for fuzzy property-name matching.
    Strips ownership % '(100%)', punctuation, street suffixes, zip codes, and
    returns sorted lowercase tokens so 'Hughes Ave 3701' == '3701 Hughes Ave'.
    """
    if not s or (isinstance(s, float) and pd.isna(s)):
        return ""
    s = str(s).lower()
    s = re.sub(r'\s*\(\d+%\)', '', s)          # drop "(100%)"
    s = re.sub(r'[^\w\s]', ' ', s)
    stop = {'ave', 'avenue', 'street', 'st', 'drive', 'dr', 'blvd', 'boulevard',
            'rd', 'road', 'ln', 'lane', 'way', 'ct', 'court', 'pl', 'place',
            'cir', 'n', 's', 'e', 'w'}
    tokens = [
        t for t in s.split()
        if t and t not in stop and not (t.isdigit() and len(t) == 5)  # skip zip codes
    ]
    return ' '.join(sorted(tokens)) if tokens else ''

# ============================================================================
# CONFIG
# ============================================================================

def load_config() -> dict:
    defaults = {
        "company_name":  "Defined Property Management",
        "primary_color": "#1B4FD8",
        "logo_path":     None,
        "data_folder":   ".",
        "thresholds": {
            "physical_occ":       95.0,
            "economic_occ":       95.0,
            "collection_rate":    98.0,
            "renewal_rate":       80.0,
            "days_vacant":        30,
            "wo_resolution_days": 7,
        },
        "phone_team": [
            "Chonalyn", "Nichole", "Alejandro", "Andrea",
            "Norman", "Inés", "Ines", "Lorena", "Carmen",
            "Laura", "Sergei"
        ],
    }
    p = Path(__file__).parent / "config.yaml"
    if p.exists():
        with open(p) as f:
            cfg = yaml.safe_load(f) or {}
        for k, v in cfg.items():
            if k == "thresholds" and isinstance(v, dict):
                defaults["thresholds"].update(v)
            elif k == "phone_team" and isinstance(v, list):
                defaults["phone_team"] = v
            elif v is not None:
                defaults[k] = v
    return defaults


CONFIG     = load_config()
DATA_DIR   = Path(CONFIG["data_folder"])
PC         = CONFIG["primary_color"]
COMPANY    = CONFIG["company_name"]
THR        = CONFIG["thresholds"]
PHONE_TEAM = CONFIG["phone_team"]

PAGES = ["All Hands", "Overview", "Vacancy", "Leasing", "Renewals",
         "Collection", "Delinquency", "Operations/Maintenance", "Calls", "Search"]

# ============================================================================
# PAGE CONFIG
# ============================================================================

st.set_page_config(layout="wide", page_title=COMPANY, page_icon="🏢")

# ============================================================================
# CSS
# ============================================================================

st.markdown(f"""
<style>
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800;900&display=swap');

/* ── Global ──────────────────────────────────────────────────────────── */
html, body, [data-testid="stAppViewContainer"], [data-testid="stAppViewBlockContainer"] {{
    font-family: 'Inter', -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif !important;
    background-color: #F0F4F8 !important;
}}
[data-testid="stHeader"] {{
    background: #FFFFFF !important;
    border-bottom: 1px solid #E2E8F0;
    box-shadow: 0 1px 4px rgba(15,23,42,.06);
}}
.block-container {{ padding-top: 1.5rem !important; padding-bottom: 2rem !important; }}

/* ── Sidebar ─────────────────────────────────────────────────────────── */
section[data-testid="stSidebar"] {{
    background: linear-gradient(180deg, #0F172A 0%, #1A2744 100%) !important;
    border-right: none !important;
    box-shadow: 2px 0 12px rgba(0,0,0,.18);
}}
section[data-testid="stSidebar"] > div {{ padding-top: 0 !important; }}
section[data-testid="stSidebar"] * {{ color: #CBD5E1 !important; }}
section[data-testid="stSidebar"] hr {{
    border-color: rgba(255,255,255,.1) !important;
    margin: 8px 0 !important;
}}
/* Nav buttons */
section[data-testid="stSidebar"] [data-testid="stButton"] > button {{
    background: transparent !important;
    border: none !important;
    color: #94A3B8 !important;
    border-radius: 8px !important;
    text-align: left !important;
    font-size: 13px !important;
    font-weight: 500 !important;
    width: 100% !important;
    padding: 9px 14px !important;
    margin: 1px 0 !important;
    transition: background .15s, color .15s;
}}
section[data-testid="stSidebar"] [data-testid="stButton"] > button:hover {{
    background: rgba(255,255,255,.08) !important;
    color: #F1F5F9 !important;
}}
section[data-testid="stSidebar"] [data-testid="stButton"] > button[kind="primary"] {{
    background: rgba(59,130,246,.18) !important;
    color: #93C5FD !important;
    font-weight: 700 !important;
    border-left: 3px solid #3B82F6 !important;
    padding-left: 11px !important;
}}
/* Sidebar labels / selects */
section[data-testid="stSidebar"] label {{
    color: #64748B !important;
    font-size: 10.5px !important;
    font-weight: 700 !important;
    text-transform: uppercase !important;
    letter-spacing: .08em !important;
}}
section[data-testid="stSidebar"] [data-testid="stSelectbox"] > div,
section[data-testid="stSidebar"] [data-testid="stMultiSelect"] > div {{
    background: rgba(255,255,255,.06) !important;
    border-color: rgba(255,255,255,.12) !important;
    border-radius: 8px !important;
}}

/* ── KPI Card ────────────────────────────────────────────────────────── */
.kpi-card {{
    background: #FFFFFF;
    border-radius: 14px;
    padding: 18px 20px 16px 20px;
    box-shadow: 0 2px 10px rgba(15,23,42,.08), 0 0 0 1px rgba(15,23,42,.04);
    margin-bottom: 8px;
    min-height: 108px;
    position: relative;
    overflow: hidden;
}}
.kpi-card::after {{
    content: '';
    position: absolute;
    top: 0; left: 0; right: 0;
    height: 4px;
    background: var(--kpi-color, {PC});
    border-radius: 14px 14px 0 0;
}}
.kpi-label {{
    font-size: 10px; color: #64748B; font-weight: 700;
    text-transform: uppercase; letter-spacing: .1em; margin-bottom: 10px;
    display: flex; align-items: center; gap: 6px;
}}
.kpi-dot {{
    width: 7px; height: 7px; border-radius: 50%;
    display: inline-block; flex-shrink: 0;
}}
.kpi-value {{
    font-size: 32px; font-weight: 900; color: #0F172A;
    line-height: 1.05; letter-spacing: -1px;
}}
.kpi-sub  {{ font-size: 11px; color: #94A3B8; margin-top: 6px; line-height: 1.45; }}
.kpi-delta-pos  {{ font-size: 11px; color: #059669; margin-top: 7px; font-weight: 600; }}
.kpi-delta-neg  {{ font-size: 11px; color: #DC2626; margin-top: 7px; font-weight: 600; }}
.kpi-delta-flat {{ font-size: 11px; color: #94A3B8; margin-top: 7px; }}

/* ── Section header ─────────────────────────────────────────────────── */
.sec-hdr {{
    font-size: 10.5px; font-weight: 800; color: #64748B;
    text-transform: uppercase; letter-spacing: .14em;
    padding: 22px 0 10px 0;
    margin-bottom: 14px;
    border-bottom: 1px solid #E2E8F0;
    display: flex; align-items: center; gap: 10px;
}}
.sec-hdr::before {{
    content: '';
    display: inline-block;
    width: 3px; height: 13px;
    background: {PC};
    border-radius: 2px;
    flex-shrink: 0;
}}

/* ── Page header ────────────────────────────────────────────────────── */
.pg-wrap {{ padding-bottom: 2px; }}
.pg-title {{
    font-size: 27px; font-weight: 900; color: #0F172A;
    letter-spacing: -0.7px; margin: 0 0 3px 0; line-height: 1.1;
}}
.pg-sub {{ font-size: 12px; color: #94A3B8; font-weight: 500; margin: 0; }}

/* ── Data tables ────────────────────────────────────────────────────── */
[data-testid="stDataFrame"] {{
    border: 1px solid #E2E8F0 !important;
    border-radius: 12px !important;
    overflow: hidden !important;
    box-shadow: 0 1px 6px rgba(15,23,42,.05) !important;
}}

/* ── Badges ─────────────────────────────────────────────────────────── */
.badge {{
    display: inline-block; padding: 3px 10px; border-radius: 999px;
    font-size: 10px; font-weight: 700; letter-spacing: .04em;
}}
.badge-green  {{ background: #DCFCE7; color: #166534; }}
.badge-yellow {{ background: #FEF9C3; color: #854D0E; }}
.badge-red    {{ background: #FEE2E2; color: #991B1B; }}

/* ── Misc ───────────────────────────────────────────────────────────── */
[data-testid="stExpander"] {{
    border: 1px solid #E2E8F0 !important; border-radius: 10px !important;
    background: #FFFFFF !important;
}}
[data-testid="stAlert"] {{ border-radius: 10px !important; }}
[data-testid="stCaption"] {{ color: #94A3B8 !important; }}
div[data-testid="metric-container"] {{ background: #FFFFFF; border-radius: 12px; padding: 12px; }}

/* ── Form controls ────────────────────────────────────────────────────── */
[data-testid="stSelectbox"] > div > div,
[data-testid="stMultiSelect"] > div > div {{
    border-color: #E2E8F0 !important;
    border-radius: 8px !important;
    background: #FFFFFF !important;
    box-shadow: 0 1px 3px rgba(15,23,42,.06) !important;
    font-size: 13px !important;
}}
[data-testid="stRadio"] label p {{
    font-size: 13px !important;
    font-weight: 500 !important;
    color: #374151 !important;
}}
/* ── Buttons ─────────────────────────────────────────────────────────── */
[data-testid="stBaseButton-secondary"] {{
    border-color: #E2E8F0 !important;
    color: #374151 !important;
    border-radius: 8px !important;
    font-size: 13px !important;
    font-weight: 600 !important;
    transition: border-color .15s, color .15s;
}}
[data-testid="stBaseButton-secondary"]:hover {{
    border-color: {PC} !important;
    color: {PC} !important;
    background: rgba(27,79,216,.04) !important;
}}
/* ── Expander ────────────────────────────────────────────────────────── */
[data-testid="stExpander"] summary {{
    font-size: 12px !important;
    font-weight: 600 !important;
    color: #374151 !important;
    padding: 10px 14px !important;
}}
[data-testid="stExpander"] summary:hover {{ color: {PC} !important; }}
[data-testid="stExpander"] summary svg {{ color: #94A3B8 !important; }}

/* ── Chart containers ────────────────────────────────────────────────── */
[data-testid="stPlotlyChart"] > div {{
    border-radius: 12px !important;
    overflow: hidden !important;
    background: #FFFFFF !important;
    box-shadow: 0 1px 6px rgba(15,23,42,.06), 0 0 0 1px rgba(15,23,42,.03) !important;
}}
/* ── Plotly SVG text → Inter ─────────────────────────────────────────── */
.js-plotly-plot .plotly text {{
    font-family: 'Inter', system-ui, sans-serif !important;
}}

/* ── Mobile responsive ───────────────────────────────────────────────── */
@media (max-width: 768px) {{
    /* Tighter padding */
    .block-container {{ padding: 0.75rem 0.75rem 1.5rem 0.75rem !important; }}

    /* Stack Streamlit columns vertically */
    [data-testid="stHorizontalBlock"] {{
        flex-wrap: wrap !important;
    }}
    [data-testid="stHorizontalBlock"] > [data-testid="column"] {{
        min-width: 100% !important;
        flex: 1 1 100% !important;
    }}

    /* KPI cards: smaller font */
    .kpi-value {{ font-size: 24px !important; }}
    .kpi-card  {{ padding: 14px 14px 12px 14px !important; min-height: 90px !important; }}

    /* Page title smaller */
    .pg-title {{ font-size: 20px !important; }}

    /* Sidebar auto-collapse hint */
    section[data-testid="stSidebar"] {{
        min-width: 220px !important;
        max-width: 240px !important;
    }}

    /* Charts full-width */
    [data-testid="stPlotlyChart"] {{ width: 100% !important; }}

    /* Tables scroll horizontally */
    [data-testid="stDataFrame"] {{ overflow-x: auto !important; }}

    /* Section headers compact */
    .sec-hdr {{ padding: 14px 0 8px 0 !important; margin-bottom: 10px !important; }}
}}

@media (max-width: 480px) {{
    .kpi-value {{ font-size: 20px !important; }}
    .pg-title  {{ font-size: 17px !important; }}
    .block-container {{ padding: 0.5rem !important; }}
}}
</style>
""", unsafe_allow_html=True)

# ============================================================================
# HELPERS
# ============================================================================

def _tl(value: float, target: float, mode: str = "higher") -> str:
    """Traffic light: 'good' | 'warn' | 'bad'."""
    if mode == "higher":
        if value >= target:           return "good"
        if value >= target * 0.95:    return "warn"
        return "bad"
    else:                             # lower is better
        if value <= target:           return "good"
        if value <= target * 1.67:    return "warn"
        return "bad"


def kpi(label: str, value: str, delta: float | None = None,
        suffix: str = "", status: str | None = None, sub: str = "",
        delta_label: str = "prior snapshot") -> str:
    bc = {"good": "#059669", "warn": "#D97706", "bad": "#DC2626"}.get(status, PC)
    dot = f'<span class="kpi-dot" style="background:{bc};"></span>' if status else ""
    delta_html = ""
    if delta is not None:
        if   delta >  0.005: delta_html = f'<div class="kpi-delta-pos">▲ {delta:+.2f}{suffix} vs {delta_label}</div>'
        elif delta < -0.005: delta_html = f'<div class="kpi-delta-neg">▼ {abs(delta):.2f}{suffix} vs {delta_label}</div>'
        else:                delta_html = f'<div class="kpi-delta-flat">→ Flat vs {delta_label}</div>'
    sub_html = f'<div class="kpi-sub">{sub}</div>' if sub else ""
    return f"""
<div class="kpi-card" style="--kpi-color:{bc};">
  <div class="kpi-label">{dot}{label}</div>
  <div class="kpi-value">{value}</div>
  {sub_html}{delta_html}
</div>"""


def section(title: str):
    st.markdown(f'<div class="sec-hdr">{title}</div>', unsafe_allow_html=True)


def page_header(title: str, sub: str = ""):
    sub_html = f'<p class="pg-sub">{sub}</p>' if sub else ""
    st.markdown(
        f'<div class="pg-wrap"><p class="pg-title">{title}</p>{sub_html}</div>',
        unsafe_allow_html=True,
    )
    st.markdown('<hr style="border:none;border-top:1px solid #E2E8F0;margin:12px 0 20px 0;">', unsafe_allow_html=True)


def to_csv_bytes(df: pd.DataFrame) -> bytes:
    return df.to_csv(index=False).encode("utf-8")


def download_btn(df: pd.DataFrame, filename: str, label: str = "⬇ Export CSV"):
    st.download_button(label, data=to_csv_bytes(df),
                       file_name=filename, mime="text/csv")


# ============================================================================
# DATA LOADERS
# ============================================================================

VALID_STATUSES = {
    "Current", "Vacant-Unrented", "Vacant-Rented",
    "Notice-Unrented", "Notice-Rented", "Evict", "Past Resident",
}

def _latest_snapshot(table: str) -> str | None:
    """Devuelve la snapshot_date más reciente disponible en la tabla dada."""
    res = supabase.table(table)\
        .select("snapshot_date")\
        .order("snapshot_date", desc=True)\
        .limit(1)\
        .execute()
    return res.data[0]["snapshot_date"] if res.data else None


def _fetch_all(table: str, snap: str, page_size: int = 1000) -> list:
    """Fetches all rows for a snapshot using pagination (bypasses server 1000-row cap)."""
    rows, start = [], 0
    while True:
        res = supabase.table(table)\
            .select("*")\
            .eq("snapshot_date", snap)\
            .range(start, start + page_size - 1)\
            .execute()
        rows.extend(res.data)
        if len(res.data) < page_size:
            break
        start += page_size
    return rows


@st.cache_data(ttl=300, show_spinner=False)
def _rent_roll():
    try:
        snap = _latest_snapshot("rent_roll")
       
        if not snap:
            return None
        data = _fetch_all("rent_roll", snap)
        if not data:
            return None
        df = pd.DataFrame(data)
     
          
        df = df.rename(columns={
            "unit_id":     "Unit ID",
            "market_rent": "Market Rent",
            "lease_from":  "Lease From",
            "lease_to":    "Lease To",
            "bd_ba":       "BD/BA",
            "past_due":    "Past Due",
            "portfolio":   "Portfolio",
        })
        df = df.rename(columns={
            "property": "Property",
            "unit": "Unit",
            "status": "Status",
            "tenant": "Tenant",
            "rent": "Rent",
            "deposit": "Deposit",
        })
        
        if "Status" in df.columns:
            df["Status"] = df["Status"].astype(str).str.strip()
            df = df[df["Status"].isin(VALID_STATUSES)].copy()
        for col in ["Rent", "Market Rent", "Deposit", "Past Due"]:
            if col in df.columns:
                df[col] = pd.to_numeric(df[col], errors="coerce").fillna(0)
        return df
    except Exception as e:
        log.error("rent_roll desde Supabase: %s", e)
        return None

@st.cache_data(ttl=300, show_spinner=False)
def _rent_roll_all():
    """Igual que _rent_roll() pero sin filtrar por VALID_STATUSES.
    Usado exclusivamente para contar el total real de unidades del portfolio."""
    try:
        snap = _latest_snapshot("rent_roll")
        if not snap:
            return None
        data = _fetch_all("rent_roll", snap)
        if not data:
            return None
        df = pd.DataFrame(data)
        df = df.rename(columns={
            "unit_id":     "Unit ID",
            "market_rent": "Market Rent",
            "lease_from":  "Lease From",
            "lease_to":    "Lease To",
            "bd_ba":       "BD/BA",
            "past_due":    "Past Due",
            "portfolio":   "Portfolio",
        })
        df = df.rename(columns={
            "property": "Property",
            "unit": "Unit",
            "status": "Status",
            "tenant": "Tenant",
            "rent": "Rent",
            "deposit": "Deposit",
        })
        for col in ["Rent", "Market Rent", "Deposit", "Past Due"]:
            if col in df.columns:
                df[col] = pd.to_numeric(df[col], errors="coerce").fillna(0)
        return df
    except Exception as e:
        log.error("rent_roll_all desde Supabase: %s", e)
        return None

@st.cache_data(ttl=300, show_spinner=False)
def _funnel():
    try:
        snap = _latest_snapshot("leasing_funnel")
        if not snap:
            return None
        res = supabase.table("leasing_funnel")\
            .select("*")\
            .eq("snapshot_date", snap)\
            .limit(10000)\
            .execute()
        if not res.data:
            return None
        df = pd.DataFrame(res.data)
        df = df.rename(columns={
            "property":           "Property",
            "inquiries":          "Inquiries",
            "completed_showings": "Completed Showings",
            "rental_apps":        "Rental Apps",
            "decision_pending":   "Decision Pending",
            "approved":           "Approved",
            "signed_leases":      "Signed Leases",
        })
        return df
    except Exception as e:
        log.error("funnel desde Supabase: %s", e)
        return None

@st.cache_data(ttl=300, show_spinner=False)
def _leasing_summary():
    """Carga leasing_summary para obtener Move Ins, Move Outs y Leased a nivel portfolio."""
    try:
        snap = _latest_snapshot("leasing_summary")
        if not snap:
            return {}
        res = supabase.table("leasing_summary")\
            .select("*")\
            .eq("snapshot_date", snap)\
            .limit(1)\
            .execute()
        if not res.data:
            return {}
        row = res.data[0]
        return {
            "Leased":       int(row.get("leased", 0) or 0),
            "Move Ins":     int(row.get("move_ins", 0) or 0),
            "Move Outs":    int(row.get("move_outs", 0) or 0),
            "Inquiries":    int(row.get("inquiries", 0) or 0),
            "Showings":     int(row.get("showings", 0) or 0),
            "Applications": int(row.get("applications", 0) or 0),
        }
    except Exception as e:
        log.error("leasing_summary desde Supabase: %s", e)
        return {}

@st.cache_data(ttl=300, show_spinner=False)
def _monthly_leasing(year: int, month: int) -> dict:
    """
    Returns MTD leasing counts for the given month.
    Primary source: monthly_leasing table (pre-computed by ETL, fast).
    Fallback: live cross-snapshot dedup query.
    """
    import calendar as _cal

    # ── Primary: read from pre-computed table ────────────────────────────
    try:
        rows = supabase.table("monthly_leasing")\
            .select("showings_completed,applications_received,leases_signed,inquiries")\
            .eq("year", year).eq("month", month)\
            .order("snapshot_date", desc=True).limit(1).execute().data
        if rows:
            r = rows[0]
            return {
                "showings_completed": int(r.get("showings_completed") or 0),
                "applications":       int(r.get("applications_received") or 0),
                "leases_signed":      int(r.get("leases_signed") or 0),
                "inquiries":          int(r.get("inquiries") or 0),
            }
    except Exception:
        pass  # table not yet created — fall through to live query

    # ── Fallback: live cross-snapshot dedup query ─────────────────────────
    month_start = f"{year}-{month:02d}-01"
    last_day    = _cal.monthrange(year, month)[1]
    month_end   = f"{year}-{month:02d}-{last_day}"
    result = {"showings_completed": 0, "applications": 0, "leases_signed": 0}

    try:
        all_sh, start = [], 0
        while True:
            rows = supabase.table("showings")\
                .select("showing_time,status,property,unit")\
                .gte("showing_time", month_start)\
                .lte("showing_time", f"{month_end} 23:59:59")\
                .range(start, start + 999).execute().data
            all_sh += rows
            if len(rows) < 1000:
                break
            start += 1000
        if all_sh:
            df_sh = pd.DataFrame(all_sh).drop_duplicates(subset=["showing_time", "property", "unit"])
            result["showings_completed"] = int(
                df_sh["status"].str.lower().str.contains("completed", na=False).sum()
            )
    except Exception as e:
        log.warning("_monthly_leasing showings fallback: %s", e)

    try:
        all_ap, start = [], 0
        while True:
            rows = supabase.table("rental_applications")\
                .select("received,status,property,applicant,snapshot_date")\
                .gte("received", month_start)\
                .lte("received", month_end)\
                .range(start, start + 999).execute().data
            all_ap += rows
            if len(rows) < 1000:
                break
            start += 1000
        if all_ap:
            df_ap = (
                pd.DataFrame(all_ap)
                .sort_values("snapshot_date", ascending=False)
                .drop_duplicates(subset=["received", "property", "applicant"])
            )
            result["applications"]  = len(df_ap)
            result["leases_signed"] = int(df_ap["status"].isin(["Converted", "Approved"]).sum())
    except Exception as e:
        log.warning("_monthly_leasing applications fallback: %s", e)

    return result


@st.cache_data(ttl=300, show_spinner=False)
def _showings_agg():
    _empty = pd.DataFrame(columns=["Property", "Calc_Completed", "Calc_Canceled", "Calc_Scheduled"])
    try:
        snap = _latest_snapshot("showings_agg")
        if not snap:
            return _empty
        res = supabase.table("showings_agg")\
            .select("*")\
            .eq("snapshot_date", snap)\
            .limit(10000)\
            .execute()
        if not res.data:
            return _empty
        df = pd.DataFrame(res.data)
        df = df.rename(columns={
            "property":       "Property",
            "calc_completed": "Calc_Completed",
            "calc_canceled":  "Calc_Canceled",
            "calc_scheduled": "Calc_Scheduled",
        })
        return df
    except Exception as e:
        log.error("showings_agg desde Supabase: %s", e)
        return _empty

@st.cache_data(ttl=300, show_spinner=False)
def _metrics():
    r, f = _rent_roll(), _funnel()
    if r is None: return None, None, None, None
    m = calculate_metrics(r, f)
    totals, econ_occ, phys_occ = calculate_totals_row(m)
    # Override Total Units con el conteo sin filtrar (VALID_STATUSES excluye algunas unidades)
    r_all = _rent_roll_all()
    if r_all is not None:
        totals["Total Units"] = int(len(r_all))
    return m, totals, phys_occ, econ_occ

@st.cache_data(ttl=300, show_spinner=False)
def _vacancy_detail():
    try:
        snap = _latest_snapshot("vacancy_detail")
        if not snap:
            return None
        res = supabase.table("vacancy_detail")\
            .select("*")\
            .eq("snapshot_date", snap)\
            .limit(10000)\
            .execute()
        if not res.data:
            return None
        df = pd.DataFrame(res.data)
        df = df.rename(columns={
            "property":       "Property",
            "unit":           "Unit",
            "unit_id":        "Unit ID",
            "unit_status":    "Unit Status",
            "days_vacant":    "Days Vacant",
            "last_rent":      "Last Rent",
            "scheduled_rent": "Scheduled Rent",
            "bed_bath":       "Bed/Bath",
            "rent_ready":     "Rent Ready",
            "available_on":   "Available On",
            "rr_status":      "RR_Status",
            "rr_tenant":      "RR_Tenant",
            "source":         "Source",
        })
        df["Days Vacant"] = pd.to_numeric(df["Days Vacant"], errors="coerce").fillna(0)
        for col in ["Last Rent", "Scheduled Rent"]:
            if col in df.columns:
                df[col] = pd.to_numeric(df[col], errors="coerce").fillna(0)
        return df
    except Exception as e:
        log.error("vacancy_detail desde Supabase: %s", e)
        return None

@st.cache_data(ttl=300, show_spinner=False)
def _aged_receivable():
    try:
        snap = _latest_snapshot("aged_receivable")
        if not snap:
            return None
        res = supabase.table("aged_receivable")\
            .select("*")\
            .eq("snapshot_date", snap)\
            .limit(10000)\
            .execute()
        if not res.data:
            return None
        df = pd.DataFrame(res.data)
        df = df.rename(columns={
            "property":          "Property",
            "payer_name":        "Payer Name",
            "amount_receivable": "Amount Receivable",
            "d0_30":             "0-30",
            "d31_60":            "31-60",
            "d61_90":            "61-90",
            "d91_plus":          "91+",
            "gl_account_name":   "GL Account Name",
            "gl_account_number": "GL Account Number",
            "total_amount":      "Total Amount",
            "charge_date":       "Charge Date",
            "posting_date":      "Posting Date",
        })
        for col in ["Amount Receivable", "Total Amount", "0-30", "31-60", "61-90", "91+"]:
            if col in df.columns:
                df[col] = pd.to_numeric(df[col], errors="coerce").fillna(0)
        if "Amount Receivable" in df.columns:
            df = df[df["Amount Receivable"] > 0].copy()
        return df
    except Exception as e:
        log.error("aged_receivable desde Supabase: %s", e)
        return None

@st.cache_data(ttl=300, show_spinner=False)
def _work_orders():
    try:
        snap = _latest_snapshot("work_orders")
        if not snap:
            return None
        # Paginate — Supabase PostgREST caps at max_rows per request
        all_rows = []
        _batch   = 1000
        _offset  = 0
        while True:
            res = supabase.table("work_orders")\
                .select("*")\
                .eq("snapshot_date", snap)\
                .range(_offset, _offset + _batch - 1)\
                .execute()
            if not res.data:
                break
            all_rows.extend(res.data)
            if len(res.data) < _batch:
                break
            _offset += _batch
        if not all_rows:
            return None
        df = pd.DataFrame(all_rows)
        df = df.rename(columns={
            "property":                              "Property",
            "unit":                                  "Unit",
            "status":                                "Status",
            "priority":                              "Priority",
            "amount":                                "Amount",
            "created_at_raw":                        "Created At",
            "completed_on":                          "Completed On",
            "days_to_resolve":                       "Days to Resolve",
            "work_order_issue":                      "Work Order Issue",
            "vendor":                                "Vendor",
            "unit_turn_id":                          "Unit Turn ID",
            "work_order_type":                       "Work Order Type",
            "estimate_req_on":                       "Estimate Req On",
            "estimated_on":                          "Estimated On",
            "estimate_amount":                       "Estimate Amount",
            "estimate_approval_status":              "Estimate Approval Status",
            "estimate_approved_on":                  "Estimate Approved On",
            "estimate_approval_last_requested_on":   "Estimate Approval Last Requested On",
            "work_done_on":                          "Work Done On",
        })
        for money_col in ["Amount", "Estimate Amount"]:
            if money_col in df.columns:
                df[money_col] = pd.to_numeric(df[money_col], errors="coerce").fillna(0)
        date_cols = [
            "Created At", "Completed On", "Estimate Req On", "Estimated On",
            "Estimate Approved On", "Estimate Approval Last Requested On", "Work Done On",
        ]


        for col in date_cols:
            if col in df.columns:
                df[col] = pd.to_datetime(df[col], errors="coerce")

        return df
    except Exception as e:
        log.error("work_orders desde Supabase: %s", e)
        return None

@st.cache_data(ttl=300, show_spinner=False)
def _showings_raw():
    try:
        snap = _latest_snapshot("showings")
        if not snap:
            return None
        res = supabase.table("showings")\
            .select("*")\
            .eq("snapshot_date", snap)\
            .limit(10000)\
            .execute()
        if not res.data:
            return None
        df = pd.DataFrame(res.data)
        df = df.rename(columns={
            "property":      "Property",
            "status":        "Status",
            "showing_time":  "Showing Time",
            "unit":          "Unit",
            "prospect_name": "Prospect Name",
            "agent":         "Agent",
        })
        if "Showing Time" in df.columns:
            df["Showing Time"] = pd.to_datetime(df["Showing Time"], errors="coerce")
        return df
    except Exception as e:
        log.error("showings_raw desde Supabase: %s", e)
        return None

@st.cache_data(ttl=300, show_spinner=False)
def _tickler():
    try:
        snap = _latest_snapshot("tenant_tickler")
        if not snap:
            return None
        res = supabase.table("tenant_tickler")\
            .select("*")\
            .eq("snapshot_date", snap)\
            .limit(10000)\
            .execute()
        if not res.data:
            return None
        df = pd.DataFrame(res.data)
        df = df.rename(columns={
            "property":   "Property",
            "event_date": "Date",
            "event":      "Event",
            "tenant":     "Tenant",
            "unit":       "Unit",
            "rent":       "Rent",
        })
        df["Date"] = pd.to_datetime(df["Date"], errors="coerce")
        if "Rent" in df.columns:
            df["Rent"] = pd.to_numeric(df["Rent"], errors="coerce").fillna(0)
        return df.dropna(subset=["Date"])
    except Exception as e:
        log.error("tenant_tickler desde Supabase: %s", e)
        return None

@st.cache_data(ttl=300, show_spinner=False)
def _renewals():
    try:
        snap = _latest_snapshot("renewal_summary")
        if not snap:
            return None
        res = supabase.table("renewal_summary")\
            .select("*")\
            .eq("snapshot_date", snap)\
            .limit(10000)\
            .execute()
        if not res.data:
            return None
        df = pd.DataFrame(res.data)
        df = df.rename(columns={
            "property":           "Property",
            "unit_id":            "Unit ID",
            "tenant_name":        "Tenant Name",
            "status":             "Status",
            "previous_rent":      "Previous Rent",
            "rent":               "Rent",
            "percent_difference": "Percent Difference",
        })
        for col in ["Previous Rent", "Rent", "Percent Difference"]:
            if col in df.columns:
                df[col] = pd.to_numeric(df[col], errors="coerce")
        return df
    except Exception as e:
        log.error("renewal_summary desde Supabase: %s", e)
        return None

@st.cache_data(ttl=300, show_spinner=False)
def _applications():
    try:
        snap = _latest_snapshot("rental_applications")
        if not snap:
            return None
        res = supabase.table("rental_applications")\
            .select("*")\
            .eq("snapshot_date", snap)\
            .limit(10000)\
            .execute()
        if not res.data:
            return None
        df = pd.DataFrame(res.data)
        df = df.rename(columns={
            "property":     "Property",
            "applicant":    "Applicant",
            "status":       "Status",
            "received":     "Received",
            "unit":         "Unit",
            "move_in_date": "Move In Date",
        })
        if "Received" in df.columns:
            df["Received"] = pd.to_datetime(df["Received"], errors="coerce")
        return df.dropna(subset=["Status"])
    except Exception as e:
        log.error("rental_applications desde Supabase: %s", e)
        return None

@st.cache_data(ttl=300, show_spinner=False)
def _leads():
    try:
        snap = _latest_snapshot("leads")
        if not snap:
            return None
        res = supabase.table("leads")\
            .select("*")\
            .eq("snapshot_date", snap)\
            .limit(10000)\
            .execute()
        if not res.data:
            return None
        df = pd.DataFrame(res.data)
        df = df.rename(columns={
            "property":         "Property",
            "name":             "Name",
            "status":           "Status",
            "monthly_income":   "Monthly Income",
            "max_rent":         "Max Rent",
            "credit_score":     "Credit Score",
            "credit_score_mid": "Credit Score Mid",
            "lead_score":       "Lead Score",
        })
        for col in ["Monthly Income", "Max Rent", "Credit Score Mid", "Lead Score"]:
            if col in df.columns:
                df[col] = pd.to_numeric(df[col], errors="coerce")
        return df
    except Exception as e:
        log.error("leads desde Supabase: %s", e)
        return None

@st.cache_data(ttl=60, show_spinner=False)
def _historical():
    try:
        res = supabase.table("historical_metrics")\
            .select("*")\
            .order("date", desc=False)\
            .execute()
        if not res.data:
            return None
        df = pd.DataFrame(res.data)
        df = df.rename(columns={
            "date":               "Date",
            "physical_occupancy": "Physical Occupancy",
            "economic_occupancy": "Economic Occupancy",
            "total_units":        "Total Units",
            "occupied_units":     "Occupied Units",
            "vacant_units":       "Vacant Units",
            "sum_of_rent":        "Sum of Rent",
            "inquiries":          "Inquiries",
            "showings":           "Showings",
            "leased":             "Leased",
        })
        df["Date"] = pd.to_datetime(df["Date"], errors="coerce")
        return df.dropna(subset=["Date"]).sort_values("Date").reset_index(drop=True)
    except Exception as e:
        log.error("historical_metrics desde Supabase: %s", e)
        return None

@st.cache_data(ttl=300)
def load_historical_metrics():
    res = (
        supabase.table("historical_metrics")
        .select("*")
        .order("date")
        .execute()
    )

    df = pd.DataFrame(res.data)

    if df.empty:
        return df

    df["date"] = pd.to_datetime(df["date"])

    numeric_cols = [
        "physical_occupancy",
        "economic_occupancy",
        "total_units",
        "occupied_units",
        "vacant_units",
        "sum_of_rent",
        "inquiries",
        "showings",
        "leased",
        "collection_rate",
    ]

    for col in numeric_cols:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")

    return df

def save_portfolio_history_snapshot(row: dict):
    """
    Guarda o actualiza el snapshot histórico del portfolio.
    Si ya existe snapshot_date, lo actualiza.
    """
    try:
        supabase.table("portfolio_history").upsert(
            row,
            on_conflict="snapshot_date"
        ).execute()
    except Exception as e:
        st.warning(f"Could not save portfolio history snapshot: {e}")


@st.cache_data(ttl=300, show_spinner=False)
def _owner_portfolios():
    """
    Reads owner_directory-*.csv and returns a dict {clean_property_name: portfolio}.

    Portfolio assignment rules (in order):
      1. Email domain @seaviewcapitalcorp.com  → "Seaview Capital"
      2. Email domain @boldpartnersre.com      → "Bold Partners"
      3. Property name contains "mirada"       → "Bold Partners"  (La Mirada override)
      4. Empty email / no match               → "Defined Property Management"
    """
    DEFAULT = "Defined Property Management"

    try:
        fp = find_csv_file(str(DATA_DIR), "owner_directory")
        if not fp:
            return {}

        df_own = pd.read_csv(fp, dtype=str).fillna("")

        def _pf_from_email(email_str):
            for e in email_str.lower().split(","):
                e = e.strip()
                if "seaview" in e:
                    return "Seaview Capital"
                if "bold" in e:
                    return "Bold Partners"
            return DEFAULT

        col = "Properties Owned"
        if col not in df_own.columns:
            return {}

        # Build {norm_key: portfolio} from owner directory entries
        owner_key_map = {}
        for _, row in df_own.iterrows():
            pf = _pf_from_email(str(row.get("Email", "")))
            props_str = str(row.get(col, "") or "")
            if not props_str or props_str == "nan":
                continue
            # Split multi-property strings: "1133 25th St (100%), 1134 26th St (100%)"
            for part in re.split(r'\)\s*,\s*', props_str):
                # strip both "(100%)" and "(100" (closing paren consumed by split)
                part = re.sub(r'\s*\(\d+%?\)?', '', part).strip()
                if not part:
                    continue
                # La Mirada hardcoded override
                if "mirada" in part.lower():
                    pf = "Bold Partners"
                k = _norm_key(part)
                if k:
                    owner_key_map[k] = pf

        # Match against rent roll to get clean property names
        rr_fp = find_csv_file(str(DATA_DIR), "rent_roll")
        if not rr_fp:
            return {}

        df_raw = pd.read_csv(rr_fp, header=None, dtype=str)
        hr = detect_header_row(df_raw)
        df_rr_raw = pd.read_csv(rr_fp, skiprows=hr, dtype=str)

        if "Property" not in df_rr_raw.columns:
            return {}

        prop_to_pf = {}
        for raw_name in df_rr_raw["Property"].dropna().unique():
            clean = clean_property_name(str(raw_name))
            if not clean or clean in prop_to_pf:
                continue

            # Build candidate keys to try against owner_key_map
            candidates = [_norm_key(clean)]           # e.g. "gardendale park"
            if " - " in raw_name:
                addr_part = raw_name.split(" - ", 1)[1]
                candidates.append(_norm_key(addr_part))   # e.g. "8350 gardendale paramount"
            candidates.append(_norm_key(raw_name))        # full raw key

            matched = False
            for k in candidates:
                if k in owner_key_map:
                    prop_to_pf[clean] = owner_key_map[k]
                    matched = True
                    break
                # Subset match: owner key tokens ⊆ candidate tokens (min 2 tokens required)
                k_tokens = set(k.split())
                for ok, opf in owner_key_map.items():
                    ok_tokens = set(ok.split())
                    if len(ok_tokens) >= 2 and ok_tokens.issubset(k_tokens):
                        prop_to_pf[clean] = opf
                        matched = True
                        break
                if matched:
                    break

            if not matched:
                prop_to_pf[clean] = DEFAULT

        return prop_to_pf

    except Exception as e:
        log.error("owner_directory CSV: %s", e)
        return {}


@st.cache_data(ttl=300, show_spinner=False)
def _calls_data():
    # ── Try Supabase first ───────────────────────────────────────────────
    try:
        snap = _latest_snapshot("calls")
        if snap:
            res = supabase.table("calls")\
                .select("*")\
                .eq("snapshot_date", snap)\
                .limit(500)\
                .execute()
            if res.data:
                df = pd.DataFrame(res.data)
                df = df.rename(columns={
                    "name":           "Name",
                    "ext":            "Ext",
                    "total_calls":    "Total Calls",
                    "avg_daily":      "Avg Daily",
                    "inbound":        "Inbound",
                    "outbound":       "Outbound",
                    "missed_with_vm": "Missed with VM",
                    "missed_vm_pct":  "Missed VM %",
                })
                for col in ["Total Calls", "Avg Daily", "Inbound", "Outbound", "Missed with VM"]:
                    if col in df.columns:
                        df[col] = pd.to_numeric(df[col], errors="coerce").fillna(0).astype(int)
                if "Missed VM %" in df.columns:
                    df["Missed VM %"] = pd.to_numeric(df["Missed VM %"], errors="coerce").fillna(0)
                period_start = pd.to_datetime(df["period_start"].iloc[0], errors="coerce") \
                               if "period_start" in df.columns else None
                period_end   = pd.to_datetime(df["period_end"].iloc[0], errors="coerce") \
                               if "period_end"   in df.columns else None
                meta = {"start": period_start, "end": period_end}
                return df.sort_values("Total Calls", ascending=False).reset_index(drop=True), meta
    except Exception as e:
        log.warning("calls desde Supabase: %s — fallback a xlsx", e)

    # ── Fallback: read local xlsx ────────────────────────────────────────
    try:
        candidates = list(Path(DATA_DIR).glob("Users_Dashboard*.xlsx"))
        if not candidates:
            return None, None
        fp = str(sorted(candidates, key=lambda x: x.stat().st_mtime, reverse=True)[0])

        raw = pd.read_excel(fp, sheet_name="Table_Table", header=None, dtype=str)

        period_start = period_end = None
        try:
            period_start = pd.to_datetime(raw.iat[3, 1], errors="coerce")
            period_end   = pd.to_datetime(raw.iat[3, 2], errors="coerce")
        except Exception:
            pass

        df = raw.iloc[11:].reset_index(drop=True)
        df.columns = ["Name", "Ext", "Total Calls", "Avg Daily",
                      "Inbound", "Outbound", "Missed with VM", "_extra"]
        df = df[["Name", "Ext", "Total Calls", "Avg Daily", "Inbound", "Outbound", "Missed with VM"]]

        for col in ["Total Calls", "Avg Daily", "Inbound", "Outbound", "Missed with VM"]:
            df[col] = pd.to_numeric(df[col], errors="coerce").fillna(0).astype(int)

        df = df[df["Name"].notna() & (df["Name"].astype(str).str.strip() != "")]
        df["Name"] = df["Name"].astype(str).str.strip()
        df["Missed VM %"] = (
            (df["Missed with VM"] / df["Inbound"].replace(0, float("nan"))) * 100
        ).fillna(0).round(1)

        meta = {"start": period_start, "end": period_end}
        return df.sort_values("Total Calls", ascending=False).reset_index(drop=True), meta
    except Exception as e:
        log.error("Users_Dashboard XLSX: %s", e)
        return None, None

@st.cache_data(ttl=300)
def _portfolio_history():
    try:
        data = (
            supabase.table("portfolio_history")
            .select("*")
            .order("snapshot_date")
            .execute()
            .data
        )

        if not data:
            return pd.DataFrame()

        df = pd.DataFrame(data)
        df["snapshot_date"] = pd.to_datetime(df["snapshot_date"])
        return df

    except Exception as e:
        log.warning("portfolio_history load failed: %s", e)
        return pd.DataFrame()

# ============================================================================
# SNAPSHOT
# ============================================================================

#def _save_snapshot(df_rr, totals, phys_occ, econ_occ) -> bool:
#    p = DATA_DIR / "historical_metrics.csv"
#    today = datetime.now().strftime("%Y-%m-%d")
#    row = {
#        "Date":               today,
#        "Physical Occupancy": round(phys_occ, 2),
#        "Economic Occupancy": round(econ_occ, 2),
#        "Total Units":        int(totals.get("Total Units", 0)),
#        "Occupied Units":     int(totals.get("Current", 0)),
#        "Vacant Units":       int(totals.get("Vacant-Unrented", 0)),
#        "Sum of Rent":        round(float(df_rr["Rent"].sum()), 2) if df_rr is not None and "Rent" in df_rr.columns else 0,
#        "Inquiries":          int(totals.get("Inquiries", 0)),
#        "Showings":           int(totals.get("Completed Showings", 0)),
#        "Signed Leases":      int(totals.get("Signed Leases", 0)),
#        "Collection Rate":    round(
#            max(0.0, min(100.0, (
#                (float(df_rr.loc[df_rr["Status"]=="Current","Rent"].sum()) -
#                 float(clean_money_column(df_rr.loc[df_rr["Status"]=="Current","Past Due"]).clip(lower=0).sum())) /
#                float(df_rr.loc[df_rr["Status"]=="Current","Rent"].sum()) * 100
#            ))) if (
#                df_rr is not None and "Rent" in df_rr.columns and "Past Due" in df_rr.columns and "Status" in df_rr.columns
#                and float(df_rr.loc[df_rr["Status"]=="Current","Rent"].sum()) > 0
#            ) else 0.0, 2),
#    }
#    if p.exists():
#        try:
#            h = pd.read_csv(p, dtype=str)
#            if today in h["Date"].values: return False
#            h = pd.concat([h, pd.DataFrame([row])], ignore_index=True)
#        except Exception as e:
#            log.warning("historical_metrics.csv unreadable, starting fresh: %s", e)
#            h = pd.DataFrame([row])
#    else: h = pd.DataFrame([row])
#    # Keep only the last 180 days (6 months)
#    try:
#        h["_dt"] = pd.to_datetime(h["Date"], errors="coerce")
#        cutoff = pd.Timestamp.now() - pd.Timedelta(days=180)
#        h = h[h["_dt"] >= cutoff].drop(columns=["_dt"])
#    except Exception as e:
#        log.warning("historical_metrics.csv date trim failed: %s", e)
#    h.to_csv(p, index=False)
#    return True#

# ============================================================================
# LOAD ALL DATA (before sidebar so filter can use it)
# ============================================================================

with st.spinner("Loading portfolio data…"):
    df_rr       = _rent_roll()
    df_funnel   = _funnel()
    df_showings = _showings_agg()
    df_metrics, totals, phys_occ, econ_occ = _metrics()
    df_hist     = _historical()
    df_aged     = _aged_receivable()
    df_vac      = _vacancy_detail()
    df_wo       = _work_orders()
    df_raw_show = _showings_raw()
    df_tickler  = _tickler()
    df_renew    = _renewals()
    df_apps     = _applications()
    df_leads_df     = _leads()
    df_calls, calls_meta = _calls_data()
    leasing_summary = _leasing_summary()
    df_ph = load_historical_metrics()

    if not df_ph.empty:
        df_ph = df_ph.copy()
        df_ph["date"] = pd.to_datetime(df_ph["date"])

    df_rr_f = df_rr.copy() if df_rr is not None else None
    df_vac_f = df_vac.copy() if df_vac is not None else None


        # Save portfolio history snapshot
    if df_rr is not None and totals is not None:
        total_units_hist = int(totals.get("Total Units", 0) or 0)

        monthly_rent_hist = (
            float(df_rr["Rent"].sum())
            if "Rent" in df_rr.columns
            else 0.0
        )

        outstanding_hist = (
            float(df_rr["Past Due"].sum())
            if "Past Due" in df_rr.columns
            else 0.0
        )

        collection_rate_hist = (
            ((monthly_rent_hist - outstanding_hist) / monthly_rent_hist * 100)
            if monthly_rent_hist > 0
            else 0.0
        )

        vacant_unrented_hist = int(totals.get("Vacant-Unrented", 0) or 0)
        notice_unrented_hist = int(totals.get("Notice-Unrented", 0) or 0)

        total_past_due_hist = 0
        exposure_91_hist = 0
        delinquency_rate_hist = 0

        if df_aged is not None and "Amount Receivable" in df_aged.columns:
            total_past_due_hist = float(df_aged["Amount Receivable"].sum())

        if "91+" in df_aged.columns:
            exposure_91_hist = float(df_aged["91+"].sum())

        delinquency_rate_hist = (
            total_past_due_hist / monthly_rent_hist * 100
            if monthly_rent_hist > 0
            else 0
        )

        history_row = {
            "snapshot_date": datetime.now().date().isoformat(),
            "total_units": total_units_hist,
            "physical_occupancy": float(phys_occ or 0),
            "economic_occupancy": float(econ_occ or 0),
            "monthly_rent": monthly_rent_hist,
            "collection_rate": collection_rate_hist,
            "outstanding_balance": outstanding_hist,
            "vacant_unrented": vacant_unrented_hist,
            "notice_unrented": notice_unrented_hist,
            "total_past_due": total_past_due_hist,
            "delinquency_rate": delinquency_rate_hist,
            "exposure_91": exposure_91_hist,
        }

        save_portfolio_history_snapshot(history_row)

       
    # Build portfolio map — local CSV is authoritative; Supabase is fallback only
    prop_portfolio_map = _owner_portfolios()
    if not prop_portfolio_map:
        _rr_all_raw = _rent_roll_all()
        if _rr_all_raw is not None and "Portfolio" in _rr_all_raw.columns and "Property" in _rr_all_raw.columns:
            _pf_df = (
                _rr_all_raw[["Property", "Portfolio"]]
                .dropna(subset=["Property", "Portfolio"])  # only rows with known portfolio
                .drop_duplicates("Property")
            )
            if _pf_df.empty:
                # Today's snapshot has NULL portfolios — fetch from most recent good snapshot
                try:
                    _good_rows = supabase.table("rent_roll")\
                        .select("property,portfolio")\
                        .neq("portfolio", "Defined Property Management")\
                        .not_.is_("portfolio", "null")\
                        .limit(500)\
                        .execute().data
                    if _good_rows:
                        _pf_df = pd.DataFrame(_good_rows)\
                            .rename(columns={"property": "Property", "portfolio": "Portfolio"})\
                            .drop_duplicates("Property")
                except Exception as _e:
                    log.warning("portfolio fallback query failed: %s", _e)
            prop_portfolio_map = (
                _pf_df.set_index("Property")["Portfolio"].to_dict()
                if not _pf_df.empty else {}
            )


df_hist = load_historical_metrics()

if df_hist is not None and not df_hist.empty:
    df_hist = df_hist.rename(columns={
        "date": "Date",
        "physical_occupancy": "Physical Occupancy",
        "economic_occupancy": "Economic Occupancy",
        "total_units": "Total Units",
        "occupied_units": "Occupied Units",
        "vacant_units": "Vacant Units",
        "sum_of_rent": "Sum of Rent",
        "collection_rate": "Collection Rate",
    })

# ============================================================================
# PROPERTY FILTER HELPER
# ============================================================================

all_props = sorted(df_metrics["Property"].tolist()) if df_metrics is not None else []

# Derive the portfolio each property belongs to; unknown → Defined
_PORTFOLIO_COLORS = {
    "Seaview Capital":              "#1B4FD8",
    "Bold Partners":                "#059669",
    "Defined Property Management":  "#D97706",
}
_ALL_PORTFOLIOS = "All Portfolios"
_known_portfolios = sorted({prop_portfolio_map.get(p) or "Defined Property Management"
                             for p in all_props})
_portfolio_options = [_ALL_PORTFOLIOS] + _known_portfolios

if "prop_filter" not in st.session_state:
    st.session_state.prop_filter = []
if "portfolio_filter" not in st.session_state:
    st.session_state.portfolio_filter = _ALL_PORTFOLIOS

# ============================================================================
# SIDEBAR
# ============================================================================

if "page" not in st.session_state:
    st.session_state.page = "Overview"

with st.sidebar:
    # Logo: try configured path, then auto-detect common names
    _logo_found = False
    _logo_path = CONFIG.get("logo_path")
    if not _logo_path:
        for _ext in ["png", "jpg", "jpeg", "svg", "webp"]:
            for _name in ["logo", "Logo", "LOGO", "brand", "Brand"]:
                _candidate = DATA_DIR / f"{_name}.{_ext}"
                if _candidate.exists():
                    _logo_path = str(_candidate)
                    break
            if _logo_path:
                break
    if _logo_path and Path(_logo_path).exists():
        st.image(_logo_path, width="stretch")
        _logo_found = True
    if not _logo_found:
        st.markdown(
            f'<div style="background:#1B4FD8;padding:14px 12px;border-radius:8px;margin-bottom:4px;">'
            f'<span style="color:#fff;font-size:18px;font-weight:800;letter-spacing:0.5px;">Defined</span>'
            f'<span style="color:#DBEAFE;font-size:11px;font-weight:500;letter-spacing:1px;">  PROPERTY MANAGEMENT</span>'
            f'</div>',
            unsafe_allow_html=True,
        )

    st.markdown('<hr style="border:none;border-top:1px solid rgba(255,255,255,.08);margin:8px 0;">', unsafe_allow_html=True)
    for p in PAGES:
        t = "primary" if st.session_state.page == p else "secondary"
        if st.button(p, key=f"nav_{p}", width="stretch", type=t):
            st.session_state.page = p
            st.rerun()

    st.markdown('<hr style="border:none;border-top:1px solid rgba(255,255,255,.08);margin:8px 0;">', unsafe_allow_html=True)

    # ── Portfolio selector ──────────────────────────────────────────────
    _cur_pf = st.session_state.portfolio_filter
    if _cur_pf not in _portfolio_options:
        _cur_pf = _ALL_PORTFOLIOS
    selected_portfolio = st.selectbox(
        "Portfolio",
        options=_portfolio_options,
        index=_portfolio_options.index(_cur_pf),
    )
    if selected_portfolio != st.session_state.portfolio_filter:
        st.session_state.portfolio_filter = selected_portfolio
        st.session_state.prop_filter = []   # clear property sub-filter on portfolio change
        st.rerun()

    # Show a colored indicator for active portfolio
    if selected_portfolio != _ALL_PORTFOLIOS:
        _pf_color = _PORTFOLIO_COLORS.get(selected_portfolio, PC)
        st.markdown(
            f'<div style="background:{_pf_color}18;border-left:3px solid {_pf_color};'
            f'padding:6px 10px;border-radius:4px;font-size:11px;color:{_pf_color};'
            f'font-weight:700;margin-bottom:4px;">{selected_portfolio}</div>',
            unsafe_allow_html=True,
        )

    # ── Property sub-filter (scoped to selected portfolio) ──────────────
    _props_in_pf = (
        [p for p in all_props if prop_portfolio_map.get(p, "Defined Property Management") == selected_portfolio]
        if selected_portfolio != _ALL_PORTFOLIOS
        else all_props
    )
    _valid_prop_default = [p for p in st.session_state.prop_filter if p in _props_in_pf]
    if _props_in_pf:
        sel = st.multiselect(
            "Filter by property",
            options=_props_in_pf,
            default=_valid_prop_default,
            placeholder="All properties",
            label_visibility="visible",
        )
        st.session_state.prop_filter = sel

    st.markdown('<hr style="border:none;border-top:1px solid rgba(255,255,255,.08);margin:8px 0;">', unsafe_allow_html=True)
    if st.button("Refresh Data", width="stretch", type="secondary"):
        st.cache_data.clear()
        st.session_state.snapshot_saved = False
        st.rerun()
    st.caption(f"Last updated: {datetime.now().strftime('%b %d, %Y  %H:%M')}")

    # ── Notes panel ─────────────────────────────────────────────────────
    st.markdown('<hr style="border:none;border-top:1px solid rgba(255,255,255,.08);margin:8px 0;">', unsafe_allow_html=True)

    _notes_path = DATA_DIR / "notes.json"

    def _load_notes():
        if _notes_path.exists():
            try:
                import json
                return json.loads(_notes_path.read_text(encoding="utf-8"))
            except Exception:
                return []
        return []

    def _save_notes(notes_list):
        try:
            import json
            _notes_path.write_text(json.dumps(notes_list, ensure_ascii=False, indent=2), encoding="utf-8")
        except Exception as e:
            log.warning("notes.json save failed: %s", e)

    if "notes" not in st.session_state:
        st.session_state.notes = _load_notes()

    with st.expander(f"Notes  ({len(st.session_state.notes)})", expanded=False):
        _new_note = st.text_area("Add note", placeholder="Write a note…", height=68,
                                  label_visibility="collapsed", key="new_note_input")
        if st.button("Add", key="add_note_btn", type="secondary"):
            if _new_note.strip():
                st.session_state.notes.append({
                    "id":        len(st.session_state.notes),
                    "page":      st.session_state.page,
                    "content":   _new_note.strip(),
                    "timestamp": datetime.now().strftime("%b %d, %Y %H:%M"),
                })
                _save_notes(st.session_state.notes)
                st.rerun()

        for _i, _n in enumerate(reversed(st.session_state.notes)):
            _orig_i = len(st.session_state.notes) - 1 - _i
            st.markdown(
                f'<div style="background:rgba(255,255,255,.06);border-radius:6px;'
                f'padding:8px 10px;margin-bottom:4px;font-size:11px;">'
                f'<div style="color:#CBD5E1;margin-bottom:3px;">{_n["content"]}</div>'
                f'<div style="color:#475569;font-size:10px;">{_n.get("page","")} · {_n.get("timestamp","")}</div>'
                f'</div>',
                unsafe_allow_html=True,
            )
            if st.button("✕", key=f"del_note_{_orig_i}", help="Delete this note"):
                st.session_state.notes.pop(_orig_i)
                _save_notes(st.session_state.notes)
                st.rerun()

# ============================================================================
# APPLY FILTER TO ALL DATAFRAMES
# ============================================================================

# Effective selection: portfolio scope + optional property sub-filter
_pf_active = st.session_state.portfolio_filter
_prop_active = st.session_state.prop_filter

if _pf_active != _ALL_PORTFOLIOS:
    _pf_props = [p for p in all_props
                 if prop_portfolio_map.get(p, "Defined Property Management") == _pf_active]
    SEL = [p for p in _prop_active if p in _pf_props] if _prop_active else _pf_props
else:
    SEL = _prop_active   # empty list = no filter (show all)

def _f(df, col="Property"):
    if df is None or not SEL: return df
    return df[df[col].isin(SEL)].copy() if col in df.columns else df

df_rr_f      = _f(df_rr)
df_metrics_f = _f(df_metrics)
df_vac_f     = _f(df_vac)
df_aged_f    = _f(df_aged)
df_wo_f      = _f(df_wo)
df_funnel_f  = _f(df_funnel)
df_tickler_f = _f(df_tickler)
df_renew_f   = _f(df_renew)
df_apps_f    = _f(df_apps, col="Property")
df_leads_f   = _f(df_leads_df)

today_ts = pd.Timestamp.now().normalize()

# Module-level lease expirations — shared across all pages
exp30 = exp60 = exp90 = 0
if df_rr_f is not None and "Lease To" in df_rr_f.columns:
    _lt = pd.to_datetime(df_rr_f.loc[df_rr_f["Status"] == "Current", "Lease To"], errors="coerce")
    exp30 = int((((_lt >= today_ts) & (_lt <= today_ts + pd.Timedelta(30, "d")))).sum())
    exp60 = int((((_lt >= today_ts) & (_lt <= today_ts + pd.Timedelta(60, "d")))).sum())
    exp90 = int((((_lt >= today_ts) & (_lt <= today_ts + pd.Timedelta(90, "d")))).sum())

# Module-level filtered totals — shared across all pages
if df_metrics_f is not None and totals is not None:
    if SEL:
        _totals, _econ_occ, _phys_occ = calculate_totals_row(df_metrics_f)
    else:
        _totals, _phys_occ, _econ_occ = totals, phys_occ, econ_occ
else:
    _totals, _phys_occ, _econ_occ = {}, 0.0, 0.0

# ============================================================================
# PAGE 0 — ALL HANDS MEETING
# ============================================================================

if st.session_state.page == "All Hands":
    _snap = _latest_snapshot("rent_roll")
    _ah_date = (
        pd.to_datetime(_snap).strftime("%B %d, %Y")
        if _snap
        else datetime.now(ZoneInfo("America/Los_Angeles")).strftime("%B %d, %Y")
    )
    _ah_col_hdr, _ah_col_btn = st.columns([5, 1])
    with _ah_col_hdr:
        page_header("All Hands Meeting", f"Monthly Company Snapshot  ·  {_ah_date}")

    if df_metrics_f is None or totals is None:
        st.warning("Data not available.")
        st.stop()

    # ── Snapshot values ────────────────────────────────────────────────────
    _tu   = int(_totals.get("Total Units", 0))
    _curr = int(_totals.get("Current", 0))
    _vu   = int(_totals.get("Vacant-Unrented", 0))
    _vr   = int(_totals.get("Vacant-Rented", 0))
    _nu   = int(_totals.get("Notice-Unrented", 0))
    _nr   = int(_totals.get("Notice-Rented", 0))
    _ev   = int(_totals.get("Evict", 0))
    _rgap = float(df_metrics_f["Revenue Gap ($)"].sum()) if "Revenue Gap ($)" in df_metrics_f.columns else 0

    _rr_pct = 0.0
    if df_renew_f is not None and "Status" in df_renew_f.columns:
        _act = df_renew_f[df_renew_f["Status"].isin(["Renewed", "Did Not Renew", "Canceled by User"])]
        if len(_act):
            _rr_pct = len(_act[_act["Status"] == "Renewed"]) / len(_act) * 100

    _sum_rent = _pct_coll = 0.0
    if df_rr_f is not None and "Rent" in df_rr_f.columns:
        _curr_rr = df_rr_f[df_rr_f["Status"] == "Current"]
        _sum_rent = float(clean_money_column(_curr_rr["Rent"]).sum())
        if "Past Due" in _curr_rr.columns and _sum_rent > 0:
            _pd_s = clean_money_column(_curr_rr["Past Due"]).clip(lower=0)  # credits (negatives) = fully collected
            _pct_coll = max(0.0, min(100.0, (_sum_rent - float(_pd_s.sum())) / _sum_rent * 100))

    _wo_open = _wo_total = _wo_completed = 0
    _wo_comp_pct = 0.0
    _wo_month_label = datetime.now().strftime("%B %Y")
    if df_wo_f is not None and "Status" in df_wo_f.columns:
        _df_wo_month = df_wo_f
        if "Created At" in df_wo_f.columns:
            _wo_created = pd.to_datetime(df_wo_f["Created At"], errors="coerce")
            _now = datetime.now()
            _df_wo_month = df_wo_f[(_wo_created.dt.year == _now.year) & (_wo_created.dt.month == _now.month)]
        _wo_status = _df_wo_month["Status"].astype(str).str.lower()
        _wo_open      = int(_wo_status.isin(["open", "in progress", "new"]).sum())
        _wo_completed = int(_wo_status.str.contains("completed", na=False).sum())
        _wo_total     = len(_df_wo_month)
        _wo_comp_pct  = (_wo_completed / _wo_total * 100) if _wo_total > 0 else 0.0

    # ── Monthly filters — All Hands only ─────────────────────────────────
    _ah_now = datetime.now()
    _ah_month, _ah_year = _ah_now.month, _ah_now.year

    # Query true monthly data across all snapshots (deduplicated)
    _monthly = _monthly_leasing(_ah_year, _ah_month)
    _shows      = _monthly["showings_completed"] or int(_totals.get("Completed Showings", 0))
    _apps_count = _monthly["applications"]       or (int(df_funnel_f["Rental Apps"].sum()) if df_funnel_f is not None and "Rental Apps" in df_funnel_f.columns else 0)
    _leased     = _monthly["leases_signed"]      or leasing_summary.get("Leased", int(_totals.get("Signed Leases", 0)))
    _inq        = _monthly.get("inquiries") or int(_totals.get("Inquiries", 0))

    # ── Alertas automáticas vs. snapshot anterior ─────────────────────────
    if df_hist is not None and len(df_hist) >= 2:
        _prev_snap = df_hist.iloc[-2]
        _curr_snap = df_hist.iloc[-1]
        _alerts = []   # (level, metric, prev_val, curr_val, msg)

        def _snap_float(row, col):
            try:    return float(row[col]) if col in row.index and pd.notna(row[col]) else None
            except: return None

        for _col, _label, _thr, _dir in [
            ("Physical Occupancy", "Physical Occupancy", 0.5,  "down"),
            ("Economic Occupancy", "Economic Occupancy", 0.5,  "down"),
            ("Collection Rate",    "Collection Rate",    0.5,  "down"),
            ("Vacant Units",       "Vacant Units",       1,    "up"),
            ("Signed Leases",      "Signed Leases",      1,    "neutral"),
        ]:
            _pv = _snap_float(_prev_snap, _col)
            _cv = _snap_float(_curr_snap, _col)
            if _pv is None or _cv is None:
                continue
            _delta = _cv - _pv
            if _dir == "down" and _delta < -_thr:
                _lvl = "bad" if abs(_delta) > _thr * 3 else "warn"
                _alerts.append((_lvl, _label, _pv, _cv,
                                 f"{_label} dropped {abs(_delta):.1f}{'%' if 'Occ' in _col or 'Rate' in _col else ''} "
                                 f"vs last snapshot ({_pv:.1f} → {_cv:.1f})"))
            elif _dir == "up" and _delta > _thr:
                _lvl = "bad" if _delta > _thr * 3 else "warn"
                _alerts.append((_lvl, _label, _pv, _cv,
                                 f"{_label} increased by {_delta:.0f} "
                                 f"vs last snapshot ({_pv:.0f} → {_cv:.0f})"))
            elif _dir == "neutral" and abs(_delta) >= _thr:
                _lvl = "good" if _delta > 0 else "warn"
                _s = "+" if _delta > 0 else ""
                _alerts.append((_lvl, _label, _pv, _cv,
                                 f"{_label} {_s}{_delta:.0f} vs last snapshot ({_pv:.0f} → {_cv:.0f})"))

        if _alerts:
            _prev_date = _prev_snap.get("Date", "previous snapshot") if hasattr(_prev_snap, "get") else str(_prev_snap.get("Date",""))
            _color_map = {"bad": ("#FEF2F2","#DC2626"), "warn": ("#FFFBEB","#D97706"), "good": ("#F0FDF4","#059669")}
            _icon_map  = {"bad": "↓", "warn": "⚠", "good": "↑"}
            with st.expander(f"KPI Alerts vs. {_prev_date}  ·  {len(_alerts)} change{'s' if len(_alerts)>1 else ''} detected", expanded=True):
                for _lvl, _label, _pv, _cv, _msg in _alerts:
                    _bg, _bc = _color_map[_lvl]
                    st.markdown(
                        f'<div style="display:flex;align-items:center;gap:10px;padding:9px 14px;'
                        f'margin-bottom:5px;border-radius:7px;background:{_bg};border-left:4px solid {_bc};">'
                        f'<span style="font-size:16px;color:{_bc};font-weight:700;">{_icon_map[_lvl]}</span>'
                        f'<span style="font-size:13px;color:#374151;">{_msg}</span>'
                        f'</div>',
                        unsafe_allow_html=True,
                    )

    # ── Export button ─────────────────────────────────────────────────────
    def _build_report_html() -> str:
        _nu_val  = int(_totals.get("Notice-Unrented", 0))
        _ev_val  = int(_totals.get("Evict", 0))
        _notes_now = st.session_state.get("notes", [])
        _notes_html = "".join(
            f'<li style="margin-bottom:4px;"><b>{n.get("timestamp","")}</b> — {n["content"]}</li>'
            for n in _notes_now
        ) or "<li>No notes added.</li>"
        return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<title>{COMPANY} — All Hands {_ah_date}</title>
<style>
  *{{box-sizing:border-box;margin:0;padding:0;}}
  body{{font-family:'Segoe UI',Arial,sans-serif;font-size:13px;color:#0F172A;background:#fff;padding:32px 40px;}}
  h1{{font-size:22px;font-weight:800;color:#1B4FD8;margin-bottom:4px;}}
  .sub{{color:#64748B;font-size:12px;margin-bottom:28px;}}
  h2{{font-size:12px;font-weight:800;text-transform:uppercase;letter-spacing:.12em;color:#64748B;
      border-bottom:1px solid #E2E8F0;padding-bottom:6px;margin:24px 0 12px 0;}}
  .grid{{display:grid;grid-template-columns:repeat(4,1fr);gap:12px;margin-bottom:16px;}}
  .card{{background:#F8FAFC;border:1px solid #E2E8F0;border-radius:8px;padding:14px 16px;}}
  .card-label{{font-size:10px;font-weight:700;color:#64748B;text-transform:uppercase;letter-spacing:.08em;}}
  .card-val{{font-size:26px;font-weight:900;color:#0F172A;margin:4px 0 2px 0;}}
  .card-sub{{font-size:11px;color:#94A3B8;}}
  ul{{padding-left:18px;color:#374151;}}
  li{{margin-bottom:3px;font-size:12px;}}
  @media print{{body{{padding:16px 20px;}}@page{{margin:1cm;}}}}
</style>
</head>
<body>
<h1>{COMPANY}</h1>
<div class="sub">All Hands Meeting Snapshot &nbsp;·&nbsp; {_ah_date}</div>

<h2>Occupancy</h2>
<div class="grid">
  <div class="card"><div class="card-label">Total Units</div><div class="card-val">{_tu:,}</div></div>
  <div class="card"><div class="card-label">Physical Occ</div><div class="card-val">{_phys_occ:.1f}%</div><div class="card-sub">Target {THR['physical_occ']}%</div></div>
  <div class="card"><div class="card-label">Economic Occ</div><div class="card-val">{_econ_occ:.1f}%</div></div>
  <div class="card"><div class="card-label">Collection Rate</div><div class="card-val">{_pct_coll:.1f}%</div><div class="card-sub">Target {THR['collection_rate']}%</div></div>
</div>

<h2>Vacancy</h2>
<div class="grid">
  <div class="card"><div class="card-label">Total Vacancies</div><div class="card-val">{_vu+_vr+_nu_val:,}</div><div class="card-sub">{_vu} unrented · {_vr} rented · {_nu_val} on notice</div></div>
  <div class="card"><div class="card-label">Vacant Unrented</div><div class="card-val">{_vu:,}</div></div>
  <div class="card"><div class="card-label">In Eviction</div><div class="card-val">{_ev_val:,}</div></div>
  <div class="card"><div class="card-label">Potential Monthly Revenue Loss</div><div class="card-val">${_rgap:,.0f}</div></div>
</div>

<h2>Leasing</h2>
<div class="grid">
  <div class="card"><div class="card-label">Renewal Rate</div><div class="card-val">{_rr_pct:.1f}%</div><div class="card-sub">Target {THR['renewal_rate']}%</div></div>
  <div class="card"><div class="card-label">Leases Signed</div><div class="card-val">{_leased:,}</div></div>
  <div class="card"><div class="card-label">Inquiries</div><div class="card-val">{_inq:,}</div></div>
  <div class="card"><div class="card-label">Showings</div><div class="card-val">{_shows:,}</div></div>
</div>

<h2>Work Orders ({_wo_month_label})</h2>
<div class="grid">
  <div class="card"><div class="card-label">Total</div><div class="card-val">{_wo_total:,}</div></div>
  <div class="card"><div class="card-label">Completed</div><div class="card-val">{_wo_completed:,}</div><div class="card-sub">{_wo_comp_pct:.0f}% completion</div></div>
  <div class="card"><div class="card-label">Open / In Progress</div><div class="card-val">{_wo_open:,}</div></div>
</div>

<h2>Notes</h2>
<ul>{_notes_html}</ul>

<div style="margin-top:32px;font-size:10px;color:#94A3B8;border-top:1px solid #E2E8F0;padding-top:10px;">
Generated {_ah_date} · {COMPANY} Executive Dashboard
</div>
</body>
</html>"""

    def _build_report_pdf() -> bytes:
        import sys
        import asyncio
        import tempfile
        from pathlib import Path

        if sys.platform.startswith("win"):
            asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())

        from playwright.sync_api import sync_playwright

        html = _build_report_html()

        with tempfile.NamedTemporaryFile(delete=False, suffix=".html", mode="w", encoding="utf-8") as f:
            f.write(html)
            html_path = f.name

        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            page = browser.new_page()
            page.goto(Path(html_path).as_uri(), wait_until="load")

            pdf_bytes = page.pdf(
                format="Letter",
                print_background=True,
                margin={
                    "top": "0.4in",
                    "right": "0.4in",
                    "bottom": "0.4in",
                    "left": "0.4in",
                },
            )

            browser.close()

        return pdf_bytes

    with _ah_col_btn:
        st.markdown("<br>", unsafe_allow_html=True)
        _report_html = _build_report_html()
        b1, b2 = st.columns(2)

        with b1:
            st.download_button(
                "🌐 HTML",
                data=_report_html,
                file_name=f"all_hands_{datetime.now().strftime('%Y-%m-%d')}.html",
                mime="text/html",
                use_container_width=True,
            )

        with b2:
            try:
                _report_pdf = _build_report_pdf()

                st.download_button(
                    "📄 PDF",
                    data=_report_pdf,
                    file_name=f"all_hands_{datetime.now().strftime('%Y-%m-%d')}.pdf",
                    mime="application/pdf",
                    use_container_width=True,
                )

            except Exception as e:
                st.error("PDF Error")

    # ── Portfolio Banner ───────────────────────────────────────────────────
    st.markdown(
        '<div style="background:linear-gradient(135deg,#1B4FD8 0%,#1e40af 100%);'
        'padding:20px 28px;border-radius:12px;margin-bottom:18px;'
        'display:flex;justify-content:space-between;align-items:center;">'
        '<div>'
        '<p style="color:#DBEAFE;font-size:11px;font-weight:700;letter-spacing:1.8px;margin:0 0 4px 0;">PORTFOLIO SNAPSHOT</p>'
        f'<p style="color:#fff;font-size:30px;font-weight:800;margin:0;line-height:1.1;">{_tu:,} Units Managed</p>'
        f'<p style="color:#93C5FD;font-size:13px;margin:5px 0 0 0;">'
        f'Physical Occ: <strong style="color:#fff;">{_phys_occ:.1f}%</strong> &nbsp;&nbsp;'
        f'Economic Occ: <strong style="color:#fff;">{_econ_occ:.1f}%</strong>'
        f'</p></div>'
        f'<div style="text-align:right;">'
        f'<p style="color:#DBEAFE;font-size:11px;font-weight:700;letter-spacing:1.8px;margin:0 0 4px 0;">MONTHLY RENT ROLL</p>'
        f'<p style="color:#fff;font-size:30px;font-weight:800;margin:0;line-height:1.1;">${_sum_rent:,.0f}</p>'
        f'<p style="color:#93C5FD;font-size:13px;margin:5px 0 0 0;">'
        f'Collection Rate: <strong style="color:#fff;">{_pct_coll:.1f}%</strong>'
        f'</p></div>'
        '</div>',
        unsafe_allow_html=True,
    )

    # ── 5 KPI cards ───────────────────────────────────────────────────────
    a1, a2 = st.columns(2)
    _vac_total = _vu + _vr + _nu
    with a1: st.markdown(kpi("Total Vacancies", f"{_vac_total:,}",
                              status="bad" if _vu > 15 else "warn" if _vu > 8 else "good",
                              sub=f"{_vu} unrented · {_vr} rented · {_nu} on notice"), unsafe_allow_html=True)
    with a2: st.markdown(kpi("Collection Rate", f"{_pct_coll:.1f}%",
                              status=_tl(_pct_coll, THR["collection_rate"]),
                              sub=f"Target {THR['collection_rate']}%"), unsafe_allow_html=True)

    # ── Row A: Gauges + Portfolio Composition ─────────────────────────────
    g1, g2, g3 = st.columns([1, 1, 2])

    def _gauge_fig(value, title, lo, hi, target, suffix="%"):
        mid = lo + (target - lo) * 0.6

        fig = go.Figure(go.Indicator(
            mode="gauge+number",
            value=value,
            number={"suffix": suffix, "font": {"size": 36, "color": "#1E293B"}},
            title={"text": title, "font": {"size": 12, "color": "#6B7280"}},
            gauge={
                "axis": {
                    "range": [lo, hi],
                    "ticksuffix": suffix,
                    "tickfont": {"size": 10},
                    "nticks": 4
                },
                "bar": {"color": "#1B4FD8", "thickness": 0.28},
                "bgcolor": "white",
                "borderwidth": 0,
                "steps": [
                    {"range": [lo, mid], "color": "#FEE2E2"},
                    {"range": [mid, target], "color": "#FEF3C7"},
                    {"range": [target, hi], "color": "#D1FAE5"},
                ],
                "threshold": {
                    "line": {"color": "#059669", "width": 8},
                    "thickness": 0.9,
                    "value": target,
                },
            },
        ))

        fig.update_layout(
            height=280,
            paper_bgcolor="#FFFFFF",
            margin=dict(l=20, r=20, t=40, b=10),
        )

        return fig

    with g1:
        st.plotly_chart(
            _gauge_fig(_phys_occ, "Physical Occupancy", 85, 100, THR["physical_occ"]),
            width="stretch",
        )
    with g2:
        st.plotly_chart(
            _gauge_fig(_pct_coll, "Collection Rate", 80, 100, THR["collection_rate"]),
            width="stretch",
        )
    with g3:
        # Portfolio composition donut
        _comp = [(l, v, c) for l, v, c in [
            ("Current",          _curr, "#1E40AF"),
            ("Vacant · Unrented", _vu,   "#991B1B"),
            ("Vacant · Rented",   _vr,   "#1D4ED8"),
            ("Notice · Unrented", _nu,   "#B45309"),
            ("Notice · Rented",   _nr,   "#065F46"),
            ("In Eviction",       _ev,   "#7F1D1D"),
        ] if v > 0]
        if _comp:
            _cl, _cv, _cc = zip(*_comp)
            fig_comp = go.Figure(go.Pie(
                labels=list(_cl), values=list(_cv),
                hole=0.62,
                marker=dict(colors=list(_cc), line=dict(color="#FFFFFF", width=2)),
                textinfo="percent",
                textfont=dict(size=10, color="#FFFFFF"),
                hovertemplate="<b>%{label}</b><br>%{value} units · %{percent}<extra></extra>",
            ))
            fig_comp.add_annotation(
                text=f"<b>{_tu:,}</b><br><span style='font-size:9px;color:#6B7280'>total</span>",
                x=0.5, y=0.5, showarrow=False,
                font=dict(size=17, color="#1E293B"), align="center",
            )
            fig_comp.update_layout(
                title=dict(text="Portfolio Composition", font=dict(size=13, color="#6B7280"), x=0.5),
                height=280, showlegend=True,
                legend=dict(orientation="v", x=1.01, y=0.5, font=dict(size=11),
                            bgcolor="rgba(0,0,0,0)"),
                paper_bgcolor="#FFFFFF",
                margin=dict(l=0, r=100, t=40, b=10),
            )
            st.plotly_chart(fig_comp, width="stretch")


    # ── Row B: Leasing activity KPIs | Vacancy pipeline | This month ─────
    _month_lbl  = _ah_now.strftime('%B %Y')
    _mtd_label = f"{_ah_now.strftime('%b')} 1–{_ah_now.day}"  # e.g. "May 1–7"
    col_f, col_p, col_w = st.columns(3)

    # Monthly move-ins from tickler (the only source with exact event dates)
    _move_ins_monthly = 0
    if df_tickler_f is not None and "Date" in df_tickler_f.columns and "Event" in df_tickler_f.columns:
        _tkt_dates = pd.to_datetime(df_tickler_f["Date"], errors="coerce")
        _move_ins_monthly = int((
            (df_tickler_f["Event"].str.strip() == "Move-in") &
            (_tkt_dates.dt.year == _ah_year) &
            (_tkt_dates.dt.month == _ah_month)
        ).sum())

    with col_f:
        section(f"Leasing Activity · {_month_lbl}  ·  {_mtd_label}")
        for _lbl, _val, _color, _bg in [
            ("Showings Completed",    _shows,      "#2563EB", "#EFF6FF"),
            ("Applications Received", _apps_count, "#7C3AED", "#F5F3FF"),
            ("Leases Signed",         _leased,     "#059669", "#F0FDF4"),
            ("Move-ins",              _move_ins_monthly, "#0D9488", "#F0FDFA"),
        ]:
            st.markdown(
                f'<div style="display:flex;justify-content:space-between;align-items:center;'
                f'padding:10px 14px;margin-bottom:7px;border-radius:8px;background:{_bg};'
                f'border-left:4px solid {_color};">'
                f'<span style="font-size:13px;color:#374151;font-weight:500;">{_lbl}</span>'
                f'<span style="font-size:22px;font-weight:800;color:{_color};">{_val:,}</span>'
                f'</div>',
                unsafe_allow_html=True,
            )

    with col_p:
        section("Vacancy Pipeline")
        for label, val, color in [
            ("Vacant · Unrented",  _vu,  "#991B1B"),
            ("Notice · Unrented",  _nu,  "#B45309"),
            ("In Eviction",        _ev,  "#7F1D1D"),
            ("Expiring (30 days)", exp30, "#D97706"),
            ("Expiring (60 days)", exp60, "#F59E0B"),
        ]:
            st.markdown(
                f'<div style="display:flex;justify-content:space-between;align-items:center;'
                f'padding:9px 14px;margin-bottom:5px;border-radius:7px;background:#F8FAFC;'
                f'border-left:4px solid {color};">'
                f'<span style="font-size:13px;color:#374151;font-weight:500;">{label}</span>'
                f'<span style="font-size:20px;font-weight:800;color:{color};">{val}</span>'
                f'</div>',
                unsafe_allow_html=True,
            )

    with col_w:
        section(f"This Month · {_month_lbl}  ·  {_mtd_label}")
        _week = [
            (f"Leases Signed",         _leased,           "#059669"),
            (f"Move-ins",              _move_ins_monthly, "#0D9488"),
            (f"Showings Completed",    _shows,            "#2563EB"),
            (f"Applications Received", _apps_count,       "#2563EB"),
        ]
        if df_calls is not None and len(df_calls) > 0:
            _inb_s  = df_calls[df_calls["Total Calls"] > 0]["Inbound"].sum()
            _vmb_s  = df_calls[df_calls["Total Calls"] > 0]["Missed with VM"].sum()
            _mbp    = round(_vmb_s / _inb_s * 100, 1) if _inb_s > 0 else 0
            _calls_period = ""
            if calls_meta and calls_meta.get("start") and calls_meta.get("end"):
                _cs = calls_meta["start"]
                _ce = calls_meta["end"]
                _calls_period = f"{_cs.strftime('%b')} {_cs.day}–{_ce.day}" if _cs.month == _ce.month else f"{_cs.strftime('%b')} {_cs.day}–{_ce.strftime('%b')} {_ce.day}"
            _week  += [
                (f"Calls handled{_calls_period}", int(df_calls["Total Calls"].sum()), "#1B4FD8"),
                ("Missed call rate",              f"{_mbp}%", "#DC2626" if _mbp > 5 else "#059669"),
            ]
        for label, val, color in _week:
            st.markdown(
                f'<div style="display:flex;justify-content:space-between;align-items:center;'
                f'padding:9px 14px;margin-bottom:5px;border-radius:7px;background:#F8FAFC;">'
                f'<span style="font-size:13px;color:#374151;">{label}</span>'
                f'<span style="font-size:20px;font-weight:800;color:{color};">'
                f'{val if isinstance(val, str) else f"{val:,}"}</span>'
                f'</div>',
                unsafe_allow_html=True,
            )

    # ── Row C+D: Past Due (top 5) | Work Orders ──────────────────────────
    _col_pd, _col_wo = st.columns([3, 2])

    with _col_pd:
        if df_rr_f is not None and "Property" in df_rr_f.columns:
            _rr_curr = df_rr_f[df_rr_f["Status"] == "Current"].copy()
            _rr_curr["_rent"] = clean_money_column(_rr_curr["Rent"]) if "Rent" in _rr_curr.columns else 0.0
            _rr_curr["_pd"]   = clean_money_column(_rr_curr["Past Due"]) if "Past Due" in _rr_curr.columns else 0.0
            _prop_c2 = (
                _rr_curr.groupby("Property")
                .agg(billed=("_rent", "sum"), past_due=("_pd", "sum"))
                .reset_index()
            )
            _prop_c2 = _prop_c2[(_prop_c2["billed"] > 0) & (_prop_c2["past_due"] > 0)]
            _prop_c2 = _prop_c2.nlargest(15, "past_due").sort_values("past_due", ascending=True)

            if len(_prop_c2):
                _prop_c2["pct"] = ((_prop_c2["billed"] - _prop_c2["past_due"]) / _prop_c2["billed"] * 100).clip(0, 100)
                section("Top 15 Past Due · Current Tenants")

                def _ccol2(p):
                    if p < 85:   return "#991B1B"
                    elif p < 95: return "#C2410C"
                    elif p < 99: return "#CA8A04"
                    else:        return "#15803D"

                # Identify Jennifer Damian (Unit 207 – Zelzah): stacked purple segment
                _jd_props_coll: set = set()
                _jd_pd_by_prop_coll: dict = {}
                if "Unit" in _rr_curr.columns:
                    _jd_mask_coll = (
                        (_rr_curr["Unit"].astype(str).str.strip() == "207") &
                        _rr_curr["Property"].str.lower().str.contains("zelzah", na=False)
                    )
                    _jd_props_coll = set(_rr_curr.loc[_jd_mask_coll, "Property"].unique())
                    _jd_pd_by_prop_coll = _rr_curr[_jd_mask_coll].groupby("Property")["_pd"].sum().to_dict()

                _prop_c2["_jd_pd"]     = _prop_c2["Property"].map(lambda p: _jd_pd_by_prop_coll.get(p, 0.0))
                _prop_c2["_normal_pd"] = _prop_c2["past_due"] - _prop_c2["_jd_pd"]
                _has_jd_coll = (_prop_c2["_jd_pd"] > 0).any()

                fig_coll = go.Figure()
                fig_coll.add_trace(go.Bar(
                    x=_prop_c2["_normal_pd"], y=_prop_c2["Property"],
                    orientation="h",
                    marker_color=[_ccol2(p) for p in _prop_c2["pct"]],
                    marker_line_width=0,
                    name="Past Due",
                    text=_prop_c2.apply(
                        lambda r: f"  ${r['past_due']:,.0f}  ({r['pct']:.1f}%)" if r["_jd_pd"] == 0 else "",
                        axis=1,
                    ),
                    textposition="outside",
                    textfont=dict(size=10),
                    hovertemplate="<b>%{y}</b><br>Past Due: $%{x:,.0f}<extra></extra>",
                ))
                if _has_jd_coll:
                    fig_coll.add_trace(go.Bar(
                        x=_prop_c2["_jd_pd"], y=_prop_c2["Property"],
                        orientation="h",
                        marker_color="#7C3AED",
                        marker_line_width=0,
                        name="Unit 207 – Exceptional",
                        text=_prop_c2.apply(
                            lambda r: f"  ${r['past_due']:,.0f}  ({r['pct']:.1f}%) ★" if r["_jd_pd"] > 0 else "",
                            axis=1,
                        ),
                        textposition="outside",
                        textfont=dict(size=10),
                        hovertemplate="<b>%{y}</b><br>Unit 207 (Exceptional): $%{x:,.0f}<extra></extra>",
                    ))
                fig_coll.update_layout(
                    barmode="stack",
                    template="dfm",
                    height=max(260, len(_prop_c2) * 26 + 60),
                    xaxis=dict(tickprefix="$", tickformat=",.0f", gridcolor="#F1F5F9"),
                    yaxis=dict(tickfont=dict(size=10)),
                    paper_bgcolor="#FFFFFF", plot_bgcolor="#FFFFFF",
                    margin=dict(l=0, r=170, t=10, b=10),
                    showlegend=bool(_has_jd_coll),
                    legend=dict(orientation="h", y=-0.08, x=0, font=dict(size=9)),
                )
                st.plotly_chart(fig_coll, width="stretch")

    with _col_wo:
        if df_wo_f is not None and _wo_total > 0:
            section(f"Work Orders · {_wo_month_label}")
            wo1, wo2 = st.columns(2)
            with wo1: st.markdown(kpi("Total", f"{_wo_total:,}",
                                       sub=f"{_wo_comp_pct:.0f}% completed"), unsafe_allow_html=True)
            with wo2: st.markdown(kpi("Open / In Progress", f"{_wo_open:,}",
                                       status="bad" if _wo_open > 30 else "warn" if _wo_open > 15 else "good",
                                       sub="Needs resolution"), unsafe_allow_html=True)
            wo3, wo4 = st.columns(2)
            with wo3: st.markdown(kpi("Completed", f"{_wo_completed:,}",
                                       status="good" if _wo_comp_pct >= 70 else "warn" if _wo_comp_pct >= 50 else "bad",
                                       sub=f"{_wo_comp_pct:.0f}% rate"), unsafe_allow_html=True)
            with wo4:
                _wo_avg_res = 0.0
                if "Days to Resolve" in df_wo_f.columns:
                    _completed_wo = df_wo_f[df_wo_f["Status"].astype(str).str.lower().str.contains("completed", na=False)]
                    _res_v = _completed_wo["Days to Resolve"].dropna()
                    _wo_avg_res = float(_res_v.mean()) if len(_res_v) else 0.0
                st.markdown(kpi("Avg Resolve", f"{_wo_avg_res:.1f}d",
                                 status=_tl(_wo_avg_res, THR["wo_resolution_days"], "lower"),
                                 sub=f"Target ≤ {THR['wo_resolution_days']}d"), unsafe_allow_html=True)
            # Open WOs by property chart
            _wo_s = _df_wo_month["Status"].astype(str).str.lower()
            _open_wo_prop = _df_wo_month[_wo_s.isin(["open", "in progress", "new"])].copy()
            if len(_open_wo_prop) > 0 and "Property" in _open_wo_prop.columns:
                _owp = (
                    _open_wo_prop.groupby("Property").size()
                    .reset_index(name="n")
                    .nlargest(7, "n")
                    .sort_values("n", ascending=True)
                )
                fig_wo_p = go.Figure(go.Bar(
                    x=_owp["n"], y=_owp["Property"],
                    orientation="h",
                    marker_color="#F97316",
                    text=_owp["n"].astype(str),
                    textposition="outside",
                    textfont=dict(size=10),
                    hovertemplate="<b>%{y}</b><br>Open WOs: %{x}<extra></extra>",
                ))
                fig_wo_p.update_layout(
                    template="dfm",
                    height=max(160, len(_owp) * 28 + 40),
                    xaxis=dict(title="Open WOs", gridcolor="#F1F5F9"),
                    yaxis=dict(title="", tickfont=dict(size=9)),
                    paper_bgcolor="#FFFFFF", plot_bgcolor="#FFFFFF",
                    margin=dict(l=0, r=30, t=4, b=10),
                )
                st.plotly_chart(fig_wo_p, width="stretch")

    # ── Row E: Lease Expiration Risk ─────────────────────────────────────
    _exp_30d = exp30
    _exp_31_60d = max(0, exp60 - exp30)
    _exp_61_90d = max(0, exp90 - exp60)
    if _exp_30d + _exp_31_60d + _exp_61_90d > 0:
        section("Lease Expiration Risk — Next 90 Days")
        _le_kpi, _le_chart = st.columns([1, 2])
        with _le_kpi:
            for _lbl, _val, _col in [
                ("Expiring ≤ 30 days",  _exp_30d,   "#DC2626" if _exp_30d > 5  else "#D97706" if _exp_30d > 0  else "#059669"),
                ("Expiring 31–60 days", _exp_31_60d, "#D97706" if _exp_31_60d > 0 else "#059669"),
                ("Expiring 61–90 days", _exp_61_90d, "#6B7280"),
            ]:
                st.markdown(
                    f'<div style="display:flex;justify-content:space-between;align-items:center;'
                    f'padding:10px 14px;margin-bottom:6px;border-radius:7px;background:#F8FAFC;'
                    f'border-left:4px solid {_col};">'
                    f'<span style="font-size:13px;color:#374151;font-weight:500;">{_lbl}</span>'
                    f'<span style="font-size:22px;font-weight:800;color:{_col};">{_val}</span>'
                    f'</div>',
                    unsafe_allow_html=True,
                )
        with _le_chart:
            # Per-property expiration breakdown for the next 30 days
            if df_rr_f is not None and "Lease To" in df_rr_f.columns and _exp_30d > 0:
                _today_norm = pd.Timestamp.now().normalize()
                _act_lt = df_rr_f[df_rr_f["Status"].isin(["Current", "Notice-Unrented", "Notice-Rented"])].copy()
                _lt_ser = pd.to_datetime(_act_lt["Lease To"], errors="coerce")
                _act_lt["_days"] = (_lt_ser - _today_norm).dt.days
                _exp_soon = _act_lt[(_act_lt["_days"] >= 0) & (_act_lt["_days"] <= 30)]
                if len(_exp_soon) and "Property" in _exp_soon.columns:
                    _ep = (_exp_soon.groupby("Property").size()
                           .reset_index(name="expiring")
                           .nlargest(6, "expiring")
                           .sort_values("expiring", ascending=True))
                    fig_exp = go.Figure(go.Bar(
                        x=_ep["expiring"], y=_ep["Property"],
                        orientation="h",
                        marker_color="#DC2626",
                        text=_ep["expiring"].astype(str),
                        textposition="outside",
                        textfont=dict(size=10),
                        hovertemplate="<b>%{y}</b><br>Expiring in 30d: %{x} leases<extra></extra>",
                    ))
                    fig_exp.update_layout(
                        template="dfm",
                        height=max(140, len(_ep) * 28 + 50),
                        xaxis=dict(title="Leases expiring ≤ 30d", gridcolor="#F1F5F9"),
                        yaxis=dict(title="", tickfont=dict(size=9)),
                        paper_bgcolor="#FFFFFF", plot_bgcolor="#FFFFFF",
                        margin=dict(l=0, r=30, t=4, b=10),
                    )
                    st.plotly_chart(fig_exp, width="stretch")
                else:
                    st.caption("No per-property breakdown available.")
            else:
                # Show bucket bar if no urgent expirations
                _exp_buckets = {"0–30d": _exp_30d, "31–60d": _exp_31_60d, "61–90d": _exp_61_90d}
                _eb = {k: v for k, v in _exp_buckets.items() if v > 0}
                if _eb:
                    fig_eb = go.Figure(go.Bar(
                        x=list(_eb.keys()), y=list(_eb.values()),
                        marker_color=["#DC2626", "#D97706", "#6B7280"][:len(_eb)],
                        text=[str(v) for v in _eb.values()],
                        textposition="outside",
                    ))
                    fig_eb.update_layout(
                        template="dfm", height=200,
                        xaxis=dict(title="Expiration window"),
                        yaxis=dict(title="Lease count", gridcolor="#F1F5F9"),
                        paper_bgcolor="#FFFFFF", plot_bgcolor="#FFFFFF",
                        margin=dict(l=0, r=30, t=4, b=10),
                    )
                    st.plotly_chart(fig_eb, width="stretch")

    # ── Row G: Wins & Attention ───────────────────────────────────────────
    section("Portfolio Status Summary")
    _wins  = []
    _watch = []

    if _phys_occ >= THR["physical_occ"]:
        _wins.append(f"Physical occupancy {_phys_occ:.1f}% — above {THR['physical_occ']}% target")
    else:
        _watch.append(f"Physical occupancy {_phys_occ:.1f}% below {THR['physical_occ']}% target")

    if _pct_coll >= THR["collection_rate"]:
        _wins.append(f"Collection rate {_pct_coll:.1f}% — on track")
    else:
        _watch.append(f"Collection rate {_pct_coll:.1f}% below {THR['collection_rate']}% target")

    if _leased > 0:
        _wins.append(f"{_leased} new lease{'s' if _leased > 1 else ''} signed this period")
    if _wo_comp_pct >= 70 and _wo_total > 0:
        _wins.append(f"Work order completion rate {_wo_comp_pct:.0f}% — {_wo_completed} of {_wo_total} resolved")
    elif _wo_total > 0:
        _watch.append(f"Work order completion {_wo_comp_pct:.0f}% — {_wo_open} still open")

    if _vu == 0:
        _wins.append("Zero vacant & unrented units")
    elif _vu <= 10:
        _watch.append(f"{_vu} vacant & unrented — ${_rgap:,.0f} revenue at risk")
    else:
        _watch.append(f"{_vu} vacant & unrented — urgent, ${_rgap:,.0f} at risk")

    if _ev > 0:
        _watch.append(f"{_ev} unit{'s' if _ev > 1 else ''} in eviction process")
    if exp30 > 0:
        _watch.append(f"{exp30} lease{'s' if exp30 > 1 else ''} expiring in 30 days — start outreach")

    gcol, wcol = st.columns(2)
    with gcol:
        st.markdown('<p style="font-size:12px;font-weight:700;color:#059669;letter-spacing:0.08em;margin-bottom:8px;">GOING WELL</p>', unsafe_allow_html=True)
        for w in (_wins or ["No items to highlight"]):
            _is_real = w != "No items to highlight"
            st.markdown(
                f'<div style="padding:9px 14px;margin-bottom:6px;border-radius:7px;'
                f'background:{"#F0FDF4" if _is_real else "#F9FAFB"};'
                f'border-left:3px solid {"#059669" if _is_real else "#E5E7EB"};">'
                f'<span style="font-size:13px;color:{"#166534" if _is_real else "#9CA3AF"};">'
                f'{"✓ " if _is_real else ""}{w}</span></div>',
                unsafe_allow_html=True,
            )
    with wcol:
        st.markdown('<p style="font-size:12px;font-weight:700;color:#D97706;letter-spacing:0.08em;margin-bottom:8px;">NEEDS ATTENTION</p>', unsafe_allow_html=True)
        for w in (_watch or ["No items flagged"]):
            _is_real = w != "No items flagged"
            _c  = "#DC2626" if _is_real and ("urgent" in w or "eviction" in w or "below" in w) else "#D97706" if _is_real else "#E5E7EB"
            _bg = "#FEF2F2" if _c == "#DC2626" else "#FFFBEB" if _c == "#D97706" else "#F9FAFB"
            st.markdown(
                f'<div style="padding:9px 14px;margin-bottom:6px;border-radius:7px;'
                f'background:{_bg};border-left:3px solid {_c};">'
                f'<span style="font-size:13px;color:{"#374151" if _is_real else "#9CA3AF"};">'
                f'{"⚠ " if _is_real else ""}{w}</span></div>',
                unsafe_allow_html=True,
            )

    # ── Row H: Phone Team — Calls ────────────────────────────────────────
    if df_calls is not None and len(df_calls) > 0:
        section("Phone Team Performance")
        # Filter to phone team members only (same list used in Calls tab)
        def _ah_is_phone_team(name: str) -> bool:
            n = str(name).strip().lower()
            return any(pt.lower() in n for pt in PHONE_TEAM)

        _df_phone = df_calls[
            (df_calls["Total Calls"] > 0) &
            df_calls["Name"].apply(_ah_is_phone_team)
        ].copy() if "Total Calls" in df_calls.columns and "Name" in df_calls.columns else df_calls.copy()

        _tc_total = int(_df_phone["Total Calls"].sum()) if "Total Calls" in _df_phone.columns else 0
        _tc_in    = int(_df_phone["Inbound"].sum())     if "Inbound"     in _df_phone.columns else 0
        _tc_out   = int(_df_phone["Outbound"].sum())    if "Outbound"    in _df_phone.columns else 0
        _tc_miss  = int(_df_phone["Missed with VM"].sum()) if "Missed with VM" in _df_phone.columns else 0
        _tc_miss_pct = round(_tc_miss / _tc_in * 100, 1) if _tc_in > 0 else 0.0

        _calls_period_lbl = ""
        if calls_meta and calls_meta.get("start") and calls_meta.get("end"):
            _cs = calls_meta["start"]
            _ce = calls_meta["end"]

            if _cs.month == _ce.month:
                _calls_period_lbl = f" · {_cs.strftime('%b')} {_cs.day}–{_ce.day}, {_ce.year}"
            else:
                _calls_period_lbl = f" · {_cs.strftime('%b')} {_cs.day}, {_cs.year}–{_ce.strftime('%b')} {_ce.day}, {_ce.year}"

        _cc1, _cc2, _cc3, _cc4 = st.columns(4)
        with _cc1:
            st.markdown(kpi("Total Calls" + _calls_period_lbl, f"{_tc_total:,}", sub="Phone team combined"), unsafe_allow_html=True)
        with _cc2:
            st.markdown(kpi("Inbound", f"{_tc_in:,}", sub=f"{round(_tc_in/_tc_total*100) if _tc_total else 0}% of total"), unsafe_allow_html=True)
        with _cc3:
            st.markdown(kpi("Outbound", f"{_tc_out:,}", sub=f"{round(_tc_out/_tc_total*100) if _tc_total else 0}% of total"), unsafe_allow_html=True)
        with _cc4:
            st.markdown(kpi(
                "Missed / VM",
                f"{_tc_miss_pct:.1f}%",
                status="bad" if _tc_miss_pct > 10 else "warn" if _tc_miss_pct > 5 else "good",
                sub=f"{_tc_miss:,} calls missed with voicemail"
            ), unsafe_allow_html=True)

        # Per-agent breakdown chart (phone team only, sorted by total)
        _calls_chart_df = _df_phone.copy()
        if len(_calls_chart_df) and "Name" in _calls_chart_df.columns:
            _calls_chart_df = _calls_chart_df.sort_values("Total Calls", ascending=True)
            _ca_fig = go.Figure()
            if "Inbound" in _calls_chart_df.columns:
                _ca_fig.add_trace(go.Bar(
                    y=_calls_chart_df["Name"], x=_calls_chart_df["Inbound"],
                    orientation="h", name="Inbound",
                    marker_color="#2563EB",
                    hovertemplate="<b>%{y}</b><br>Inbound: %{x:,}<extra></extra>",
                ))
            if "Outbound" in _calls_chart_df.columns:
                _ca_fig.add_trace(go.Bar(
                    y=_calls_chart_df["Name"], x=_calls_chart_df["Outbound"],
                    orientation="h", name="Outbound",
                    marker_color="#059669",
                    hovertemplate="<b>%{y}</b><br>Outbound: %{x:,}<extra></extra>",
                ))
            if "Missed with VM" in _calls_chart_df.columns:
                _ca_fig.add_trace(go.Bar(
                    y=_calls_chart_df["Name"], x=_calls_chart_df["Missed with VM"],
                    orientation="h", name="Missed / VM",
                    marker_color="#DC2626",
                    hovertemplate="<b>%{y}</b><br>Missed w/ VM: %{x:,}<extra></extra>",
                ))
            _ca_fig.update_layout(
                barmode="stack",
                template="dfm",
                height=max(260, len(_calls_chart_df) * 28 + 60),
                xaxis=dict(title="Calls", gridcolor="#F1F5F9"),
                yaxis=dict(title="", tickfont=dict(size=10)),
                paper_bgcolor="#FFFFFF", plot_bgcolor="#FFFFFF",
                legend=dict(orientation="h", y=-0.12),
                margin=dict(l=0, r=20, t=10, b=40),
            )
            st.plotly_chart(_ca_fig, width="stretch")

    # ── Row E: Occupancy trend ────────────────────────────────────────────
    if df_hist is not None and len(df_hist) >= 15:   
        section("Occupancy Trend — Last 6 Months")
        fig_ah = go.Figure()

        df_hist = df_hist.copy()

    # Normalizar columnas por si viene de _historical() o load_historical_metrics()
        df_hist = df_hist.rename(columns={
            "date": "Date",
            "physical_occupancy": "Physical Occupancy",
            "economic_occupancy": "Economic Occupancy",
        })

        df_hist["snapshot_date"] = pd.to_datetime(df_hist["Date"], errors="coerce")
        df_hist = df_hist.dropna(subset=["snapshot_date"])

        fig_ah.add_trace(go.Scatter(
            x=df_hist["snapshot_date"],
            y=pd.to_numeric(df_hist["Physical Occupancy"], errors="coerce"),
            name="Physical Occ %",
            line=dict(color=PC, width=3),
            mode="lines+markers",
            marker=dict(size=7),
            fill="tozeroy",
            fillcolor="rgba(27,79,216,0.07)",
        ))

        fig_ah.add_trace(go.Scatter(
            x=df_hist["snapshot_date"],
            y=pd.to_numeric(df_hist["Economic Occupancy"], errors="coerce"),
            name="Economic Occ %",
            line=dict(color="#059669", width=3),
            mode="lines+markers",
            marker=dict(size=7),
        ))

        fig_ah.add_hline(
            y=THR["physical_occ"],
            line_dash="dot",
            line_color="#DC2626",
            annotation_text=f"{THR['physical_occ']}% target",
            annotation_font=dict(size=10),
        )

        fig_ah.update_layout(
            template="dfm",
            height=260,
            yaxis=dict(
                title="Occupancy %",
                ticksuffix="%",
                range=[85, 100],
                gridcolor="#F1F5F9"
            ),
            xaxis=dict(gridcolor="#F1F5F9"),
            paper_bgcolor="#FFFFFF",
            plot_bgcolor="#FFFFFF",
            legend=dict(orientation="h", y=-0.25),
            margin=dict(l=0, r=0, t=10, b=40),
        )

        st.plotly_chart(fig_ah, width="stretch")


# ============================================================================
# PAGE 1 — OVERVIEW
# ============================================================================

if st.session_state.page == "Overview":
    page_header(COMPANY, f"Executive Dashboard  ·  {datetime.now().strftime('%B %d, %Y')}")

    if df_metrics_f is None or totals is None:
        st.warning("No rent roll data found. Verify CSV files are in the configured folder.")
        st.stop()

    total_units    = int(_totals.get("Total Units", 0))
    vacant_units   = int(_totals.get("Vacant-Unrented", 0))
    evict_units    = int(_totals.get("Evict", 0))
    notice_unr     = int(_totals.get("Notice-Unrented", 0))
    notice_ren     = int(_totals.get("Notice-Rented", 0))
    revenue_gap    = float(df_metrics_f["Revenue Gap ($)"].sum()) if "Revenue Gap ($)" in df_metrics_f.columns else 0

    # Sum of rent + % collected (Current tenants only)
    sum_rent = pct_collected = 0.0
    if df_rr_f is not None and "Rent" in df_rr_f.columns:
        df_curr = df_rr_f[df_rr_f["Status"] == "Current"]
        sum_rent = float(df_curr["Rent"].sum())
        if "Past Due" in df_curr.columns:
            pd_sum = clean_money_column(df_curr["Past Due"]).clip(lower=0).sum()  # credits = fully collected
            if sum_rent > 0:
                pct_collected = max(0, min(100, (sum_rent - pd_sum) / sum_rent * 100))

    if sum_rent > 0:
        pct_collected = max(0, min(100, (sum_rent - pd_sum) / sum_rent * 100))

    # Renewal rate
    renewal_rate = 0.0
    if df_renew_f is not None and "Status" in df_renew_f.columns:
        actionable = df_renew_f[df_renew_f["Status"].isin(["Renewed", "Did Not Renew", "Canceled by User"])]
        if len(actionable):
            renewal_rate = len(actionable[actionable["Status"] == "Renewed"]) / len(actionable) * 100

   
    # Historical deltas — only meaningful when no portfolio filter is active,
    # because df_hist stores all-portfolio numbers and _phys_occ/_econ_occ would
    # be portfolio-specific, making the delta apples-to-oranges.
    delta_phys = delta_econ = None
    _prev_date_label = "prior snapshot"

    delta_phys = delta_econ = None
    _prev_date_label = "prior snapshot"

    if df_hist is not None and len(df_hist) >= 2 and not SEL:
        prev = df_hist.iloc[-2]

        try:
            prev_phys = pd.to_numeric(prev.get("physical_occupancy", None), errors="coerce")
            prev_econ = pd.to_numeric(prev.get("economic_occupancy", None), errors="coerce")
            _prev_dt = pd.to_datetime(prev.get("date", None), errors="coerce")

            if pd.notna(prev_phys):
                delta_phys = _phys_occ - float(prev_phys)

            if pd.notna(prev_econ):
                delta_econ = _econ_occ - float(prev_econ)

            if pd.notna(_prev_dt):
                days_ago = (pd.Timestamp.now().normalize() - _prev_dt.normalize()).days

                if days_ago == 1:
                    _prev_date_label = "yesterday"
                elif days_ago == 0:
                    _prev_date_label = "earlier today"
                else:
                    _prev_date_label = f"{_prev_dt.month}/{_prev_dt.day}"

        except Exception as e:
            log.debug("historical delta calc: %s", e)

    # ── KPI Groups ────────────────────────────────────────────────────────
    def _grp(label, color):
        st.markdown(
            f'<div style="display:flex;align-items:center;gap:10px;font-size:10.5px;font-weight:800;'
            f'color:#64748B;text-transform:uppercase;letter-spacing:.14em;'
            f'padding:22px 0 10px 0;margin-bottom:14px;border-bottom:1px solid #E2E8F0;">'
            f'<span style="display:inline-block;width:3px;height:13px;background:{color};'
            f'border-radius:2px;flex-shrink:0;"></span>{label}</div>',
            unsafe_allow_html=True,
        )

    _grp("Occupancy", PC)
    c1, c2, c3 = st.columns(3)
    with c1: st.markdown(kpi("Total Units", f"{total_units:,}",
                              sub="Total managed units"), unsafe_allow_html=True)
    with c2: st.markdown(kpi("Physical Occupancy", f"{_phys_occ:.1f}%", delta_phys, "%",
                              _tl(_phys_occ, THR["physical_occ"]),
                              sub=f"Target {THR['physical_occ']}% · Vacant: {vacant_units}",
                              delta_label=_prev_date_label), unsafe_allow_html=True)
    with c3: st.markdown(kpi("Economic Occupancy", f"{_econ_occ:.1f}%", delta_econ, "%",
                              _tl(_econ_occ, THR["economic_occ"]),
                              sub=f"Target {THR['economic_occ']}% · Rent vs. market",
                              delta_label=_prev_date_label), unsafe_allow_html=True)

    _grp("Financials", "#059669")
    c4, c5, c6 = st.columns(3)
    with c4: st.markdown(kpi("Monthly Rent (Current)", f"${sum_rent:,.0f}",
                              sub="Sum of rent — Current tenants only"), unsafe_allow_html=True)
    with c5: st.markdown(kpi("% Collected", f"{pct_collected:.1f}%",
                              status=_tl(pct_collected, THR["collection_rate"]),
                              sub=f"Target {THR['collection_rate']}% · Rent roll basis"), unsafe_allow_html=True)
    with c6: st.markdown(kpi("Revenue Gap", f"${revenue_gap:,.0f}",
                              sub="Market rent at risk: Vacant-Unrented + Evict units"),
                         unsafe_allow_html=True)

    _grp("Leasing & Retention", "#D97706")
    c7, c8, c9, c10 = st.columns(4)
    with c7: st.markdown(kpi("Vacant (Unrented)", f"{vacant_units:,}",
                              sub=f"Unrented as of today  ·  {evict_units} in eviction"), unsafe_allow_html=True)
    with c8: st.markdown(kpi("On Notice", f"{notice_unr + notice_ren:,}",
                              sub=f"{notice_unr} leaving unrented · {notice_ren} already re-leased"),
                         unsafe_allow_html=True)
    with c9: st.markdown(kpi("Leases Expiring (30d)", f"{exp30:,}",
                              sub=f"{exp60} expiring in 60d · {exp90} in 90d"), unsafe_allow_html=True)
    with c10: st.markdown(kpi("Renewal Rate", f"{renewal_rate:.1f}%",
                               status=_tl(renewal_rate, THR["renewal_rate"]),
                               sub=f"Target {THR['renewal_rate']}% · Renewed vs. actionable"), unsafe_allow_html=True)

    # ── Upcoming Events ───────────────────────────────────────────────────
    if df_tickler_f is not None and len(df_tickler_f):
        section("Upcoming Events — Next 14 Days")
        window = df_tickler_f[
            (df_tickler_f["Date"] >= today_ts) &
            (df_tickler_f["Date"] <= today_ts + pd.Timedelta(14, "d"))
        ].copy().sort_values("Date")

        if len(window):
            EVENT_COLORS = {"Move-in": "🟢", "Move-out": "🔴", "Notice": "🟡"}
            window["📅 Date"] = window["Date"].dt.strftime("%b %d")
            window["Type"]    = window["Event"].map(lambda e: f"{EVENT_COLORS.get(e,'')} {e}")
            disp_cols = [c for c in ["📅 Date","Type","Property","Unit","Tenant","Rent"] if c in window.columns]
            st.dataframe(window[disp_cols], width="stretch", hide_index=True)
        else:
            st.info("No events in the next 14 days.")

    # ── Historical trends ─────────────────────────────────────────────────
    # ── Historical trends ─────────────────────────────────────────────────
    section("Historical Trends")

    df_hist = load_historical_metrics()
    df_ph = df_hist.copy()

    df_ph = df_ph.rename(columns={"date": "snapshot_date"})

    def trend_delta(df, col):
        if df is None or len(df) < 2 or col not in df.columns:
            return None

        vals = pd.to_numeric(df[col], errors="coerce").dropna()

        if len(vals) < 2:
            return None

        return vals.iloc[-1] - vals.iloc[-2]


    occ_delta  = trend_delta(df_ph, "physical_occupancy")
    econ_delta = trend_delta(df_ph, "economic_occupancy")
    coll_delta = trend_delta(df_ph, "collection_rate")

    if df_ph is None or df_ph.empty:
        st.info("Historical trend will accumulate with each data refresh.")
    else:
        df_ph = df_ph.copy()

    if "snapshot_date" not in df_ph.columns and "date" in df_ph.columns:
        df_ph = df_ph.rename(columns={"date": "snapshot_date"})

    df_ph["snapshot_date"] = pd.to_datetime(df_ph["snapshot_date"], errors="coerce")
    df_ph = df_ph.dropna(subset=["snapshot_date"])
    df_ph["snapshot_date"] = df_ph["snapshot_date"].dt.date
    df_ph = df_ph.drop_duplicates(subset=["snapshot_date"], keep="last")
    df_ph = df_ph.sort_values("snapshot_date")

    if df_ph["snapshot_date"].nunique() >= 15:
        for col in [
            "physical_occupancy",
            "economic_occupancy",
            "collection_rate",
            "vacant_units",
            "sum_of_rent",
        ]:
            if col in df_ph.columns:
                df_ph[col] = pd.to_numeric(df_ph[col], errors="coerce")

        _view = st.radio(
            "View",
            ["Occupancy", "Collection", "Vacancy / Rent"],
            horizontal=True,
            label_visibility="collapsed",
        )

        fig_ht = go.Figure()

        if _view == "Occupancy":
            fig_ht.add_trace(go.Scatter(
                x=df_ph["snapshot_date"],
                y=df_ph["physical_occupancy"],
                name="Physical Occupancy",
                mode="lines+markers",
                line=dict(color=PC, width=2.5),
            ))

            fig_ht.add_trace(go.Scatter(
                x=df_ph["snapshot_date"],
                y=df_ph["economic_occupancy"],
                name="Economic Occupancy",
                mode="lines+markers",
                line=dict(color="#059669", width=2.5),
            ))

            fig_ht.add_hline(
                y=THR["physical_occ"],
                line_dash="dot",
                line_color="#DC2626",
                annotation_text=f"Target {THR['physical_occ']}%",
                annotation_position="right",
            )

            fig_ht.update_layout(
                yaxis=dict(title="Occupancy %", ticksuffix="%", range=[80, 100]),
            )

        elif _view == "Collection":
            fig_ht.add_trace(go.Scatter(
                x=df_ph["snapshot_date"],
                y=df_ph["collection_rate"],
                name="Collection Rate",
                mode="lines+markers",
                line=dict(color="#059669", width=2.5),
            ))

            fig_ht.add_hline(
                y=THR["collection_rate"],
                line_dash="dot",
                line_color="#DC2626",
                annotation_text=f"Target {THR['collection_rate']}%",
                annotation_position="right",
            )

            fig_ht.update_layout(
                yaxis=dict(title="Collection Rate %", ticksuffix="%", range=[0, 100]),
            )

        else:
            fig_ht.add_trace(go.Bar(
                x=df_ph["snapshot_date"],
                y=df_ph["vacant_units"],
                name="Vacant Units",
                marker_color="#DC2626",
                opacity=0.75,
            ))

            fig_ht.add_trace(go.Scatter(
                x=df_ph["snapshot_date"],
                y=df_ph["sum_of_rent"],
                name="Sum of Rent",
                mode="lines+markers",
                line=dict(color="#D97706", width=2.5),
                yaxis="y2",
            ))

            fig_ht.update_layout(
                yaxis=dict(title="Vacant Units", rangemode="tozero"),
                yaxis2=dict(
                    title="Sum of Rent ($)",
                    overlaying="y",
                    side="right",
                    tickprefix="$",
                    showgrid=False,
                ),
            )

        fig_ht.update_layout(
            template="dfm",
            height=330,
            xaxis=dict(title="", gridcolor="#F1F5F9"),
            paper_bgcolor="#FFFFFF",
            plot_bgcolor="#FFFFFF",
            legend=dict(orientation="h", y=-0.25),
            margin=dict(l=0, r=80, t=10, b=50),
        )

        st.plotly_chart(fig_ht, use_container_width=True)

        

    # ── Top 5 Properties by Vacant Units ─────────────────────────────────
    section("Top 5 Properties by Vacant Units")

    df_metrics["Vacant-Unrented"] = pd.to_numeric(
        df_metrics["Vacant-Unrented"],
        errors="coerce"
    ).fillna(0)

    top5 = (df_metrics_f[["Property","Vacant-Unrented","Total Units","Physical Occ %","Revenue Gap ($)"]]
            .nlargest(5, "Vacant-Unrented").copy())
    top5.columns = ["Property","Vacant Units","Total Units","Physical Occ %","Revenue at Risk"]
    top5["Physical Occ %"]   = top5["Physical Occ %"].map(lambda x: f"{x:.1f}%")
    top5["Revenue at Risk"]  = top5["Revenue at Risk"].map(lambda x: f"${x:,.0f}")
    col_a, col_b = st.columns([3, 1])
    with col_a: st.dataframe(top5, width="stretch", hide_index=True)
    with col_b: download_btn(top5, "top5_vacant.csv")

    # ── Full Portfolio Box Score ──────────────────────────────────────────
    section("Full Portfolio Box Score")
    _box_want = ["Property", "Total Units", "Physical Occ %", "Economic Occ %",
                 "Current", "Vacant-Unrented", "Notice-Unrented", "Notice-Rented", "Evict",
                 "Revenue Gap ($)"]
    _box_cols = [c for c in _box_want if c in df_metrics_f.columns]
    df_box = df_metrics_f[_box_cols].copy().sort_values("Physical Occ %")
    df_box["Physical Occ %"]  = df_box["Physical Occ %"].map(lambda x: f"{x:.1f}%")
    df_box["Economic Occ %"]  = df_box["Economic Occ %"].map(lambda x: f"{x:.1f}%")
    if "Revenue Gap ($)" in df_box.columns:
        df_box["Revenue Gap ($)"] = df_box["Revenue Gap ($)"].map(lambda x: f"${x:,.0f}")
    df_box = df_box.rename(columns={
        "Vacant-Unrented":  "Vacant",
        "Notice-Unrented":  "Ntc-Unrntd",
        "Notice-Rented":    "Ntc-Rntd",
        "Revenue Gap ($)":  "Rev Gap",
    })
    c_box, c_dbox = st.columns([5, 1])
    with c_box:
        st.dataframe(df_box, width="stretch", hide_index=True, height=min(520, len(df_box) * 36 + 40))
    with c_dbox:
        download_btn(df_metrics_f[_box_cols], "portfolio_box_score.csv")

    # ── Property Benchmarks vs. Portfolio Average ─────────────────────────
    if "Physical Occ %" in df_metrics_f.columns and len(df_metrics_f) > 1:
        section("Property Benchmarks vs. Portfolio Average")
        _bm = df_metrics_f[["Property","Physical Occ %","Economic Occ %","Revenue Gap ($)","Total Units"]].copy()
        _avg_phys = _bm["Physical Occ %"].mean()
        _avg_econ = _bm["Economic Occ %"].mean()
        _bm["Phys vs Avg"] = (_bm["Physical Occ %"] - _avg_phys).round(2)
        _bm["Econ vs Avg"] = (_bm["Economic Occ %"] - _avg_econ).round(2)
        _bm["Rev Gap / Unit"] = (_bm["Revenue Gap ($)"] / _bm["Total Units"].replace(0, float("nan"))).round(0)
        _avg_rgpu = _bm["Rev Gap / Unit"].mean()
        _bm["Rev Gap vs Avg"] = (_bm["Rev Gap / Unit"] - _avg_rgpu).round(0)

        bm_l, bm_r = st.columns(2)
        with bm_l:
            _bm_occ = _bm.sort_values("Phys vs Avg")
            _bm_colors = ["#DC2626" if v < -2 else "#D97706" if v < 0 else "#059669" for v in _bm_occ["Phys vs Avg"]]
            fig_bm_occ = go.Figure(go.Bar(
                x=_bm_occ["Phys vs Avg"],
                y=_bm_occ["Property"],
                orientation="h",
                marker_color=_bm_colors,
                text=_bm_occ["Phys vs Avg"].map(lambda v: f"{v:+.1f}%"),
                textposition="outside",
            ))
            fig_bm_occ.add_vline(x=0, line_color="#374151", line_width=1.5)
            fig_bm_occ.update_layout(
                template="dfm", height=max(300, len(_bm_occ) * 28 + 60),
                title=dict(text=f"Physical Occ % vs Portfolio Avg ({_avg_phys:.1f}%)", font_size=12),
                xaxis=dict(title="pp vs average", ticksuffix="%", gridcolor="#F1F5F9", zeroline=False),
                yaxis=dict(title=""), paper_bgcolor="#FFFFFF", plot_bgcolor="#FFFFFF",
                margin=dict(l=0, r=70, t=40, b=20),
            )
            st.plotly_chart(fig_bm_occ, width="stretch")

        with bm_r:
            _bm_rgpu = _bm.dropna(subset=["Rev Gap vs Avg"]).sort_values("Rev Gap vs Avg", ascending=False)
            _rgpu_colors = ["#DC2626" if v > 200 else "#D97706" if v > 0 else "#059669" for v in _bm_rgpu["Rev Gap vs Avg"]]
            fig_bm_rg = go.Figure(go.Bar(
                x=_bm_rgpu["Rev Gap vs Avg"],
                y=_bm_rgpu["Property"],
                orientation="h",
                marker_color=_rgpu_colors,
                text=_bm_rgpu["Rev Gap vs Avg"].map(lambda v: f"${v:+,.0f}"),
                textposition="outside",
            ))
            fig_bm_rg.add_vline(x=0, line_color="#374151", line_width=1.5)
            fig_bm_rg.update_layout(
                template="dfm", height=max(300, len(_bm_rgpu) * 28 + 60),
                title=dict(text=f"Revenue Gap per Unit vs Avg (${_avg_rgpu:,.0f}/unit)", font_size=12),
                xaxis=dict(title="$ vs average/unit", tickprefix="$", gridcolor="#F1F5F9", zeroline=False),
                yaxis=dict(title=""), paper_bgcolor="#FFFFFF", plot_bgcolor="#FFFFFF",
                margin=dict(l=0, r=90, t=40, b=20),
            )
            st.plotly_chart(fig_bm_rg, width="stretch")


# ============================================================================
# PAGE 2 — VACANCY
# ============================================================================

elif st.session_state.page == "Vacancy":
    page_header("Vacancy", f"Data as of {datetime.now().strftime('%B %d, %Y')}")

    if df_vac_f is None:
        st.warning("unit_vacancy_detail.csv not found.")
        st.stop()

    # ── Filters ───────────────────────────────────────────────────────────
    filt_col1, filt_col2, filt_col3 = st.columns([3, 3, 2])
    with filt_col1:
        status_opts = ["All Statuses", "Vacant-Unrented", "Vacant-Rented", "Notice-Unrented"]
        status_filter = st.selectbox("Status", status_opts)
    with filt_col2:
        _prop_opts = ["All Properties"] + sorted(df_vac_f["Property"].dropna().unique().tolist()) if "Property" in df_vac_f.columns else ["All Properties"]
        prop_filter = st.selectbox("Property", _prop_opts)
    with filt_col3:
        st.markdown("<br>", unsafe_allow_html=True)
        rent_ready_only = st.toggle("Rent Ready Only", value=False)

    df_v = df_vac_f.copy()
    if rent_ready_only and "Rent Ready" in df_v.columns:
        df_v = df_v[df_v["Rent Ready"].astype(str).str.lower() == "yes"]
    if status_filter != "All Statuses" and "Unit Status" in df_v.columns:
        df_v = df_v[df_v["Unit Status"] == status_filter]
    if prop_filter != "All Properties" and "Property" in df_v.columns:
        df_v = df_v[df_v["Property"] == prop_filter]

    # ── KPIs — use rent roll as source of truth (matches Overview) ────────
    vu_total = int((df_rr_f["Status"] == "Vacant-Unrented").sum()) if df_rr_f is not None and "Status" in df_rr_f.columns else 0
    vr_total = int((df_rr_f["Status"] == "Vacant-Rented").sum())   if df_rr_f is not None and "Status" in df_rr_f.columns else 0
    nu_total = int((df_rr_f["Status"] == "Notice-Unrented").sum()) if df_rr_f is not None and "Status" in df_rr_f.columns else 0
    avg_days   = float(df_v["Days Vacant"].mean()) if len(df_v) else 0
    rev_lost   = float((df_v["Last Rent"] * df_v["Days Vacant"] / 30).sum()) if "Last Rent" in df_v.columns and "Days Vacant" in df_v.columns else 0
    rent_ready = int((df_vac_f["Rent Ready"].astype(str).str.lower() == "yes").sum()) if "Rent Ready" in df_vac_f.columns else 0
    total_tracked = len(df_vac_f)

    k1, k2, k3, k4 = st.columns(4)
    with k1: st.markdown(kpi("Vacant · Unrented", f"{vu_total:,}",
                              status="bad" if vu_total > 15 else "warn" if vu_total > 8 else "good",
                              sub="Needs immediate leasing"), unsafe_allow_html=True)
    with k2: st.markdown(kpi("Vacant · Rented", f"{vr_total:,}",
                              status="warn" if vr_total > 5 else "good",
                              sub="Leased, awaiting move-in"), unsafe_allow_html=True)
    with k3: st.markdown(kpi("Notice · Unrented", f"{nu_total:,}",
                              status="warn" if nu_total > 10 else "good",
                              sub="Upcoming — start leasing"), unsafe_allow_html=True)
    with k4: st.markdown(kpi("Avg Days Vacant", f"{avg_days:.0f}",
                              status=_tl(avg_days, THR["days_vacant"], "lower"),
                              sub=f"Target ≤ {THR['days_vacant']} days"), unsafe_allow_html=True)

    # Revenue at risk banner
    st.markdown(
        f'<div style="background:linear-gradient(135deg,#7F1D1D 0%,#991B1B 100%);'
        f'border-radius:8px;padding:16px 24px;margin:14px 0 4px;'
        f'display:flex;justify-content:space-between;align-items:center;">'
        f'<div><div style="color:#FCA5A5;font-size:11px;font-weight:700;letter-spacing:0.08em;text-transform:uppercase;">Estimated Revenue at Risk</div>'
        f'<div style="color:#FFFFFF;font-size:28px;font-weight:700;line-height:1.1;margin-top:2px;">${rev_lost:,.0f}</div></div>'
        f'<div style="color:#FCA5A5;font-size:12px;line-height:1.6;text-align:right;">'
        f'Days vacant × last rent ÷ 30<br>'
        f'{rent_ready} rent-ready &nbsp;·&nbsp; {total_tracked} units tracked</div>'
        f'</div>',
        unsafe_allow_html=True,
    )

    # ── Charts ────────────────────────────────────────────────────────────
    col_donut, col_bar = st.columns([4, 6])

    with col_donut:
        section("Status Mix")
        _rr_vac = df_rr_f[df_rr_f["Status"].isin(["Vacant-Unrented","Vacant-Rented","Notice-Unrented","Notice-Rented"])] if df_rr_f is not None and "Status" in df_rr_f.columns else pd.DataFrame()
        status_summary = _rr_vac["Status"].value_counts().reset_index() if len(_rr_vac) else pd.DataFrame()
        if len(status_summary):
            status_summary.columns = ["Status", "Count"]
            _status_colors = {
                "Vacant-Unrented":  "#991B1B",
                "Vacant-Rented":    "#1E40AF",
                "Notice-Unrented":  "#B45309",
                "Notice-Rented":    "#065F46",
            }
            fig_donut = go.Figure(go.Pie(
                labels=status_summary["Status"],
                values=status_summary["Count"],
                hole=0.65,
                marker=dict(
                    colors=[_status_colors.get(s, "#6B7280") for s in status_summary["Status"]],
                    line=dict(color="#FFFFFF", width=2),
                ),
                textinfo="percent",
                textfont=dict(size=11, color="#FFFFFF"),
                hovertemplate="<b>%{label}</b><br>%{value} units · %{percent}<extra></extra>",
            ))
            fig_donut.add_annotation(
                text=f"<b>{int(status_summary['Count'].sum())}</b><br><span style='font-size:10px'>units</span>",
                x=0.5, y=0.5, showarrow=False,
                font=dict(size=18, color="#1E293B"), align="center",
            )
            fig_donut.update_layout(
                template="dfm", height=300, showlegend=True,
                legend=dict(orientation="v", x=1.0, y=0.5,
                            font=dict(size=10), bgcolor="rgba(0,0,0,0)"),
                paper_bgcolor="#FFFFFF",
                margin=dict(l=0, r=90, t=10, b=10),
            )
            st.plotly_chart(fig_donut, width="stretch")

        # ── Longest vacant units (below donut) ────────────────────────────
        _vac_u = df_v[df_v["Days Vacant"] > 0].nlargest(5, "Days Vacant") if len(df_v) else pd.DataFrame()
        if len(_vac_u):
            st.markdown(
                '<p style="font-size:10px;font-weight:700;color:#6B7280;'
                'letter-spacing:0.08em;text-transform:uppercase;margin:10px 0 6px 0;">'
                'Longest Vacant</p>',
                unsafe_allow_html=True,
            )
            for _, _row in _vac_u.iterrows():
                _prop  = str(_row.get("Property", ""))[:20]
                _unit  = str(_row.get("Unit", "—"))
                _days  = int(_row.get("Days Vacant", 0))
                _ready = str(_row.get("Rent Ready", "")).strip().lower() == "yes"
                _d_col = "#7F1D1D" if _days > 60 else "#C2410C" if _days > 30 else "#D97706"
                _r_bg  = "#D1FAE5" if _ready else "#FEE2E2"
                _r_col = "#065F46" if _ready else "#991B1B"
                st.markdown(
                    f'<div style="display:flex;justify-content:space-between;align-items:center;'
                    f'padding:5px 10px;margin-bottom:4px;border-radius:6px;background:#F8FAFC;'
                    f'border-left:3px solid {_d_col};">'
                    f'<div style="line-height:1.3;">'
                    f'<span style="font-size:11px;font-weight:600;color:#1E293B;">Unit {_unit}</span>'
                    f'<span style="font-size:10px;color:#6B7280;margin-left:4px;">· {_prop}</span>'
                    f'</div>'
                    f'<div style="display:flex;align-items:center;gap:5px;">'
                    f'<span style="font-size:12px;font-weight:700;color:{_d_col};">{_days}d</span>'
                    f'<span style="font-size:9px;font-weight:600;padding:2px 5px;border-radius:4px;'
                    f'background:{_r_bg};color:{_r_col};">{"Ready" if _ready else "Not Ready"}</span>'
                    f'</div></div>',
                    unsafe_allow_html=True,
                )

    with col_bar:
        section("Avg Days Vacant by Property")
        prop_v = (df_v.groupby("Property")
                      .agg(avg_days=("Days Vacant", "mean"), units=("Unit", "count"))
                      .reset_index().sort_values("avg_days", ascending=True))

        def _days_color(d):
            t = THR["days_vacant"]
            if d <= t:        return "#15803D"
            elif d <= t * 1.5: return "#D97706"
            elif d <= t * 2:   return "#DC2626"
            else:              return "#7F1D1D"

        fig_bar = go.Figure(go.Bar(
            x=prop_v["avg_days"],
            y=prop_v["Property"],
            orientation="h",
            marker_color=[_days_color(d) for d in prop_v["avg_days"]],
            marker_line_width=0,
            text=prop_v.apply(
                lambda r: f"{r['avg_days']:.0f}d  ·  {int(r['units'])} unit{'s' if r['units']>1 else ''}",
                axis=1,
            ),
            textposition="outside",
            textfont=dict(size=11, color="#374151"),
            hovertemplate="<b>%{y}</b><br>Avg: %{x:.0f} days<extra></extra>",
        ))
        fig_bar.add_vline(
            x=THR["days_vacant"], line_dash="dot",
            line_color="#94A3B8", line_width=1.5,
            annotation_text=f"Target {THR['days_vacant']}d",
            annotation_font=dict(size=10, color="#94A3B8"),
            annotation_position="top right",
        )
        fig_bar.update_layout(
            template="dfm",
            height=max(280, len(prop_v) * 30 + 60),
            xaxis=dict(title="", gridcolor="#F1F5F9", showticklabels=False),
            yaxis=dict(title="", tickfont=dict(size=11)),
            paper_bgcolor="#FFFFFF", plot_bgcolor="#FFFFFF",
            margin=dict(l=0, r=140, t=10, b=10),
        )
        st.plotly_chart(fig_bar, width="stretch")

    # ── Cross-Reference discrepancies ─────────────────────────────────────
    has_rr_status = "RR_Status" in df_vac_f.columns and "Unit Status" in df_vac_f.columns
    if has_rr_status:
        disc_all = df_vac_f[
            (df_vac_f["Unit Status"].astype(str) != df_vac_f["RR_Status"].astype(str)) &
            df_vac_f["RR_Status"].notna() &
            (df_vac_f.get("Source", pd.Series("Vacancy Detail", index=df_vac_f.index)) == "Vacancy Detail")
        ]
        if len(disc_all) > 0:
            with st.expander(f"⚠ Status Discrepancies between Vacancy Detail and Rent Roll ({len(disc_all)} units)", expanded=False):
                disc_disp = disc_all[["Property", "Unit", "Unit Status", "RR_Status"]].copy()
                disc_disp.columns = ["Property", "Unit", "Vacancy Detail Status", "Rent Roll Status"]
                st.dataframe(disc_disp, hide_index=True, width="stretch")

    # ── Detail table ──────────────────────────────────────────────────────
    section(f"Unit Detail  ·  {len(df_v)} units")
    df_v = df_v.copy()
    if "Last Rent" in df_v.columns and "Scheduled Rent" in df_v.columns:
        df_v["Rent Delta"] = (df_v["Scheduled Rent"] - df_v["Last Rent"]).map(
            lambda x: f"+${x:,.0f}" if x >= 0 else f"-${abs(x):,.0f}")

    df_v_sorted = df_v.sort_values("Days Vacant", ascending=False).reset_index(drop=True)
    df_v_sorted.insert(0, "#", range(1, len(df_v_sorted) + 1))

    want = ["#", "Property", "Unit", "Bed/Bath", "Unit Status", "Days Vacant",
            "Rent Ready", "Last Rent", "Scheduled Rent", "Rent Delta", "Available On"]
    disp = [c for c in want if c in df_v_sorted.columns]

    c_tbl, c_dl = st.columns([5, 1])
    with c_tbl:
        st.dataframe(
            df_v_sorted[disp],
            width="stretch", hide_index=True,
            height=min(520, len(df_v_sorted) * 36 + 40),
            column_config={
                "#":              st.column_config.NumberColumn("#", width="small"),
                "Days Vacant":    st.column_config.NumberColumn("Days Vacant", format="%d days"),
                "Last Rent":      st.column_config.NumberColumn("Last Rent", format="$%,.0f"),
                "Scheduled Rent": st.column_config.NumberColumn("Scheduled Rent", format="$%,.0f"),
                "Rent Ready":     st.column_config.TextColumn("Rent Ready", width="small"),
            },
        )
    with c_dl:
        st.markdown("<br><br><br>", unsafe_allow_html=True)
        download_btn(df_v_sorted[disp], "vacancy_detail.csv")


# ============================================================================
# PAGE 3 — LEASING
# ============================================================================

elif st.session_state.page == "Leasing":
    _leasing_snap = _latest_snapshot("leasing_funnel") or ""
    try:
        _dt = pd.to_datetime(_leasing_snap)
        _leasing_snap_lbl = f"{_dt.strftime('%b')} {_dt.day}, {_dt.year}"
    except Exception:
        _leasing_snap_lbl = _leasing_snap
    page_header("Leasing", f"AppFolio report · {_leasing_snap_lbl}")

    # ── Funnel ───────────────────────────────────────────────────────────
    section(f"Leasing Conversion Funnel · {_leasing_snap_lbl}")
    if df_funnel_f is not None:
        inq  = int(df_funnel_f.get("Inquiries",          pd.Series([0])).sum()) if "Inquiries"          in df_funnel_f else 0
        shw  = int(df_funnel_f.get("Completed Showings",  pd.Series([0])).sum()) if "Completed Showings" in df_funnel_f else 0
        apps = int(df_funnel_f.get("Rental Apps",         pd.Series([0])).sum()) if "Rental Apps"        in df_funnel_f else 0
        lsd  = leasing_summary.get("Leased", 0)  # from leasing_summary CSV (authoritative)

        s2l = (lsd / shw  * 100) if shw  > 0 else 0
        i2l = (lsd / inq  * 100) if inq  > 0 else 0
        a2l = (lsd / apps * 100) if apps > 0 else 0
        ck1, ck2, ck3 = st.columns(3)
        with ck1: st.markdown(kpi("Inquiry → Lease", f"{i2l:.1f}%",
                                   sub=f"{inq} inquiries · {lsd} leased"), unsafe_allow_html=True)
        with ck2: st.markdown(kpi("Showing → Lease", f"{s2l:.1f}%",
                                   sub=f"{shw} showings · {lsd} leased"), unsafe_allow_html=True)
        with ck3: st.markdown(kpi("App → Lease", f"{a2l:.1f}%",
                                   sub=f"{apps} applications · {lsd} leased"), unsafe_allow_html=True)

        fig_fn = go.Figure(go.Funnel(
            y=["Inquiries","Showings","Applications","Leased"],
            x=[inq, shw, apps, lsd],
            textposition="inside", textinfo="value+percent initial",
            marker=dict(color=[PC,"#3B82F6","#60A5FA","#93C5FD"]),
            connector=dict(line=dict(color="#E2E8F0", width=1)),
        ))
        fig_fn.update_layout(template="dfm", height=280,
                             paper_bgcolor="#FFFFFF", margin=dict(l=0,r=0,t=10,b=10))
        st.plotly_chart(fig_fn, width="stretch")

    # ── Showings — weekly trend + In-Person vs Virtual ────────────────────
    section(f"Showings Analysis · {_leasing_snap_lbl}")
    if df_raw_show is not None and "Status" in df_raw_show.columns:
        df_s = df_raw_show.copy()
        df_s["Showing Time"] = pd.to_datetime(df_s["Showing Time"], errors="coerce")
        df_comp = df_s[df_s["Status"].astype(str).str.strip().str.lower() == "completed"].dropna(subset=["Showing Time"])

        col_wk, col_type = st.columns(2)
        with col_wk:
            if len(df_comp):
                df_comp = df_comp.copy()
                df_comp["Week"] = df_comp["Showing Time"].dt.to_period("W").dt.start_time
                weekly = df_comp.groupby("Week").size().reset_index(name="Showings")
                fig_w = go.Figure()
                fig_w.add_trace(go.Bar(x=weekly["Week"], y=weekly["Showings"],
                                       name="Showings", marker_color=PC, opacity=0.85))
                if len(weekly) >= 2:
                    fig_w.add_trace(go.Scatter(
                        x=weekly["Week"],
                        y=weekly["Showings"].rolling(3, min_periods=1).mean(),
                        name="Trend", line=dict(color="#EF4444", width=2), mode="lines"))
                fig_w.update_layout(template="dfm", height=260,
                                    title="Completed Showings by Week",
                                    xaxis=dict(gridcolor="#F1F5F9"),
                                    yaxis=dict(gridcolor="#F1F5F9"),
                                    paper_bgcolor="#FFFFFF", plot_bgcolor="#FFFFFF",
                                    legend=dict(orientation="h", y=-0.3),
                                    margin=dict(l=0,r=0,t=30,b=40))
                st.plotly_chart(fig_w, width="stretch")
        with col_type:
            if "Type" in df_comp.columns:
                type_cnt = df_comp["Type"].value_counts().reset_index()
                type_cnt.columns = ["Type","Count"]
                fig_t = go.Figure(go.Pie(
                    labels=type_cnt["Type"], values=type_cnt["Count"],
                    hole=0.55, marker=dict(colors=[PC,"#93C5FD","#34D399"]),
                    textinfo="label+percent",
                ))
                fig_t.update_layout(template="dfm", height=260,
                                    title="Showing Type Breakdown",
                                    showlegend=False, paper_bgcolor="#FFFFFF",
                                    margin=dict(l=10,r=10,t=30,b=10))
                st.plotly_chart(fig_t, width="stretch")

    # ── Applications ──────────────────────────────────────────────────────
    section(f"Application Pipeline · {_leasing_snap_lbl}")
    if df_apps_f is not None and len(df_apps_f):
        col_st, col_src = st.columns(2)
        with col_st:
            if "Status" in df_apps_f.columns:
                st_cnt = df_apps_f["Status"].value_counts().reset_index()
                st_cnt.columns = ["Status","Count"]
                fig_st = px.bar(st_cnt, x="Count", y="Status", orientation="h",
                                color="Status",
                                color_discrete_sequence=["#1B4FD8","#059669","#D97706","#DC2626","#7C3AED","#0891B2"],
                                title="Applications by Status")
                fig_st.update_layout(template="dfm", height=240,
                                     showlegend=False, paper_bgcolor="#FFFFFF",
                                     plot_bgcolor="#FFFFFF",
                                     margin=dict(l=0,r=0,t=30,b=10))
                st.plotly_chart(fig_st, width="stretch")
        with col_src:
            if "Lead Source" in df_apps_f.columns:
                src_cnt = df_apps_f["Lead Source"].value_counts().reset_index()
                src_cnt.columns = ["Source","Count"]
                fig_src = px.pie(src_cnt, names="Source", values="Count",
                                 hole=0.5, title="Lead Source Distribution",
                                 color_discrete_sequence=["#1B4FD8","#3B82F6","#60A5FA","#93C5FD","#BFDBFE","#E0EAFF"])
                fig_src.update_layout(template="dfm", height=240,
                                      paper_bgcolor="#FFFFFF",
                                      margin=dict(l=10,r=10,t=30,b=10))
                st.plotly_chart(fig_src, width="stretch")

        want_a = [c for c in ["Applicant(s)","Property","Status","Lead Source","Received","Desired Move In"] if c in df_apps_f.columns]
        c_a, c_da = st.columns([4,1])
        with c_a:  st.dataframe(df_apps_f[want_a], width="stretch", hide_index=True)
        with c_da: download_btn(df_apps_f[want_a], "applications.csv")
    else:
        st.info("No application data available.")

    # ── Lead Quality ──────────────────────────────────────────────────────
    section("Active Lead Quality")
    
    if df_leads_f is not None and len(df_leads_f):
        active = df_leads_f[df_leads_f["Status"].astype(str).str.lower() == "active"].copy()
        if len(active):
            c1, c2, c3 = st.columns(3)
            with c1: st.markdown(kpi("Active Leads", f"{len(active):,}",
                                      sub="Guest cards with Active status"), unsafe_allow_html=True)
            _raw_score = active["Lead Score"].mean() if "Lead Score" in active.columns else 0
            avg_score = float(_raw_score) if pd.notna(_raw_score) else 0.0
            score_color = "#DC2626" if avg_score < 40 else ("#D97706" if avg_score < 70 else "#059669")
            score_label = "Cold" if avg_score < 40 else ("Warm" if avg_score < 70 else "Hot")
            with c2:
                st.markdown(kpi("Avg Lead Score", f"{avg_score:.0f}/100",
                                status="bad" if avg_score < 40 else ("warn" if avg_score < 70 else "good"),
                                sub=f"Quality: {score_label}"),
                            unsafe_allow_html=True)
            
            avg_inc = 0

            if "Monthly Income" in active.columns:
                _income = active.loc[
                    active["Monthly Income"] > 0,
                    "Monthly Income"
                ]

            if len(_income):
                avg_inc = float(_income.median())

            with c3:
                st.markdown(
                    kpi(
                        "Avg Monthly Income",
                        f"${avg_inc:,.0f}",
                        sub="Active leads · monthly gross income"
                    ),
                unsafe_allow_html=True
                )

            with st.expander(f"How is Lead Score calculated?  ·  Current avg: {avg_score:.0f}/100 — {score_label}", expanded=False):
                st.markdown(f"""
**Score range: 0 – 100 points**

| Component | Max pts | How it's measured |
|---|---|---|
| Income qualification | **40 pts** | Monthly income ÷ (max rent × 3). Full 40 pts if income ≥ 3× rent |
| Credit score | **40 pts** | Scaled from 580–820. Score of 820+ = full 40 pts |
| Lead status | **20 pts** | Active = 20 · Inactive = 8 · Cold = 2 |

**Example — Perfect 100/100 lead:**
- Monthly income: $15,000 · Max rent: $5,000 → ratio 3.0× → **40 pts**
- Credit score: 820+ → **40 pts**
- Status: Active → **20 pts**
- **Total: 100/100**

**Current portfolio average: {avg_score:.0f}/100 — {score_label}**
- {score_label == "Hot" and "≥70 pts — strong applicant pool" or ""}{"" if score_label == "Hot" else (score_label == "Warm" and "40–69 pts — acceptable, some risk" or "< 40 pts — low-quality leads, review sourcing")}
""")

            want_l = [c for c in ["Name","Property","Lead Score","Status","Max Rent",
                                   "Monthly Income","Credit Score","Move In Preference"] if c in active.columns]
            c_l, c_dl = st.columns([4,1])
            with c_l:
                st.dataframe(active[want_l].sort_values("Lead Score", ascending=False),
                             width="stretch", hide_index=True, height=300)
            with c_dl: download_btn(active[want_l].sort_values("Lead Score",ascending=False), "active_leads.csv")


# ============================================================================
# PAGE 4 — RENEWALS
# ============================================================================

elif st.session_state.page == "Renewals":
    page_header("Renewals", f"Data as of {datetime.now().strftime('%B %d, %Y')}")

    # ── KPIs ──────────────────────────────────────────────────────────────
    rr_pct = avg_inc_pct = rev_retained = did_not_renew = 0
    if df_renew_f is not None and len(df_renew_f):
        actionable = df_renew_f[df_renew_f["Status"].isin(["Renewed", "Did Not Renew", "Canceled by User"])]
        renewed    = actionable[actionable["Status"] == "Renewed"]
        rr_pct     = len(renewed) / len(actionable) * 100 if len(actionable) else 0
        did_not_renew = len(actionable) - len(renewed)
        if "Percent Difference" in renewed.columns:
            _pd_vals = renewed["Percent Difference"].dropna()
            avg_inc_pct = float(_pd_vals.mean()) if len(_pd_vals) else 0.0
        if "Rent" in renewed.columns:
            rev_retained = renewed["Rent"].sum()

    c1,c2,c3,c4 = st.columns(4)
    with c1: st.markdown(kpi("Renewal Rate", f"{rr_pct:.1f}%",
                              status=_tl(rr_pct, THR["renewal_rate"]),
                              sub=f"Target {THR['renewal_rate']}% · Renewed vs. actionable"), unsafe_allow_html=True)
    with c2: st.markdown(kpi("Revenue Retained", f"${rev_retained:,.0f}",
                              sub="Monthly rent from renewed leases"), unsafe_allow_html=True)
    with c3: st.markdown(kpi("Did Not Renew", f"{did_not_renew:,}",
                              sub="Actionable leases lost this period"), unsafe_allow_html=True)
    with c4: st.markdown(kpi("Expiring (90d)", f"{exp90:,}",
                              sub=f"{exp30} in 30d · {exp60} in 60d"), unsafe_allow_html=True)

    # ── Status breakdown ──────────────────────────────────────────────────
    col_ch, col_bar = st.columns(2)
    if df_renew_f is not None and len(df_renew_f):
        with col_ch:
            section("Renewal Status Breakdown")
            st_cnt = df_renew_f["Status"].value_counts().reset_index()
            st_cnt.columns = ["Status","Count"]
            status_colors = {"Renewed":"#059669","Did Not Renew":"#DC2626","Canceled by User":"#94A3B8"}
            fig_pie = go.Figure(go.Pie(
                labels=st_cnt["Status"], values=st_cnt["Count"],
                hole=0.55,
                marker=dict(colors=[status_colors.get(s,"#CBD5E1") for s in st_cnt["Status"]]),
                textinfo="label+value",
            ))
            fig_pie.update_layout(template="dfm", height=280, showlegend=False,
                                  paper_bgcolor="#FFFFFF", margin=dict(l=10,r=10,t=10,b=10))
            st.plotly_chart(fig_pie, width="stretch")

        with col_bar:
            section("Rent Change on Renewed Leases")
            if "Rent" in df_renew_f.columns and "Previous Rent" in df_renew_f.columns:
                ren = df_renew_f[df_renew_f["Status"]=="Renewed"].dropna(subset=["Previous Rent","Rent"]).copy()
                ren = ren[ren["Previous Rent"] > 0]
                if len(ren):
                    ren = ren.sort_values("Rent", ascending=True).head(15)
                    fig_bar = go.Figure()
                    fig_bar.add_trace(go.Bar(
                        x=ren["Previous Rent"], y=ren["Tenant Name"],
                        orientation="h", name="Previous Rent", marker_color="#94A3B8"))
                    fig_bar.add_trace(go.Bar(
                        x=ren["Rent"], y=ren["Tenant Name"],
                        orientation="h", name="New Rent", marker_color=PC))
                    fig_bar.update_layout(barmode="overlay", template="dfm",
                                          height=280, paper_bgcolor="#FFFFFF",
                                          plot_bgcolor="#FFFFFF",
                                          xaxis=dict(tickprefix="$",gridcolor="#F1F5F9"),
                                          legend=dict(orientation="h",y=-0.25),
                                          margin=dict(l=0,r=0,t=10,b=40))
                    st.plotly_chart(fig_bar, width="stretch")

    # ── Lease Expiration Calendar (6 months) ──────────────────────────────
    if df_rr_f is not None and "Lease To" in df_rr_f.columns:
        _df_cal = df_rr_f[df_rr_f["Status"] == "Current"].copy()
        _df_cal["Lease To"] = pd.to_datetime(_df_cal["Lease To"], errors="coerce")
        _cal_start = pd.Timestamp(datetime.now().replace(day=1))
        _cal_end   = _cal_start + pd.DateOffset(months=6)
        _df_cal = _df_cal[(_df_cal["Lease To"] >= _cal_start) & (_df_cal["Lease To"] < _cal_end)]
        if len(_df_cal):
            _df_cal["Month"] = _df_cal["Lease To"].dt.to_period("M")
            _month_counts = (_df_cal.groupby("Month").size().reset_index(name="Leases Expiring")
                             .sort_values("Month"))
            _month_counts["Month Label"] = _month_counts["Month"].dt.strftime("%b %Y")
            _now_period = pd.Period(datetime.now(), "M")
            _month_counts["_color"] = _month_counts["Month"].apply(
                lambda m: "#DC2626" if m == _now_period
                else "#D97706" if m == _now_period + 1
                else "#F59E0B" if m == _now_period + 2
                else "#1B4FD8"
            )
            section("Lease Expiration Calendar — Next 6 Months")
            fig_cal = go.Figure(go.Bar(
                x=_month_counts["Month Label"],
                y=_month_counts["Leases Expiring"],
                marker_color=_month_counts["_color"],
                text=_month_counts["Leases Expiring"],
                textposition="outside",
            ))
            fig_cal.update_layout(
                template="dfm", height=260,
                xaxis=dict(title=""),
                yaxis=dict(title="Leases Expiring", gridcolor="#F1F5F9", rangemode="tozero"),
                paper_bgcolor="#FFFFFF", plot_bgcolor="#FFFFFF",
                margin=dict(l=0, r=0, t=10, b=20),
            )
            # Legend
            _leg_html = (
                '<div style="display:flex;gap:18px;font-size:11px;color:#64748B;margin:4px 0 12px 4px;">'
                '<span><span style="display:inline-block;width:10px;height:10px;border-radius:2px;background:#DC2626;margin-right:4px;"></span>This month</span>'
                '<span><span style="display:inline-block;width:10px;height:10px;border-radius:2px;background:#D97706;margin-right:4px;"></span>Next month</span>'
                '<span><span style="display:inline-block;width:10px;height:10px;border-radius:2px;background:#F59E0B;margin-right:4px;"></span>+2 months</span>'
                '<span><span style="display:inline-block;width:10px;height:10px;border-radius:2px;background:#1B4FD8;margin-right:4px;"></span>Later</span>'
                '</div>'
            )
            st.markdown(_leg_html, unsafe_allow_html=True)
            st.plotly_chart(fig_cal, width="stretch")

    # ── Upcoming expirations ──────────────────────────────────────────────
    section("Leases Expiring in the Next 90 Days")
    if df_rr_f is not None and "Lease To" in df_rr_f.columns:
        df_exp = df_rr_f[df_rr_f["Status"]=="Current"].copy()
        df_exp["Lease To"] = pd.to_datetime(df_exp["Lease To"], errors="coerce")
        df_exp = df_exp[
            (df_exp["Lease To"] >= today_ts) &
            (df_exp["Lease To"] <= today_ts + pd.Timedelta(90,"d"))
        ].sort_values("Lease To")
        if len(df_exp):
            df_exp["Days Until Exp"] = (df_exp["Lease To"] - today_ts).dt.days
            want_e = [c for c in ["Property","Unit","Tenant","Rent","Lease To","Days Until Exp"] if c in df_exp.columns]
            c_e, c_de = st.columns([4,1])
            with c_e:  st.dataframe(df_exp[want_e], width="stretch", hide_index=True, height=350)
            with c_de: download_btn(df_exp[want_e], "expiring_leases.csv")
        else:
            st.success("No leases expiring in the next 90 days.")

    # ── Renewals detail ───────────────────────────────────────────────────
    if df_renew_f is not None and len(df_renew_f):
        section("Renewals Detail")
        want_r = [c for c in ["Tenant Name","Property","Unit Name","Previous Rent","Rent",
                               "Percent Difference","Status","Lease End","Term"] if c in df_renew_f.columns]
        c_r, c_dr = st.columns([4,1])
        with c_r:  st.dataframe(df_renew_f[want_r], width="stretch", hide_index=True)
        with c_dr: download_btn(df_renew_f[want_r], "renewals.csv")


# ============================================================================
# PAGE 5 — COLLECTION
# ============================================================================

elif st.session_state.page == "Collection":
    page_header("Collection", f"Data as of {datetime.now().strftime('%B %d, %Y')}")

    if df_rr_f is None:
        st.warning("Rent roll data not found.")
        st.stop()

    df_c = df_rr_f[df_rr_f["Status"]=="Current"].copy() if "Status" in df_rr_f.columns else df_rr_f.copy()
    if "Rent"     in df_c.columns: df_c["Rent"]     = df_c["Rent"].astype(float)
    if "Past Due" in df_c.columns: df_c["Past Due"] = clean_money_column(df_c["Past Due"])

    billed    = df_c["Rent"].sum()     if "Rent"     in df_c.columns else 0
    past_due  = df_c["Past Due"].sum() if "Past Due" in df_c.columns else 0
    collected = billed - past_due
    pct_c     = max(0.0, min(100.0, (collected / billed * 100) if billed > 0 else 0.0))

    section8_billed = 0
    section8_receivable = 0
    section8_collected = 0

    _s8 = pd.DataFrame()

    if df_aged_f is not None and "GL Account Name" in df_aged_f.columns:
        _s8 = df_aged_f[
            df_aged_f["GL Account Name"]
            .astype(str)
            .str.contains("section 8", case=False, na=False)
        ].copy()

    if "Total Amount" in _s8.columns:
        section8_billed = _s8["Total Amount"].sum()

    if "Amount Receivable" in _s8.columns:
        section8_receivable = _s8["Amount Receivable"].sum()

    section8_collected = section8_billed - section8_receivable

    section8_collection_rate = (
        section8_collected / section8_billed
        if section8_billed > 0
        else 0
    )

    c1,c2,c3 = st.columns(3)
    with c1: st.markdown(kpi("Total Billed", f"${billed:,.0f}",
                              sub="Monthly rent — Current tenants"), unsafe_allow_html=True)
    with c2: st.markdown(kpi("Amount Collected", f"${collected:,.0f}",
                              sub="Billed minus Past Due balance"), unsafe_allow_html=True)
    with c3: st.markdown(kpi("Outstanding Balance", f"${past_due:,.0f}",
                              status=_tl(pct_c, THR["collection_rate"]),
                              sub="Past Due from rent roll · All ages · Current tenants only"),
                         unsafe_allow_html=True)

    
#================SECTION 8 PERFORMANCE ============================

    st.markdown(
        """
        <div style="
            font-size:10px;
            font-weight:800;
            letter-spacing:2.5px;
            text-transform:uppercase;
            color:#64748b;
            margin-top:18px;
            margin-bottom:12px;
        ">
            ▌ Section 8 Performance
        </div>
        """,
        unsafe_allow_html=True
        )

    s8c1, s8c2, s8c3, s8c4 = st.columns(4)

    with s8c1:
        st.markdown(
            kpi(
                "Section 8 Billed",
                f"${section8_billed:,.0f}",
                sub="Total Section 8 charges"
            ),
            unsafe_allow_html=True
        )

    with s8c2:
        st.markdown(
            kpi(
                "Section 8 Collected",
                f"${section8_collected:,.0f}",
                status="good" if section8_collected >= 0 else "bad",
                sub="Billed minus receivable"
            ),
            unsafe_allow_html=True
        )

    with s8c3:
        st.markdown(
            kpi(
                "Section 8 Receivable",
                f"${section8_receivable:,.0f}",
                status="warn" if section8_receivable > 0 else "good",
                sub="Outstanding Section 8 balance"
            ),
            unsafe_allow_html=True
        )

    with s8c4:
        st.markdown(
            kpi(
                "Collection Rate",
                f"{section8_collection_rate:.1%}",
                status="good" if section8_collection_rate >= 0.95 else "warn",
                sub="Section 8 collected vs billed"
            ),
            unsafe_allow_html=True
        )

    section("% Collected by Property")
    if "Past Due" not in df_c.columns:
        df_c["Past Due"] = 0.0
    prop_c = (df_c.groupby("Property")
                  .agg(billed=("Rent","sum"), past_due=("Past Due","sum"))
                  .reset_index())
    prop_c["pct"] = ((prop_c["billed"]-prop_c["past_due"])/prop_c["billed"]*100).clip(0,100).fillna(100)

    _COLL_BRACKETS = {
        "🔴  Critical  (<85%)":        ("#991B1B", lambda p: p < 85),
        "🟠  Below target  (85–94%)":  ("#C2410C", lambda p: 85 <= p < 95),
        "🟡  Watch  (95–98%)":         ("#CA8A04", lambda p: 95 <= p < 99),
        "🟢  On track  (≥99%)":        ("#166534", lambda p: p >= 99),
    }

    def _coll_color(p):
        for _, (color, fn) in _COLL_BRACKETS.items():
            if fn(p): return color
        return "#166534"

    
    # ── Bracket filter ────────────────────────────────────────────────────
    bracket_counts = {label: int((prop_c["pct"].apply(fn)).sum())
                      for label, (_, fn) in _COLL_BRACKETS.items()}
    total_props = len(prop_c)
    dropdown_options = [f"All Properties  ({total_props})"] + [
        f"{label}  ({bracket_counts[label]})" for label in _COLL_BRACKETS
    ]
    sel_bracket_raw = st.selectbox(
        "Filter by collection status:",
        dropdown_options,
        label_visibility="collapsed",
    )

    prop_c_view = prop_c.copy()
    if not sel_bracket_raw.startswith("All Properties"):
        bracket_key = sel_bracket_raw.rsplit("  (", 1)[0]
        _, fn = _COLL_BRACKETS[bracket_key]
        prop_c_view = prop_c_view[prop_c_view["pct"].apply(fn)]
    sel_bracket = sel_bracket_raw

    prop_c_view = prop_c_view.sort_values("pct", ascending=False)
    bar_c = [_coll_color(p) for p in prop_c_view["pct"]]

    if len(prop_c_view) == 0:
        st.info("No properties in this bracket.")
    else:
        fig_c = go.Figure(go.Bar(
            x=prop_c_view["pct"], y=prop_c_view["Property"],
            orientation="h",
            marker=dict(color=bar_c, opacity=0.88),
            text=prop_c_view["pct"].map(lambda x: f"{x:.1f}%"),
            textposition="outside",
            textfont=dict(size=11, color="#374151"),
        ))
        fig_c.add_vline(x=THR["collection_rate"], line_dash="dot", line_color="#6B7280",
                        annotation_text=f"{THR['collection_rate']}% target",
                        annotation_position="top right",
                        annotation_font=dict(size=10, color="#6B7280"))
        fig_c.update_layout(
            template="dfm",
            height=max(280, len(prop_c_view) * 26 + 80),
            xaxis=dict(title="% Collected", ticksuffix="%", range=[0, 115],
                       gridcolor="#F1F5F9", tickfont=dict(size=11)),
            yaxis=dict(title="", tickfont=dict(size=11), autorange="reversed"),
            paper_bgcolor="#FFFFFF", plot_bgcolor="#FFFFFF",
            margin=dict(l=0, r=80, t=10, b=40),
        )
        st.plotly_chart(fig_c, width="stretch")

    section("Collection Detail by Property")
    prop_c_disp = prop_c_view.sort_values("pct", ascending=True).copy()  # worst first in table
    prop_c_disp["#"]            = range(1, len(prop_c_disp) + 1)
    prop_c_disp["% Collected"]  = prop_c_disp["pct"].map(lambda x: f"{x:.1f}%")
    prop_c_disp["Billed"]       = prop_c_disp["billed"].map(lambda x: f"${x:,.0f}")
    prop_c_disp["Collected"]    = (prop_c_disp["billed"]-prop_c_disp["past_due"]).map(lambda x: f"${x:,.0f}")
    prop_c_disp["Outstanding"]  = prop_c_disp["past_due"].map(lambda x: f"${x:,.0f}")
    disp_c = ["#", "Property", "Billed", "Collected", "Outstanding", "% Collected"]
    c_ct, c_dct = st.columns([4,1])
    with c_ct:  st.dataframe(prop_c_disp[disp_c], width="stretch", hide_index=True)
    with c_dct: download_btn(prop_c_disp[disp_c], "collection_by_property.csv")


# ============================================================================
# PAGE 6 — DELINQUENCY
# ============================================================================

elif st.session_state.page == "Delinquency":
    page_header("Delinquency", f"Data as of {datetime.now().strftime('%B %d, %Y')}")

    if df_aged_f is None:
        st.warning("aged_receivable_detail-*.csv not found.")
        st.stop()

    
    # ── Controls row ─────────────────────────────────────────────────────
    ctrl_l, ctrl_r = st.columns([2, 2])

    with ctrl_l:
        aging_mode = st.radio(
            "Period",
            options=["0–30 days", "0–60 days", "0–90 days", "91+ days", "All Periods"],
            horizontal=True,
            help=(
                "0–30 days: current month charges only.\n\n"
                "0–60 days: cumulative 0–30 + 31–60.\n\n"
                "0–90 days: cumulative 0–30 + 31–60 + 61–90.\n\n"
                "All Periods: full accumulated balance (includes 91+ days)."
            ),
        )
  
    if "GL Account Name" in df_aged_f.columns:
        _gl = df_aged_f["GL Account Name"].astype(str).str.lower()

        df_d = df_aged_f[
            _gl.str.contains("rental income", na=False) |
            _gl.str.contains("late fee", na=False) |
            _gl.str.contains("section 8", na=False)
        ].copy()

    else:
        df_d = df_aged_f.copy()

    # Build a computed column based on the selected period
    if aging_mode == "0–30 days":
        df_d["_period_amt"] = df_d["0-30"]
        aging_label = "0–30 days"
        use_all_aging = False
    elif aging_mode == "0–60 days":
        df_d["_period_amt"] = df_d["0-30"].fillna(0) + df_d["31-60"].fillna(0)
        aging_label = "0–60 days"
        use_all_aging = False
    elif aging_mode == "0–90 days":
        df_d["_period_amt"] = df_d["0-30"].fillna(0) + df_d["31-60"].fillna(0) + df_d["61-90"].fillna(0)
        aging_label = "0–90 days"
        use_all_aging = False
    elif aging_mode == "91+ days":
        df_d["_period_amt"] = df_d["91+"].fillna(0)
        aging_label = "91+ days"
        use_all_aging = False
    else:  # All Periods
        df_d["_period_amt"] = df_d["Amount Receivable"]
        aging_label = "All Periods"
        use_all_aging = True

    amount_col = "_period_amt"
    if "GL Account Name" in df_d.columns:
        is_rent = df_d["GL Account Name"].astype(str).str.contains(
            "Rental Income",
            case=False,
            na=False
        )

        is_late = df_d["GL Account Name"].astype(str).str.contains(
            "Late fee",
            case=False,
            na=False
        )

        is_section8 = df_d["GL Account Name"].astype(str).str.contains(
            "Section 8",
            case=False,
            na=False
        )
        

    else:
        is_rent = pd.Series(False, index=df_d.index)
        is_late = pd.Series(False, index=df_d.index)

    total_pd  = df_d[amount_col].sum()
    n_delinq  = df_d[df_d[amount_col] > 0]["Payer Name"].nunique()
    rent_amt  = df_d.loc[is_rent, amount_col].sum()
    late_amt  = df_d.loc[is_late, amount_col].sum()
    section8_amt = df_d.loc[is_section8, amount_col].sum()

       
    total_rental_income = (
        df_rr_f["Rent"].sum()
    if df_rr_f is not None and "Rent" in df_rr_f.columns
    else 0
    )
    delinq_rate = (total_pd / total_rental_income * 100) if total_rental_income > 0 else 0

    unit_207_mask = df_d["Payer Name"].astype(str).str.lower().str.contains("damian, jennifer|jennifer damian", na=False)

    unit_207_amt = df_d.loc[unit_207_mask, amount_col].sum()
    adjusted_past_due = total_pd - unit_207_amt
   
    c1,c2,c3,c4,c5,c6 = st.columns(6)
    with c1: st.markdown(kpi("Total Past Due", f"${total_pd:,.0f}", status="bad",
            sub=f"Current view: {aging_label}"),unsafe_allow_html=True)
    with c2: st.markdown(kpi("Delinquent Tenants", f"{n_delinq:,}",
                          sub="With balance in selected view"), unsafe_allow_html=True)
    with c3: st.markdown(kpi("Rental Income", f"${rent_amt:,.0f}",
                          sub=aging_label), unsafe_allow_html=True)
    with c4: st.markdown(kpi("Section 8", f"${section8_amt:,.0f}",
                          sub=aging_label), unsafe_allow_html=True)
    with c5: st.markdown(kpi("Late Fees", f"${late_amt:,.0f}",
                          sub=aging_label), unsafe_allow_html=True)
    with c6: st.markdown(kpi("Delinquency Rate", f"{delinq_rate:.1f}%", status="bad" if delinq_rate > 5 else "warn" if delinq_rate > 3 else "good",
            sub=f"Current view: {aging_label}"),unsafe_allow_html=True)

    c7, c8 = st.columns(2)

    with c7: st.markdown(kpi("Adjusted Past Due", f"${adjusted_past_due:,.0f}",
            sub=f"Excludes 10020 Zelzah Unit 207: ${unit_207_amt:,.0f}"),unsafe_allow_html=True)

    # ── Aging breakdown ───────────────────────────────────────────────────
    section("Past Due Aging Breakdown")
    aging = {
        "0–30":  df_d["0-30"].sum(),
        "31–60": df_d["31-60"].sum(),
        "61–90": df_d["61-90"].sum(),
        "91+":   df_d["91+"].sum(),
    }
    # Highlight which buckets are active in the selected period
    bucket_active = {
        "0–30 days":   [True,  False, False, False],
        "0–60 days":   [True,  True,  False, False],
        "0–90 days":   [True,  True,  True,  False],
        "91+ days":    [False, False, False, True ],
        "All Periods": [True,  True,  True,  True ],
    }
    active_mask = bucket_active.get(aging_mode, [True, True, True, True])
    bar_opacities = [1.0 if a else 0.25 for a in active_mask]
    fig_ag = go.Figure(go.Bar(
        x=list(aging.keys()), y=list(aging.values()),
        marker_color=[PC, "#F59E0B", "#EF4444", "#7F1D1D"],
        marker_opacity=bar_opacities,
        text=[f"${v:,.0f}" for v in aging.values()],
        textposition="outside",
    ))
    fig_ag.update_layout(
        template="dfm", height=290,
        yaxis=dict(title="Amount ($)", tickprefix="$", gridcolor="#F1F5F9"),
        xaxis=dict(title="Aging Bucket"),
        paper_bgcolor="#FFFFFF", plot_bgcolor="#FFFFFF",
        margin=dict(l=0, r=0, t=10, b=40),
    )
    st.plotly_chart(fig_ag, width="stretch")

    is_rent = df_d["GL Account Name"].astype(str).str.contains(
        "Rental Income",
        case=False,
        na=False
    )       

    is_late = df_d["GL Account Name"].astype(str).str.contains(
        "Late fees",
        case=False,
        na=False
    )

    amount_col = "_period_amt"

    rent_amt = df_d.loc[is_rent, amount_col].sum()
    late_amt = df_d.loc[is_late, amount_col].sum()

    # ── Top 10 Properties ─────────────────────────────────────────────────
    section(f"Top 10 Properties by Past Due · {aging_label}")
    prop_d = (df_d.groupby("Property")[amount_col].sum().reset_index()
                  .nlargest(10, amount_col).sort_values(amount_col, ascending=True))
    prop_d = prop_d.rename(columns={amount_col: "_amt"})

    # Identify Jennifer Damian (Unit 207 – Zelzah) as exceptional case
    _jd_d_mask = df_d["Payer Name"].str.lower().str.contains("jennifer damian", na=False)
    _jd_by_prop_d = df_d[_jd_d_mask].groupby("Property")[amount_col].sum().to_dict()
    prop_d["_jd_amt"]     = prop_d["Property"].map(lambda p: _jd_by_prop_d.get(p, 0.0))
    prop_d["_normal_amt"] = prop_d["_amt"] - prop_d["_jd_amt"]
    _has_jd_d = (prop_d["_jd_amt"] > 0).any()

    fig_pd = go.Figure()
    fig_pd.add_trace(go.Bar(
        x=prop_d["_normal_amt"], y=prop_d["Property"],
        orientation="h", marker_color="#EF4444", name="Past Due",
        text=prop_d.apply(lambda r: f"${r['_amt']:,.0f}" if r["_jd_amt"] == 0 else "", axis=1),
        textposition="outside",
    ))
    if _has_jd_d:
        fig_pd.add_trace(go.Bar(
            x=prop_d["_jd_amt"], y=prop_d["Property"],
            orientation="h", marker_color="#7C3AED", name="Unit 207 – Exceptional",
            text=prop_d.apply(lambda r: f"${r['_amt']:,.0f} ★" if r["_jd_amt"] > 0 else "", axis=1),
            textposition="outside",
        ))
    fig_pd.update_layout(
        barmode="stack",
        template="dfm",
        height=max(300, len(prop_d) * 36 + 80),
        xaxis=dict(title="Past Due ($)", tickprefix="$", gridcolor="#F1F5F9"),
        yaxis=dict(title=""),
        paper_bgcolor="#FFFFFF", plot_bgcolor="#FFFFFF",
        margin=dict(l=0, r=120, t=10, b=40),
        showlegend=bool(_has_jd_d),
        legend=dict(orientation="h", y=-0.14),
    )
    st.plotly_chart(fig_pd, width="stretch")

    # ── Aging Heatmap by Property ─────────────────────────────────────────
    _hm_cols = [c for c in ["0-30","31-60","61-90","91+"] if c in df_d.columns]
    if len(_hm_cols) >= 2:
        section("Aging Heatmap by Property")
        _hm = df_d.groupby("Property")[_hm_cols].sum().reset_index()
        _hm["_total"] = _hm[_hm_cols].sum(axis=1)
        _hm = _hm[_hm["_total"] > 0].sort_values("_total", ascending=False).head(20)
        if len(_hm):
            _z = _hm[_hm_cols].values.tolist()
            _text = [[f"${v:,.0f}" if v > 0 else "—" for v in row] for row in _z]
            _col_labels = ["0–30d","31–60d","61–90d","91+d"][:len(_hm_cols)]
            fig_hm = go.Figure(go.Heatmap(
                z=_z,
                x=_col_labels,
                y=_hm["Property"].tolist(),
                colorscale=[[0,"#F0FDF4"],[0.01,"#FEF9C3"],[0.3,"#FED7AA"],
                            [0.6,"#FCA5A5"],[1.0,"#7F1D1D"]],
                text=_text,
                texttemplate="%{text}",
                textfont=dict(size=11),
                showscale=True,
                colorbar=dict(title="$", tickprefix="$", len=0.8),
                hovertemplate="<b>%{y}</b><br>%{x}: %{text}<extra></extra>",
            ))
            fig_hm.update_layout(
                template="dfm",
                height=max(320, len(_hm) * 30 + 80),
                xaxis=dict(side="top"),
                yaxis=dict(autorange="reversed"),
                paper_bgcolor="#FFFFFF",
                margin=dict(l=0, r=80, t=50, b=20),
            )
            st.plotly_chart(fig_hm, width="stretch")

    # ── Top 20 Tenants ────────────────────────────────────────────────────
    section(f"Top 20 Delinquent Tenants · {aging_label}")
    sort_col = {"0–30 days": "d0", "0–60 days": "d_60", "0–90 days": "d_90", "91+ days": "d3", "All Periods": "total"}.get(aging_mode, "total")
    ten_tbl = (
        df_d.groupby(["Payer Name", "Property"])
            .agg(total=("Amount Receivable", "sum"),
                 d0=("0-30", "sum"), d1=("31-60", "sum"),
                 d2=("61-90", "sum"), d3=("91+",   "sum"))
            .reset_index()
    )
    ten_tbl["d_60"] = ten_tbl["d0"] + ten_tbl["d1"]
    ten_tbl["d_90"] = ten_tbl["d0"] + ten_tbl["d1"] + ten_tbl["d2"]
    ten_tbl = ten_tbl.sort_values(sort_col, ascending=False).head(20).copy()
    ten_tbl = ten_tbl[["Payer Name", "Property", "total", "d0", "d1", "d2", "d3"]]
    ten_tbl.columns = ["Tenant", "Property", "Total Past Due", "0–30", "31–60", "61–90", "91+"]
    # Flag Jennifer Damian (Unit 207 – Zelzah) as exceptional case
    ten_tbl["Tenant"] = ten_tbl["Tenant"].apply(
        lambda n: f"⚠️ {n} (Unit 207)" if "jennifer damian" in str(n).lower() else n
    )
    for col in ["Total Past Due", "0–30", "31–60", "61–90", "91+"]:
        ten_tbl[col] = ten_tbl[col].map(lambda x: f"${x:,.2f}")
    c_dt, c_ddt = st.columns([4, 1])
    with c_dt:  st.dataframe(ten_tbl, width="stretch", hide_index=True)
    with c_ddt: download_btn(ten_tbl, "delinquent_tenants.csv")


# ============================================================================
# PAGE 7 — OPERATIONS
# ============================================================================

elif st.session_state.page == "Operations/Maintenance":
    page_header("Operations / Maintenance", f"Data as of {datetime.now().strftime('%B %d, %Y')}")

    if df_wo_f is None:
        st.warning("work_order.csv not found.")
        st.stop()

    df_w = df_wo_f.copy()

 
    if "Created At" in df_w.columns:
        df_w["Created At"] = pd.to_datetime(
            df_w["Created At"],
            errors="coerce"
        )

    # ── Month filter ──────────────────────────────────────────────────────
    if "Created At" in df_w.columns and df_w["Created At"].notna().any():
        wo_months = df_w["Created At"].dt.to_period("M")
        unique_months = sorted(wo_months.dropna().unique(), reverse=True)
        month_labels  = ["All Months"] + [m.strftime("%B %Y") for m in unique_months]
        month_periods = [None] + list(unique_months)
        _cur_period   = pd.Period(datetime.now(), "M")
        _default_idx  = next((i for i, p in enumerate(month_periods) if p == _cur_period), 1)
        col_mf, _ = st.columns([2, 4])
        with col_mf:
            sel_month_label = st.selectbox("Filter by month", options=month_labels, index=_default_idx)
        sel_period = month_periods[month_labels.index(sel_month_label)]
        if sel_period is not None:
            df_w = df_w[wo_months == sel_period].copy()
        st.markdown("")
    # df_w_all retains ALL work orders regardless of month filter — used by Turn KPI Board
    df_w_all = df_wo_f.copy()
    total_wo     = len(df_w)
    completed    = df_w[df_w["Status"].astype(str).str.lower().str.contains("completed", na=False)]
    canceled     = df_w[df_w["Status"].astype(str).str.lower().str.contains("canceled",  na=False)]
    n_comp       = len(completed)
    n_canc       = len(canceled)
    total_cost   = df_w["Amount"].sum() if "Amount" in df_w.columns else 0
    _res_vals    = completed["Days to Resolve"].dropna() if "Days to Resolve" in completed.columns else pd.Series(dtype=float)
    avg_resolve  = float(_res_vals.mean()) if len(_res_vals) else 0.0

    # ── Top KPIs ──────────────────────────────────────────────────────────
    c1,c2,c3,c4 = st.columns(4)
    with c1: st.markdown(kpi("Total Work Orders", f"{total_wo:,}"), unsafe_allow_html=True)
    with c2: st.markdown(kpi("Completed", f"{n_comp:,}",
                              sub=f"{n_comp/total_wo*100:.0f}% of total" if total_wo else ""),
                         unsafe_allow_html=True)
    with c3: st.markdown(kpi("Avg Days to Resolve", f"{avg_resolve:.1f}d",
                              status=_tl(avg_resolve, THR["wo_resolution_days"], "lower")),
                         unsafe_allow_html=True)
    with c4: st.markdown(kpi("Total WO Cost", f"${total_cost:,.0f}"), unsafe_allow_html=True)

    col_l, col_r = st.columns(2)

    # ── Left: Status donut + cost by property ─────────────────────────────
    with col_l:
        section("Work Order Status")
        st_c = df_w["Status"].astype(str).value_counts().reset_index()
        st_c.columns = ["Status","Count"]
        fig_dn = go.Figure(go.Pie(
            labels=st_c["Status"], values=st_c["Count"],
            hole=0.55, marker=dict(colors=["#059669","#1B4FD8","#D97706","#DC2626","#7C3AED","#0891B2","#64748B"]),
            textinfo="label+percent", textposition="outside",
        ))
        fig_dn.update_layout(template="dfm", height=320, showlegend=False,
                             paper_bgcolor="#FFFFFF",
                             margin=dict(l=20,r=20,t=10,b=10),
                             annotations=[dict(text=f"<b>{total_wo}</b><br>Total",
                                               x=0.5,y=0.5,font_size=15,showarrow=False)])
        st.plotly_chart(fig_dn, width="stretch")

        if "Amount" in df_w.columns:
            section("Total Cost by Property (Top 10)")
            cost_p = (df_w.groupby("Property")["Amount"].sum().reset_index()
                          .nlargest(10,"Amount").sort_values("Amount",ascending=True))
            fig_cp = go.Figure(go.Bar(
                x=cost_p["Amount"], y=cost_p["Property"],
                orientation="h", marker_color=PC,
                text=cost_p["Amount"].map(lambda x:f"${x:,.0f}"), textposition="outside",
            ))
            fig_cp.update_layout(template="dfm", height=max(260, len(cost_p)*32+60),
                                 xaxis=dict(tickprefix="$",gridcolor="#F1F5F9"),
                                 yaxis=dict(title=""),
                                 paper_bgcolor="#FFFFFF", plot_bgcolor="#FFFFFF",
                                 margin=dict(l=0,r=80,t=10,b=30))
            st.plotly_chart(fig_cp, width="stretch")

    # ── Right: Priority breakdown + Issue categories + Vendor ─────────────
    with col_r:
        if "Priority" in df_w.columns:
            section("Turnaround Time by Priority (Completed)")
            df_comp_p = completed.dropna(subset=["Days to Resolve"]) if "Days to Resolve" in completed.columns else pd.DataFrame()
            if len(df_comp_p):
                pri_avg = (df_comp_p.groupby("Priority")["Days to Resolve"]
                               .agg(["mean","count"]).reset_index()
                               .rename(columns={"mean":"Avg Days","count":"# WOs"}))
                pri_avg["Avg Days"] = pd.to_numeric(
                    pri_avg["Avg Days"],
                    errors="coerce"
                ).fillna(0).round(1)
                color_map = {"Normal":PC,"Urgent":"#F59E0B","Emergency":"#DC2626"}
                fig_pri = px.bar(pri_avg, x="Priority", y="Avg Days",
                                 color="Priority",
                                 color_discrete_map=color_map,
                                 text="Avg Days",
                                 title="Avg Days to Resolve by Priority")
                fig_pri.update_layout(template="dfm", height=260,
                                      showlegend=False,
                                      paper_bgcolor="#FFFFFF", plot_bgcolor="#FFFFFF",
                                      yaxis=dict(title="Avg Days",gridcolor="#F1F5F9"),
                                      margin=dict(l=0,r=0,t=30,b=30))
                st.plotly_chart(fig_pri, width="stretch")

        if "Work Order Issue" in df_w.columns:
            section("Top Issue Categories")
            iss = (df_w["Work Order Issue"].dropna()
                       .value_counts().head(10).reset_index())
            iss.columns = ["Issue","Count"]
            fig_iss = px.bar(iss, x="Count", y="Issue", orientation="h",
                             color_discrete_sequence=[PC])
            fig_iss.update_layout(template="dfm", height=max(260, len(iss)*28+60),
                                  paper_bgcolor="#FFFFFF", plot_bgcolor="#FFFFFF",
                                  xaxis=dict(gridcolor="#F1F5F9"),
                                  yaxis=dict(title=""),
                                  margin=dict(l=0,r=0,t=10,b=20))
            st.plotly_chart(fig_iss, width="stretch")

        if "Vendor" in df_w.columns:
            section("Vendor Scorecard")

            _ven_df = df_w[
                df_w["Vendor"].notna()
                & (df_w["Vendor"].astype(str).str.strip() != "")
                & (df_w["Vendor"].astype(str).str.lower() != "none")
            ].copy()

            _ven_df["Vendor"] = _ven_df["Vendor"].astype(str).str.strip()

            if len(_ven_df) == 0:
                st.info("No vendor data available.")
            else:
                _ven_df["Days to Resolve"] = pd.to_numeric(
                    _ven_df.get("Days to Resolve"),
                    errors="coerce"
                )

                _ven_df["Amount"] = pd.to_numeric(
                    _ven_df.get("Amount"),
                    errors="coerce"
                ).fillna(0)

                _sc = (
                    _ven_df
                    .groupby("Vendor")
                    .agg(
                        WOs=("Status", "count"),
                        Completed=("Status", lambda x: x.astype(str).str.lower().str.contains("completed", na=False).sum()),
                        Avg_Days=("Days to Resolve", "mean"),
                        Total_Cost=("Amount", "sum"),
                    )
                    .reset_index()
                )

                _sc["% Done"] = (_sc["Completed"] / _sc["WOs"] * 100).fillna(0).round(0).astype(int)
                _sc["Avg Days"] = pd.to_numeric(_sc["Avg_Days"], errors="coerce").fillna(0).round(1)
                _sc["Total Cost $"] = _sc["Total_Cost"].map(lambda x: f"${x:,.0f}" if pd.notna(x) else "—")

                _sc_disp = (
                    _sc[["Vendor", "WOs", "Completed", "% Done", "Avg Days", "Total Cost $"]]
                    .sort_values("WOs", ascending=False)
                    .head(10)
                    .copy()
                )

                _sc_disp["Avg Days"] = _sc_disp["Avg Days"].map(lambda x: f"{x:.1f}d")

                c_v, c_dv = st.columns([3, 1])
                with c_v:
                    st.dataframe(_sc_disp, width="stretch", hide_index=True)
                with c_dv:
                    download_btn(_sc_disp, "vendor_scorecard.csv")

        st.markdown("<br>", unsafe_allow_html=True)

    # ── Work Order Aging ───────────────────────────────────────────────────
    if "Created At" in df_w.columns and "Status" in df_w.columns:
        _open_mask = df_w["Status"].astype(str).str.lower().isin(["open", "in progress", "new"])
        _open_wo   = df_w[_open_mask].copy()
        if len(_open_wo):
            _today_ts = pd.Timestamp(datetime.now().date())
            _open_wo["Days Open"] = (_today_ts - pd.to_datetime(_open_wo["Created At"], errors="coerce")).dt.days.fillna(0).astype(int)
            _aging_thr = int(THR.get("wo_resolution_days", 7))
            _overdue   = _open_wo[_open_wo["Days Open"] > _aging_thr].sort_values("Days Open", ascending=False)

            _n_overdue = len(_overdue)
            _pct_over  = round(_n_overdue / len(_open_wo) * 100) if len(_open_wo) else 0

            section(f"Work Order Aging  ·  {_n_overdue} overdue (>{_aging_thr}d open)")
            ag1, ag2, ag3 = st.columns(3)
            with ag1: st.markdown(kpi("Open WOs", f"{len(_open_wo):,}", sub="Open · In Progress · New"), unsafe_allow_html=True)
            with ag2: st.markdown(kpi(f"Overdue  (>{_aging_thr}d)", f"{_n_overdue:,}",
                                      status="bad" if _pct_over > 30 else "warn" if _pct_over > 10 else "good",
                                      sub=f"{_pct_over}% of open WOs"), unsafe_allow_html=True)
            _longest = int(_open_wo["Days Open"].max()) if len(_open_wo) else 0
            with ag3: st.markdown(kpi("Longest Open", f"{_longest}d",
                                      status="bad" if _longest > _aging_thr * 3 else "warn" if _longest > _aging_thr else "good",
                                      sub="Single oldest open WO"), unsafe_allow_html=True)

            if len(_overdue):
                ag_l, ag_r = st.columns(2)
                with ag_l:
                    # Aging by property
                    _prop_aging = (_overdue.groupby("Property")["Days Open"]
                                   .agg(["count","max"]).reset_index()
                                   .rename(columns={"count":"Overdue WOs","max":"Max Days"})
                                   .sort_values("Max Days", ascending=True))
                    fig_aging_p = go.Figure(go.Bar(
                        x=_prop_aging["Max Days"], y=_prop_aging["Property"],
                        orientation="h",
                        text=_prop_aging["Max Days"].map(lambda d: f"{d}d"),
                        textposition="outside",
                        marker_color=["#DC2626" if d > _aging_thr*3 else "#D97706" if d > _aging_thr else "#059669"
                                      for d in _prop_aging["Max Days"]],
                    ))
                    fig_aging_p.update_layout(template="dfm", height=max(240, len(_prop_aging)*32+60),
                                              xaxis=dict(title="Max Days Open", gridcolor="#F1F5F9"),
                                              yaxis=dict(title=""),
                                              paper_bgcolor="#FFFFFF", plot_bgcolor="#FFFFFF",
                                              margin=dict(l=0,r=60,t=10,b=20))
                    section("Overdue by Property")
                    st.plotly_chart(fig_aging_p, width="stretch")

                with ag_r:
                    # Aging buckets
                    _open_wo["Aging Bucket"] = pd.cut(
                        _open_wo["Days Open"],
                        bins=[0, _aging_thr, _aging_thr*2, _aging_thr*4, float("inf")],
                        labels=[f"0–{_aging_thr}d (on time)",
                                f"{_aging_thr+1}–{_aging_thr*2}d",
                                f"{_aging_thr*2+1}–{_aging_thr*4}d",
                                f"{_aging_thr*4+1}d+"],
                    )
                    _buckets = _open_wo["Aging Bucket"].value_counts().sort_index().reset_index()
                    _buckets.columns = ["Bucket","Count"]
                    _bkt_colors = [("#059669","#ECFDF5"),("#D97706","#FFFBEB"),
                                   ("#DC2626","#FEF2F2"),("#7F1D1D","#FEE2E2")]
                    section("Open WOs by Age")
                    for i, row in _buckets.iterrows():
                        _bc, _bg = _bkt_colors[i] if i < len(_bkt_colors) else ("#64748B","#F8FAFC")
                        st.markdown(
                            f'<div style="display:flex;justify-content:space-between;align-items:center;'
                            f'padding:9px 14px;margin-bottom:5px;border-radius:7px;background:{_bg};'
                            f'border-left:4px solid {_bc};">'
                            f'<span style="font-size:13px;color:#374151;">{row["Bucket"]}</span>'
                            f'<span style="font-size:20px;font-weight:800;color:{_bc};">{row["Count"]}</span>'
                            f'</div>',
                            unsafe_allow_html=True,
                        )

                # Overdue detail table
                st.markdown("<br>", unsafe_allow_html=True)
                _overdue_want = ["Property","Unit","Work Order Issue","Priority","Status","Created At","Days Open","Vendor"]
                _overdue_show = [c for c in _overdue_want if c in _overdue.columns]
                _od_disp = _overdue[_overdue_show].copy()
                if "Created At" in _od_disp.columns:
                    _od_disp["Created At"] = pd.to_datetime(_od_disp["Created At"], errors="coerce").dt.strftime("%b %d, %Y")
                c_od, c_dod = st.columns([4,1])
                with c_od:  st.dataframe(_od_disp, width="stretch", hide_index=True, height=300)
                with c_dod: download_btn(_od_disp, "overdue_workorders.csv")

    # ══════════════════════════════════════════════════════════════════════
    # UNIT TURN KPI BOARD
    # ══════════════════════════════════════════════════════════════════════
    st.markdown("<br>", unsafe_allow_html=True)
    section("Unit Turn KPI Board")

    # Turn KPI Board always uses full dataset — turns span multiple months
    # so month filter would break per-turn aggregation
    _turns_raw = df_w_all[
        df_w_all["Unit Turn ID"].notna() &
        (df_w_all["Unit Turn ID"].astype(str).str.strip() != "")
    ].copy() if "Unit Turn ID" in df_w_all.columns else pd.DataFrame()

    if len(_turns_raw) == 0:
        st.info("No unit turn work orders found.")
    else:
        # ── Vendor classification at WO level ───────────────────────────
        _DPM = "Defined Property Management"
        _turns_raw["_is_internal"] = (
            _turns_raw["Vendor"].astype(str).str.strip() == _DPM
        ) if "Vendor" in _turns_raw.columns else False
        # Internal/external spend — treat NaN Amount as 0
        _amt = _turns_raw["Amount"].fillna(0) if "Amount" in _turns_raw.columns \
               else pd.Series(0, index=_turns_raw.index)
        _turns_raw["_int_spend"] = _amt.where(_turns_raw["_is_internal"], 0)
        _turns_raw["_ext_spend"] = _amt.where(~_turns_raw["_is_internal"], 0)

        # ── Status flags per WO ──────────────────────────────────────────
        if "Status" in _turns_raw.columns:
            _st = _turns_raw["Status"].astype(str).str.lower()
            _turns_raw["_is_completed"] = _st.str.contains("completed", na=False)
            _turns_raw["_is_canceled"]  = _st.str.contains("cancel",    na=False)
        else:
            _turns_raw["_is_completed"] = False
            _turns_raw["_is_canceled"]  = False

        # ── Per-turn aggregation ─────────────────────────────────────────
        def _tfirst(s):
            v = s.dropna()
            return v.iloc[0] if len(v) else None

        _grp = _turns_raw.groupby("Unit Turn ID", sort=False)

        # A turn is "fully completed" only when ALL non-canceled WOs are completed
        def _turn_status(grp):
            active = grp[~grp["_is_canceled"]]
            if len(active) == 0:               return "Canceled"
            if active["_is_completed"].all():  return "Completed"
            return "In Progress"

        _turn_status_map = _turns_raw.groupby("Unit Turn ID").apply(_turn_status)

        _agg = pd.DataFrame({
            "Property":     _grp["Property"].agg(_tfirst) if "Property" in _turns_raw.columns else None,
            "Unit":         _grp["Unit"].agg(_tfirst)     if "Unit"     in _turns_raw.columns else None,
            "turn_start":   _grp["Created At"].min()      if "Created At"   in _turns_raw.columns else None,
            # turn_end = max Completed On only for truly finished turns; else NaT
            "turn_end":     _grp["Completed On"].max()    if "Completed On" in _turns_raw.columns else None,
            "total_cost":   _grp["Amount"].sum()          if "Amount"   in _turns_raw.columns else 0,
            "int_spend":    _grp["_int_spend"].sum(),
            "ext_spend":    _grp["_ext_spend"].sum(),
            "n_wos":        _grp["Amount"].count(),
            "qc_status":    _grp["Estimate Approval Status"].agg(_tfirst) if "Estimate Approval Status" in _turns_raw.columns else None,
            "_n_internal":  _grp["_is_internal"].sum(),
            "_n_total":     _grp["_is_internal"].count(),
        }).reset_index()

        # Attach correct completion status and null turn_end for non-completed turns
        _agg = _agg.merge(_turn_status_map.rename("_turn_status"), on="Unit Turn ID", how="left")
        _agg.loc[_agg["_turn_status"] != "Completed", "turn_end"] = pd.NaT

        # Work type per turn
        def _wtype(row):
            if row["_n_total"] == 0:                  return "Unknown"
            if row["_n_internal"] == row["_n_total"]: return "Internal"
            if row["_n_internal"] == 0:               return "External"
            return "Mixed"
        _agg["Work Type"] = _agg.apply(_wtype, axis=1)

        # Duration & cost/day
        _agg["total_duration"] = (_agg["turn_end"] - _agg["turn_start"]).dt.days
        _agg["total_duration"] = _agg["total_duration"].where(_agg["total_duration"] > 0)
        _agg["cost_per_day"]   = pd.to_numeric(
            _agg.apply(lambda r: r["total_cost"] / r["total_duration"]
                       if pd.notna(r["total_duration"]) and r["total_duration"] > 0 else None,
                       axis=1), errors="coerce")
        _agg["total_duration"] = pd.to_numeric(_agg["total_duration"], errors="coerce")
        _agg["total_cost"]     = pd.to_numeric(_agg["total_cost"],     errors="coerce")

        # Approval wait: max days from last request to approved (worst-case per turn)
        if "Estimate Approved On" in _turns_raw.columns and \
           "Estimate Approval Last Requested On" in _turns_raw.columns:
            _appr_wo = _turns_raw[
                _turns_raw["Estimate Approved On"].notna() &
                _turns_raw["Estimate Approval Last Requested On"].notna()
            ].copy()
            _appr_wo["_appr_days"] = (
                _appr_wo["Estimate Approved On"] -
                _appr_wo["Estimate Approval Last Requested On"]
            ).dt.days.clip(lower=0)  # negative = approved before request logged → treat as 0
            _appr_by_turn = _appr_wo.groupby("Unit Turn ID")["_appr_days"].max().reset_index()
            _appr_by_turn.columns = ["Unit Turn ID", "approval_wait"]
            _agg = _agg.merge(_appr_by_turn, on="Unit Turn ID", how="left")
        else:
            _agg["approval_wait"] = None

        # Estimate funnel counts (across all WOs, not per turn)
        _n_est_req  = int(_turns_raw["Estimate Req On"].notna().sum()) \
                      if "Estimate Req On" in _turns_raw.columns else 0
        _n_estimated = int(_turns_raw["Estimated On"].notna().sum()) \
                       if "Estimated On" in _turns_raw.columns else 0
        _n_est_appr = int(_turns_raw["Estimate Approved On"].notna().sum()) \
                      if "Estimate Approved On" in _turns_raw.columns else 0

        # ── KPI Row ──────────────────────────────────────────────────────
        _total_turns  = len(_agg)
        _active_turns = int((_agg["_turn_status"] == "In Progress").sum())
        _comp_turns   = int((_agg["_turn_status"] == "Completed").sum())
        _avg_duration = _agg["total_duration"].mean()
        _med_duration = _agg["total_duration"].median()
        _avg_cost     = _agg["total_cost"].mean()
        _total_spend  = _agg["total_cost"].sum()
        _avg_cpd      = _agg["cost_per_day"].mean()

        _k1, _k2, _k3, _k4 = st.columns(4)
        with _k1: st.markdown(kpi("Total Turns", f"{_total_turns}",
                                   sub=f"{_active_turns} active · {_comp_turns} completed"),
                               unsafe_allow_html=True)
        with _k2: st.markdown(kpi("Avg Turn Duration",
                                   f"{_avg_duration:.0f}d" if pd.notna(_avg_duration) else "—",
                                   sub=f"Median {_med_duration:.0f}d" if pd.notna(_med_duration) else "",
                                   status=_tl(_avg_duration, THR["wo_resolution_days"], "lower")
                                   if pd.notna(_avg_duration) else ""),
                               unsafe_allow_html=True)
        with _k3: st.markdown(kpi("Avg Cost / Turn",
                                   f"${_avg_cost:,.0f}" if pd.notna(_avg_cost) else "—",
                                   sub=f"Total ${_total_spend:,.0f}"),
                               unsafe_allow_html=True)
        with _k4: st.markdown(kpi("Avg $/Day",
                                   f"${_avg_cpd:,.0f}" if pd.notna(_avg_cpd) else "—",
                                   sub="Spend efficiency"),
                               unsafe_allow_html=True)

        st.markdown("<br>", unsafe_allow_html=True)

        # ════════════════════════════════════════════════════════════════
        # ROW A — TOTAL DURATION
        # ════════════════════════════════════════════════════════════════
        section("Total Duration")
        _ra1, _ra2 = st.columns(2)

        with _ra1:
            # Duration distribution histogram
            _dur_data = _agg["total_duration"].dropna()
            if len(_dur_data):
                _dur_bins   = [0, 15, 30, 45, 60, float("inf")]
                _dur_labels = ["≤15d", "16–30d", "31–45d", "46–60d", "60d+"]
                _dur_bucket = pd.cut(_dur_data, bins=_dur_bins, labels=_dur_labels)
                _dur_counts = _dur_bucket.value_counts().reindex(_dur_labels, fill_value=0).reset_index()
                _dur_counts.columns = ["Range", "Turns"]
                # Color by urgency
                _dur_colors = ["#10B981", "#3B82F6", "#F59E0B", "#EF4444", "#7F1D1D"]
                _fig_dur = px.bar(
                    _dur_counts, x="Range", y="Turns",
                    color="Range",
                    color_discrete_sequence=_dur_colors,
                    labels={"Range": "Duration", "Turns": "# Turns"},
                    template="dfm", title="Duration Distribution",
                )
                _fig_dur.update_layout(showlegend=False,
                                        margin=dict(t=40, b=10, l=0, r=0), height=300)
                st.plotly_chart(_fig_dur, use_container_width=True)
            else:
                st.caption("No duration data available.")

        with _ra2:
            # Scatter: Duration vs Total Cost — one dot per turn
            _sc_data = _agg[_agg["total_duration"].notna() & _agg["total_cost"].notna()].copy()
            # Replace None with "—" in hover columns so tooltip is readable
            for _hc in ["Property", "Unit"]:
                if _hc in _sc_data.columns:
                    _sc_data[_hc] = _sc_data[_hc].fillna("—")
            if len(_sc_data):
                _color_map = {"Internal": "#3B82F6", "External": "#F59E0B",
                               "Mixed": "#8B5CF6", "Unknown": "#9CA3AF"}
                _fig_scatter = px.scatter(
                    _sc_data,
                    x="total_duration", y="total_cost",
                    color="Work Type",
                    size="n_wos",
                    hover_data={c: True for c in ["Property", "Unit", "n_wos"]
                                if c in _sc_data.columns},
                    color_discrete_map=_color_map,
                    labels={"total_duration": "Duration (days)",
                             "total_cost": "Total Cost ($)",
                             "n_wos": "# WOs"},
                    template="dfm", title="Duration vs Cost per Turn",
                )
                _fig_scatter.update_layout(margin=dict(t=40, b=10, l=0, r=0), height=300)
                st.plotly_chart(_fig_scatter, use_container_width=True)
            else:
                st.caption("Not enough data for scatter.")

        st.markdown("<br>", unsafe_allow_html=True)

        # ════════════════════════════════════════════════════════════════
        # ROW B — OWNER APPROVAL TIMEFRAME
        # ════════════════════════════════════════════════════════════════
        section("Owner Approval Timeframe")
        _rb1, _rb2 = st.columns(2)

        with _rb1:
            _appr_data = _agg["approval_wait"].dropna() if "approval_wait" in _agg.columns \
                         else pd.Series(dtype=float)
            if len(_appr_data):
                _ab_bins   = [-1, 3, 7, 14, float("inf")]
                _ab_labels = ["0–3 days", "4–7 days", "8–14 days", "15+ days"]
                _ab_bucket = pd.cut(_appr_data, bins=_ab_bins, labels=_ab_labels)
                _ab_counts = _ab_bucket.value_counts().reindex(_ab_labels, fill_value=0).reset_index()
                _ab_counts.columns = ["Wait Time", "Turns"]
                _fig_appr = px.bar(
                    _ab_counts, x="Wait Time", y="Turns",
                    color="Wait Time",
                    color_discrete_sequence=["#10B981", "#3B82F6", "#F59E0B", "#EF4444"],
                    template="dfm", title="Approval Wait Distribution",
                )
                _fig_appr.update_layout(showlegend=False,
                                         margin=dict(t=40, b=10, l=0, r=0), height=300)
                st.plotly_chart(_fig_appr, use_container_width=True)
            else:
                st.info("Approval wait data not available — AppFolio estimate fields may not be populated for these turns.")

        with _rb2:
            # Estimate funnel: Requested → Estimated → Approved
            st.markdown("**Estimate Funnel**")
            if _n_est_req > 0:
                _funnel_df = pd.DataFrame({
                    "Stage": ["Estimate Requested", "Estimate Submitted", "Estimate Approved"],
                    "Count": [_n_est_req, _n_estimated, _n_est_appr],
                })
                _fig_funnel = px.funnel(
                    _funnel_df, x="Count", y="Stage",
                    template="dfm", color_discrete_sequence=["#3B82F6"],
                )
                _fig_funnel.update_layout(margin=dict(t=10, b=10, l=0, r=0), height=260)
                st.plotly_chart(_fig_funnel, use_container_width=True)
                if len(_appr_data):
                    _avg_wait = float(_appr_data.mean())
                    _max_wait = float(_appr_data.max())
                    _c1, _c2 = st.columns(2)
                    with _c1: st.markdown(kpi("Avg Wait", f"{_avg_wait:.1f}d",
                                               sub="from request to approval"),
                                          unsafe_allow_html=True)
                    with _c2: st.markdown(kpi("Longest Wait", f"{_max_wait:.0f}d",
                                               sub="worst case"),
                                          unsafe_allow_html=True)
            else:
                st.caption("No estimate request data.")

        st.markdown("<br>", unsafe_allow_html=True)

        # ════════════════════════════════════════════════════════════════
        # ROW C — COMPLETION ($/DAY) BY PROPERTY
        # ════════════════════════════════════════════════════════════════
        section("Completion Cost — $/Day")
        _rc1, _rc2 = st.columns([3, 2])

        with _rc1:
            if "Property" in _agg.columns and _agg["cost_per_day"].notna().any():
                _cpd_prop = (
                    _agg[_agg["cost_per_day"].notna()]
                    .groupby("Property")["cost_per_day"]
                    .agg(["mean", "count"])
                    .reset_index()
                    .rename(columns={"mean": "Avg $/Day", "count": "Turns"})
                    .sort_values("Avg $/Day", ascending=True)
                    .tail(12)
                )
                _fig_cpd = px.bar(
                    _cpd_prop, x="Avg $/Day", y="Property",
                    orientation="h",
                    hover_data={"Turns": True},
                    color="Avg $/Day",
                    color_continuous_scale=["#10B981", "#F59E0B", "#EF4444"],
                    labels={"Avg $/Day": "$/Day", "Property": ""},
                    template="dfm", title="Avg $/Day per Property (higher = more expensive)",
                )
                _fig_cpd.update_layout(coloraxis_showscale=False,
                                        margin=dict(t=40, b=10, l=0, r=10), height=380)
                st.plotly_chart(_fig_cpd, use_container_width=True)
            else:
                st.caption("No $/day data available.")

        with _rc2:
            # Top 5 most expensive turns
            st.markdown("**Most Expensive Turns**")
            _top5 = (_agg[_agg["cost_per_day"].notna()]
                     .nlargest(5, "cost_per_day")[
                         ["Property", "Unit", "total_duration", "total_cost", "cost_per_day"]]
                     .copy())
            _top5.columns = ["Property", "Unit", "Days", "Total $", "$/Day"]
            _top5["Total $"] = _top5["Total $"].map(lambda x: f"${x:,.0f}")
            _top5["$/Day"]   = _top5["$/Day"].map(lambda x: f"${x:,.0f}")
            st.dataframe(_top5, hide_index=True, use_container_width=True)

            st.markdown("<br>", unsafe_allow_html=True)
            st.markdown("**Fastest Completed Turns**")
            _fast5 = (_agg[_agg["total_duration"].notna() & (_agg["total_duration"] > 0)]
                      .nsmallest(5, "total_duration")[
                          ["Property", "Unit", "total_duration", "total_cost"]]
                      .copy())
            _fast5.columns = ["Property", "Unit", "Days", "Total $"]
            _fast5["Total $"] = _fast5["Total $"].map(lambda x: f"${x:,.0f}")
            st.dataframe(_fast5, hide_index=True, use_container_width=True)

        st.markdown("<br>", unsafe_allow_html=True)

        # ════════════════════════════════════════════════════════════════
        # ROW D — INTERNAL vs EXTERNAL
        # ════════════════════════════════════════════════════════════════
        section("Internal vs External Spend")
        _rd1, _rd2 = st.columns([2, 3])

        with _rd1:
            # Donut: total internal vs external spend
            _int_total = float(_agg["int_spend"].sum())
            _ext_total = float(_agg["ext_spend"].sum())
            _spend_df  = pd.DataFrame({
                "Type":  ["Internal (DPM)", "External Vendors"],
                "Spend": [_int_total, _ext_total],
            })
            _fig_donut = px.pie(
                _spend_df, names="Type", values="Spend",
                hole=0.55, template="dfm",
                color_discrete_sequence=["#3B82F6", "#F59E0B"],
                title="Total Spend Split",
            )
            _fig_donut.update_traces(texttemplate="%{percent:.0%}")
            _fig_donut.update_layout(margin=dict(t=40, b=10, l=0, r=0),
                                      height=300, showlegend=True,
                                      legend=dict(orientation="h", y=-0.05))
            st.plotly_chart(_fig_donut, use_container_width=True)
            _tot = _int_total + _ext_total
            _ki1, _ki2 = st.columns(2)
            with _ki1: st.markdown(kpi("Internal", f"${_int_total:,.0f}",
                                        sub=f"{_int_total/_tot*100:.0f}% of total" if _tot else ""),
                                    unsafe_allow_html=True)
            with _ki2: st.markdown(kpi("External", f"${_ext_total:,.0f}",
                                        sub=f"{_ext_total/_tot*100:.0f}% of total" if _tot else ""),
                                    unsafe_allow_html=True)

        with _rd2:
            # Stacked bar: internal vs external spend by property
            if "Property" in _agg.columns:
                _prop_spend = (
                    _agg.groupby("Property")[["int_spend", "ext_spend"]]
                    .sum()
                    .reset_index()
                )
                _prop_spend["total"] = _prop_spend["int_spend"] + _prop_spend["ext_spend"]
                _prop_spend = _prop_spend.sort_values("total", ascending=True).tail(12)
                _fig_stack = px.bar(
                    _prop_spend,
                    x=["int_spend", "ext_spend"], y="Property",
                    orientation="h",
                    barmode="stack",
                    color_discrete_map={
                        "int_spend": "#3B82F6",
                        "ext_spend": "#F59E0B",
                    },
                    labels={"value": "$", "variable": "Type", "Property": ""},
                    template="dfm", title="Internal vs External Spend by Property",
                )
                _fig_stack.for_each_trace(lambda t: t.update(
                    name="Internal (DPM)" if t.name == "int_spend" else "External"))
                _fig_stack.update_layout(margin=dict(t=40, b=10, l=0, r=0),
                                          height=380, legend_title_text="")
                st.plotly_chart(_fig_stack, use_container_width=True)

        st.markdown("<br>", unsafe_allow_html=True)

        # ════════════════════════════════════════════════════════════════
        # ROW E — QC PASS RATES
        # ════════════════════════════════════════════════════════════════
        section("QC Pass Rates")
        _re1, _re2, _re3 = st.columns(3)

        with _re1:
            # Turn completion rate — uses _turn_status computed during aggregation
            _sc_grp = _agg["_turn_status"].value_counts().reset_index()
            _sc_grp.columns = ["Status", "Count"]
            _fig_comp = px.pie(
                _sc_grp, names="Status", values="Count",
                hole=0.55, template="dfm",
                color_discrete_map={
                    "Completed":   "#10B981",
                    "In Progress": "#3B82F6",
                    "Canceled":    "#EF4444",
                },
                title="Turn Completion Rate",
            )
            _fig_comp.update_traces(texttemplate="%{percent:.0%}")
            _fig_comp.update_layout(margin=dict(t=40, b=30, l=0, r=0),
                                     height=300, showlegend=True,
                                     legend=dict(orientation="h", y=-0.1))
            st.plotly_chart(_fig_comp, use_container_width=True)
            _n_comp_t = int((_agg["_turn_status"] == "Completed").sum())
            _comp_rate = _n_comp_t / _total_turns * 100 if _total_turns else 0
            st.markdown(
                f"<div style='text-align:center;font-size:13px;color:#6B7280;'>"
                f"Completion rate: <b style='color:#10B981'>{_comp_rate:.0f}%</b></div>",
                unsafe_allow_html=True,
            )

        with _re2:
            # Estimate approval rate
            _wo_appr_status = _turns_raw["Estimate Approval Status"].dropna() \
                if "Estimate Approval Status" in _turns_raw.columns else pd.Series(dtype=str)
            if len(_wo_appr_status):
                _eas_counts = _wo_appr_status.value_counts().reset_index()
                _eas_counts.columns = ["Status", "Count"]
                _fig_eas = px.pie(
                    _eas_counts, names="Status", values="Count",
                    hole=0.55, template="dfm",
                    color_discrete_map={
                        "Approved": "#10B981",
                        "Pending":  "#F59E0B",
                        "Rejected": "#EF4444",
                    },
                    title="Estimate Approval Rate",
                )
                _fig_eas.update_traces(texttemplate="%{percent:.0%}")
                _fig_eas.update_layout(margin=dict(t=40, b=30, l=0, r=0),
                                        height=300, showlegend=True,
                                        legend=dict(orientation="h", y=-0.1))
                st.plotly_chart(_fig_eas, use_container_width=True)
                _n_appr  = int((_wo_appr_status.str.lower() == "approved").sum())
                _appr_rt = _n_appr / len(_wo_appr_status) * 100
                st.markdown(
                    f"<div style='text-align:center;font-size:13px;color:#6B7280;'>"
                    f"Approved: <b style='color:#10B981'>{_appr_rt:.0f}%</b> "
                    f"of {len(_wo_appr_status)} estimates</div>",
                    unsafe_allow_html=True,
                )
            else:
                st.caption("No estimate approval data.")

        with _re3:
            # Re-open / callback rate
            st.markdown("**Callback / Re-open Rate**")
            st.caption("Turns where a new WO was opened on the same unit within 30 days of completion.")
            _comp_turns_df = _agg[_agg["turn_end"].notna()].copy()
            if len(_comp_turns_df) and "Created At" in df_w_all.columns and \
               "Property" in df_w_all.columns and "Unit" in df_w_all.columns:
                _reopen_ids = []
                for _, _t in _comp_turns_df.iterrows():
                    # Skip turns with null Property or Unit — can't match reliably
                    if pd.isna(_t.get("Property")) or pd.isna(_t.get("Unit")):
                        continue
                    _mask = (
                        (df_w_all["Property"].fillna("") == _t["Property"]) &
                        (df_w_all["Unit"].fillna("")     == _t["Unit"])     &
                        (df_w_all["Created At"] > _t["turn_end"])           &
                        (df_w_all["Created At"] <= _t["turn_end"] + pd.Timedelta(days=30))
                    )
                    if df_w_all[_mask].shape[0] > 0:
                        _reopen_ids.append(_t["Unit Turn ID"])
                _n_reopen    = len(_reopen_ids)
                _n_comp_base = len(_comp_turns_df)
                _reopen_rate = _n_reopen / _n_comp_base * 100 if _n_comp_base else 0
                _first_time  = 100 - _reopen_rate
                # Gauge-style display
                _gauge_color = "#10B981" if _first_time >= 85 else \
                               "#F59E0B" if _first_time >= 70 else "#EF4444"
                st.markdown(
                    f"<div style='text-align:center;padding:30px 0;'>"
                    f"<div style='font-size:52px;font-weight:800;color:{_gauge_color};'>"
                    f"{_first_time:.0f}%</div>"
                    f"<div style='font-size:14px;color:#6B7280;margin-top:4px;'>"
                    f"First-time completion</div>"
                    f"<div style='font-size:12px;color:#9CA3AF;margin-top:12px;'>"
                    f"{_n_reopen} of {_n_comp_base} completed turns had a callback</div>"
                    f"</div>",
                    unsafe_allow_html=True,
                )
            else:
                st.caption("Not enough data for re-open rate.")

        # ── Turn Detail Table ────────────────────────────────────────────
        st.markdown("<br>", unsafe_allow_html=True)
        section("Turn Detail")
        _disp_cols = ["Unit Turn ID", "Property", "Unit", "turn_start", "turn_end",
                       "total_duration", "total_cost", "cost_per_day",
                       "approval_wait", "Work Type", "qc_status"]
        _turn_disp = _agg[[c for c in _disp_cols if c in _agg.columns]].copy()
        _turn_disp = _turn_disp.rename(columns={
            "Unit Turn ID":   "Turn ID",
            "turn_start":     "Start Date",
            "turn_end":       "End Date",
            "total_duration": "Duration (days)",
            "total_cost":     "Total Cost",
            "cost_per_day":   "$/Day",
            "approval_wait":  "Approval Wait",
            "qc_status":      "QC Status",
        })
        for _dc in ["Start Date", "End Date"]:
            if _dc in _turn_disp.columns:
                _turn_disp[_dc] = pd.to_datetime(_turn_disp[_dc], errors="coerce").dt.strftime("%b %d, %Y")
        if "Total Cost"     in _turn_disp.columns:
            _turn_disp["Total Cost"]    = _agg["total_cost"].map(lambda x: f"${x:,.0f}" if pd.notna(x) else "—")
        if "$/Day"          in _turn_disp.columns:
            _turn_disp["$/Day"]         = _agg["cost_per_day"].map(lambda x: f"${x:,.0f}" if pd.notna(x) else "—")
        if "Approval Wait"  in _turn_disp.columns:
            _turn_disp["Approval Wait"] = _agg["approval_wait"].map(lambda x: f"{int(x)}d" if pd.notna(x) else "—")
        _turn_disp_sorted = _turn_disp.sort_values("Start Date", ascending=False) \
            if "Start Date" in _turn_disp.columns else _turn_disp
        _ct, _cdt = st.columns([4, 1])
        with _ct:  st.dataframe(_turn_disp_sorted, width="stretch", hide_index=True, height=400)
        with _cdt: download_btn(_turn_disp_sorted, "turn_kpi_detail.csv")

    # ── Work Order Detail ────────────────────────────────────────────────
    st.markdown("<br>", unsafe_allow_html=True)
    section("Work Order Detail")
    _wo_want = ["Property", "Unit", "Work Order Issue", "Priority", "Status",
                "Created At", "Completed On", "Days to Resolve", "Amount", "Vendor"]
    _wo_show = [c for c in _wo_want if c in df_w.columns]
    if _wo_show:
        _df_wo_disp = df_w[_wo_show].copy()
        if "Created At" in _df_wo_disp.columns:
            _df_wo_disp["Created At"] = pd.to_datetime(_df_wo_disp["Created At"], errors="coerce").dt.strftime("%b %d, %Y")
        if "Completed On" in _df_wo_disp.columns:
            _df_wo_disp["Completed On"] = pd.to_datetime(_df_wo_disp["Completed On"], errors="coerce").dt.strftime("%b %d, %Y")
        if "Amount" in _df_wo_disp.columns:
            _df_wo_disp["Amount"] = df_w["Amount"].map(lambda x: f"${x:,.0f}" if pd.notna(x) else "—")
        c_wod, c_dwod = st.columns([4, 1])
        with c_wod:
            st.dataframe(_df_wo_disp.sort_values("Created At", ascending=False) if "Created At" in _df_wo_disp.columns else _df_wo_disp,
                         width="stretch", hide_index=True, height=400)
        with c_dwod:
            download_btn(df_w[_wo_show], "work_order_detail.csv")


# ============================================================================
# PAGE 8 — CALLS
# ============================================================================

elif st.session_state.page == "Calls":
    _period_label = ""
    if calls_meta and calls_meta.get("start") and calls_meta.get("end"):
        _s = calls_meta["start"].strftime("%b %d")
        _e = calls_meta["end"].strftime("%b %d, %Y")
        _period_label = f"{_s} – {_e}"

    page_header("Calls", f"Team phone activity  ·  {_period_label}" if _period_label else "Team phone activity")

    if df_calls is None or len(df_calls) == 0:
        st.warning("No call data found. Place a Users_Dashboard*.xlsx file in the data folder.")
        st.stop()

    # ── Phone team filter (list driven by config.yaml > phone_team) ───────
    def _is_phone_team(name: str) -> bool:
        n = str(name).strip().lower()
        return any(pt.lower() in n for pt in PHONE_TEAM)

    col_ft, _ = st.columns([2, 4])
    with col_ft:
        phone_only = st.toggle("Phone Team Only", value=True,
                               help=" · ".join(PHONE_TEAM))

    # Active agents only (at least 1 call), then apply team filter
    df_active = df_calls[df_calls["Total Calls"] > 0].copy()
    if phone_only:
        df_active = df_active[df_active["Name"].apply(_is_phone_team)].copy()

    # ── Portfolio KPIs ────────────────────────────────────────────────────
    total_calls   = int(df_active["Total Calls"].sum())
    total_inbound = int(df_active["Inbound"].sum())
    total_outbound= int(df_active["Outbound"].sum())
    total_missed  = int(df_active["Missed with VM"].sum())
    missed_pct    = round(total_missed / total_inbound * 100, 1) if total_inbound > 0 else 0
    n_agents      = len(df_active)
    top_agent     = df_active.iloc[0]["Name"] if len(df_active) else "—"
    top_agent_calls = int(df_active.iloc[0]["Total Calls"]) if len(df_active) else 0

    c1, c2, c3, c4 = st.columns(4)
    with c1: st.markdown(kpi("Total Calls", f"{total_calls:,}",
                              sub=f"{n_agents} active agents"), unsafe_allow_html=True)
    with c2: st.markdown(kpi("Inbound", f"{total_inbound:,}",
                              sub=f"{round(total_inbound/total_calls*100,1) if total_calls > 0 else 0}% of total"),
                         unsafe_allow_html=True)
    with c3: st.markdown(kpi("Outbound", f"{total_outbound:,}",
                              sub=f"{round(total_outbound/total_calls*100,1) if total_calls > 0 else 0}% of total"),
                         unsafe_allow_html=True)
    with c4: st.markdown(kpi("Missed with VM", f"{total_missed:,}",
                              sub=f"{missed_pct}% of inbound calls",
                              status="warn" if missed_pct > 5 else "good"),
                         unsafe_allow_html=True)

    # ── Charts row ────────────────────────────────────────────────────────
    col_l, col_r = st.columns(2)

    with col_l:
        section("Total Calls by Agent")
        fig_calls = go.Figure(go.Bar(
            y=df_active["Name"],
            x=df_active["Total Calls"],
            orientation="h",
            marker_color=PC,
            text=df_active["Total Calls"].map(lambda x: f"{x:,}"),
            textposition="outside",
        ))
        fig_calls.update_layout(
            template="dfm",
            height=max(340, len(df_active) * 22 + 60),
            xaxis=dict(title="Total Calls", gridcolor="#F1F5F9"),
            yaxis=dict(title="", autorange="reversed"),
            paper_bgcolor="#FFFFFF", plot_bgcolor="#FFFFFF",
            margin=dict(l=0, r=60, t=10, b=30),
        )
        st.plotly_chart(fig_calls, width="stretch")

    with col_r:
        section("Inbound vs Outbound by Agent (Top 15)")
        df_top15 = df_active.head(15).sort_values("Inbound")
        fig_io = go.Figure()
        fig_io.add_trace(go.Bar(
            y=df_top15["Name"], x=df_top15["Inbound"],
            name="Inbound", orientation="h",
            marker_color="#3B82F6",
        ))
        fig_io.add_trace(go.Bar(
            y=df_top15["Name"], x=df_top15["Outbound"],
            name="Outbound", orientation="h",
            marker_color=PC,
        ))
        fig_io.update_layout(
            barmode="stack",
            template="dfm",
            height=max(340, len(df_top15) * 22 + 60),
            xaxis=dict(title="Calls", gridcolor="#F1F5F9"),
            yaxis=dict(title=""),
            legend=dict(orientation="h", y=-0.12),
            paper_bgcolor="#FFFFFF", plot_bgcolor="#FFFFFF",
            margin=dict(l=0, r=20, t=10, b=50),
        )
        st.plotly_chart(fig_io, width="stretch")

    # ── Missed VM rate ────────────────────────────────────────────────────
    section("Missed with VM Rate by Agent  (inbound calls only)")

    def _vm_color(p):
        if p > 15: return "#7F1D1D"   # deep crimson — very high
        if p > 10: return "#9F1239"   # rose-dark — high
        if p > 5:  return "#B45309"   # warm amber — above threshold
        return "#1E40AF"              # deep blue — within target

    df_miss = df_active[df_active["Inbound"] > 0].copy()
    df_miss = df_miss.sort_values("Missed VM %", ascending=False)  # worst at top
    bar_colors_miss = [_vm_color(p) for p in df_miss["Missed VM %"]]

    st.markdown(
        '<p style="font-size:11px;color:#6B7280;margin-bottom:6px;">'
        '<span style="display:inline-block;width:10px;height:10px;border-radius:2px;background:#1E40AF;margin-right:4px;vertical-align:middle;"></span>On target (≤5%) &nbsp;'
        '<span style="display:inline-block;width:10px;height:10px;border-radius:2px;background:#B45309;margin-right:4px;vertical-align:middle;"></span>Above threshold (5–10%) &nbsp;'
        '<span style="display:inline-block;width:10px;height:10px;border-radius:2px;background:#9F1239;margin-right:4px;vertical-align:middle;"></span>High (10–15%) &nbsp;'
        '<span style="display:inline-block;width:10px;height:10px;border-radius:2px;background:#7F1D1D;margin-right:4px;vertical-align:middle;"></span>Critical (&gt;15%)'
        '</p>',
        unsafe_allow_html=True,
    )
    fig_miss = go.Figure(go.Bar(
        y=df_miss["Name"],
        x=df_miss["Missed VM %"],
        orientation="h",
        marker=dict(color=bar_colors_miss, opacity=0.88),
        text=df_miss["Missed VM %"].map(lambda x: f"{x:.1f}%"),
        textposition="outside",
        textfont=dict(size=11, color="#374151"),
    ))
    fig_miss.add_vline(x=5, line_dash="dot", line_color="#6B7280",
                       annotation_text="5% target",
                       annotation_position="top right",
                       annotation_font=dict(size=10, color="#6B7280"))
    fig_miss.update_layout(
        template="dfm",
        height=max(280, len(df_miss) * 26 + 60),
        xaxis=dict(title="Missed with VM %", ticksuffix="%", gridcolor="#F1F5F9",
                   tickfont=dict(size=11)),
        yaxis=dict(title="", tickfont=dict(size=11), autorange="reversed"),
        paper_bgcolor="#FFFFFF", plot_bgcolor="#FFFFFF",
        margin=dict(l=0, r=80, t=10, b=30),
    )
    st.plotly_chart(fig_miss, width="stretch")

    # ── Full detail table ─────────────────────────────────────────────────
    section("Agent Call Detail")
    df_tbl = df_calls.copy()
    df_tbl["Avg Daily"] = df_tbl["Avg Daily"].map(lambda x: f"{x:.0f}")
    df_tbl["Missed VM %"] = df_tbl["Missed VM %"].map(lambda x: f"{x:.1f}%")
    c_ct, c_dct = st.columns([5, 1])
    with c_ct:
        st.dataframe(df_tbl, width="stretch", hide_index=True, height=min(600, len(df_tbl) * 36 + 40))
    with c_dct:
        download_btn(df_calls, "calls_march_2026.csv")


# ============================================================================
# PAGE 9 — SEARCH
# ============================================================================

elif st.session_state.page == "Search":
    page_header("Search", "Find tenants, units, properties, and work orders across all data")

    _sq = st.text_input("", placeholder="Type a tenant name, unit number, property, or address…",
                        label_visibility="collapsed")

    if not _sq or len(_sq.strip()) < 2:
        st.markdown(
            '<div style="text-align:center;padding:48px 0;color:#94A3B8;">'
            '<div style="font-size:32px;margin-bottom:12px;">🔍</div>'
            '<div style="font-size:15px;font-weight:600;color:#64748B;">Search across all data</div>'
            '<div style="font-size:13px;margin-top:6px;">Rent roll · Work orders · Applications · Leads</div>'
            '</div>',
            unsafe_allow_html=True,
        )
    else:
        _q = _sq.strip().lower()
        _total_hits = 0

        def _search_df(df, search_cols, label_cols, source_label, badge_col=None):
            """Return matching rows from df as list of display dicts."""
            if df is None or len(df) == 0:
                return []
            mask = pd.Series(False, index=df.index)
            for col in search_cols:
                if col in df.columns:
                    mask |= df[col].astype(str).str.lower().str.contains(_q, na=False)
            hits = df[mask].copy()
            if hits.empty:
                return []
            rows = []
            for _, row in hits.iterrows():
                fields = {c: str(row[c]) if c in row.index and pd.notna(row[c]) else "—"
                          for c in label_cols if c in df.columns}
                badge = str(row[badge_col]) if badge_col and badge_col in row.index else None
                rows.append({"source": source_label, "fields": fields, "badge": badge})
            return rows

        _badge_colors = {
            "Current":          ("#DCFCE7","#166534"),
            "Vacant-Unrented":  ("#FEE2E2","#991B1B"),
            "Vacant-Rented":    ("#FEF9C3","#854D0E"),
            "Notice-Unrented":  ("#FEF3C7","#92400E"),
            "Notice-Rented":    ("#EDE9FE","#5B21B6"),
            "Evict":            ("#FEE2E2","#7F1D1D"),
            "Open":             ("#FEE2E2","#991B1B"),
            "In Progress":      ("#FEF9C3","#854D0E"),
            "Completed":        ("#DCFCE7","#166534"),
            "Active":           ("#DCFCE7","#166534"),
            "Inactive":         ("#F1F5F9","#475569"),
        }

        def _render_results(results, icon):
            for r in results:
                _bg, _bc = _badge_colors.get(r["badge"] or "", ("#F1F5F9","#475569"))
                _badge_html = (
                    f'<span style="background:{_bg};color:{_bc};padding:2px 8px;border-radius:999px;'
                    f'font-size:10px;font-weight:700;">{r["badge"]}</span>'
                ) if r["badge"] else ""
                _fields_html = "  ·  ".join(
                    f'<span style="color:#64748B;">{k}:</span> <span style="color:#0F172A;font-weight:600;">{v}</span>'
                    for k, v in r["fields"].items() if v not in ("—", "nan", "None")
                )
                st.markdown(
                    f'<div style="display:flex;align-items:flex-start;gap:12px;padding:11px 16px;'
                    f'margin-bottom:5px;border-radius:9px;background:#FFFFFF;'
                    f'border:1px solid #E2E8F0;border-left:4px solid {PC};">'
                    f'<span style="font-size:16px;margin-top:1px;">{icon}</span>'
                    f'<div style="flex:1;min-width:0;">'
                    f'<div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:4px;">'
                    f'<span style="font-size:10px;font-weight:700;color:#94A3B8;text-transform:uppercase;letter-spacing:.08em;">{r["source"]}</span>'
                    f'{_badge_html}</div>'
                    f'<div style="font-size:12.5px;color:#374151;line-height:1.6;">{_fields_html}</div>'
                    f'</div></div>',
                    unsafe_allow_html=True,
                )

        # ── Rent Roll ─────────────────────────────────────────────────────
        _rr_hits = _search_df(
            df_rr,
            search_cols=["Tenant", "Unit", "Property", "Unit ID"],
            label_cols=["Tenant", "Property", "Unit", "Status", "Rent"],
            source_label="Rent Roll",
            badge_col="Status",
        )
        if _rr_hits:
            _total_hits += len(_rr_hits)
            section(f"Rent Roll  ·  {len(_rr_hits)} match{'es' if len(_rr_hits)>1 else ''}")
            _render_results(_rr_hits[:20], "🏠")

        # ── Work Orders ───────────────────────────────────────────────────
        _wo_hits = _search_df(
            df_wo,
            search_cols=["Property", "Unit", "Work Order Issue", "Vendor"],
            label_cols=["Property", "Unit", "Work Order Issue", "Status", "Vendor"],
            source_label="Work Orders",
            badge_col="Status",
        )
        if _wo_hits:
            _total_hits += len(_wo_hits)
            section(f"Work Orders  ·  {len(_wo_hits)} match{'es' if len(_wo_hits)>1 else ''}")
            _render_results(_wo_hits[:20], "🔧")

        # ── Applications ──────────────────────────────────────────────────
        _app_hits = _search_df(
            df_apps,
            search_cols=["Applicant", "Property", "Property Name"],
            label_cols=["Applicant", "Property", "Status"],
            source_label="Applications",
            badge_col="Status",
        )
        if _app_hits:
            _total_hits += len(_app_hits)
            section(f"Applications  ·  {len(_app_hits)} match{'es' if len(_app_hits)>1 else ''}")
            _render_results(_app_hits[:20], "📋")

        # ── Leads / Guest Cards ───────────────────────────────────────────
        _lead_hits = _search_df(
            df_leads_df,
            search_cols=["Name", "Property", "Email", "Phone"],
            label_cols=["Name", "Property", "Status", "Monthly Income"],
            source_label="Guest Cards",
            badge_col="Status",
        )
        if _lead_hits:
            _total_hits += len(_lead_hits)
            section(f"Guest Cards  ·  {len(_lead_hits)} match{'es' if len(_lead_hits)>1 else ''}")
            _render_results(_lead_hits[:20], "👤")

        # ── Renewals ─────────────────────────────────────────────────────
        _renew_hits = _search_df(
            df_renew,
            search_cols=["Tenant Name", "Property", "Unit Name"],
            label_cols=["Tenant Name", "Property", "Unit Name", "Status", "Rent"],
            source_label="Renewals",
            badge_col="Status",
        )
        if _renew_hits:
            _total_hits += len(_renew_hits)
            section(f"Renewals  ·  {len(_renew_hits)} match{'es' if len(_renew_hits)>1 else ''}")
            _render_results(_renew_hits[:20], "🔄")

        if _total_hits == 0:
            st.info(f'No results found for "{_sq}". Try a partial name, unit number, or property.')
        else:
            st.caption(f"{_total_hits} total result{'s' if _total_hits>1 else ''} across all data sources")
