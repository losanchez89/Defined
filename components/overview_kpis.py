import streamlit as st


def render(context):
    """
    Overview KPI cards
    """

    kpi = context["kpi"]
    section = context["section"]
    THR = context["THR"]
    PC = context["PC"]
    _tl = context["_tl"]

    totals = context["_totals"]
    df_metrics = context["df_metrics_f"]
    df_rr = context["df_rr_f"]
    df_renew = context["df_renew_f"]

    phys_occ = context["_phys_occ"]
    econ_occ = context["_econ_occ"]

    exp30 = context["exp30"]
    exp60 = context["exp60"]
    exp90 = context["exp90"]

    delta_phys = context.get("delta_phys")
    delta_econ = context.get("delta_econ")
    delta_coll = context.get("delta_coll")
    prev_label = context.get("_prev_date_label", "previous month")

    total_units = int(totals.get("Total Units", 0))
    vacant_units = int(totals.get("Vacant-Unrented", 0))
    evict_units = int(totals.get("Evict", 0))
    notice_unr = int(totals.get("Notice-Unrented", 0))
    notice_ren = int(totals.get("Notice-Rented", 0))

    revenue_gap = 0
    if (
        df_metrics is not None
        and "Revenue Gap ($)" in df_metrics.columns
    ):
        revenue_gap = float(df_metrics["Revenue Gap ($)"].sum())

    # ----------------------------------------------------
    # Collection Rate
    # ----------------------------------------------------
    sum_rent = 0
    pct_collected = 0

    if df_rr is not None and "Rent" in df_rr.columns:
        df_curr = df_rr[df_rr["Status"] == "Current"]

        sum_rent = float(df_curr["Rent"].sum())

        if "Past Due" in df_curr.columns and sum_rent > 0:
            pd_sum = (
                context["clean_money_column"](df_curr["Past Due"])
                .clip(lower=0)
                .sum()
            )

            pct_collected = max(
                0,
                min(
                    100,
                    (sum_rent - pd_sum) / sum_rent * 100,
                ),
            )

    # ----------------------------------------------------
    # Renewal Rate
    # ----------------------------------------------------
    renewal_rate = 0

    if df_renew is not None and "Status" in df_renew.columns:

        actionable = df_renew[
            df_renew["Status"].isin(
                [
                    "Renewed",
                    "Did Not Renew",
                    "Canceled by User",
                ]
            )
        ]

        if len(actionable):

            renewal_rate = (
                len(actionable[actionable["Status"] == "Renewed"])
                / len(actionable)
                * 100
            )

    # ====================================================
    # OCCUPANCY
    # ====================================================

    section("Occupancy")

    c1, c2, c3 = st.columns(3)

    with c1:
        st.markdown(
            kpi(
                "Total Units",
                f"{total_units:,}",
                sub="Total managed units",
            ),
            unsafe_allow_html=True,
        )

    with c2:
        st.markdown(
            kpi(
                "Physical Occupancy",
                f"{phys_occ:.1f}%",
                delta_phys,
                "%",
                _tl(phys_occ, THR["physical_occ"]),
                sub=f"Target {THR['physical_occ']}% · Vacant: {vacant_units}",
                delta_label=prev_label,
            ),
            unsafe_allow_html=True,
        )

    with c3:
        st.markdown(
            kpi(
                "Economic Occupancy",
                f"{econ_occ:.1f}%",
                delta_econ,
                "%",
                _tl(econ_occ, THR["economic_occ"]),
                sub=f"Target {THR['economic_occ']}%",
                delta_label=prev_label,
            ),
            unsafe_allow_html=True,
        )

    # ====================================================
    # FINANCIALS
    # ====================================================

    section("Financials")

    c4, c5, c6 = st.columns(3)

    with c4:
        st.markdown(
            kpi(
                "Monthly Rent (Current)",
                f"${sum_rent:,.0f}",
                sub="Current residents",
            ),
            unsafe_allow_html=True,
        )

    with c5:
        st.markdown(
            kpi(
                "% Collected",
                f"{pct_collected:.1f}%",
                delta_coll,
                "%",
                status=_tl(
                    pct_collected,
                    THR["collection_rate"],
                ),
                sub=f"Target {THR['collection_rate']}%",
                delta_label=prev_label,
            ),
            unsafe_allow_html=True,
        )

    with c6:
        st.markdown(
            kpi(
                "Revenue Gap",
                f"${revenue_gap:,.0f}",
                sub="Vacant + Evict",
            ),
            unsafe_allow_html=True,
        )

    # ====================================================
    # LEASING
    # ====================================================

    section("Leasing & Retention")

    c7, c8, c9, c10 = st.columns(4)

    with c7:
        st.markdown(
            kpi(
                "Vacant (Unrented)",
                f"{vacant_units:,}",
                sub=f"{evict_units} in eviction",
            ),
            unsafe_allow_html=True,
        )

    with c8:
        st.markdown(
            kpi(
                "On Notice",
                f"{notice_unr + notice_ren:,}",
                sub=f"{notice_unr} leaving · {notice_ren} re-leased",
            ),
            unsafe_allow_html=True,
        )

    with c9:
        st.markdown(
            kpi(
                "Lease Expiring (30d)",
                f"{exp30:,}",
                sub=f"{exp60} in 60d · {exp90} in 90d",
            ),
            unsafe_allow_html=True,
        )

    with c10:
        st.markdown(
            kpi(
                "Renewal Rate",
                f"{renewal_rate:.1f}%",
                status=_tl(
                    renewal_rate,
                    THR["renewal_rate"],
                ),
                sub=f"Target {THR['renewal_rate']}%",
            ),
            unsafe_allow_html=True,
        )