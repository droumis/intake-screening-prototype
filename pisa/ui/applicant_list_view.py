"""View A — Applicant List: filesystem-driven discovery, dataset-scoped table."""

from __future__ import annotations

import param
import panel as pn
import panel_material_ui as pmui
from pathlib import Path

from pisa.config import load_config
from pisa.model.ollama import OllamaProvider
from pisa.parser.markdown import parse_file
from pisa.pipeline.queue import pipeline_queue
from pisa.pipeline.runner import PipelineResult, ProgressCallback
from pisa.profile.loader import load_context_documents, compute_context_hash
from pisa.profile.store import load_profile
from pisa.store.db import (
    get_connection, init_db, list_applicants, save_applicant,
    get_flag_summary, get_flag_ack_summary, replace_flags, save_pipeline_run, get_last_screened,
)
from pisa.ui.theme import LEVEL_RED, LEVEL_AMBER, LEVEL_GREEN, STATE_COLORS, MUTED, PRIMARY
from pisa.ui.fmt import ago_label, fmt_duration


def _flag_chips_html(red: int, yellow: int, green: int) -> str:
    if not red and not yellow and not green:
        return f'<span style="color:{MUTED}">—</span>'
    parts = []
    if red:
        parts.append(f'<span style="color:{LEVEL_RED}; font-weight:600">{red}R</span>')
    if yellow:
        parts.append(f'<span style="color:{LEVEL_AMBER}; font-weight:600">{yellow}Y</span>')
    if green:
        parts.append(f'<span style="color:{LEVEL_GREEN}; font-weight:600">{green}G</span>')
    return " · ".join(parts)


def _ack_html(ack: int, total: int) -> str:
    if total == 0:
        return f'<span style="color:{MUTED}">—</span>'
    color = LEVEL_GREEN if ack == total else MUTED
    return f'<span style="color:{color}; font-weight:500">{ack}/{total}</span>'




def _state_chip_html(state: str) -> str:
    color = STATE_COLORS.get(state, MUTED)
    label = state.replace("_", " ")
    return (
        f'<span style="display:inline-block; padding:2px 8px; border-radius:12px; '
        f'font-size:12px; background:{color}18; color:{color}; font-weight:500">'
        f'{label}</span>'
    )


