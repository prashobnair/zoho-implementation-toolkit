"""Record a redacted cassette through the GET-only client (TK-CONN-9).

Usage: ``make record MODULE=<module> PROFILE=<profile> [PATH=/crm/v8/...]``

Reads flow through :class:`ZohoClient` (GET-only guard enforced), is
redacted with the shared :class:`Redactor` BEFORE anything is written,
and refuses to run in CI so cassettes can never be recorded where
secrets live.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from zohokit.connectors.zoho.budget import CallBudget  # noqa: E402
from zohokit.connectors.zoho.cache import ResponseCache  # noqa: E402
from zohokit.connectors.zoho.client import ZohoClient  # noqa: E402
from zohokit.connectors.zoho.dc import DC_TABLE  # noqa: E402
from zohokit.connectors.zoho.profiles import load_profile  # noqa: E402
from zohokit.core.redact import Redactor  # noqa: E402


def record(module: str, profile_name: str, path: str, out: Path) -> Path:
    """GET *path* through the guarded client and write the redacted cassette."""
    if os.environ.get("CI"):
        raise PermissionError("refusing to record in CI: cassettes are recorded locally only")
    profile = load_profile(profile_name)
    api_base = DC_TABLE[profile.dc].api_base
    client = ZohoClient(api_base, budget=CallBudget())
    response = client.get(path, endpoint=path, experimental=True)
    redacted = Redactor().redact_obj(response.json())
    out.parent.mkdir(parents=True, exist_ok=True)
    assert isinstance(redacted, dict)
    out.write_text(json.dumps(redacted, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    _ = (module, ResponseCache)
    return out


def main(argv: list[str] | None = None) -> int:
    """CLI entry point for ``make record``."""
    parser = argparse.ArgumentParser(description="Record one redacted cassette.")
    parser.add_argument("--module", required=True)
    parser.add_argument("--profile", required=True)
    parser.add_argument("--path", required=True)
    parser.add_argument("--out", required=True)
    args = parser.parse_args(argv)
    try:
        written = record(args.module, args.profile, args.path, Path(args.out))
    except (PermissionError, ValueError) as exc:
        print(f"record refused: {exc}", file=sys.stderr)
        return 1
    print(f"recorded {written}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
