"""Profile persistence — save/load/approve screening profiles."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Optional

from pisa.profile.models import ScreeningProfile, PROFILE_SCHEMA_VERSION

PROFILE_CACHE_DIR = Path(__file__).parent.parent.parent / ".profile_cache"


def _cache_path(profile_hash: str) -> Path:
    PROFILE_CACHE_DIR.mkdir(exist_ok=True)
    return PROFILE_CACHE_DIR / f"{profile_hash}.json"


def save_profile(profile: ScreeningProfile) -> None:
    """Save a profile to the cache."""
    path = _cache_path(profile.profile_hash)
    data = json.loads(profile.model_dump_json(indent=2))
    data["_schema_version"] = PROFILE_SCHEMA_VERSION
    path.write_text(json.dumps(data, indent=2), encoding="utf-8")


def load_profile(profile_hash: str) -> Optional[ScreeningProfile]:
    """Load a cached profile by its hash. Returns None if schema version is stale."""
    path = _cache_path(profile_hash)
    if not path.exists():
        return None
    data = json.loads(path.read_text(encoding="utf-8"))
    if data.get("_schema_version") != PROFILE_SCHEMA_VERSION:
        return None
    data.pop("_schema_version", None)
    return ScreeningProfile(**data)



def approve_profile(profile: ScreeningProfile) -> ScreeningProfile:
    """Mark a profile as approved and save it."""
    profile.approved = True
    save_profile(profile)
    return profile


def is_profile_stale(profile: ScreeningProfile, current_hash: str) -> bool:
    """Check if the profile's source documents have changed."""
    return profile.profile_hash != current_hash
