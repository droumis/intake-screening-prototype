"""PISA formatting helpers — humanized times, durations, criterion refs."""

from __future__ import annotations

from datetime import datetime


def ago_label(iso_str: str) -> str:
    """Humanize an ISO timestamp to relative time (e.g., '2m ago', 'yesterday 14:30')."""
    if not iso_str or iso_str == "—":
        return "—"
    try:
        dt = datetime.fromisoformat(iso_str[:19])
        now = datetime.now()
        delta = now - dt
        seconds = delta.total_seconds()
        if seconds < 60:
            return "just now"
        if seconds < 3600:
            m = int(seconds // 60)
            return f"{m}m ago"
        if seconds < 86400:
            h = int(seconds // 3600)
            return f"{h}h ago"
        days = int(seconds // 86400)
        if days == 1:
            return f"yesterday {dt.strftime('%H:%M')}"
        if days < 7:
            return f"{days}d ago"
        if days < 365:
            return dt.strftime("%b %d")
        return dt.strftime("%b %d, %Y")
    except (ValueError, TypeError):
        return iso_str[:10] if len(iso_str) >= 10 else iso_str


def fmt_duration(seconds: float | None) -> str:
    """Format seconds as compact duration (e.g., '2m 05s', '45s')."""
    if not seconds:
        return ""
    if seconds < 60:
        return f"{seconds:.0f}s"
    minutes = int(seconds // 60)
    secs = int(seconds % 60)
    return f"{minutes}m {secs:02d}s"


def fmt_clock(iso_str: str) -> str:
    """Extract HH:MM from an ISO timestamp."""
    if not iso_str:
        return ""
    try:
        dt = datetime.fromisoformat(iso_str[:19])
        return dt.strftime("%H:%M")
    except (ValueError, TypeError):
        return ""


def fmt_absolute(iso_str: str) -> str:
    """Full human-readable absolute timestamp for tooltips."""
    if not iso_str:
        return ""
    try:
        dt = datetime.fromisoformat(iso_str[:19])
        return dt.strftime("%Y-%m-%d %H:%M:%S")
    except (ValueError, TypeError):
        return iso_str
