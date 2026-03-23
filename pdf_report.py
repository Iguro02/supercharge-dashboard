"""
pdf_report.py — Monthly PDF report using ReportLab.
Branded with SuperCharge SG colours. Downloadable on demand.
"""
import io
from datetime import datetime, timezone
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import cm
from reportlab.lib import colors
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, HRFlowable
)
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.enums import TA_CENTER, TA_LEFT

# SuperCharge brand colours
SC_GREEN = colors.HexColor("#1D9E75")
SC_DARK = colors.HexColor("#085041")
SC_LIGHT = colors.HexColor("#E1F5EE")
SC_GRAY = colors.HexColor("#888780")
SC_BLACK = colors.HexColor("#2C2C2A")


def _styles():
    styles = getSampleStyleSheet()
    styles.add(ParagraphStyle(
        "SCTitle",
        fontSize=22, textColor=SC_DARK, fontName="Helvetica-Bold",
        spaceAfter=4, alignment=TA_LEFT
    ))
    styles.add(ParagraphStyle(
        "SCSubtitle",
        fontSize=11, textColor=SC_GRAY, fontName="Helvetica",
        spaceAfter=16, alignment=TA_LEFT
    ))
    styles.add(ParagraphStyle(
        "SCSection",
        fontSize=13, textColor=SC_DARK, fontName="Helvetica-Bold",
        spaceBefore=14, spaceAfter=6
    ))
    styles.add(ParagraphStyle(
        "SCBody",
        fontSize=10, textColor=SC_BLACK, fontName="Helvetica",
        spaceAfter=6, leading=15
    ))
    return styles


def generate_monthly_report(
    client_name: str,
    site_name: str,
    solar_kwh: float,
    ev_sessions: int,
    ev_kwh: float,
    ecis_credits: float,
    anomaly_log: list[dict],
    month_label: str = None,
) -> bytes:
    """
    Generate a branded monthly PDF report.
    Returns raw PDF bytes for streaming download.
    """
    buffer = io.BytesIO()
    doc = SimpleDocTemplate(
        buffer, pagesize=A4,
        leftMargin=2*cm, rightMargin=2*cm,
        topMargin=2*cm, bottomMargin=2*cm
    )
    S = _styles()
    now = datetime.now(timezone.utc)
    month_label = month_label or now.strftime("%B %Y")
    story = []

    # ── Header ──────────────────────────────────────────────────────────────
    story.append(Paragraph("⚡ SuperCharge SG", S["SCTitle"]))
    story.append(Paragraph(f"Monthly Energy Report · {month_label}", S["SCSubtitle"]))
    story.append(HRFlowable(width="100%", thickness=2, color=SC_GREEN))
    story.append(Spacer(1, 0.4*cm))

    story.append(Paragraph(f"<b>Client:</b> {client_name}", S["SCBody"]))
    story.append(Paragraph(f"<b>Site:</b> {site_name}", S["SCBody"]))
    story.append(Paragraph(f"<b>Report generated:</b> {now.strftime('%d %b %Y, %H:%M SGT')}", S["SCBody"]))
    story.append(Spacer(1, 0.5*cm))

    # ── Site summary table ───────────────────────────────────────────────────
    story.append(Paragraph("Site Performance Summary", S["SCSection"]))

    co2_kg = round(solar_kwh * 0.4233, 1)
    exported_kwh = round(solar_kwh * 0.30, 1)

    summary_data = [
        ["Metric", "Value"],
        ["Total solar generated", f"{solar_kwh:.1f} kWh"],
        ["Estimated solar exported (30%)", f"{exported_kwh} kWh"],
        ["ECIS export credits earned", f"SGD {ecis_credits:.2f}"],
        ["EV charging sessions", str(ev_sessions)],
        ["Total EV energy delivered", f"{ev_kwh:.1f} kWh"],
        ["EV charging revenue", f"SGD {ev_kwh * 0.50:.2f}"],
        ["CO₂ emissions avoided", f"{co2_kg} kg"],
        ["Equivalent trees planted", f"~{int(co2_kg / 21.7)} trees"],
    ]

    tbl = Table(summary_data, colWidths=[9*cm, 7*cm])
    tbl.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), SC_DARK),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, 0), 11),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [SC_LIGHT, colors.white]),
        ("FONTNAME", (0, 1), (-1, -1), "Helvetica"),
        ("FONTSIZE", (0, 1), (-1, -1), 10),
        ("TEXTCOLOR", (0, 1), (-1, -1), SC_BLACK),
        ("GRID", (0, 0), (-1, -1), 0.5, SC_GRAY),
        ("LEFTPADDING", (0, 0), (-1, -1), 10),
        ("RIGHTPADDING", (0, 0), (-1, -1), 10),
        ("TOPPADDING", (0, 0), (-1, -1), 7),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 7),
    ]))
    story.append(tbl)
    story.append(Spacer(1, 0.5*cm))

    # ── ECIS section ─────────────────────────────────────────────────────────
    story.append(Paragraph("ECIS Export Credit Calculation", S["SCSection"]))
    story.append(Paragraph(
        f"Exported energy: <b>{exported_kwh} kWh</b> × SGD 0.218/kWh "
        f"= <b>SGD {ecis_credits:.2f}</b><br/>"
        "Rate source: SP Group Enhanced Central Intermediary Scheme (ECIS). "
        "Credits applied to SP electricity bill.",
        S["SCBody"]
    ))
    story.append(Spacer(1, 0.3*cm))

    # ── Anomaly log ──────────────────────────────────────────────────────────
    story.append(Paragraph("Anomaly Log", S["SCSection"]))

    if not anomaly_log:
        story.append(Paragraph("No anomalies detected this month. All systems operating normally.", S["SCBody"]))
    else:
        anom_data = [["Timestamp", "Severity", "Actual kW", "Expected kW", "Drop %"]]
        for a in anomaly_log[:15]:  # cap at 15 rows
            ts = a.get("ts", "")[:16].replace("T", " ")
            sev = a.get("anomaly_severity", "WARNING")
            actual = a.get("power_kw", 0)
            expected = a.get("expected_kw", 0) or 1
            drop = round((1 - actual / expected) * 100, 1)
            anom_data.append([ts, sev, f"{actual:.2f}", f"{expected:.2f}", f"{drop}%"])

        anom_tbl = Table(anom_data, colWidths=[4.5*cm, 3*cm, 2.5*cm, 3*cm, 2.5*cm])
        anom_tbl.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), SC_DARK),
            ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
            ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
            ("FONTSIZE", (0, 0), (-1, -1), 9),
            ("FONTNAME", (0, 1), (-1, -1), "Helvetica"),
            ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.HexColor("#FFF3F3"), colors.white]),
            ("GRID", (0, 0), (-1, -1), 0.5, SC_GRAY),
            ("LEFTPADDING", (0, 0), (-1, -1), 8),
            ("TOPPADDING", (0, 0), (-1, -1), 5),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
        ]))
        story.append(anom_tbl)

    story.append(Spacer(1, 0.8*cm))

    # ── Footer ───────────────────────────────────────────────────────────────
    story.append(HRFlowable(width="100%", thickness=1, color=SC_GRAY))
    story.append(Spacer(1, 0.2*cm))
    story.append(Paragraph(
        "SuperCharge SG · supercharge.sg · support@supercharge.sg · LTA-licensed EVCO",
        ParagraphStyle("Footer", fontSize=8, textColor=SC_GRAY, alignment=TA_CENTER)
    ))

    doc.build(story)
    return buffer.getvalue()
