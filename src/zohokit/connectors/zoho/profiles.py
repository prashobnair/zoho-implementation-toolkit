"""Named auth profiles: DC, scopes, environment type (STD-L3, STD-L4, TK-CONN-1)."""

from __future__ import annotations

import json
import os
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from zohokit.connectors.zoho.dc import DC_TABLE

EnvironmentType = Literal["developer_edition", "sandbox", "trial", "production"]

PRODUCTION_ALLOW_ENV = "ZOHOKIT_ALLOW_PRODUCTION_READ"


class Profile(BaseModel):
    """One named Zoho login: DC, requested scopes and environment type."""

    model_config = ConfigDict(extra="forbid")

    name: str
    dc: str
    scopes: list[str] = Field(default_factory=list)
    environment: EnvironmentType = "developer_edition"
    org_name: str = ""
    saved_at: str = ""


def profiles_dir(base: Path | None = None) -> Path:
    """Directory holding profile files (overridable for tests)."""
    if base is not None:
        return base
    return Path.home() / ".zohokit" / "profiles"


def profile_path(name: str, base: Path | None = None) -> Path:
    """File for profile *name*; names are restricted to a safe alphabet."""
    if not name or any(char not in "abcdefghijklmnopqrstuvwxyz0123456789-_" for char in name):
        raise ValueError(f"invalid profile name {name!r} (use [a-z0-9-_])")
    return profiles_dir(base) / f"{name}.json"


def save_profile(profile: Profile, base: Path | None = None) -> Path:
    """Persist *profile*; validates the DC code first."""
    if profile.dc not in DC_TABLE:
        raise ValueError(f"unknown DC {profile.dc!r} (choose from {sorted(DC_TABLE)})")
    stamped = profile.model_copy(
        update={"saved_at": datetime.now(UTC).isoformat(timespec="seconds")}
    )
    path = profile_path(profile.name, base)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(stamped.model_dump(), indent=2) + "\n", encoding="utf-8")
    return path


def load_profile(name: str | None, base: Path | None = None) -> Profile:
    """Load a profile by name; there is no default profile (STD-L3)."""
    if not name:
        raise ValueError("--live requires --profile: there is no default profile (STD-L3)")
    path = profile_path(name, base)
    if not path.exists():
        raise ValueError(f"unknown profile {name!r}: run `zohokit auth login --profile {name} ...`")
    return Profile.model_validate(json.loads(path.read_text(encoding="utf-8")))


def production_allowed(profile: Profile) -> bool:
    """True only when the env flag is set; CI (`CI` env) always refuses."""
    if os.environ.get("CI"):
        return False
    return os.environ.get(PRODUCTION_ALLOW_ENV) == "1"


def check_production(profile: Profile, *, confirmed_org_name: str | None) -> None:
    """Refuse production profiles unless flag + interactive org-name confirmation."""
    if profile.environment != "production":
        return
    if not production_allowed(profile):
        raise PermissionError(
            "refusing production profile "
            f"{profile.name!r}: set ZOHOKIT_ALLOW_PRODUCTION_READ=1 and confirm "
            "interactively; production is always refused in CI"
        )
    if confirmed_org_name != profile.org_name or not profile.org_name:
        raise PermissionError(
            f"production confirmation failed for {profile.name!r}: "
            "type the org name exactly to confirm"
        )


__all__: list[str] = [
    "PRODUCTION_ALLOW_ENV",
    "EnvironmentType",
    "Profile",
    "check_production",
    "load_profile",
    "production_allowed",
    "profile_path",
    "profiles_dir",
    "save_profile",
]
