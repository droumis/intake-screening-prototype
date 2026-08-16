"""View B — Applicant Detail: flags, sections, follow-up workflow, pipeline history."""

from __future__ import annotations

import json
import uuid
from datetime import datetime
from pathlib import Path

import param
import panel as pn
import panel_material_ui as pmui

from pisa.config import load_config
from pisa.model.ollama import OllamaProvider
from pisa.parser.models import ApplicantRecord, ParsedSection, Identity
from pisa.pipeline.queue import pipeline_queue
from pisa.pipeline.runner import PipelineResult, ProgressCallback
from pisa.profile.loader import load_context_documents, compute_context_hash
from pisa.profile.store import load_profile
from pisa.store.db import (
    get_connection, get_applicant, get_flags, get_pipeline_runs, update_review_state,
    get_followups, save_followup, update_followup, delete_followup,
    update_flag_status, downgrade_flag, purge_applicant,
    save_flags, replace_flags, save_pipeline_run, get_setting, get_review_history,
)
from pisa.ui.theme import (
    LEVEL_RED, LEVEL_AMBER, LEVEL_GREEN, LEVEL_COLORS, LEVEL_TINTS,
    CHIP_COLOR_MAP, TEXT_SECONDARY, STATE_COLORS, MUTED, PRIMARY, TEXT_PRIMARY,
)
from pisa.ui.style import (
    eyebrow, fmt_criterion, criterion_badge_html,
    provenance_chip_html, flag_header_chips_html, html_list,
)
from pisa.ui.fmt import ago_label, fmt_duration, fmt_absolute


class UIProgressCallback(ProgressCallback):
    """Progress callback that updates Panel UI panes in real-time."""

    def __init__(self, run_status: pn.Column, applicant_id: str, display_name: str, generation: int):
        self._run_status = run_status
        self._applicant_id = applicant_id
        self._display_name = display_name
        self._gen = generation
        self._progress_md = pn.pane.Markdown("", sizing_mode="stretch_width")
        self._flags_column = pn.Column(sizing_mode="stretch_width")
        self._persisted_flag_ids: set[str] = set()
        self._sections_done = 0
        self._sections_total = 0
        self._progress_bar: pmui.LinearProgress | None = None

    def on_section_start(self, section_key: str, index: int, total: int):
        self._sections_total = total
        label = section_key.replace("_", " ").title()
        text = f"Analyzing {index + 1}/{total}: {label}..."

        def _update():
            self._progress_md.object = text

        pn.state.execute(_update)

    def on_section_done(self, section_key: str, index: int, total: int, flags: list[dict] | None = None):
        self._sections_done = index + 1
        self._sections_total = total
        text = f"Done {index + 1}/{total}: {section_key.replace('_', ' ').title()}"

        def _update():
            self._progress_md.object = text
            self._update_progress_bar()
            if flags:
                self._persist_and_render_flags(flags)

        pn.state.execute(_update)

    def on_batch_start(self, section_keys: list[str]):
        labels = ", ".join(k.replace("_", " ").title() for k in section_keys[:3])
        text = f"Analyzing batch: {labels}..."

        def _update():
            self._progress_md.object = text

        pn.state.execute(_update)

    def on_synthesis_start(self):
        def _update():
            self._progress_md.object = "Synthesis pass — correlating findings..."

        pn.state.execute(_update)

    def on_complete(self, result: PipelineResult):
        pass

    def on_failure(self, result: PipelineResult, error: str):
        def _update():
            self._run_status.clear()
            self._run_status.append(pn.pane.Alert(
                f"**Pipeline failed:** {error}", alert_type="danger",
            ))

        pn.state.execute(_update)

    def _persist_and_render_flags(self, flags: list[dict]):
        new_flags = [f for f in flags if f.get("flag_id") and f["flag_id"] not in self._persisted_flag_ids]
        if not new_flags:
            return
        conn = get_connection()
        save_flags(conn, new_flags)
        conn.close()
        for flag in new_flags:
            self._persisted_flag_ids.add(flag["flag_id"])
        self._flags_column.clear()
        count = len(self._persisted_flag_ids)
        self._flags_column.append(pn.pane.HTML(
            f'<div style="font-size:12px; color:{TEXT_SECONDARY}">Flags found: {count}</div>',
            sizing_mode="stretch_width",
        ))

    def _update_progress_bar(self):
        if self._sections_total > 0 and self._progress_bar:
            pct = int(100 * self._sections_done / self._sections_total)
            self._progress_bar.value = pct

    def setup_in_status(self):
        self._run_status.clear()
        self._progress_bar = pmui.LinearProgress(value=0, width=200)
        self._run_status.append(pmui.Row(
            self._progress_bar,
            self._progress_md,
            align="center",
        ))
        self._run_status.append(self._flags_column)


