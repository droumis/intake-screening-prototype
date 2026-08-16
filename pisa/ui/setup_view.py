"""View C — Program Setup: model health, context docs, profile approval."""

from __future__ import annotations

import threading

import param
import panel as pn
import panel_material_ui as pmui
from pathlib import Path

from pisa.config import load_config
from pisa.model.ollama import OllamaProvider, ModelResponseError
from pisa.profile.loader import load_context_documents, compute_context_hash
from pisa.profile.models import ScreeningProfile
from pisa.profile.builder import build_profile, detect_conflicts
from pisa.profile.store import save_profile, load_profile, approve_profile, is_profile_stale
from pisa.store.db import get_connection, get_setting, set_setting
from pisa.ui.theme import (
    LEVEL_RED, LEVEL_AMBER, LEVEL_GREEN, MUTED, PRIMARY,
    TEXT_SECONDARY, DIVIDER, SUCCESS, WARNING,
)
from pisa.ui.style import card, eyebrow, criterion_badge_html


class SetupView(param.Parameterized):
    check_health = param.Event()
    dataset = param.Selector(default="", objects=[""])
    build_profile_event = param.Event()
    approve_profile_event = param.Event()
    include_conflicting = param.Boolean(default=False)

    def __init__(self, **params):
        super().__init__(**params)
        self._config = load_config()
        self._provider = OllamaProvider(self._config.model)
        self._status_pane = pn.pane.Alert("Checking model status...", alert_type="info")
        self._profile_pane = pn.Column(sizing_mode="stretch_width")
        self._conflict_pane = pn.Column(sizing_mode="stretch_width")
        self._cache_pane = pn.Column(sizing_mode="stretch_width")
        self._docs_pane = pn.Column(sizing_mode="stretch_width")
        self._current_profile: ScreeningProfile | None = None
        self._building = False
        self._doc_selector: pn.widgets.CheckBoxGroup | None = None
        self._available_docs: list = []
        self._run_health_check()
        self._discover_datasets()

    def _discover_datasets(self):
        data_dir = Path(self._config.app.data_dir)
        if data_dir.exists():
            datasets = sorted(p.name for p in data_dir.iterdir() if p.is_dir() and not p.name.startswith("."))
            self.param.dataset.objects = datasets
            if datasets:
                self.dataset = datasets[0]

    def _run_health_check(self):
        status = self._provider.health_check()
        if status.available:
            self._status_pane.object = f"Model ready: {status.model_name}"
            self._status_pane.alert_type = "success"
        elif status.server_reachable:
            self._status_pane.object = (
                f"Model not found: {status.model_name}  \n"
                f"Run: `ollama pull {status.model_name}`"
            )
            self._status_pane.alert_type = "warning"
        else:
            self._status_pane.object = (
                f"Ollama server not reachable at {self._config.model.base_url}  \n"
                "Start Ollama or check your configuration."
            )
            self._status_pane.alert_type = "danger"

    @param.depends("check_health", watch=True)
    def _on_check_health(self):
        self._run_health_check()

    @param.depends("dataset", watch=True)
    def _on_dataset_change(self):
        self._current_profile = None
        self._profile_pane.clear()
        self._conflict_pane.clear()
        self._refresh_docs()
        self._check_cache()
        self._refresh_sidebar_summary()

    def _refresh_docs(self):
        self._docs_pane.clear()
        self._doc_selector = None
        self._available_docs = []

        if not self.dataset:
            return

        context_dir = Path(self._config.app.data_dir) / self.dataset / "context"
        docs = load_context_documents(context_dir, include_conflicting=True)

        if not docs:
            self._docs_pane.append(pn.pane.Alert(
                "No context documents found in this dataset's `context/` folder.",
                alert_type="warning",
            ))
            return

        self._available_docs = docs

        options = []
        default_value = []
        for doc in docs:
            is_conflicting = "CONFLICTING" in doc.path.name
            char_count = len(doc.content)
            type_label = doc.doc_type.replace("_", " ")
            label = f"{doc.path.name} ({type_label}, {char_count:,} chars)"
            if is_conflicting:
                label += " [test-only]"
            options.append(label)
            if not is_conflicting:
                default_value.append(label)

        self._doc_selector = pn.widgets.CheckBoxGroup(
            options=options,
            value=default_value,
            sizing_mode="stretch_width",
        )
        self._docs_pane.append(self._doc_selector)

    def _get_selected_docs(self):
        if not self._doc_selector or not self._available_docs:
            return []
        selected_labels = set(self._doc_selector.value)
        selected = []
        for doc in self._available_docs:
            is_conflicting = "CONFLICTING" in doc.path.name
            char_count = len(doc.content)
            type_label = doc.doc_type.replace("_", " ")
            label = f"{doc.path.name} ({type_label}, {char_count:,} chars)"
            if is_conflicting:
                label += " [test-only]"
            if label in selected_labels:
                selected.append(doc)
        return selected

    def _check_cache(self):
        self._cache_pane.clear()
        docs = self._get_selected_docs()
        if not docs:
            return

        context_hash = compute_context_hash(docs)
        cached = load_profile(context_hash)

        if cached:
            status = "approved" if cached.approved else "unapproved"
            self._cache_pane.append(pn.pane.Alert(
                f"**Cached profile found** ({status}) — "
                f"{len(cached.hard_criteria)} hard, {len(cached.caution_criteria)} caution criteria. "
                f"Click **Use Cached** to load it, or **Rebuild** to generate fresh.",
                alert_type="success",
            ))

            use_btn = pmui.Button(label="Use Cached", color="success", width=120, sizing_mode="fixed")

            def on_use_cached(event):
                self._current_profile = cached
                self._profile_pane.clear()
                self._conflict_pane.clear()
                self._render_profile(cached)
                self._refresh_sidebar_summary()
                if not cached.approved:
                    self._profile_pane.insert(0, pn.pane.Alert(
                        "Loaded from cache. Review and **Approve** to unblock analysis.",
                        alert_type="info",
                    ))
                else:
                    self._profile_pane.insert(0, pn.pane.Alert(
                        "Loaded approved profile from cache. Ready to analyze applicants.",
                        alert_type="success",
                    ))

            use_btn.on_click(on_use_cached)
            self._cache_pane.append(use_btn)
        else:
            self._cache_pane.append(pn.pane.Alert(
                "No cached profile for this dataset. Click **Build Profile** to generate one (~3-5 min).",
                alert_type="info",
            ))

    @param.depends("build_profile_event", watch=True)
    def _on_build_profile(self):
        if self._building:
            pn.state.notifications.warning("Profile build already in progress.")
            return

        self._profile_pane.clear()
        self._conflict_pane.clear()
        self._cache_pane.clear()
        self._building = True

        self._profile_pane.append(pn.pane.Alert(
            "**Building Screening Profile...** This takes ~3-5 minutes. "
            "The model is extracting criteria from your context documents. "
            "You can continue using other tabs while this runs.",
            alert_type="info",
        ))
        spinner = pn.indicators.LoadingSpinner(value=True, size=30)
        self._profile_pane.append(spinner)

        thread = threading.Thread(target=self._build_profile_async, daemon=True)
        thread.start()

    def _build_profile_async(self):
        try:
            docs = self._get_selected_docs()

            if not docs:
                pn.state.execute(self._build_done_no_docs)
                return

            current_hash = compute_context_hash(docs)

            cached = load_profile(current_hash)
            if cached and cached.approved:
                self._current_profile = cached
                pn.state.execute(lambda: self._build_done_cached(cached))
                return

            profile = build_profile(self._provider, docs)
            conflicts = detect_conflicts(profile, docs)
            profile.conflicts = conflicts
            self._current_profile = profile
            save_profile(profile)

            pn.state.execute(lambda: self._build_done_success(profile, conflicts))

        except ModelResponseError as e:
            pn.state.execute(lambda: self._build_done_error(f"Profile build failed: {e}"))
        except Exception as e:
            pn.state.execute(lambda: self._build_done_error(f"Error: {e}"))
        finally:
            self._building = False

    def _build_done_no_docs(self):
        self._profile_pane.clear()
        self._profile_pane.append(pn.pane.Alert("No context documents found.", alert_type="warning"))

    def _build_done_cached(self, cached: ScreeningProfile):
        self._profile_pane.clear()
        self._render_profile(cached)
        self._refresh_sidebar_summary()
        self._profile_pane.insert(0, pn.pane.Alert(
            "Loaded approved profile from cache.", alert_type="success",
        ))

    def _build_done_success(self, profile: ScreeningProfile, conflicts: list):
        self._profile_pane.clear()
        self._profile_pane.insert(0, pn.pane.Alert(
            "**Profile built successfully.** Review below and click **Approve** to unblock analysis.",
            alert_type="success",
        ))
        self._render_profile(profile)
        self._render_conflicts(conflicts)
        self._refresh_sidebar_summary()

    def _build_done_error(self, message: str):
        self._profile_pane.clear()
        self._profile_pane.append(pn.pane.Alert(message, alert_type="danger"))

    @param.depends("approve_profile_event", watch=True)
    def _on_approve_profile(self):
        if self._current_profile and not self._current_profile.approved:
            self._current_profile = approve_profile(self._current_profile)
            self._profile_pane.insert(0, pn.pane.Alert(
                "Profile approved. Analysis is now unblocked.",
                alert_type="success",
            ))
            self._refresh_sidebar_summary()
            pn.state.notifications.success("Screening Profile approved.")

    def _render_profile(self, profile: ScreeningProfile):
        """§5: Render profile with one status line + stat chips, criteria as expandable rows."""
        # One status line (§5)
        status_color = SUCCESS if profile.approved else WARNING
        status_label = "Approved" if profile.approved else "Awaiting approval"
        stat_chips = (
            f'<div style="display:flex; gap:8px; flex-wrap:wrap; align-items:center; margin:8px 0">'
            f'<span style="padding:3px 10px; border-radius:12px; font-size:12px; '
            f'background:{status_color}18; color:{status_color}; font-weight:500">{status_label}</span>'
            f'<span style="padding:3px 10px; border-radius:12px; font-size:12px; '
            f'background:{LEVEL_RED}18; color:{LEVEL_RED}">{len(profile.hard_criteria)} hard</span>'
            f'<span style="padding:3px 10px; border-radius:12px; font-size:12px; '
            f'background:{LEVEL_AMBER}18; color:{LEVEL_AMBER}">{len(profile.caution_criteria)} caution</span>'
            f'<span style="padding:3px 10px; border-radius:12px; font-size:12px; '
            f'background:{DIVIDER}; color:{TEXT_SECONDARY}">{len(profile.medication_classes_of_concern)} med classes</span>'
            f'<span style="padding:3px 10px; border-radius:12px; font-size:12px; '
            f'background:{DIVIDER}; color:{TEXT_SECONDARY}">{len(profile.program_demands)} demands</span>'
            f'<span style="padding:3px 10px; border-radius:12px; font-size:12px; '
            f'background:{DIVIDER}; color:{TEXT_SECONDARY}">{len(profile.ground_rules)} rules</span>'
            f'</div>'
        )
        self._profile_pane.append(pn.pane.HTML(stat_chips, sizing_mode="stretch_width"))

        # §5: Hard criteria as expandable rows (not table)
        if profile.hard_criteria:
            criteria_col = pn.Column(sizing_mode="stretch_width")
            for c in profile.hard_criteria:
                det = c.detection
                # Detection spec visible (§5)
                det_parts = []
                if det.keywords:
                    det_parts.append(f"**Keywords:** {', '.join(det.keywords[:8])}")
                if det.sections:
                    det_parts.append(f"**Sections:** {', '.join(det.sections)}")
                if det.medication_names:
                    det_parts.append(f"**Medications:** {', '.join(det.medication_names[:6])}")
                if det.checklist_fields:
                    det_parts.append(f"**Checklist:** {', '.join(det.checklist_fields[:4])}")
                det_md = "\n\n".join(det_parts) if det_parts else "*No detection spec*"

                body = f"{c.description}\n\n"
                if c.source_excerpt:
                    body += f"> {c.source_excerpt[:120]}{'...' if len(c.source_excerpt) > 120 else ''}\n\n"
                body += det_md

                criteria_col.append(pn.Card(
                    pn.pane.Markdown(body, sizing_mode="stretch_width"),
                    title=f"{c.id} — {c.description[:60]}",
                    collapsed=True,
                    sizing_mode="stretch_width",
                    styles={"border-left": f"3px solid {LEVEL_RED}"},
                ))

            self._profile_pane.append(pn.Card(
                criteria_col,
                title=f"Hard Criteria ({len(profile.hard_criteria)})",
                collapsed=False,
                sizing_mode="stretch_width",
            ))

        # §5: Caution criteria as expandable rows
        if profile.caution_criteria:
            criteria_col = pn.Column(sizing_mode="stretch_width")
            for c in profile.caution_criteria:
                det = c.detection
                det_parts = []
                if det.keywords:
                    det_parts.append(f"**Keywords:** {', '.join(det.keywords[:8])}")
                if det.sections:
                    det_parts.append(f"**Sections:** {', '.join(det.sections)}")
                if det.medication_names:
                    det_parts.append(f"**Medications:** {', '.join(det.medication_names[:6])}")
                if det.checklist_fields:
                    det_parts.append(f"**Checklist:** {', '.join(det.checklist_fields[:4])}")
                det_md = "\n\n".join(det_parts) if det_parts else "*No detection spec*"

                body = f"{c.description}\n\n"
                if c.source_excerpt:
                    body += f"> {c.source_excerpt[:120]}{'...' if len(c.source_excerpt) > 120 else ''}\n\n"
                body += det_md

                criteria_col.append(pn.Card(
                    pn.pane.Markdown(body, sizing_mode="stretch_width"),
                    title=f"{c.id} — {c.description[:60]}",
                    collapsed=True,
                    sizing_mode="stretch_width",
                    styles={"border-left": f"3px solid {LEVEL_AMBER}"},
                ))

            self._profile_pane.append(pn.Card(
                criteria_col,
                title=f"Caution Criteria ({len(profile.caution_criteria)})",
                collapsed=True,
                sizing_mode="stretch_width",
            ))

        # Ground rules
        if profile.ground_rules:
            rules_md = "\n".join(f"- {gr.rule}" for gr in profile.ground_rules)
            self._profile_pane.append(pn.Card(
                pn.pane.Markdown(rules_md, sizing_mode="stretch_width"),
                title=f"Ground Rules ({len(profile.ground_rules)})",
                collapsed=True,
                sizing_mode="stretch_width",
            ))

        # Program demands
        if profile.program_demands:
            demands_md = "\n".join(
                f"- **{d.id}:** {d.demand} (interacts: {', '.join(d.interacts_with)})"
                for d in profile.program_demands
            )
            self._profile_pane.append(pn.Card(
                pn.pane.Markdown(demands_md, sizing_mode="stretch_width"),
                title=f"Program Demands ({len(profile.program_demands)})",
                collapsed=True,
                sizing_mode="stretch_width",
            ))

    def _render_conflicts(self, conflicts: list):
        self._conflict_pane.clear()
        if not conflicts:
            return

        for conflict in conflicts:
            alert_type = "danger" if conflict.is_ground_rule_conflict else "warning"
            label = "GROUND RULE CONFLICT" if conflict.is_ground_rule_conflict else "CONFLICT WARNING"
            self._conflict_pane.append(pn.pane.Alert(
                f"**{label}** — Criteria: {', '.join(conflict.criteria_involved)}\n\n"
                f"{conflict.description}\n\n"
                f"**Conservative reading applied:** {conflict.conservative_reading}",
                alert_type=alert_type,
            ))

    def get_profile_summary(self) -> pn.Column:
        """Return a persistent sidebar column that updates via refresh_profile_summary()."""
        self._sidebar_summary = pn.Column(sizing_mode="stretch_width")
        self._refresh_sidebar_summary()
        return self._sidebar_summary

    def _refresh_sidebar_summary(self):
        """Re-render the sidebar profile summary from current state."""
        if not hasattr(self, "_sidebar_summary"):
            return
        col = self._sidebar_summary
        col.clear()

        if not self._current_profile:
            col.append(pn.pane.HTML(
                f'<div style="font-size:12px; color:{MUTED}">No profile loaded</div>',
                sizing_mode="stretch_width",
            ))
            return

        p = self._current_profile
        status_color = SUCCESS if p.approved else WARNING
        status_label = "Approved" if p.approved else "Pending"

        col.append(pn.pane.HTML(
            f'<div style="font-size:12px; margin-bottom:6px">'
            f'<span style="color:{status_color}; font-weight:500">{status_label}</span>'
            f' · {len(p.hard_criteria)}H · {len(p.caution_criteria)}C '
            f'· {len(p.ground_rules)} rules</div>',
            sizing_mode="stretch_width",
        ))

        if p.hard_criteria:
            col.append(pn.pane.HTML(
                f'<div style="font-size:11px; color:{MUTED}; margin-top:4px">Hard criteria:</div>',
                sizing_mode="stretch_width",
            ))
            for c in p.hard_criteria[:6]:
                col.append(pn.pane.HTML(
                    f'<div style="font-size:11px; padding:1px 0; display:flex; gap:4px">'
                    f'<span style="color:{LEVEL_RED}; font-size:8px; margin-top:4px">●</span>'
                    f'<span>{c.id}: {c.description[:45]}{"..." if len(c.description) > 45 else ""}</span></div>',
                    sizing_mode="stretch_width",
                ))
            if len(p.hard_criteria) > 6:
                col.append(pn.pane.HTML(
                    f'<div style="font-size:11px; color:{MUTED}">...and {len(p.hard_criteria) - 6} more</div>',
                    sizing_mode="stretch_width",
                ))

        return col

    def panel(self) -> pn.Column:
        # Reviewer identity
        conn = get_connection()
        saved_name = get_setting(conn, "reviewer_name", "")
        conn.close()

        reviewer_input = pn.widgets.TextInput(
            name="Reviewer",
            placeholder="Your name or initials (e.g. JD)",
            value=saved_name,
            width=250,
        )

        def on_reviewer_change(event):
            conn = get_connection()
            set_setting(conn, "reviewer_name", event.new.strip())
            conn.close()

        reviewer_input.param.watch(on_reviewer_change, "value")

        check_btn = pmui.Button(label="Re-check", color="primary", variant="outlined", width=100, sizing_mode="fixed")
        check_btn.on_click(lambda e: self.param.trigger("check_health"))

        config_info = pmui.Typography(
            f"`{self._config.model.provider}` · `{self._config.model.model}` · "
            f"temp {self._config.model.temperature} · ctx {self._config.model.num_ctx}",
            variant="body2",
        )

        build_btn = pmui.Button(label="Build Profile", color="primary", width=130, sizing_mode="fixed")
        build_btn.on_click(lambda e: self.param.trigger("build_profile_event"))

        approve_btn = pmui.Button(label="Approve Profile", color="secondary", width=140, sizing_mode="fixed")
        approve_btn.on_click(lambda e: self.param.trigger("approve_profile_event"))

        self._refresh_docs()
        self._check_cache()

        # Card 0: Reviewer
        reviewer_card = pn.Card(
            reviewer_input,
            title="Reviewer",
            sizing_mode="stretch_width",
        )

        # Card 1: Model
        model_card = pn.Card(
            pmui.Row(self._status_pane, check_btn, align="center"),
            config_info,
            title="1. Model Connection",
            sizing_mode="stretch_width",
        )

        # Card 2: Documents
        docs_card = pn.Card(
            self._docs_pane,
            title="2. Context Documents",
            sizing_mode="stretch_width",
        )

        # Card 3: Profile
        profile_card = pn.Card(
            self._cache_pane,
            pmui.Row(build_btn, approve_btn),
            self._conflict_pane,
            self._profile_pane,
            title="3. Screening Profile",
            sizing_mode="stretch_width",
        )

        return pn.Column(
            pmui.Typography("Program Setup", variant="h5"),
            reviewer_card,
            model_card,
            docs_card,
            profile_card,
            sizing_mode="stretch_width",
        )
