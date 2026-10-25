#!/usr/bin/env python3
"""Incremental update checker for APK-Morpher.

Compares upstream patch source tags and app versions against the existing
'latest' release manifest to determine which apps need rebuilding.

Outputs:
  - build_matrix.json   : matrix entries that need rebuild
  - carry_over.json     : existing APK names to keep unchanged
  - new_manifest.json   : manifest skeleton for the new release
  - GitHub Actions outputs: build_matrix, has_updates, counts
"""
from __future__ import annotations

import json
import logging
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

from builder.config import load_config

logging.basicConfig(level=logging.INFO, format='%(asctime)s [%(levelname)s] %(message)s', datefmt='%H:%M:%S')

REPO_ROOT = Path(__file__).resolve().parent.parent
GITHUB_TOKEN = os.environ.get("GITHUB_TOKEN", "")
FORCE_FULL = os.environ.get("FORCE_FULL_REBUILD", "false").lower() in ("true", "1", "yes")


def write_gh_output(key: str, value: str) -> None:
    out = os.environ.get("GITHUB_OUTPUT")
    if not out:
        print(f"[gh-output] {key}={value[:200]}")
        return
    with open(out, "a", encoding="utf-8") as f:
        if "\n" in value:
            f.write(f"{key}<<EOF_GH\n{value}\nEOF_GH\n")
        else:
            f.write(f"{key}={value}\n")


def run_gh(args: list[str], timeout: int = 60) -> tuple[int, str, str]:
    env = os.environ.copy()
    if GITHUB_TOKEN and "GH_TOKEN" not in env:
        env["GH_TOKEN"] = GITHUB_TOKEN
    try:
        r = subprocess.run(
            ["gh", *args], capture_output=True, text=True, timeout=timeout, env=env
        )
        return r.returncode, r.stdout.strip(), r.stderr.strip()
    except Exception as e:
        return 1, "", str(e)


def fetch_existing_manifest() -> dict:
    """Download manifest.json from the 'latest' release if it exists."""
    rc, stdout, _ = run_gh(["release", "view", "latest", "--json", "assets", "--jq",
                            '.assets[] | select(.name=="manifest.json") | .url'])
    if rc != 0 or not stdout:
        return {}
    try:
        rc2, manifest_str, _ = run_gh(["release", "download", "latest", "-p", "manifest.json", "-D", "/tmp"])
        if rc2 == 0:
            p = Path("/tmp/manifest.json")
            if p.exists():
                return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        pass
    return {}


def get_source_signature(source_cfg) -> str:
    """Get a unique signature for the current state of a patch source.

    Uses the latest release tag to detect changes.
    """
    from builder import utils
    try:
        cli_owner, cli_repo = source_cfg.cli_owner_repo()
        patches_owner, patches_repo = source_cfg.patches_owner_repo()
        parts = []
        for owner, repo in [(cli_owner, cli_repo), (patches_owner, patches_repo)]:
            if not owner or not repo:
                continue
            try:
                release = utils.detect_github_release(owner, repo, source_cfg.tag or "latest")
                parts.append(f"{owner}/{repo}@{release.get('tag_name', '?')}")
            except Exception:
                parts.append(f"{owner}/{repo}@unknown")
        return "|".join(parts)
    except Exception as e:
        logging.warning(f"Could not get source signature: {e}")
        return "unknown"


def main() -> int:
    config = load_config()

    if not config.apps:
        logging.warning("No apps configured in apps.yaml")
        write_gh_output("has_updates", "false")
        write_gh_output("build_matrix", "[]")
        return 0

    existing_manifest = {} if FORCE_FULL else fetch_existing_manifest()
    existing_entries = existing_manifest.get("entries", {})

    rebuild_matrix: list[dict[str, str]] = []
    carry_over: list[str] = []
    new_entries: dict[str, Any] = {}

    for app in config.apps:
        entry_key = f"{app.name}-{app.arch}-{app.source}"
        old = existing_entries.get(entry_key, {})

        # Check if upstream source has changed
        source_cfg = config.get_source(app.source)
        current_sig = get_source_signature(source_cfg) if source_cfg else ""
        old_sig = old.get("source_signature", "")

        needs_rebuild = FORCE_FULL
        reason = ""

        if not old:
            needs_rebuild = True
            reason = "new app"
        elif not old.get("apk"):
            needs_rebuild = True
            reason = "missing APK"
        elif current_sig != old_sig:
            needs_rebuild = True
            reason = "upstream source updated"
        else:
            reason = "no changes"

        if needs_rebuild:
            logging.info(f"  REBUILD {entry_key}: {reason}")
            rebuild_matrix.append(app.to_matrix_entry())
        else:
            logging.info(f"  CARRY   {entry_key}: {reason}")
            if old.get("apk"):
                carry_over.append(old["apk"])

        new_entries[entry_key] = {
            "app_name": app.name,
            "display_name": app.display_name,
            "package": app.package,
            "source": app.source,
            "arch": app.arch,
            "source_signature": current_sig,
            "apk": old.get("apk", ""),
            "built_version": old.get("built_version", ""),
        }

    has_updates = len(rebuild_matrix) > 0
    logging.info(f"Total: {len(config.apps)}, Rebuild: {len(rebuild_matrix)}, Carry: {len(carry_over)}")

    # Write outputs
    Path("build_matrix.json").write_text(json.dumps(rebuild_matrix, indent=2), encoding="utf-8")
    Path("carry_over.json").write_text(json.dumps(carry_over, indent=2), encoding="utf-8")
    Path("new_manifest.json").write_text(
        json.dumps({"entries": new_entries}, indent=2), encoding="utf-8"
    )

    write_gh_output("has_updates", str(has_updates).lower())
    write_gh_output("build_matrix", json.dumps(rebuild_matrix))
    write_gh_output("update_count", str(len(rebuild_matrix)))
    write_gh_output("total_count", str(len(config.apps)))
    write_gh_output("carry_count", str(len(carry_over)))

    return 0


if __name__ == "__main__":
    sys.exit(main())
