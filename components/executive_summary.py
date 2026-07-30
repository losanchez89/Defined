import html

import pandas as pd
import streamlit as st


def _calculate_collection_rate(df_rr):
    """
    Calcula Collection Rate usando únicamente Current tenants
    y valores positivos de Past Due.
    """
    if (
        df_rr is None
        or df_rr.empty
        or "Status" not in df_rr.columns
        or "Rent" not in df_rr.columns
    ):
        return 0.0

    current = df_rr[
        df_rr["Status"].astype(str).str.strip() == "Current"
    ].copy()

    if current.empty:
        return 0.0

    rent = pd.to_numeric(
        current["Rent"], errors="coerce"
    ).fillna(0).sum()

    if rent <= 0:
        return 0.0

    if "Past Due" not in current.columns:
        return 100.0

    past_due = pd.to_numeric(
        current["Past Due"], errors="coerce"
    ).fillna(0)

    # Solo números positivos.
    positive_past_due = past_due.clip(lower=0).sum()

    return max(
        0.0,
        min(
            100.0,
            (rent - positive_past_due) / rent * 100,
        ),
    )


def _previous_collection_rate(df_hist):
    """
    Obtiene el Collection Rate del snapshot anterior.
    """
    if df_hist is None or len(df_hist) < 2:
        return None

    try:
        hist = df_hist.copy()

        date_col = "date" if "date" in hist.columns else "Date"

        collection_col = (
            "collection_rate"
            if "collection_rate" in hist.columns
            else "Collection Rate"
        )

        if date_col not in hist.columns or collection_col not in hist.columns:
            return None

        hist[date_col] = pd.to_datetime(
            hist[date_col], errors="coerce"
        )

        hist[collection_col] = pd.to_numeric(
            hist[collection_col], errors="coerce"
        )

        hist = (
            hist.dropna(subset=[date_col, collection_col])
            .sort_values(date_col)
        )

        if len(hist) < 2:
            return None

        return float(hist.iloc[-2][collection_col])

    except Exception:
        return None


def _long_term_vacancies(df_vacancy, days=30):
    """
    Cuenta las unidades con más de `days` días vacantes.
    """
    if (
        df_vacancy is None
        or df_vacancy.empty
        or "Days Vacant" not in df_vacancy.columns
    ):
        return 0

    days_vacant = pd.to_numeric(
        df_vacancy["Days Vacant"], errors="coerce"
    ).fillna(0)

    return int((days_vacant > days).sum())


def _open_work_orders(df_work_orders):
    """
    Cuenta work orders que todavía no están completados o cancelados.
    """
    if (
        df_work_orders is None
        or df_work_orders.empty
        or "Status" not in df_work_orders.columns
    ):
        return 0

    closed_statuses = {
        "completed",
        "closed",
        "cancelled",
        "canceled",
    }

    status = (
        df_work_orders["Status"]
        .fillna("")
        .astype(str)
        .str.strip()
        .str.lower()
    )

    return int((~status.isin(closed_statuses)).sum())


def _summary_item(status, title, message):
    styles = {
        "good": {
            "background": "#ECFDF5",
            "border": "#10B981",
            "icon": "✓",
            "icon_background": "#D1FAE5",
            "icon_color": "#047857",
        },
        "warning": {
            "background": "#FFFBEB",
            "border": "#F59E0B",
            "icon": "!",
            "icon_background": "#FEF3C7",
            "icon_color": "#B45309",
        },
        "bad": {
            "background": "#FEF2F2",
            "border": "#EF4444",
            "icon": "!",
            "icon_background": "#FEE2E2",
            "icon_color": "#B91C1C",
        },
        "info": {
            "background": "#EFF6FF",
            "border": "#3B82F6",
            "icon": "i",
            "icon_background": "#DBEAFE",
            "icon_color": "#1D4ED8",
        },
    }

    style = styles.get(status, styles["info"])
    safe_title = html.escape(str(title))
    safe_message = html.escape(str(message))

    # HTML compacto, sin saltos de línea ni sangrías.
    # Esto evita que Markdown interprete los <div> internos como código.
    return (
        f'<div style="background:{style["background"]};'
        f'border-left:4px solid {style["border"]};'
        'border-radius:10px;padding:13px 15px;display:flex;'
        'align-items:flex-start;gap:12px;min-height:72px;">'
        f'<div style="width:25px;height:25px;border-radius:50%;'
        f'background:{style["icon_background"]};'
        f'color:{style["icon_color"]};display:flex;align-items:center;'
        'justify-content:center;font-size:13px;font-weight:800;'
        f'flex-shrink:0;">{style["icon"]}</div>'
        '<div>'
        '<div style="color:#0F172A;font-size:12px;font-weight:800;'
        f'margin-bottom:4px;">{safe_title}</div>'
        '<div style="color:#475569;font-size:11.5px;line-height:1.45;">'
        f'{safe_message}</div>'
        '</div>'
        '</div>'
    )