class ApplicantDetailView(param.Parameterized):
    applicant_id = param.String(default="")
    request_list_refresh = param.Event()
    screening_applicant_id = param.String(default="")

    def __init__(self, **params):
        super().__init__(**params)
        self._config = load_config()
        self._content = pn.Column(sizing_mode="stretch_width")
        self._run_status = pn.Column(sizing_mode="stretch_width")
        self._ack_chip_pane = None
        self._gen = 0

    def _reviewer_name(self) -> str:
        conn = get_connection()
        name = get_setting(conn, "reviewer_name", "reviewer")
        conn.close()
        return name or "reviewer"

    def _refresh_ack_chip(self):
        """Update the ack count chip in the flags tab after acknowledge/reopen."""
        if not self._ack_chip_pane or not self.applicant_id:
            return
        conn = get_connection()
        flags = get_flags(conn, self.applicant_id)
        conn.close()
        system_flags = [f for f in flags if f.get("source") != "reviewer"]
        red_count = sum(1 for f in system_flags if f.get("level") == "red")
        yellow_count = sum(1 for f in system_flags if f.get("level") == "yellow")
        green_count = sum(1 for f in system_flags if f.get("level") == "green")
        ack_count = sum(1 for f in flags if f.get("status") in ("acknowledged", "resolved"))
        total_count = len(flags)
        self._ack_chip_pane.object = (
            f'<div style="display:flex; gap:8px; margin-bottom:8px; align-items:center">'
            f'<span class="pisa-tip" data-tip="{red_count} red flags" style="padding:3px 10px; border-radius:12px; '
            f'font-size:12px; font-weight:500; background:{LEVEL_RED}{"18" if red_count else "08"}; '
            f'color:{LEVEL_RED if red_count else MUTED}">Red {red_count}</span>'
            f'<span class="pisa-tip" data-tip="{yellow_count} yellow flags" style="padding:3px 10px; border-radius:12px; '
            f'font-size:12px; font-weight:500; background:{LEVEL_AMBER}{"18" if yellow_count else "08"}; '
            f'color:{LEVEL_AMBER if yellow_count else MUTED}">Yellow {yellow_count}</span>'
            f'<span class="pisa-tip" data-tip="{green_count} green flags" style="padding:3px 10px; border-radius:12px; '
            f'font-size:12px; font-weight:500; background:{LEVEL_GREEN}{"18" if green_count else "08"}; '
            f'color:{LEVEL_GREEN if green_count else MUTED}">Green {green_count}</span>'
            f'<span style="padding:3px 10px; border-radius:12px; font-size:12px; '
            f'background:{MUTED}18; color:{MUTED}">{ack_count}/{total_count} ack\'d</span>'
            f'</div>'
        )

    @param.depends("applicant_id", watch=True)
    def _on_applicant_change(self):
        self._gen += 1
        self._render()

    def _render(self):
        self._content.clear()

        if not self.applicant_id:
            self._content.append(pn.pane.HTML(
                f'<div style="padding:24px; color:{MUTED}; font-size:14px">'
                f'Click a row in the table above to review an applicant.</div>',
                sizing_mode="stretch_width",
            ))
            return

        conn = get_connection()
        applicant = get_applicant(conn, self.applicant_id)
        if not applicant:
            self._content.append(pn.pane.Alert(
                f"Applicant not found.", alert_type="danger",
            ))
            conn.close()
            return

        flags = get_flags(conn, self.applicant_id)
        runs = get_pipeline_runs(conn, self.applicant_id)
        followups = get_followups(conn, self.applicant_id)
        conn.close()

        # --- §2: Consolidated sticky header (two rows) ---
        self._content.append(self._build_header(applicant, runs))

        # Pipeline run status
        self._run_status.clear()
        if runs and runs[0].get("status") == "incomplete":
            self._run_status.append(pn.pane.Alert(
                f"**Last run failed:** {runs[0].get('notes', 'Unknown error')}",
                alert_type="danger",
            ))
        self._content.append(self._run_status)

        # Detail tabs
        sections_data = json.loads(applicant.get("sections_json", "{}"))
        flags_tab = self._build_flags_tab(flags, followups)
        form_tab = self._build_sections_panel(sections_data) if sections_data else pn.pane.HTML(
            f'<div style="color:{MUTED}; padding:16px">No parsed sections available.</div>',
        )
        followups_tab = self._build_followup_panel(flags, followups)
        timeline_tab = self._build_timeline_tab(flags, followups, runs)

        open_count = sum(1 for f in flags if f.get("status") not in ("resolved", "acknowledged"))
        flags_label = f"Flags ({open_count})" if flags else "Flags"

        detail_tabs = pmui.Tabs(
            (flags_label, flags_tab),
            ("Form", form_tab),
            (f"Follow-ups ({len(followups)})" if followups else "Follow-ups", followups_tab),
            ("Timeline", timeline_tab),
            sizing_mode="stretch_width",
        )
        self._content.append(detail_tabs)

    def _build_header(self, applicant: dict, runs: list[dict]) -> pn.Column:
        """§2: Two-row consolidated header."""
        display_name = applicant["display_name"]
        current_state = applicant.get("review_state", "unreviewed")
        state_color = STATE_COLORS.get(current_state, MUTED)

        # State selector (the chip IS the dropdown — §2)
        state_select = pmui.Select(
            options=["unreviewed", "in_review", "followup_pending", "cleared", "not_cleared", "deferred"],
            value=current_state,
            width=155,
            variant="outlined",
            label="",
            sx={"& .MuiSelect-select": {"padding": "4px 8px", "fontSize": "13px"}},
        )

        gating_msg = pn.pane.Alert("", alert_type="warning", visible=False)

        def on_state_change(event):
            gating_msg.visible = False
            if event.new == "cleared":
                conn = get_connection()
                flags = get_flags(conn, self.applicant_id)
                conn.close()
                open_reds = [f for f in flags if f.get("level") == "red" and f.get("status") == "open"]
                open_yellows = [f for f in flags if f.get("level") == "yellow" and f.get("status") == "open"]
                if open_reds or open_yellows:
                    blockers = []
                    if open_reds:
                        blockers.append(f"{len(open_reds)} red")
                    if open_yellows:
                        blockers.append(f"{len(open_yellows)} yellow")
                    gating_msg.object = f"Note: {', '.join(blockers)} open flags remain unacknowledged."
                    gating_msg.visible = True
            conn = get_connection()
            update_review_state(conn, self.applicant_id, event.new, actor=self._reviewer_name())
            conn.close()
            new_color = STATE_COLORS.get(event.new, MUTED)
            state_pill.object = (
                f'<span style="display:inline-block; padding:3px 10px; border-radius:12px; '
                f'font-size:12px; background:{new_color}18; color:{new_color}; font-weight:500">'
                f'{event.new.replace("_", " ")}</span>'
            )
            self.param.trigger("request_list_refresh")

        state_select.param.watch(on_state_change, "value")

        # Action buttons (right-aligned, fixed width — §7.10)
        run_btn = pmui.Button(
            label="Run Screening", color="primary", icon="play_arrow",
            width=150, sizing_mode="fixed",
        )
        run_btn.on_click(lambda e: self._run_single(applicant))

        actions_menu = pmui.MenuButton(
            items=[
                {"label": "Stop screening", "icon": "stop"},
                {"label": "Purge applicant data", "icon": "delete_forever"},
            ],
            label="",
            icon="more_vert",
            variant="text",
            color="default",
            sx={"minWidth": "36px", "p": 0},
            width=40,
        )

        def on_actions_menu(event):
            if not event.new:
                return
            label = event.new.get("label", "").lower()
            if "purge" in label:
                self._confirm_purge(applicant)
            elif "stop" in label:
                pipeline_queue.cancel()
                self._run_status.clear()
                self._run_status.append(pn.pane.Alert("Screening interrupted.", alert_type="warning"))
                self.screening_applicant_id = ""
                self.param.trigger("request_list_refresh")

        actions_menu.param.watch(on_actions_menu, "value")

        # Row 1: name + state + actions
        state_pill = pn.pane.HTML(
            f'<span style="display:inline-block; padding:3px 10px; border-radius:12px; '
            f'font-size:12px; background:{state_color}18; color:{state_color}; font-weight:500">'
            f'{current_state.replace("_", " ")}</span>',
        )
        row1 = pmui.Row(
            pmui.Typography(display_name, variant="h4"),
            state_pill,
            state_select,
            pn.Spacer(),
            run_btn,
            actions_menu,
            sizing_mode="stretch_width",
            align="center",
        )

        # Row 2: demographics + last run info (§2 — fold run banner into header line)
        identity_json = applicant.get("identity_json")
        demo_parts = []
        if identity_json:
            identity = Identity.model_validate_json(identity_json)
            if identity.age:
                demo_parts.append(identity.age)
            if identity.pronouns:
                demo_parts.append(identity.pronouns)
            if identity.occupation:
                demo_parts.append(identity.occupation)

        if runs:
            latest = runs[0]
            run_ago = ago_label(latest.get("started_at", ""))
            duration = fmt_duration(latest.get("duration_seconds", 0))
            status_dot = f'<span style="color:{LEVEL_GREEN}">●</span>' if latest["status"] == "complete" else f'<span style="color:{LEVEL_RED}">●</span>'
            demo_parts.append(f"{status_dot} screened {run_ago} · {duration}")

        row2_html = f'<div style="font-size:13px; color:{TEXT_SECONDARY}">{" · ".join(demo_parts)}</div>' if demo_parts else ""

        # AI summary (collapsed by default, within the header area)
        summary_card = pn.Spacer(height=0)
        if runs:
            latest = runs[0]
            if latest.get("status") == "complete":
                overall_notes = latest.get("overall_notes", "") or latest.get("progress", {}).get("overall_notes", "")
                if overall_notes:
                    model_id = latest.get("model_id", "model")
                    run_date = latest.get("started_at", "")[:10]
                    summary_card = pn.Card(
                        pn.pane.Markdown(overall_notes, sizing_mode="stretch_width"),
                        pn.pane.HTML(
                            f'<div style="font-size:11px; color:{MUTED}">Generated by {model_id} · {run_date}</div>',
                            sizing_mode="stretch_width",
                        ),
                        title="AI Summary · advisory only",
                        collapsed=True,
                        collapsible=True,
                        sizing_mode="stretch_width",
                        styles={"border-left": f"4px solid {PRIMARY}"},
                    )

        header = pn.Column(
            row1,
            pn.pane.HTML(row2_html, sizing_mode="stretch_width") if row2_html else pn.Spacer(height=0),
            gating_msg,
            summary_card,
            sizing_mode="stretch_width",
            css_classes=["pisa-sticky-header"],
            styles={
                "border-top": f"2px solid {MUTED}33",
                "margin-top": "16px",
                "padding-top": "12px",
            },
        )
        return header

    def _confirm_purge(self, applicant: dict):
        display_name = applicant.get("display_name", "this applicant")
        first_name = display_name.split()[0] if display_name else "DELETE"

        conn = get_connection()
        flag_count = len(get_flags(conn, self.applicant_id))
        run_count = len(get_pipeline_runs(conn, self.applicant_id))
        conn.close()

        confirm_input = pn.widgets.TextInput(
            name=f'Type "{first_name}" to confirm',
            placeholder=first_name,
            sizing_mode="stretch_width",
        )
        delete_btn = pmui.Button(
            label="Delete permanently", color="error", disabled=True, width=180, sizing_mode="fixed",
        )

        def on_input_change(event):
            delete_btn.disabled = (event.new.strip().lower() != first_name.lower())

        confirm_input.param.watch(on_input_change, "value")

        dialog_content = pn.Column(
            pn.pane.Markdown(
                f"Permanently deletes {flag_count} flags and {run_count} run records. Cannot be undone.\n\n"
                f"*The intake file remains on disk and will re-import on next Refresh.*",
                sizing_mode="stretch_width",
            ),
            confirm_input,
            delete_btn,
            sizing_mode="stretch_width",
        )

        dialog = pmui.Dialog(
            dialog_content,
            title=f"Delete all data for {display_name}?",
            open=True,
            width_option="sm",
        )

        def on_delete(event):
            if confirm_input.value.strip().lower() == first_name.lower():
                conn = get_connection()
                purge_applicant(conn, self.applicant_id)
                conn.close()
                dialog.open = False
                self.applicant_id = ""
                self.param.trigger("request_list_refresh")

        delete_btn.on_click(on_delete)
        self._content.append(dialog)

    def _run_single(self, applicant: dict):
        dataset = applicant.get("dataset", "")
        context_dir = Path(self._config.app.data_dir) / dataset / "context"

        if not context_dir.exists():
            self._run_status.clear()
            self._run_status.append(pn.pane.Alert("No context directory. Build a profile in Setup.", alert_type="danger"))
            return

        docs = load_context_documents(context_dir)
        if not docs:
            self._run_status.clear()
            self._run_status.append(pn.pane.Alert("No context documents found.", alert_type="danger"))
            return

        context_hash = compute_context_hash(docs)
        profile = load_profile(context_hash)

        if not profile:
            self._run_status.clear()
            self._run_status.append(pn.pane.Alert("No approved profile. Go to Setup first.", alert_type="warning"))
            return

        conn = get_connection()
        record = self._load_record(conn, self.applicant_id)
        conn.close()

        if not record:
            self._run_status.clear()
            self._run_status.append(pn.pane.Alert("Could not load applicant record.", alert_type="danger"))
            return

        current_gen = self._gen
        progress_cb = UIProgressCallback(
            run_status=self._run_status,
            applicant_id=self.applicant_id,
            display_name=applicant["display_name"],
            generation=current_gen,
        )
        progress_cb.setup_in_status()

        provider = OllamaProvider(self._config.model)
        aid = self.applicant_id
        self.screening_applicant_id = aid

        def on_complete(result: PipelineResult):
            if self._gen != current_gen:
                return
            conn = get_connection()
            replace_flags(conn, aid, result.flags)
            save_pipeline_run(conn, result.to_run_record(), aid)
            applicant_row = conn.execute(
                "SELECT review_state FROM applicants WHERE applicant_id = ?", (aid,)
            ).fetchone()
            if applicant_row and applicant_row["review_state"] == "unreviewed":
                update_review_state(conn, aid, "in_review")
            conn.close()

            def _done():
                self.screening_applicant_id = ""
                self._render()
                self.param.trigger("request_list_refresh")

            pn.state.execute(_done)

        pipeline_queue.enqueue(
            record=record,
            profile=profile,
            provider=provider,
            progress=progress_cb,
            on_complete=on_complete,
        )

    def _load_record(self, conn, applicant_id: str):
        row = conn.execute(
            "SELECT * FROM applicants WHERE applicant_id = ?", (applicant_id,)
        ).fetchone()
        if not row:
            return None
        row = dict(row)
        identity = Identity.model_validate_json(row["identity_json"]) if row.get("identity_json") else Identity()
        sections_data = json.loads(row.get("sections_json", "{}"))
        sections = {k: ParsedSection.model_validate(v) for k, v in sections_data.items()}
        return ApplicantRecord(
            applicant_id=row["applicant_id"],
            display_name=row["display_name"],
            created_at=row["created_at"],
            raw_form_path=row.get("raw_form_path", ""),
            identity=identity,
            sections=sections,
            unmapped_content=row.get("unmapped_content", ""),
        )

    # --- FLAGS TAB ---

    def _build_flags_tab(self, flags: list[dict], followups: list[dict]) -> pn.Column:
        tab = pn.Column(sizing_mode="stretch_width")

        # Build flag_id → followups index
        followups_by_flag = {}
        for fu in followups:
            for fid in fu.get("linked_flag_ids", []):
                followups_by_flag.setdefault(fid, []).append(fu)

        # Split system vs reviewer flags
        system_flags = [f for f in flags if f.get("source") != "reviewer"]
        reviewer_flags = [f for f in flags if f.get("source") == "reviewer"]

        if not flags:
            tab.append(pn.pane.HTML(
                f'<div style="padding:24px; color:{MUTED}; font-size:14px">'
                f'No flags yet. Click Run Screening to analyze this applicant.</div>',
                sizing_mode="stretch_width",
            ))

        if system_flags:
            # Filter chips — counts across all system flags
            red_count = sum(1 for f in system_flags if f.get("level") == "red")
            yellow_count = sum(1 for f in system_flags if f.get("level") == "yellow")
            green_count = sum(1 for f in system_flags if f.get("level") == "green")
            ack_count = sum(1 for f in flags if f.get("status") in ("acknowledged", "resolved"))
            total_count = len(flags)

            chip_row_html = (
                f'<div style="display:flex; gap:8px; margin-bottom:8px; align-items:center">'
                f'<span class="pisa-tip" data-tip="{red_count} red flags" style="padding:3px 10px; border-radius:12px; '
                f'font-size:12px; font-weight:500; background:{LEVEL_RED}{"18" if red_count else "08"}; '
                f'color:{LEVEL_RED if red_count else MUTED}">Red {red_count}</span>'
                f'<span class="pisa-tip" data-tip="{yellow_count} yellow flags" style="padding:3px 10px; border-radius:12px; '
                f'font-size:12px; font-weight:500; background:{LEVEL_AMBER}{"18" if yellow_count else "08"}; '
                f'color:{LEVEL_AMBER if yellow_count else MUTED}">Yellow {yellow_count}</span>'
                f'<span class="pisa-tip" data-tip="{green_count} green flags" style="padding:3px 10px; border-radius:12px; '
                f'font-size:12px; font-weight:500; background:{LEVEL_GREEN}{"18" if green_count else "08"}; '
                f'color:{LEVEL_GREEN if green_count else MUTED}">Green {green_count}</span>'
                f'<span style="padding:3px 10px; border-radius:12px; font-size:12px; '
                f'background:{MUTED}18; color:{MUTED}">{ack_count}/{total_count} ack\'d</span>'
                f'</div>'
            )
            self._ack_chip_pane = pn.pane.HTML(chip_row_html, sizing_mode="stretch_width")
            tab.append(self._ack_chip_pane)

            # Pinned hard-red strip (§7.8)
            hard_reds = [f for f in system_flags if f.get("level") == "red" and f.get("hard_flag") and f.get("status") == "open"]
            if hard_reds:
                titles = ", ".join(f.get("title", "")[:40] for f in hard_reds)
                tab.append(pn.pane.HTML(
                    f'<div style="padding:6px 12px; background:{LEVEL_RED}14; border-radius:8px; '
                    f'font-size:12px; color:{LEVEL_RED}; font-weight:500; margin-bottom:8px">'
                    f'Hard exclusion: {titles}</div>',
                    sizing_mode="stretch_width",
                ))

            # All system flags rendered in place (acknowledged get dimmed styling)
            flags_panel = self._build_flags_panel(system_flags, followups_by_flag)
            expand_btn = pmui.Button(label="Expand all", variant="text", color="default", width=100, sizing_mode="fixed")
            collapse_btn = pmui.Button(label="Collapse all", variant="text", color="default", width=110, sizing_mode="fixed")

            def _set_collapsed(value):
                for item in flags_panel:
                    if hasattr(item, "collapsed"):
                        item.collapsed = value

            expand_btn.on_click(lambda e: _set_collapsed(False))
            collapse_btn.on_click(lambda e: _set_collapsed(True))
            tab.append(pmui.Row(expand_btn, collapse_btn))
            tab.append(flags_panel)

        # --- Reviewer Flags section (separate) ---
        tab.append(self._build_reviewer_flags_section(reviewer_flags, followups_by_flag))

        return tab

    def _build_reviewer_flags_section(self, reviewer_flags: list[dict], followups_by_flag: dict) -> pn.Column:
        """Separate section for manually-created reviewer flags with add form."""
        section = pn.Column(sizing_mode="stretch_width")
        section.append(pn.pane.HTML(
            f'<div style="margin-top:16px; padding-top:12px; border-top:1px solid {MUTED}33"></div>',
            sizing_mode="stretch_width",
        ))
        section.append(eyebrow("Reviewer Flags"))

        if reviewer_flags:
            section.append(self._build_flags_panel(reviewer_flags, followups_by_flag))

        # Add Reviewer Flag form
        add_btn = pmui.Button(
            label="Add Flag", icon="add", variant="outlined", color="default",
            width=110, sizing_mode="fixed",
        )
        form_container = pn.Column(sizing_mode="stretch_width")

        def show_form(event):
            form_container.clear()
            form_container.append(self._build_add_reviewer_flag_form(form_container))

        add_btn.on_click(show_form)
        section.append(add_btn)
        section.append(form_container)
        return section

    def _build_add_reviewer_flag_form(self, form_container: pn.Column) -> pn.Column:
        """Form to create a manual reviewer flag."""
        form = pn.Column(sizing_mode="stretch_width")

        title_input = pn.widgets.TextInput(
            name="Title",
            placeholder="Brief description of the concern...",
            sizing_mode="stretch_width",
        )
        level_select = pmui.Select(
            label="Level",
            options=["yellow", "red", "green"],
            value="yellow",
            width=120,
        )
        category_input = pn.widgets.TextInput(
            name="Category",
            placeholder="e.g. behavioral, medical, substance",
            width=200,
        )
        rationale_input = pn.widgets.TextAreaInput(
            name="Rationale",
            placeholder="Why are you raising this flag?",
            height=60,
            sizing_mode="stretch_width",
        )

        save_btn = pmui.Button(label="Save Flag", color="primary", icon="save", width=120, sizing_mode="fixed", disabled=True)
        cancel_btn = pmui.Button(label="Cancel", variant="text", color="default", width=80, sizing_mode="fixed")

        def on_title_change(event):
            save_btn.disabled = not bool(event.new.strip())

        title_input.param.watch(on_title_change, "value")

        def on_save(event):
            if not title_input.value.strip():
                return
            flag = {
                "flag_id": str(uuid.uuid4()),
                "applicant_id": self.applicant_id,
                "created_at": datetime.now().isoformat(),
                "source": "reviewer",
                "level": level_select.value,
                "severity": 5 if level_select.value == "red" else 3,
                "category": category_input.value.strip() or "reviewer_observation",
                "title": title_input.value.strip(),
                "evidence": [],
                "rationale": rationale_input.value.strip(),
                "recommended_followup": [],
                "resolution_criteria": "",
                "suggested_lookup": [],
                "hard_flag": False,
                "status": "open",
                "history": [],
            }
            conn = get_connection()
            save_flags(conn, [flag])
            conn.close()
            self._render()
            self.param.trigger("request_list_refresh")

        def on_cancel(event):
            form_container.clear()

        save_btn.on_click(on_save)
        cancel_btn.on_click(on_cancel)

        form.extend([
            title_input,
            pmui.Row(level_select, category_input, align="end"),
            rationale_input,
            pmui.Row(save_btn, cancel_btn),
        ])
        return form

    def _build_flags_panel(self, flags: list[dict], followups_by_flag: dict | None = None) -> pn.Column:
        cards_col = pn.Column(sizing_mode="stretch_width")
        followups_by_flag = followups_by_flag or {}

        for flag in flags:
            level = flag.get("level", "green")
            title = flag.get("title", "Untitled")
            flag_id = flag.get("flag_id", "")
            flag_status = flag.get("status", "open")
            level_color = LEVEL_COLORS.get(level, MUTED)
            is_acked = flag_status in ("acknowledged", "resolved")

            # Follow-ups linked to this flag
            flag_followups = followups_by_flag.get(flag_id, [])
            fu_count = len(flag_followups)

            # Header chips (§3 — level + category + criterion IDs + follow-up count)
            header_html = flag_header_chips_html(flag)
            if fu_count:
                header_html += (
                    f' <span style="padding:2px 8px; border-radius:12px; font-size:10px; '
                    f'font-weight:500; background:{PRIMARY}14; color:{PRIMARY}; '
                    f'display:inline-flex; align-items:center; gap:3px">'
                    f'💬 {fu_count}</span>'
                )
            if is_acked:
                status_label = "acknowledged" if flag_status == "acknowledged" else "resolved"
                header_html += (
                    f' <span style="padding:2px 8px; border-radius:12px; font-size:10px; '
                    f'font-weight:500; background:{MUTED}18; color:{MUTED}">'
                    f'{status_label} ✓</span>'
                )

            header_pane = pn.pane.HTML(header_html, sizing_mode="stretch_width")

            # Body
            body_parts = []

            if flag.get("rationale"):
                body_parts.append(flag["rationale"])

            evidence = flag.get("evidence", [])
            if evidence:
                ev_lines = []
                for ev in evidence:
                    section = ev.get("section", "").replace("_", " ").title()
                    quote = ev.get("quote", "")
                    if len(quote) > 200:
                        quote = quote[:200].rsplit(" ", 1)[0] + "..."
                    cref = ev.get("criterion_ref", "")
                    badge = criterion_badge_html(cref) if cref else ""
                    ev_lines.append(f"> *\"{quote}\"*\n>\n> — {section} {badge}")
                body_parts.append("\n\n".join(ev_lines))

            lookups = flag.get("suggested_lookup", [])
            if lookups:
                chips = " ".join(f'<span class="pisa-lookup-chip">{l}</span>' for l in lookups)
                body_parts.append(f"**Suggested lookup:** {chips}")

            followups_list = flag.get("recommended_followup", [])
            if followups_list:
                fu_md = "\n".join(f"- {f}" for f in followups_list)
                body_parts.append(f"**Recommended follow-up:**\n{fu_md}")

            if flag.get("resolution_criteria"):
                body_parts.append(
                    f'<div class="pisa-resolution-box"><strong>Clears when:</strong> '
                    f'{flag["resolution_criteria"]}</div>'
                )

            body_md = "\n\n".join(body_parts) if body_parts else "*No details*"

            card_styles = {"border-left": f"4px solid {level_color}"}
            if is_acked:
                card_styles["opacity"] = "0.6"

            # Build card first, then attach actions that reference it
            flag_card = pn.Card(
                header_pane,
                pn.pane.Markdown(body_md, sizing_mode="stretch_width"),
                title=title,
                collapsed=True,
                collapsible=True,
                sizing_mode="stretch_width",
                styles=card_styles,
            )

            # Mutable follow-up section container (updated in-place on new follow-ups)
            fu_section = pn.Column(sizing_mode="stretch_width")
            if flag_followups:
                fu_section.append(self._build_flag_followups_section(flag_followups))
            flag_card.append(fu_section)

            # Per-flag actions — pass card ref so actions can mutate in place
            if flag_status == "open":
                flag_card.append(self._build_flag_actions(
                    flag, flags, flag_card, header_pane, fu_section, fu_count,
                ))
            elif is_acked:
                flag_card.append(self._build_reopen_action(flag, flag_card, header_pane))

            cards_col.append(flag_card)

        return cards_col

    def _build_flag_followups_section(self, followups: list[dict]) -> pn.Card:
        """Collapsible section showing follow-ups linked to this flag."""
        fu_items = pn.Column(sizing_mode="stretch_width")
        for fu in followups:
            ts = ago_label(fu.get("created_at", ""))
            note = fu.get("reviewer_note", "")
            response = fu.get("applicant_response", "")
            fu_items.append(pn.pane.HTML(
                f'<div style="padding:6px 8px; border-bottom:1px solid {MUTED}22; font-size:12px">'
                f'<div style="color:{MUTED}; font-size:11px; margin-bottom:2px">{ts}</div>'
                f'<div>{note}</div>'
                + (f'<div style="margin-top:4px; color:{TEXT_SECONDARY}; font-style:italic">'
                   f'Response: {response}</div>' if response else '')
                + f'</div>',
                sizing_mode="stretch_width",
            ))

        return pn.Card(
            fu_items,
            header=pn.pane.HTML(
                f'<span style="font-size:11px; font-weight:500; color:{TEXT_SECONDARY}">'
                f'💬 Follow-ups ({len(followups)})</span>',
            ),
            collapsed=True,
            collapsible=True,
            sizing_mode="stretch_width",
            styles={
                "border": f"1px solid {MUTED}33",
                "border-radius": "6px",
                "max-height": "200px",
                "overflow-y": "auto",
            },
        )

    def _build_flag_actions(self, flag: dict, all_flags: list[dict], flag_card: pn.Card,
                            header_pane: pn.pane.HTML, fu_section: pn.Column = None,
                            fu_count: int = 0) -> pn.Column:
        flag_id = flag.get("flag_id", "")
        level_color = LEVEL_COLORS.get(flag.get("level", "green"), MUTED)
        followup_btn = pmui.Button(
            label="Follow-up", icon="chat", variant="outlined", color="primary",
            width=120, sizing_mode="fixed",
        )
        ack_btn = pmui.Button(
            label="Acknowledge", icon="check_circle", variant="outlined", color="success",
            width=140, sizing_mode="fixed",
        )
        adjust_btn = pmui.Button(
            label="Level", icon="tune", variant="outlined", color="default",
            width=90, sizing_mode="fixed",
        )

        actions_column = pn.Column(sizing_mode="stretch_width")
        action_row = pmui.Row(followup_btn, ack_btn, adjust_btn)
        actions_column.append(action_row)

        def show_followup_drawer(event):
            actions_column.clear()
            actions_column.append(action_row)
            drawer = self._build_followup_drawer(
                flag, all_flags, actions_column, header_pane, fu_section, fu_count,
                flag_card=flag_card,
            )
            actions_column.append(drawer)

        followup_btn.on_click(show_followup_drawer)

        def on_acknowledge(event):
            conn = get_connection()
            history_entry = {
                "action": "acknowledge",
                "from_level": flag.get("level", ""),
                "to_level": flag.get("level", ""),
                "reason": "",
                "actor": self._reviewer_name(),
                "timestamp": datetime.now().isoformat(),
            }
            update_flag_status(conn, flag_id, "acknowledged", history_entry)
            conn.close()
            flag["status"] = "acknowledged"
            # Update card in place
            flag_card.collapsed = True
            flag_card.styles = {"border-left": f"4px solid {level_color}", "opacity": "0.6"}
            actions_column.clear()
            actions_column.append(
                self._build_reopen_action(flag, flag_card, header_pane)
            )
            current_html = header_pane.object or ""
            header_pane.object = current_html + (
                f' <span style="padding:2px 8px; border-radius:12px; font-size:10px; '
                f'font-weight:500; background:{MUTED}18; color:{MUTED}">'
                f'acknowledged ✓</span>'
            )
            self._refresh_ack_chip()
            self.param.trigger("request_list_refresh")

        ack_btn.on_click(on_acknowledge)

        def show_adjust_drawer(event):
            actions_column.clear()
            actions_column.append(action_row)
            reason_drawer = self._build_adjust_drawer(flag, actions_column, flag_card, header_pane)
            actions_column.append(reason_drawer)

        adjust_btn.on_click(show_adjust_drawer)

        return actions_column

    def _build_reopen_action(self, flag: dict, flag_card: pn.Card, header_pane: pn.pane.HTML) -> pn.Column:
        """Button to reopen an acknowledged flag."""
        flag_id = flag.get("flag_id", "")
        level_color = LEVEL_COLORS.get(flag.get("level", "green"), MUTED)
        actions_column = pn.Column(sizing_mode="stretch_width")

        reopen_btn = pmui.Button(
            label="Reopen", icon="undo", variant="text", color="default",
            width=100, sizing_mode="fixed",
        )

        def on_reopen(event):
            conn = get_connection()
            history_entry = {
                "action": "reopened",
                "from_level": flag.get("level", ""),
                "to_level": flag.get("level", ""),
                "reason": "",
                "actor": self._reviewer_name(),
                "timestamp": datetime.now().isoformat(),
            }
            update_flag_status(conn, flag_id, "open", history_entry)
            conn.close()
            flag["status"] = "open"
            # Update card in place — explicitly reset opacity
            flag_card.collapsed = False
            flag_card.styles = {"border-left": f"4px solid {level_color}", "opacity": "1"}
            # Reset header — remove the acknowledged badge
            header_pane.object = flag_header_chips_html(flag)
            # Replace reopen button with full action set
            actions_column.clear()
            actions_column.append(
                self._build_flag_actions(flag, [], flag_card, header_pane)
            )
            self._refresh_ack_chip()
            self.param.trigger("request_list_refresh")

        reopen_btn.on_click(on_reopen)
        actions_column.append(reopen_btn)
        return actions_column

    def _build_followup_drawer(self, flag: dict, all_flags: list[dict], parent_column: pn.Column,
                               header_pane: pn.pane.HTML = None, fu_section: pn.Column = None,
                               fu_count: int = 0, flag_card: pn.Card = None) -> pn.Column:
        flag_id = flag.get("flag_id", "")
        current_level = flag.get("level", "green")
        recommended_qs = flag.get("recommended_followup", [])
        resolution_criteria = flag.get("resolution_criteria", "")

        drawer = pn.Column(sizing_mode="stretch_width")

        reviewer_note = pn.widgets.TextAreaInput(
            name="Reviewer note",
            placeholder="What was asked or observed...",
            height=60,
            sizing_mode="stretch_width",
        )

        if recommended_qs:
            drawer.append(eyebrow("Suggested questions (click to insert)"))
            for q in recommended_qs:
                q_btn = pmui.Button(
                    label=q[:60], variant="text", color="default",
                    sizing_mode="stretch_width",
                    sx={"justifyContent": "flex-start", "textAlign": "left"},
                )

                def _make_inserter(question):
                    def insert(event):
                        current = reviewer_note.value or ""
                        reviewer_note.value = (current + "\n" + question).strip()
                    return insert

                q_btn.on_click(_make_inserter(q))
                drawer.append(q_btn)

        if resolution_criteria:
            drawer.append(pn.pane.HTML(
                f'<div class="pisa-resolution-box"><strong>Clears when:</strong> {resolution_criteria}</div>',
                sizing_mode="stretch_width",
            ))

        applicant_response = pn.widgets.TextAreaInput(
            name="Applicant response",
            placeholder="What the applicant said or provided...",
            height=60,
            sizing_mode="stretch_width",
        )

        new_level_select = pmui.Select(
            label="Level after follow-up",
            options=["red", "yellow", "green"],
            value=current_level,
            width=150,
        )

        save_btn = pmui.Button(label="Save", color="primary", icon="save", width=90, sizing_mode="fixed")
        cancel_btn = pmui.Button(label="Cancel", variant="text", color="default", width=80, sizing_mode="fixed")

        def on_save(event):
            if not reviewer_note.value and not applicant_response.value:
                return
            selected_level = new_level_select.value
            level_changed = selected_level != current_level

            followup_record = {
                "followup_id": str(uuid.uuid4()),
                "applicant_id": self.applicant_id,
                "linked_flag_ids": [flag_id],
                "reviewer_note": reviewer_note.value,
                "applicant_response": applicant_response.value,
                "created_at": datetime.now().isoformat(),
                "triggered_reeval": level_changed,
            }

            conn = get_connection()
            save_followup(conn, followup_record)

            if level_changed:
                reason = f"Follow-up: {reviewer_note.value[:100]}"
                downgrade_flag(conn, flag_id, selected_level, reason)

            conn.close()
            # Close drawer in place
            parent_column.pop(-1)

            # Update flag card border color if level changed
            if level_changed and flag_card is not None:
                new_color = LEVEL_COLORS.get(selected_level, MUTED)
                flag_card.styles = {"border-left": f"4px solid {new_color}"}
                flag["level"] = selected_level

            # Update follow-up section and header badge in place
            conn2 = get_connection()
            all_fus = get_followups(conn2, self.applicant_id)
            conn2.close()
            flag_fus = [f for f in all_fus if flag_id in f.get("linked_flag_ids", [])]

            if fu_section is not None:
                fu_section.clear()
                if flag_fus:
                    fu_section.append(self._build_flag_followups_section(flag_fus))

            if header_pane is not None:
                new_count = len(flag_fus)
                base_html = flag_header_chips_html(flag)
                if new_count:
                    base_html += (
                        f' <span style="padding:2px 8px; border-radius:12px; font-size:10px; '
                        f'font-weight:500; background:{PRIMARY}14; color:{PRIMARY}; '
                        f'display:inline-flex; align-items:center; gap:3px">'
                        f'💬 {new_count}</span>'
                    )
                header_pane.object = base_html

            self._refresh_ack_chip()
            self.param.trigger("request_list_refresh")

        def on_cancel(event):
            parent_column.pop(-1)

        save_btn.on_click(on_save)
        cancel_btn.on_click(on_cancel)

        drawer.extend([reviewer_note, applicant_response, new_level_select])
        drawer.append(pmui.Row(save_btn, cancel_btn))
        return drawer

    def _build_adjust_drawer(self, flag: dict, parent_column: pn.Column,
                             flag_card: pn.Card = None, header_pane: pn.pane.HTML = None) -> pn.Column:
        """Drawer for changing flag level (any direction)."""
        flag_id = flag.get("flag_id", "")
        current_level = flag.get("level", "green")

        drawer = pn.Column(sizing_mode="stretch_width")

        level_options = [l for l in ["red", "yellow", "green"] if l != current_level]
        level_select = pmui.Select(
            label=f"New level (currently {current_level})",
            options=level_options,
            value=level_options[0],
            width=200,
        )
        drawer.append(level_select)

        reason_input = pn.widgets.TextAreaInput(
            name="Reason (required)",
            placeholder="Why are you making this change?",
            height=60,
            sizing_mode="stretch_width",
        )
        save_btn = pmui.Button(label="Confirm", color="primary", icon="check", width=110, sizing_mode="fixed", disabled=True)
        cancel_btn = pmui.Button(label="Cancel", variant="text", color="default", width=80, sizing_mode="fixed")

        def on_reason_change(event):
            save_btn.disabled = not bool(event.new.strip())

        reason_input.param.watch(on_reason_change, "value")

        def on_confirm(event):
            reason = reason_input.value.strip()
            if not reason:
                return
            new_level = level_select.value
            conn = get_connection()
            downgrade_flag(conn, flag_id, new_level, reason, actor=self._reviewer_name())
            conn.close()
            # Close drawer in place
            parent_column.pop(-1)
            # Update card border color in place
            new_color = LEVEL_COLORS.get(new_level, MUTED)
            if flag_card is not None:
                flag_card.styles = {"border-left": f"4px solid {new_color}"}
            if header_pane is not None:
                flag["level"] = new_level
                header_pane.object = flag_header_chips_html(flag)
            self._refresh_ack_chip()
            self.param.trigger("request_list_refresh")

        def on_cancel(event):
            parent_column.pop(-1)

        save_btn.on_click(on_confirm)
        cancel_btn.on_click(on_cancel)
        drawer.extend([reason_input, pmui.Row(save_btn, cancel_btn)])
        return drawer

    # --- FOLLOW-UPS TAB ---

    def _build_followup_actions(self, fu: dict) -> pn.Column:
        """Edit and delete buttons for an existing follow-up."""
        fu_id = fu.get("followup_id", "")
        actions = pn.Column(sizing_mode="stretch_width")

        edit_btn = pmui.Button(
            label="Edit", icon="edit", variant="text", color="primary",
            width=80, sizing_mode="fixed",
        )
        delete_btn = pmui.Button(
            label="Delete", icon="delete", variant="text", color="error",
            width=90, sizing_mode="fixed",
        )

        def on_edit(event):
            actions.clear()
            note_input = pn.widgets.TextAreaInput(
                name="Reviewer note",
                value=fu.get("reviewer_note", ""),
                height=60,
                sizing_mode="stretch_width",
            )
            response_input = pn.widgets.TextAreaInput(
                name="Applicant response",
                value=fu.get("applicant_response", ""),
                height=60,
                sizing_mode="stretch_width",
            )
            save_btn = pmui.Button(
                label="Save", color="primary", variant="outlined",
                width=80, sizing_mode="fixed",
            )
            cancel_btn = pmui.Button(
                label="Cancel", variant="text", color="default",
                width=80, sizing_mode="fixed",
            )

            def on_save(event):
                conn = get_connection()
                update_followup(conn, fu_id, note_input.value, response_input.value)
                conn.close()
                self._render()
                self.param.trigger("request_list_refresh")

            def on_cancel(event):
                actions.clear()
                actions.append(btn_row)

            save_btn.on_click(on_save)
            cancel_btn.on_click(on_cancel)
            actions.extend([note_input, response_input, pmui.Row(save_btn, cancel_btn)])

        def on_delete(event):
            actions.clear()
            confirm_label = pn.pane.HTML(
                f'<span style="font-size:12px; color:{LEVEL_RED}">Delete this follow-up?</span>',
                sizing_mode="fixed", width=160,
            )
            confirm_btn = pmui.Button(
                label="Confirm", color="error", variant="outlined",
                width=90, sizing_mode="fixed",
            )
            cancel_btn = pmui.Button(
                label="Cancel", variant="text", color="default",
                width=80, sizing_mode="fixed",
            )

            def on_confirm(event):
                conn = get_connection()
                delete_followup(conn, fu_id)
                conn.close()
                self._render()
                self.param.trigger("request_list_refresh")

            def on_cancel(event):
                actions.clear()
                actions.append(btn_row)

            confirm_btn.on_click(on_confirm)
            cancel_btn.on_click(on_cancel)
            actions.append(pmui.Row(confirm_label, confirm_btn, cancel_btn, align="center"))

        edit_btn.on_click(on_edit)
        delete_btn.on_click(on_delete)
        btn_row = pmui.Row(edit_btn, delete_btn, sizing_mode="stretch_width")
        actions.append(btn_row)
        return actions

    def _build_followup_panel(self, flags: list[dict], followups: list[dict]) -> pn.Column:
        panel = pn.Column(sizing_mode="stretch_width")

        if followups:
            for fu in followups:
                linked = fu.get("linked_flag_ids", [])
                linked_badges = []
                for fid in linked:
                    for f in flags:
                        if f.get("flag_id") == fid:
                            crefs = [ev.get("criterion_ref", "") for ev in f.get("evidence", []) if ev.get("criterion_ref")]
                            badge = fmt_criterion(crefs[0]) if crefs else f.get("title", "")[:15]
                            linked_badges.append(badge)
                            break

                body = ""
                if fu.get("reviewer_note"):
                    body += f"**Note:** {fu['reviewer_note']}\n\n"
                if fu.get("applicant_response"):
                    body += f"**Response:** {fu['applicant_response']}\n\n"
                if linked_badges:
                    body += f"**Linked:** {', '.join(linked_badges)}\n"

                # §6: Informative header
                date_ago = ago_label(fu.get("created_at", ""))
                note_preview = (fu.get("reviewer_note") or "")[:40]
                resolved = " · resolved ✓" if fu.get("triggered_reeval") else ""
                linked_str = f" · re: {', '.join(linked_badges[:2])}" if linked_badges else ""
                card_title = f"{date_ago}{linked_str}{resolved}"
                if note_preview:
                    card_title = f"{date_ago} · {note_preview}{'...' if len(fu.get('reviewer_note', '')) > 40 else ''}{resolved}"

                fu_body = pn.Column(
                    pn.pane.Markdown(body, sizing_mode="stretch_width"),
                    sizing_mode="stretch_width",
                )
                fu_actions = self._build_followup_actions(fu)
                fu_body.append(fu_actions)

                panel.append(pn.Card(
                    fu_body,
                    title=card_title,
                    collapsed=True,
                    sizing_mode="stretch_width",
                ))

        # General note form
        open_flags = [f for f in flags if f.get("status") == "open"]
        if not open_flags and not followups:
            panel.append(pn.pane.HTML(
                f'<div style="padding:16px; color:{MUTED}">No open flags to follow up on.</div>',
                sizing_mode="stretch_width",
            ))
            return panel

        if open_flags:
            flag_options = {f"{f['level'].upper()} | {f['title'][:40]}": f["flag_id"] for f in open_flags}
            flag_select = pn.widgets.MultiChoice(
                name="Link to flags",
                options=list(flag_options.keys()),
                sizing_mode="stretch_width",
            )
            reviewer_note = pn.widgets.TextAreaInput(
                name="General note",
                placeholder="Non-flag-specific observation...",
                height=60,
                sizing_mode="stretch_width",
            )
            save_btn = pmui.Button(label="Save Note", color="primary", variant="outlined", width=120, sizing_mode="fixed")

            def on_save(event):
                if not reviewer_note.value:
                    return
                selected_labels = flag_select.value or []
                linked_ids = [flag_options[label] for label in selected_labels]
                followup_record = {
                    "followup_id": str(uuid.uuid4()),
                    "applicant_id": self.applicant_id,
                    "linked_flag_ids": linked_ids,
                    "reviewer_note": reviewer_note.value,
                    "applicant_response": "",
                    "created_at": datetime.now().isoformat(),
                    "triggered_reeval": False,
                }
                conn = get_connection()
                save_followup(conn, followup_record)
                conn.close()
                self._render()
                self.param.trigger("request_list_refresh")

            save_btn.on_click(on_save)
            panel.append(pn.Card(
                flag_select, reviewer_note, save_btn,
                title="Add general note",
                collapsed=True,
                sizing_mode="stretch_width",
            ))

        return panel

    # --- TIMELINE TAB (§6) ---

    def _build_timeline_tab(self, flags: list[dict], followups: list[dict], runs: list[dict]) -> pn.Column:
        tab = pn.Column(sizing_mode="stretch_width")

        conn = get_connection()
        review_history = get_review_history(conn, self.applicant_id)
        conn.close()

        if not runs and not flags and not followups and not review_history:
            tab.append(pn.pane.HTML(
                f'<div style="padding:24px; color:{MUTED}">No activity yet.</div>',
                sizing_mode="stretch_width",
            ))
            return tab

        # Group events by run (§6)
        for run in runs:
            run_ts = run.get("started_at", "")
            run_ago = ago_label(run_ts)
            duration = fmt_duration(run.get("duration_seconds", 0))
            model = run.get("model_id", "?")
            status = run.get("status", "?")
            status_color = LEVEL_GREEN if status == "complete" else LEVEL_RED

            # Run header
            tab.append(pn.pane.HTML(
                f'<div style="display:flex; align-items:center; gap:8px; padding:8px 0; '
                f'border-bottom:1px solid {MUTED}33; margin-top:12px">'
                f'<span style="color:{status_color}">↻</span>'
                f'<span style="font-size:13px; font-weight:500">Screening · {run_ago} · {duration} · {model}</span>'
                f'</div>',
                sizing_mode="stretch_width",
            ))

            # Flags created in this run (match by timestamp proximity)
            run_start = run.get("started_at", "")
            run_end = run.get("completed_at", "")
            run_flags = [
                f for f in flags
                if f.get("created_at", "") >= run_start and (not run_end or f.get("created_at", "") <= run_end)
            ]

            if run_flags:
                for flag in run_flags:
                    level = flag.get("level", "green")
                    color = LEVEL_COLORS.get(level, MUTED)
                    title = flag.get("title", "")[:50]
                    tab.append(pn.pane.HTML(
                        f'<div style="padding:2px 0 2px 20px; font-size:12px; display:flex; gap:6px; align-items:center">'
                        f'<span style="color:{color}; font-size:8px">●</span>'
                        f'<span>Flag: {title}</span></div>',
                        sizing_mode="stretch_width",
                    ))

            # Flag history entries from this run period
            for flag in flags:
                for entry in flag.get("history", []):
                    entry_ts = entry.get("timestamp", "")
                    if entry_ts >= run_start and (not run_end or entry_ts <= run_end):
                        tab.append(self._render_history_entry(entry, flag))

        # Follow-ups (outside runs)
        if followups:
            tab.append(pn.pane.HTML(
                f'<div style="font-size:11px; text-transform:uppercase; letter-spacing:0.06em; '
                f'color:{MUTED}; margin-top:16px; padding-bottom:4px; border-bottom:1px solid {MUTED}33">'
                f'Follow-ups</div>',
                sizing_mode="stretch_width",
            ))
            for fu in followups:
                fu_ago = ago_label(fu.get("created_at", ""))
                note = (fu.get("reviewer_note") or "")[:50]
                resolved = " · resolved ✓" if fu.get("triggered_reeval") else ""
                tab.append(pn.pane.HTML(
                    f'<div style="padding:4px 0 4px 20px; font-size:12px; display:flex; gap:6px">'
                    f'<span>💬</span><span>{fu_ago} — {note}{resolved}</span></div>',
                    sizing_mode="stretch_width",
                ))

        # Flag changes outside of runs
        orphan_changes = []
        for flag in flags:
            for entry in flag.get("history", []):
                entry_ts = entry.get("timestamp", "")
                in_run = False
                for run in runs:
                    if entry_ts >= run.get("started_at", "") and (not run.get("completed_at") or entry_ts <= run.get("completed_at", "")):
                        in_run = True
                        break
                if not in_run:
                    orphan_changes.append((entry_ts, flag, entry))

        # Combine orphan flag changes and review state changes into one section
        reviewer_events = []
        for ts, flag, entry in orphan_changes:
            reviewer_events.append((ts, "flag", flag, entry))
        for entry in review_history:
            reviewer_events.append((entry.get("timestamp", ""), "state", None, entry))

        if reviewer_events:
            reviewer_events.sort(key=lambda x: x[0], reverse=True)
            tab.append(pn.pane.HTML(
                f'<div style="font-size:11px; text-transform:uppercase; letter-spacing:0.06em; '
                f'color:{MUTED}; margin-top:16px; padding-bottom:4px; border-bottom:1px solid {MUTED}33">'
                f'Reviewer actions</div>',
                sizing_mode="stretch_width",
            ))
            for ts, event_type, flag, entry in reviewer_events:
                change_ago = ago_label(ts)
                if event_type == "flag":
                    title = flag.get("title", "")[:30]
                    icon, label = self._history_icon_label(entry)
                    tab.append(pn.pane.HTML(
                        f'<div style="padding:4px 0 4px 20px; font-size:12px">'
                        f'{icon} {change_ago} — {title}: {label}</div>',
                        sizing_mode="stretch_width",
                    ))
                elif event_type == "state":
                    from_s = entry.get("from_state", "?").replace("_", " ")
                    to_s = entry.get("to_state", "?").replace("_", " ")
                    actor = entry.get("actor", "")
                    actor_suffix = f" by {actor}" if actor and actor != "reviewer" else ""
                    tab.append(pn.pane.HTML(
                        f'<div style="padding:4px 0 4px 20px; font-size:12px">'
                        f'◆ {change_ago} — status: {from_s} → {to_s}{actor_suffix}</div>',
                        sizing_mode="stretch_width",
                    ))

        return tab

    def _history_icon_label(self, entry: dict) -> tuple[str, str]:
        """Return (icon, label) for a history entry."""
        action = entry.get("action", "changed")
        from_l = entry.get("from_level", "?")
        to_l = entry.get("to_level", "?")
        reason = entry.get("reason", "")[:40]
        actor = entry.get("actor", "")
        actor_suffix = f" by {actor}" if actor and actor != "reviewer" else ""
        if action == "acknowledge":
            return ("✓", f"acknowledged{actor_suffix}")
        elif action == "reopened":
            return ("↺", f"reopened{actor_suffix}")
        elif action == "merged":
            merged_title = entry.get("merged_from", "?")[:35]
            return ("⇄", f'merged "{merged_title}" (kept {to_l})')
        elif action in ("escalated", "downgraded"):
            suffix = f" — {reason}" if reason else ""
            return ("⇅", f"{action} {from_l} → {to_l}{suffix}{actor_suffix}")
        else:
            suffix = f" — {reason}" if reason else ""
            return ("⇅", f"{action} {from_l} → {to_l}{suffix}{actor_suffix}")

    def _render_history_entry(self, entry: dict, flag: dict) -> pn.pane.HTML:
        """Render a single history entry as an HTML pane."""
        action = entry.get("action", "changed")
        icon, label = self._history_icon_label(entry)
        return pn.pane.HTML(
            f'<div style="padding:2px 0 2px 20px; font-size:12px; color:{TEXT_SECONDARY}">'
            f'{icon} {label}</div>',
            sizing_mode="stretch_width",
        )

    # --- FORM TAB ---

    def _build_sections_panel(self, sections_data: dict) -> pn.Column:
        accordions = pn.Column(sizing_mode="stretch_width")

        for section_key, section in sections_data.items():
            qa_pairs = section.get("qa_pairs", [])
            meds = section.get("medications", [])
            checklist = section.get("condition_checklist", [])
            consumption = section.get("consumption_table", [])

            if not qa_pairs and not meds and not checklist and not consumption:
                continue

            body_parts = []

            for qa in qa_pairs:
                status = qa.get("status", "answered")
                answer = qa.get("answer", "")
                status_note = ""
                if status == "deferred":
                    status_note = " *(DEFERRED)*"
                elif status == "blank":
                    status_note = " *(BLANK)*"
                body_parts.append(f"**Q:** {qa.get('question', '')}\n\n**A:** {answer}{status_note}")

            if meds:
                med_lines = [f"| {m.get('medication','')} | {m.get('dosage','')} | {m.get('indication','')} | {m.get('since','')} |" for m in meds]
                body_parts.append("**Medications:**\n\n| Medication | Dosage | Indication | Since |\n|---|---|---|---|\n" + "\n".join(med_lines))

            if checklist:
                checked = [e["condition"] for e in checklist if e.get("checked")]
                if checked:
                    body_parts.append(f"**Conditions checked:** {', '.join(checked)}")

            if consumption:
                c_lines = [f"- {c.get('substance','')}: {c.get('amount','')}" for c in consumption]
                body_parts.append("**Consumption:**\n" + "\n".join(c_lines))

            body_md = "\n\n---\n\n".join(body_parts) if body_parts else "*Empty section*"
            accordions.append(pn.Card(
                pn.pane.Markdown(body_md, sizing_mode="stretch_width"),
                title=section_key.replace("_", " ").title(),
                collapsed=True,
                sizing_mode="stretch_width",
            ))

        return accordions

    def panel(self) -> pn.Column:
        self._render()
        return pn.Column(self._content, sizing_mode="stretch_width")
