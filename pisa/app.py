"""PISA — Panel application entry point. Serve with: panel serve pisa/app.py"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import panel as pn
import panel_material_ui as pmui

_CSS_PATH = Path(__file__).parent / "ui" / "pisa.css"
_CUSTOM_CSS = _CSS_PATH.read_text() if _CSS_PATH.exists() else ""

pn.extension("tabulator", notifications=True, raw_css=[_CUSTOM_CSS])

from pisa.config import load_config
from pisa.ui.setup_view import SetupView
from pisa.ui.applicant_list_view import ApplicantListView
from pisa.ui.applicant_detail_view import ApplicantDetailView
from pisa.ui.theme import THEME, LEVEL_COLORS, MUTED, LEVEL_RED, LEVEL_AMBER, LEVEL_GREEN
from pisa.ui.style import fmt_criterion, eyebrow
from pisa.ui.fmt import ago_label
from pisa.store.db import get_connection, get_flags, list_applicants


def _discover_datasets():
    config = load_config()
    data_dir = Path(config.app.data_dir)
    if data_dir.exists():
        return sorted(p.name for p in data_dir.iterdir() if p.is_dir() and not p.name.startswith("."))
    return []


def create_app():
    config = load_config()
    datasets = _discover_datasets()

    dataset_select = pmui.Select(
        label="Program",
        options=datasets,
        value=datasets[0] if datasets else "",
        width=220,
    )

    setup = SetupView()
    applicant_list = ApplicantListView()
    applicant_detail = ApplicantDetailView()

    def on_dataset_change(event):
        if event.new:
            setup.dataset = event.new
            applicant_list.dataset_filter = event.new
            applicant_detail.applicant_id = ""
            detail_container.clear()

    dataset_select.param.watch(on_dataset_change, "value")

    if datasets:
        setup.dataset = datasets[0]
        applicant_list.dataset_filter = datasets[0]

    detail_container = pmui.Column(sizing_mode="stretch_width")

    def on_applicant_selected(event):
        if event.new:
            applicant_detail.applicant_id = event.new
            detail_container.clear()
            detail_container.append(applicant_detail.panel())
        else:
            detail_container.clear()

    applicant_list.param.watch(on_applicant_selected, "selected_applicant_id")

    def on_list_refresh_requested(event):
        applicant_list.param.trigger("refresh")

    applicant_detail.param.watch(on_list_refresh_requested, "request_list_refresh")

    def on_screening_change(event):
        from pisa.ui.theme import PRIMARY, MUTED
        if event.new:
            screening_html = (
                f'<span style="display:inline-flex; align-items:center; gap:4px; padding:2px 8px; '
                f'border-radius:12px; font-size:12px; background:{PRIMARY}14; color:{PRIMARY}; font-weight:500">'
                f'⟳ screening</span>'
            )
            applicant_list._patch_state_cell(event.new, screening_html)
        elif event.old:
            applicant_list._refresh_table()

    applicant_detail.param.watch(on_screening_change, "screening_applicant_id")

    review_content = pmui.Column(
        applicant_list.panel(),
        detail_container,
        sizing_mode="stretch_width",
    )

    # --- Context-sensitive sidebar (§1) ---
    minimap_pane = pn.Column(sizing_mode="stretch_width", css_classes=["pisa-scroll-cap"])
    profile_summary_pane = pn.Column(sizing_mode="stretch_width")

    # Sidebar sections: minimap (Review) and profile summary (Setup)
    review_sidebar = pn.Column(
        eyebrow("Flag Minimap"),
        minimap_pane,
        sizing_mode="stretch_width",
        visible=True,
    )

    # Wire profile summary from setup view (§1 context-sensitive sidebar)
    profile_summary_pane.append(setup.get_profile_summary())

    setup_sidebar = pn.Column(
        eyebrow("Profile"),
        profile_summary_pane,
        sizing_mode="stretch_width",
        visible=False,
    )

    def _refresh_minimap():
        minimap_pane.clear()
        aid = applicant_detail.applicant_id
        if not aid:
            minimap_pane.append(pn.pane.HTML(
                f'<div style="font-size:12px; color:{MUTED}">Select an applicant</div>',
                sizing_mode="stretch_width",
            ))
            return
        conn = get_connection()
        flags = get_flags(conn, aid)
        conn.close()
        if not flags:
            minimap_pane.append(pn.pane.HTML(
                f'<div style="font-size:12px; color:{MUTED}">No flags yet</div>',
                sizing_mode="stretch_width",
            ))
            return

        # Group by level (§4)
        by_level = {"red": [], "yellow": [], "green": []}
        for f in flags:
            by_level.setdefault(f.get("level", "green"), []).append(f)

        for level in ["red", "yellow", "green"]:
            group = by_level.get(level, [])
            if not group:
                continue
            color = LEVEL_COLORS.get(level, MUTED)
            minimap_pane.append(pn.pane.HTML(
                f'<div style="font-size:10px; color:{MUTED}; text-transform:uppercase; '
                f'letter-spacing:0.06em; margin-top:6px">'
                f'{level.title()} · {len(group)}</div>',
                sizing_mode="stretch_width",
            ))
            for flag in group:
                title = flag.get("title", "")
                full_title = title
                title_short = title[:32] + "..." if len(title) > 32 else title
                status = flag.get("status", "open")
                resolved_cls = " pisa-minimap-row--resolved" if status in ("resolved", "acknowledged") else ""
                status_mark = " ✓" if status in ("resolved", "acknowledged") else ""
                crefs = set()
                for ev in flag.get("evidence", []):
                    cref = ev.get("criterion_ref", "")
                    if cref:
                        crefs.add(fmt_criterion(cref))
                badge = f'<span class="pisa-criterion-badge">{sorted(crefs)[0]}</span>' if crefs else ""
                minimap_pane.append(pn.pane.HTML(
                    f'<div class="pisa-tip pisa-minimap-row{resolved_cls}" data-tip="{full_title}">'
                    f'<span style="color:{color}; font-size:10px">●</span>'
                    f'{badge}'
                    f'<span style="flex:1; overflow:hidden; text-overflow:ellipsis">{title_short}{status_mark}</span>'
                    f'</div>',
                    sizing_mode="stretch_width",
                ))

    def _on_applicant_change(event):
        _refresh_minimap()

    def _on_flags_changed(event):
        _refresh_minimap()

    applicant_detail.param.watch(_on_applicant_change, "applicant_id")
    applicant_detail.param.watch(_on_flags_changed, "request_list_refresh")

    # Tab switch → toggle sidebar sections
    main_tabs = pmui.Tabs(
        ("Setup", pmui.Column(setup.panel(), sizing_mode="stretch_width")),
        ("Review", review_content),
        sizing_mode="stretch_width",
    )

    def _on_tab_change(event):
        is_review = event.new == 1
        review_sidebar.visible = is_review
        setup_sidebar.visible = not is_review

    main_tabs.param.watch(_on_tab_change, "active")

    sidebar_content = [
        pmui.Typography("PISA", variant="h6"),
        pmui.Divider(),
        dataset_select,
        pmui.Divider(),
        review_sidebar,
        setup_sidebar,
    ]

    # Fixed page footer (§1 — out of sidebar)
    footer_html = pn.pane.HTML(
        '<div class="pisa-footer">'
        '<b>Unvalidated prototype — demo data only. Do not enter real participant information.</b> '
        'Not a medical device, not medical or legal advice. All decisions are made by the human reviewer.'
        '</div>',
        sizing_mode="stretch_width",
    )

    page = pmui.Page(
        title="PISA",
        sidebar=sidebar_content,
        main=[main_tabs, footer_html],
        theme_config=THEME,
    )
    return page


create_app().servable()
