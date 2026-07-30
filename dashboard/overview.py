from components.executive_summary import render as render_executive_summary


def render(context):
    page_header = context["page_header"]
    company = context["COMPANY"]
    now = context["now"]

    page_header(
        company,
        (
            f"Portfolio Snapshot · "
            f"{now().strftime('%B %d, %Y')} · "
            f"{now().strftime('%I:%M %p').lstrip('0')}"
        ),
    )

    render_executive_summary(context)

    # Executive Score temporalmente desactivado
    # hasta corregir components/executive_score.py