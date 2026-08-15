from __future__ import annotations

from io import BytesIO
from xml.sax.saxutils import escape

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import (
    PageBreak,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

from app.domain.command_center.schemas import CommandCenterResponse

_TEAL = colors.HexColor("#006D77")
_INK = colors.HexColor("#162322")
_MUTED = colors.HexColor("#5B6B69")
_HAIRLINE = colors.HexColor("#D8E2E0")
_SUBTLE = colors.HexColor("#E6F4F3")


def _metric(value: float | int | None, suffix: str = "") -> str:
    return "—" if value is None else f"{value:g}{suffix}"


def _paragraph_text(value: object) -> str:
    return escape(str(value))


def render_executive_pdf(command_center: CommandCenterResponse) -> bytes:
    measurement = command_center.measurement
    if measurement is None:
        raise ValueError("An executive report requires a completed audit")
    """Render a provider-free report from the command-center projection."""
    buffer = BytesIO()
    document = SimpleDocTemplate(
        buffer,
        pagesize=A4,
        leftMargin=18 * mm,
        rightMargin=18 * mm,
        topMargin=16 * mm,
        bottomMargin=16 * mm,
        title=f"CiteLadder executive report — {command_center.project.brand_name}",
        author="CiteLadder",
        pageCompression=0,
    )
    styles = getSampleStyleSheet()
    title = ParagraphStyle(
        "Title",
        parent=styles["Title"],
        fontName="Helvetica-Bold",
        fontSize=24,
        leading=28,
        textColor=_INK,
        spaceAfter=8,
    )
    heading = ParagraphStyle(
        "Heading",
        parent=styles["Heading2"],
        fontName="Helvetica-Bold",
        fontSize=13,
        textColor=_INK,
        spaceBefore=14,
        spaceAfter=7,
    )
    body = ParagraphStyle(
        "Body", parent=styles["BodyText"], fontSize=9, leading=13, textColor=_MUTED
    )
    story = [
        Paragraph("CiteLadder", ParagraphStyle("Brand", parent=body, textColor=_TEAL)),
        Paragraph(
            f"{_paragraph_text(command_center.project.brand_name)} executive report",
            title,
        ),
        Paragraph(
            f"Completed {measurement.completed_at:%d %b %Y} · "
            f"{_paragraph_text(measurement.measurement_mode)} "
            "measurement",
            body,
        ),
        Spacer(1, 8 * mm),
        Paragraph("Current state", heading),
    ]
    state = command_center.state
    state_table = Table(
        [
            ["Visibility", "Share of voice", "Deterministic rank"],
            [
                _metric(state.visibility.value),
                _metric(state.share_of_voice.value, "%"),
                _metric(state.brand_rank.value),
            ],
            [
                f"Δ {_metric(state.visibility.delta)}",
                f"Δ {_metric(state.share_of_voice.delta)}",
                f"Δ {_metric(state.brand_rank.delta)}",
            ],
        ],
        colWidths=[58 * mm, 58 * mm, 58 * mm],
    )
    state_table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, 0), _SUBTLE),
                ("TEXTCOLOR", (0, 0), (-1, 0), _TEAL),
                ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                ("FONTNAME", (0, 1), (-1, 1), "Helvetica-Bold"),
                ("FONTSIZE", (0, 1), (-1, 1), 18),
                ("TEXTCOLOR", (0, 1), (-1, -1), _INK),
                ("GRID", (0, 0), (-1, -1), 0.5, _HAIRLINE),
                ("BOX", (0, 0), (-1, -1), 0.5, _HAIRLINE),
                ("TOPPADDING", (0, 0), (-1, -1), 7),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 7),
            ]
        )
    )
    story.extend([state_table, Paragraph("Movement", heading)])
    if command_center.movements:
        movement_rows = [["Engine", "Current", "Previous", "Change"]] + [
            [row.label, _metric(row.current), _metric(row.previous), _metric(row.delta)]
            for row in command_center.movements
        ]
        movement_table = Table(
            movement_rows, colWidths=[55 * mm, 40 * mm, 40 * mm, 39 * mm]
        )
        movement_table.setStyle(
            TableStyle(
                [
                    ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                    ("TEXTCOLOR", (0, 0), (-1, 0), _TEAL),
                    ("LINEBELOW", (0, 0), (-1, -1), 0.5, _HAIRLINE),
                    ("TOPPADDING", (0, 0), (-1, -1), 6),
                    ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
                ]
            )
        )
        story.append(movement_table)
    else:
        story.append(
            Paragraph("No comparable run with the same measurement identity.", body)
        )
    story.extend([Paragraph("Resolved actions and subsequent movement", heading)])
    story.append(
        Paragraph(
            f"{command_center.resolved_actions.count} action(s) were marked "
            "resolved since the comparable run. Metric movement is presented "
            "alongside completion and does "
            "not establish causation.",
            body,
        )
    )
    story.extend([Paragraph("Next actions", heading)])
    action_rows = [["Rank", "Action", "Priority", "Evidence"]] + [
        [
            str(action.display_rank),
            action.title,
            f"{action.priority_score:g}",
            f"{action.evidence_summary.get('count', 0)} persisted item(s)",
        ]
        for action in command_center.actions
    ]
    action_table = Table(
        action_rows, colWidths=[15 * mm, 102 * mm, 25 * mm, 32 * mm], repeatRows=1
    )
    action_table.setStyle(
        TableStyle(
            [
                ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                ("TEXTCOLOR", (0, 0), (-1, 0), _TEAL),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("LINEBELOW", (0, 0), (-1, -1), 0.5, _HAIRLINE),
                ("FONTSIZE", (0, 0), (-1, -1), 8),
                ("TOPPADDING", (0, 0), (-1, -1), 6),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
            ]
        )
    )
    story.extend(
        [
            action_table,
            PageBreak(),
            Paragraph("Measurement scope and methodology", title),
        ]
    )
    story.append(
        Paragraph(
            "Visibility, share of voice, and rank are deterministic projections "
            "of persisted audit artifacts. Deltas appear only when measurement "
            "mode, benchmark mode, logical engine set, and frozen prompt identity "
            "set match. A dash means no valid comparison.",
            body,
        )
    )
    story.extend([Paragraph("Evidence appendix", heading)])
    for action in command_center.actions:
        raw_kinds = action.evidence_summary.get("kinds", [])
        kinds = ", ".join(raw_kinds) if isinstance(raw_kinds, list) else "none"
        kinds = kinds or "none"
        formula_version = action.priority_factors.get("formula_version", "—")
        story.append(
            Paragraph(
                f"<b>{action.display_rank}. {_paragraph_text(action.title)}</b><br/>"
                f"Target: {_paragraph_text(action.target_label or '—')} · "
                f"Evidence types: {_paragraph_text(kinds)} · "
                f"Formula: {_paragraph_text(formula_version)}",
                body,
            )
        )
        story.append(Spacer(1, 3 * mm))
    document.build(story)
    return buffer.getvalue()
