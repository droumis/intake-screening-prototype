"""PISA UI style helpers — Compass playbook patterns centralized."""

from __future__ import annotations

import re

import panel as pn
import panel_material_ui as pmui

from pisa.ui.theme import (
    PRIMARY, MUTED, DIVIDER, TEXT_PRIMARY, TEXT_SECONDARY,
    LEVEL_COLORS, LEVEL_TINTS, LEVEL_RED,
)


# §7.3 — The card recipe
def card(*children, accent: str | None = None, pad: str = "16px") -> pmui.Paper:
    sx = {
        "backgroundColor": "background.paper",
        "border": "1px solid",
        "borderColor": "divider",
        "borderRadius": "12px",
        "p": pad,
        "display": "flex",
        "flexDirection": "column",
        "gap": "12px",
    }
    if accent:
        sx["borderLeft"] = f"4px solid {accent}"
    return pmui.Paper(*children, elevation=0, sizing_mode="stretch_width", sx=sx)


# §7.5 — Eyebrow section labels
def eyebrow(text: str) -> pn.pane.HTML:
    return pn.pane.HTML(
        f'<div style="font-size:11px; text-transform:uppercase; letter-spacing:0.06em; '
        f'color:{MUTED}; margin-bottom:4px">{text}</div>',
        sizing_mode="stretch_width",
    )


# §3 — Criterion ref normalization
_CREF_RE = re.compile(r"\[?\[?([A-Z]\d+)\]?\]?")


def fmt_criterion(raw: str) -> str:
    """Normalize [[D2]], [D2], D2 → 'D2'."""
    m = _CREF_RE.match(raw.strip())
    return m.group(1) if m else raw.strip()


def criterion_badge_html(raw: str, tip: str = "") -> str:
    """Render a criterion ref as a styled monospace badge with optional tooltip."""
    cid = fmt_criterion(raw)
    if not cid:
        return ""
    tip_attr = f' data-tip="{tip}"' if tip else ""
    return (
        f'<span class="pisa-tip pisa-criterion-badge"{tip_attr}>{cid}</span>'
    )


# Basis chip (regulatory = filled like "rule"; house = outlined)
def basis_chip_html(basis: str, citation: str = "") -> str:
    """Small basis chip: regulatory (filled) or house (outlined). Tooltip shows citation."""
    if not basis:
        return ""
    tip_attr = f' data-tip="{citation}"' if citation else ""
    if basis == "regulatory":
        return (
            f'<span class="pisa-tip pisa-provenance pisa-provenance--rule"{tip_attr}>'
            f'regulatory</span>'
        )
    return (
        f'<span class="pisa-tip pisa-provenance pisa-provenance--model"{tip_attr}>'
        f'house</span>'
    )


# §7.7 — Provenance chip
def provenance_chip_html(source: str) -> str:
    """Small source chip: rule (filled) | model (outlined) | reviewer."""
    if source == "rule":
        return (
            f'<span class="pisa-tip pisa-provenance pisa-provenance--rule" '
            f'data-tip="Deterministic match — rules engine">rule</span>'
        )
    elif source == "model":
        return (
            f'<span class="pisa-tip pisa-provenance pisa-provenance--model" '
            f'data-tip="AI-inferred — verify against evidence">model</span>'
        )
    else:
        return (
            f'<span class="pisa-tip pisa-provenance pisa-provenance--reviewer" '
            f'data-tip="Reviewer action">reviewer</span>'
        )


# §7.9 — Dense HTML fragment list (single pane, many rows)
def html_list(rows: list[str], max_height: str | None = None) -> pn.pane.HTML:
    """Render a list of HTML row strings as one dense block."""
    sep_style = f"border-bottom:1px solid {DIVIDER}"
    items = []
    for i, row in enumerate(rows):
        border = sep_style if i < len(rows) - 1 else ""
        items.append(
            f'<div style="padding:6px 0; {border}; display:flex; align-items:center; gap:8px">'
            f'{row}</div>'
        )
    container_style = "font-size:13px; line-height:1.5"
    if max_height:
        container_style += f"; max-height:{max_height}; overflow-y:auto"
    html = f'<div style="{container_style}">{"".join(items)}</div>'
    return pn.pane.HTML(html, sizing_mode="stretch_width")


# Flag card header chips (§3 — level + category + criterion IDs only)
def flag_header_chips_html(flag: dict) -> str:
    """Compact header line: level · source · category · criterion badges."""
    level = flag.get("level", "green")
    color = LEVEL_COLORS.get(level, MUTED)
    source = flag.get("source", "model")
    category = flag.get("category", "").replace("_", " ")
    hard = flag.get("hard_flag", False)

    parts = []
    # Level chip
    parts.append(
        f'<span style="display:inline-block; padding:2px 8px; border-radius:12px; '
        f'font-size:11px; font-weight:600; background:{color}18; color:{color}">'
        f'{level.upper()}</span>'
    )
    # Hard badge
    if hard:
        parts.append(
            f'<span style="display:inline-block; padding:2px 6px; border-radius:12px; '
            f'font-size:10px; font-weight:600; border:1px solid {LEVEL_RED}; '
            f'color:{LEVEL_RED}">HARD</span>'
        )
    # Provenance
    parts.append(provenance_chip_html(source))
    # Basis (regulatory / house)
    basis = flag.get("basis", "")
    citation = flag.get("citation", "")
    if basis:
        parts.append(basis_chip_html(basis, citation))
    # Category
    if category:
        parts.append(
            f'<span style="display:inline-block; padding:2px 8px; border-radius:12px; '
            f'font-size:11px; background:{DIVIDER}; color:{TEXT_SECONDARY}">'
            f'{category}</span>'
        )
    # Criterion badges
    crefs = set()
    for ev in flag.get("evidence", []):
        cref = ev.get("criterion_ref", "")
        if cref:
            crefs.add(fmt_criterion(cref))
    for cid in sorted(crefs):
        parts.append(
            f'<span class="pisa-criterion-badge">{cid}</span>'
        )
    return " ".join(parts)