class ApplicantListView(param.Parameterized):
    refresh = param.Event()
    run_all = param.Event()
    selected_applicant_id = param.String(default="")
    dataset_filter = param.String(default="")

    def __init__(self, **params):
        super().__init__(**params)
        self._config = load_config()
        self._conn = get_connection()
        init_db(self._conn)
        self._table_pane = pn.Column(sizing_mode="stretch_width")
        self._tabulator = None
        self._table_rows = []
        self._run_progress_row = None
        self._status_pane = pn.pane.Alert("", alert_type="info", visible=False)
        self._dismiss_btn = pmui.Button(
            icon="close", variant="text", color="default",
            width=36, sizing_mode="fixed", visible=False,
            sx={"minWidth": "36px", "p": 0},
        )
        self._dismiss_btn.on_click(lambda e: self._dismiss_status())
        self._status_row = pmui.Row(
            self._status_pane, self._dismiss_btn,
            sizing_mode="stretch_width", align="center",
        )
        self._count_label = pn.pane.HTML("", sizing_mode="fixed", width=200)
        self._sync_from_filesystem()
        self._refresh_table()

    def _row_index_for_applicant(self, applicant_id: str) -> int | None:
        for i, row in enumerate(self._table_rows):
            if row.get("ID") == applicant_id:
                return i
        return None

    def _patch_state_cell(self, applicant_id: str, html: str):
        idx = self._row_index_for_applicant(applicant_id)
        if idx is not None and self._tabulator is not None:
            self._tabulator.patch({"State": [(idx, html)]})

    def _patch_row_for_applicant(self, applicant_id: str):
        """Patch all data columns for a single applicant after their run completes."""
        idx = self._row_index_for_applicant(applicant_id)
        if idx is None or self._tabulator is None:
            return
        conn = get_connection()
        row = conn.execute(
            "SELECT review_state FROM applicants WHERE applicant_id = ?", (applicant_id,)
        ).fetchone()
        flag_counts = get_flag_summary(conn, applicant_id)
        ack_summary = get_flag_ack_summary(conn, applicant_id)
        last_screened_map = get_last_screened(conn)
        conn.close()

        state = row["review_state"] if row else "unreviewed"
        red = flag_counts.get("red", 0)
        yellow = flag_counts.get("yellow", 0)
        green = flag_counts.get("green", 0)
        run_info = last_screened_map.get(applicant_id)
        last_screened_display = ago_label(run_info["last_run"]) if run_info else "—"
        duration_str = fmt_duration(run_info["duration_seconds"]) if run_info else ""

        self._tabulator.patch({
            "State": [(idx, _state_chip_html(state))],
            "Flags": [(idx, _flag_chips_html(red, yellow, green))],
            "Acknowledged": [(idx, _ack_html(ack_summary["ack"], ack_summary["total"]))],
            "Last Screened": [(idx, last_screened_display)],
            "Duration": [(idx, duration_str)],
        })

    def _show_status(self, message: str, alert_type: str = "info"):
        self._status_pane.object = message
        self._status_pane.alert_type = alert_type
        self._status_pane.visible = True
        self._dismiss_btn.visible = True

    def _dismiss_status(self):
        self._status_pane.visible = False
        self._dismiss_btn.visible = False

    @param.depends("dataset_filter", watch=True)
    def _on_dataset_filter_change(self):
        self._refresh_table()

    def _discover_datasets(self) -> list[Path]:
        data_dir = Path(self._config.app.data_dir)
        if not data_dir.exists():
            return []
        return sorted(
            p for p in data_dir.iterdir()
            if p.is_dir() and not p.name.startswith(".")
        )

    def _sync_from_filesystem(self):
        existing = list_applicants(self._conn)
        existing_paths = {a.get("applicant_id") for a in existing}

        existing_form_paths = set()
        for a in existing:
            row = self._conn.execute(
                "SELECT raw_form_path FROM applicants WHERE applicant_id = ?",
                (a["applicant_id"],),
            ).fetchone()
            if row and row["raw_form_path"]:
                existing_form_paths.add(row["raw_form_path"])

        datasets = self._discover_datasets()
        imported = 0

        for dataset_dir in datasets:
            forms_dir = dataset_dir / "forms"
            if not forms_dir.exists():
                continue
            dataset_name = dataset_dir.name
            for form_path in sorted(forms_dir.glob("*.md")):
                if str(form_path) in existing_form_paths:
                    continue
                try:
                    record = parse_file(form_path)
                    if record.applicant_id in existing_paths:
                        continue
                    save_applicant(self._conn, record, dataset=dataset_name)
                    existing_paths.add(record.applicant_id)
                    existing_form_paths.add(str(form_path))
                    imported += 1
                except Exception:
                    pass

        if imported:
            self._show_status(f"Imported {imported} new applicant(s).", "success")

    def _refresh_table(self):
        self._table_pane.clear()
        conn = get_connection()
        if self.dataset_filter:
            applicants = list_applicants(conn, dataset=self.dataset_filter)
        else:
            applicants = list_applicants(conn)

        self._count_label.object = (
            f'<span style="font-size:14px; font-weight:600">Applicants ({len(applicants)})</span>'
        )

        if not applicants:
            self._table_pane.append(pn.pane.Alert(
                "No applicants found. Add `.md` forms to the dataset's `forms/` directory and click Refresh.",
                alert_type="info",
            ))
            conn.close()
            return

        last_screened_map = get_last_screened(conn)

        rows = []
        for app in applicants:
            flag_counts = get_flag_summary(conn, app["applicant_id"])
            red = flag_counts.get("red", 0)
            yellow = flag_counts.get("yellow", 0)
            green = flag_counts.get("green", 0)

            ack_summary = get_flag_ack_summary(conn, app["applicant_id"])

            run_info = last_screened_map.get(app["applicant_id"])
            if run_info:
                last_screened_display = ago_label(run_info["last_run"])
                duration_str = fmt_duration(run_info["duration_seconds"])
            else:
                last_screened_display = "—"
                duration_str = ""

            rows.append({
                "Name": app["display_name"],
                "State": _state_chip_html(app["review_state"]),
                "Flags": _flag_chips_html(red, yellow, green),
                "Acknowledged": _ack_html(ack_summary["ack"], ack_summary["total"]),
                "Last Screened": last_screened_display,
                "Duration": duration_str,
                "ID": app["applicant_id"],
            })

        import pandas as pd
        df = pd.DataFrame(rows)

        formatters = {
            "State": {"type": "html"},
            "Flags": {"type": "html"},
            "Acknowledged": {"type": "html"},
        }

        widths = {
            "Name": "26%",
            "State": "16%",
            "Flags": "16%",
            "Acknowledged": "12%",
            "Last Screened": "16%",
            "Duration": "14%",
        }

        tabulator = pn.widgets.Tabulator(
            df,
            sizing_mode="stretch_width",
            height=min(360, 50 + len(rows) * 38),
            show_index=False,
            hidden_columns=["ID"],
            selectable=1,
            disabled=True,
            formatters=formatters,
            widths=widths,
            text_align={"Flags": "center", "Duration": "right"},
        )

        def on_row_click(event):
            if event.row is not None and event.row < len(rows):
                clicked_id = rows[event.row]["ID"]
                self.selected_applicant_id = clicked_id

        tabulator.on_click(on_row_click)
        self._table_pane.append(tabulator)
        self._tabulator = tabulator
        self._table_rows = rows
        conn.close()

    @param.depends("refresh", watch=True)
    def _on_refresh(self):
        self._sync_from_filesystem()
        self._refresh_table()

    @param.depends("run_all", watch=True)
    def _on_run_all(self):
        if not self.dataset_filter:
            self._show_status("Select a program first.", "warning")
            return

        applicants = list_applicants(self._conn, dataset=self.dataset_filter)

        if not applicants:
            self._show_status("No applicants to analyze.", "warning")
            return

        config = self._config
        provider = OllamaProvider(config.model)

        dataset = self.dataset_filter
        context_dir = Path(config.app.data_dir) / dataset / "context"
        if not context_dir.exists():
            self._show_status(f"No context directory for dataset '{dataset}'.", "danger")
            return

        docs = load_context_documents(context_dir)
        if not docs:
            self._show_status(f"No context documents found for '{dataset}'.", "danger")
            return
        context_hash = compute_context_hash(docs)
        profile = load_profile(context_hash)

        if not profile:
            self._show_status(
                f"No profile found for '{dataset}' (hash: {context_hash[:12]}…). "
                f"Go to Setup and build/approve a profile first.",
                "warning",
            )
            return

        total = len(applicants)
        completed = [0]
        failed = [0]

        progress_bar = pmui.LinearProgress(value=0, width=300)
        progress_label = pn.pane.HTML(
            f'<span style="font-size:13px">Running 0/{total}...</span>',
            sizing_mode="fixed", width=200,
        )
        self._status_pane.visible = False
        self._dismiss_btn.visible = False
        self._run_progress_row = pmui.Row(
            progress_bar, progress_label,
            sizing_mode="stretch_width", align="center",
        )
        self._status_row.append(self._run_progress_row)

        screening_html = (
            f'<span style="display:inline-flex; align-items:center; gap:4px; padding:2px 8px; '
            f'border-radius:12px; font-size:12px; background:{PRIMARY}14; color:{PRIMARY}; font-weight:500">'
            f'⟳ screening</span>'
        )
        queued_html = (
            f'<span style="display:inline-block; padding:2px 8px; border-radius:12px; '
            f'font-size:12px; background:{MUTED}18; color:{MUTED}; font-weight:500">'
            f'queued</span>'
        )
        app_queue = list(applicants)

        def _mark_next_running():
            for a in app_queue:
                if a.get("_status") == "queued":
                    a["_status"] = "running"
                    self._patch_state_cell(a["applicant_id"], screening_html)
                    break

        def _update_progress(aid: str, name: str, success: bool):
            if success:
                completed[0] += 1
            else:
                failed[0] += 1
            done = completed[0] + failed[0]
            pct = int(100 * done / total)

            def _do():
                progress_bar.value = pct
                self._patch_row_for_applicant(aid)

                if done < total:
                    progress_label.object = (
                        f'<span style="font-size:13px">{done}/{total} done...</span>'
                    )
                    _mark_next_running()
                else:
                    if self._run_progress_row in self._status_row:
                        self._status_row.remove(self._run_progress_row)
                    msg = f"Completed {completed[0]}/{total} applicants."
                    if failed[0]:
                        msg += f" ({failed[0]} failed)"
                    self._show_status(msg, "success" if not failed[0] else "warning")

            pn.state.execute(_do)

        # Mark all as queued in the table, then start processing
        for app in app_queue:
            app["_status"] = "queued"
            self._patch_state_cell(app["applicant_id"], queued_html)

        for app in app_queue:
            record = _load_record_from_db(self._conn, app["applicant_id"])
            if not record:
                app["_status"] = "done"
                _update_progress(app["applicant_id"], app["display_name"], False)
                continue

            def _make_completion_handler(aid, name):
                def on_complete(result: PipelineResult):
                    conn = get_connection()
                    replace_flags(conn, aid, result.flags)
                    save_pipeline_run(conn, result.to_run_record(), aid)
                    conn.close()
                    _update_progress(aid, name, result.status == "complete")
                return on_complete

            pipeline_queue.enqueue(
                record=record,
                profile=profile,
                provider=provider,
                on_complete=_make_completion_handler(app["applicant_id"], app["display_name"]),
            )

        # Mark the first one as actively running
        _mark_next_running()
        progress_label.object = (
            f'<span style="font-size:13px">0/{total} done...</span>'
        )

    def _cancel_all_runs(self):
        pipeline_queue.cancel()
        if self._run_progress_row and self._run_progress_row in self._status_row:
            self._status_row.remove(self._run_progress_row)
        self._show_status("Screening interrupted.", "warning")
        self._refresh_table()

    def panel(self) -> pn.Column:
        refresh_btn = pmui.Button(
            label="Refresh", color="primary", variant="outlined",
            icon="refresh", width=110, sizing_mode="fixed",
        )
        refresh_btn.on_click(lambda e: self.param.trigger("refresh"))

        run_btn = pmui.Button(
            label="Run All", color="primary",
            icon="play_arrow", width=110, sizing_mode="fixed",
        )
        run_btn.on_click(lambda e: self.param.trigger("run_all"))

        self._more_menu = pmui.MenuButton(
            items=[{"label": "Stop screening", "icon": "stop"}],
            label="",
            icon="more_vert",
            variant="text",
            color="default",
            sx={"minWidth": "36px", "p": 0},
            width=40,
        )

        def on_more_action(event):
            if not event.new:
                return
            label = event.new.get("label", "").lower()
            if "stop" in label:
                self._cancel_all_runs()

        self._more_menu.param.watch(on_more_action, "value")

        # §2: heading left, buttons right
        toolbar = pmui.Row(
            self._count_label,
            pn.Spacer(),
            refresh_btn,
            run_btn,
            self._more_menu,
            sizing_mode="stretch_width",
            align="center",
        )

        return pn.Column(
            toolbar,
            self._status_row,
            self._table_pane,
            sizing_mode="stretch_width",
        )


def _load_record_from_db(conn, applicant_id: str):
    """Reconstruct an ApplicantRecord from the database."""
    import json
    from pisa.parser.models import ApplicantRecord, ParsedSection, Identity

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