def render(context):
    """
    Renderiza el Executive Summary del Overview.
    """

    totals = context.get("_totals", {})
    physical_occ = float(context.get("_phys_occ", 0) or 0)
    economic_occ = float(context.get("_econ_occ", 0) or 0)

    df_rr = context.get("df_rr_f")
    df_vacancy = (
        context.get("df_vac_f")
        if context.get("df_vac_f") is not None
        else context.get("df_vacancy_f")
    )
    df_work_orders = (
        context.get("df_wo_f")
        if context.get("df_wo_f") is not None
        else context.get("df_work_orders_f")
    )
    df_hist = context.get("df_hist")

    collection_rate = _calculate_collection_rate(df_rr)
    previous_collection = _previous_collection_rate(df_hist)

    vacant_units = int(
        totals.get("Vacant-Unrented", 0) or 0
    )

    long_term_vacancies = _long_term_vacancies(
        df_vacancy,
        days=30,
    )

    open_work_orders = _open_work_orders(df_work_orders)

    messages = []

    # Physical Occupancy
    if physical_occ >= 95:
        messages.append(
            (
                "good",
                "Physical Occupancy",
                (
                    f"Physical occupancy is {physical_occ:.2f}%, "
                    "above the 95% portfolio target."
                ),
            )
        )
    elif physical_occ >= 92:
        messages.append(
            (
                "warning",
                "Physical Occupancy",
                (
                    f"Physical occupancy is {physical_occ:.2f}%, "
                    "slightly below the 95% target."
                ),
            )
        )
    else:
        messages.append(
            (
                "bad",
                "Physical Occupancy",
                (
                    f"Physical occupancy is {physical_occ:.2f}%, "
                    "below the expected portfolio level."
                ),
            )
        )

    # Economic Occupancy
    if economic_occ >= 95:
        messages.append(
            (
                "good",
                "Economic Occupancy",
                (
                    f"Economic occupancy is {economic_occ:.2f}% "
                    "and remains above target."
                ),
            )
        )
    elif economic_occ >= 92:
        messages.append(
            (
                "warning",
                "Economic Occupancy",
                (
                    f"Economic occupancy is {economic_occ:.2f}% "
                    "and should be monitored."
                ),
            )
        )
    else:
        messages.append(
            (
                "bad",
                "Economic Occupancy",
                (
                    f"Economic occupancy is {economic_occ:.2f}%, "
                    "indicating a meaningful revenue gap."
                ),
            )
        )

    # Collection Rate
    if collection_rate >= 95:
        collection_status = "good"
        collection_message = (
            f"Collection rate is {collection_rate:.2f}% "
            "and is performing strongly."
        )
    elif collection_rate >= 90:
        collection_status = "warning"
        collection_message = (
            f"Collection rate is {collection_rate:.2f}% "
            "and remains below the preferred 95% level."
        )
    else:
        collection_status = "bad"
        collection_message = (
            f"Collection rate is {collection_rate:.2f}% "
            "and requires close monitoring."
        )

    if previous_collection is not None:
        change = collection_rate - previous_collection

        if abs(change) < 0.01:
            collection_message += " It is unchanged from the prior snapshot."
        elif change > 0:
            collection_message += (
                f" It improved {change:.2f} points "
                "from the prior snapshot."
            )
        else:
            collection_message += (
                f" It decreased {abs(change):.2f} points "
                "from the prior snapshot."
            )

    messages.append(
        (
            collection_status,
            "Collection Rate",
            collection_message,
        )
    )

    # Vacancy
    if long_term_vacancies > 0:
        messages.append(
            (
                "bad" if long_term_vacancies >= 10 else "warning",
                "Vacancy Exposure",
                (
                    f"{vacant_units} units are currently vacant-unrented, "
                    f"including {long_term_vacancies} vacant for more "
                    "than 30 days."
                ),
            )
        )
    else:
        messages.append(
            (
                "good",
                "Vacancy Exposure",
                (
                    f"{vacant_units} units are currently vacant-unrented, "
                    "with no units exceeding 30 days vacant."
                ),
            )
        )

    # Work orders
    if open_work_orders > 0:
        messages.append(
            (
                "warning" if open_work_orders < 30 else "bad",
                "Maintenance Activity",
                (
                    f"{open_work_orders} work orders are currently open "
                    "across the selected portfolio."
                ),
            )
        )

    st.markdown(
        """
        <div style="
            font-size:10.5px;
            font-weight:800;
            color:#64748B;
            text-transform:uppercase;
            letter-spacing:.14em;
            padding:18px 0 10px 0;
            margin-bottom:12px;
            border-bottom:1px solid #E2E8F0;
        ">
            Executive Summary
        </div>
        """,
        unsafe_allow_html=True,
    )

    # Mostrar máximo 4 mensajes para mantener el Overview compacto.
    messages = messages[:4]

    columns = st.columns(2)

    for index, (status, title, message) in enumerate(messages):
        with columns[index % 2]:
            st.markdown(
                _summary_item(
                    status,
                    title,
                    message,
                ),
                unsafe_allow_html=True,
            )