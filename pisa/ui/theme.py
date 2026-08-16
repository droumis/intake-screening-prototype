"""PISA UI theme constants — single source of truth for colors and tokens."""

# Level colors (reserved for flag levels, review states, run status only)
LEVEL_RED = "#B4453A"
LEVEL_AMBER = "#C07A1F"
LEVEL_GREEN = "#3E7D4F"

# Level tints (alpha-byte hex, §7.2)
LEVEL_RED_TINT = f"{LEVEL_RED}18"
LEVEL_AMBER_TINT = f"{LEVEL_AMBER}18"
LEVEL_GREEN_TINT = f"{LEVEL_GREEN}18"

# Review state colors
STATE_COLORS = {
    "unreviewed": "#8A939B",
    "in_review": "#33628C",
    "followup_pending": "#C07A1F",
    "cleared": "#3E7D4F",
    "not_cleared": "#B4453A",
    "deferred": "#6B5B95",
}

# Semantic palette
PRIMARY = "#33628C"
SURFACE = "#FAFAF8"
CARD_BG = "#FFFFFF"
CARD_BORDER = "#E5E3DE"
TEXT_PRIMARY = "#1F2933"
TEXT_SECONDARY = "#5F6B76"
MUTED = "#8A939B"
DIVIDER = "#E5E3DE"
SUCCESS = "#3E7D4F"
WARNING = "#C07A1F"
ERROR = "#B4453A"
INFO = "#33628C"

# Map from level to pmui Chip color prop
CHIP_COLOR_MAP = {"red": "error", "yellow": "warning", "green": "success"}

# Map from level to hex color
LEVEL_COLORS = {"red": LEVEL_RED, "yellow": LEVEL_AMBER, "green": LEVEL_GREEN}
LEVEL_TINTS = {"red": LEVEL_RED_TINT, "yellow": LEVEL_AMBER_TINT, "green": LEVEL_GREEN_TINT}

# pmui theme config
THEME = {
    "light": {
        "palette": {
            "primary": {"main": PRIMARY},
            "secondary": {"main": LEVEL_GREEN},
            "error": {"main": LEVEL_RED},
            "warning": {"main": LEVEL_AMBER},
        },
        "shape": {"borderRadius": 8},
    },
    "dark": {
        "palette": {
            "primary": {"main": "#4a90d9"},
            "secondary": {"main": LEVEL_GREEN},
            "error": {"main": LEVEL_RED},
            "warning": {"main": LEVEL_AMBER},
        },
        "shape": {"borderRadius": 8},
    },
}
