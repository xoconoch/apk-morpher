"""Parse and validate apps.yaml — the single source of truth for APK-Morpher."""
from __future__ import annotations

import logging
import sys
from pathlib import Path
from typing import Any

import yaml

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_CONFIG = REPO_ROOT / "apps.yaml"

REQUIRED_APP_FIELDS = {"name", "package", "source", "download"}
VALID_PROVIDERS = {"apkmirror", "apkpure", "apkcombo", "uptodown", "aptoide", "direct", "github", "playstore"}

# ── Default settings ─────────────────────────────────────────────────────
DEFAULT_SETTINGS = {
    "arch": "arm64-v8a",
    "schedule_cron": "0 4 * * *",
    "retention_runs": 5,
}


class AppConfig:
    """Parsed representation of a single app entry."""
    __slots__ = (
        "name", "display_name", "package", "source", "arch",
        "download", "patches_include", "patches_exclude",
    )

    def __init__(self, entry: dict[str, Any], global_arch: str = "arm64-v8a"):
        self.name: str = entry["name"]
        self.display_name: str = entry.get("display_name") or self.name.replace("-", " ").title()
        self.package: str = entry["package"]
        self.source: str = entry["source"]
        self.arch: str = entry.get("arch") or global_arch
        self.download: dict[str, Any] = entry.get("download", {})

        patches = entry.get("patches") or {}
        self.patches_include: list[str] = patches.get("include") or []
        self.patches_exclude: list[str] = patches.get("exclude") or []

    def to_matrix_entry(self) -> dict[str, str]:
        """Return a dict suitable for GitHub Actions matrix ``include``."""
        return {
            "app_name": self.name,
            "display_name": self.display_name,
            "package": self.package,
            "source": self.source,
            "arch": self.arch,
        }


class SourceConfig:
    """A patch source definition (CLI + patches repos)."""
    __slots__ = ("name", "cli_repo", "patches_repo", "tag")

    def __init__(self, name: str, entry: dict[str, Any]):
        self.name = name
        self.cli_repo: str = entry.get("cli", "")
        self.patches_repo: str = entry.get("patches", "")
        self.tag: str = entry.get("tag", "latest")

    def cli_owner_repo(self) -> tuple[str, str]:
        parts = self.cli_repo.split("/", 1)
        return (parts[0], parts[1]) if len(parts) == 2 else ("", "")

    def patches_owner_repo(self) -> tuple[str, str]:
        parts = self.patches_repo.split("/", 1)
        return (parts[0], parts[1]) if len(parts) == 2 else ("", "")


class Config:
    """Top-level parsed config from apps.yaml."""

    def __init__(self, path: Path | str = DEFAULT_CONFIG):
        path = Path(path)
        if not path.exists():
            logging.error(f"Config file not found: {path}")
            sys.exit(1)

        with path.open("r", encoding="utf-8") as f:
            raw = yaml.safe_load(f) or {}

        # Settings
        raw_settings = raw.get("settings") or {}
        self.arch: str = raw_settings.get("arch") or DEFAULT_SETTINGS["arch"]
        self.schedule_cron: str = raw_settings.get("schedule_cron") or DEFAULT_SETTINGS["schedule_cron"]
        self.retention_runs: int = int(raw_settings.get("retention_runs") or DEFAULT_SETTINGS["retention_runs"])

        # Sources
        self.sources: dict[str, SourceConfig] = {}
        for name, entry in (raw.get("sources") or {}).items():
            self.sources[name] = SourceConfig(name, entry)

        # Apps
        self.apps: list[AppConfig] = []
        for entry in raw.get("apps") or []:
            missing = REQUIRED_APP_FIELDS - set(entry.keys())
            if missing:
                logging.warning(f"Skipping app entry missing fields {missing}: {entry}")
                continue
            provider = (entry.get("download") or {}).get("provider", "")
            if provider and provider not in VALID_PROVIDERS:
                logging.warning(f"Skipping app '{entry.get('name')}': unknown provider '{provider}'")
                continue
            if entry["source"] not in self.sources:
                logging.warning(
                    f"Skipping app '{entry.get('name')}': source '{entry['source']}' "
                    f"not defined in sources section"
                )
                continue
            self.apps.append(AppConfig(entry, global_arch=self.arch))

    def get_source(self, name: str) -> SourceConfig | None:
        return self.sources.get(name)

    def build_matrix(self) -> list[dict[str, str]]:
        """Return the full GitHub Actions matrix include list."""
        return [app.to_matrix_entry() for app in self.apps]

    def get_app(self, name: str) -> AppConfig | None:
        for app in self.apps:
            if app.name == name:
                return app
        return None


def load_config(path: Path | str = DEFAULT_CONFIG) -> Config:
    """Convenience loader."""
    return Config(path)


if __name__ == "__main__":
    import json
    cfg = load_config()
    print(f"Loaded {len(cfg.apps)} apps, {len(cfg.sources)} sources")
    print(json.dumps(cfg.build_matrix(), indent=2))
