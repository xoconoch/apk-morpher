#!/usr/bin/env python3
"""Generate the complete static GitHub Pages site from manifest.json.

Produces three files in an output directory (default: public/):
  1. downloads.html  – Machine-readable APK link page for Obtainium HTML source
  2. obtainium.json  – Bulk import bundle for Obtainium
  3. index.html      – Beautiful dark-mode web catalog with 1-click Obtainium badges

Zero npm/Node dependencies. Pure Python + embedded HTML/CSS.
"""
from __future__ import annotations

import html
import json
import os
import re
import sys
import urllib.parse
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parent.parent


# ── Obtainium helpers ────────────────────────────────────────────────────

def extract_identity_prefix(apk_name: str) -> str:
    if not apk_name:
        return ""
    match = re.search(r"^(.*)-v\d+\.\d[\w.+\-]*\.apk$", apk_name)
    if match:
        return match.group(1)
    if "-v" in apk_name:
        stem = apk_name[:-4] if apk_name.lower().endswith(".apk") else apk_name
        parts = stem.rsplit("-v", 1)
        return parts[0]
    return ""


def build_obtainium_app(entry: dict, pages_url: str, author: str) -> dict:
    app_name = entry.get("app_name", "")
    arch = entry.get("arch", "arm64-v8a")
    source = entry.get("source", "")
    pkg = entry.get("package", f"org.morphe.{app_name}")
    display_name = entry.get("display_name", app_name.replace("-", " ").title())

    head = f"{app_name}-{arch}-"
    filter_pat = f"{head}.*-v.*\\.apk$"
    ver_pat = f"{head}.*-v([^/]+)\\.apk$"

    additional = json.dumps({
        "apkFilterRegEx": filter_pat,
        "versionExtractionRegEx": ver_pat,
        "matchGroupToUse": "1"
    }, separators=(',', ':'))

    return {
        "id": pkg,
        "url": pages_url,
        "author": author,
        "name": display_name,
        "preferredApkIndex": 0,
        "additionalSettings": additional
    }


def make_deep_links(app_obj: dict) -> tuple[str, str]:
    json_str = json.dumps(app_obj, separators=(',', ':'))
    encoded = urllib.parse.quote(json_str)
    direct = f"obtainium://app/{encoded}"
    redirect = f"https://apps.obtainium.imranr.dev/redirect?r={urllib.parse.quote(direct, safe='')}"
    return direct, redirect


# ── downloads.html ───────────────────────────────────────────────────────

def generate_downloads_html(manifest: dict, repo_slug: str) -> str:
    entries = manifest.get("entries", {})
    rows = []
    for key in sorted(entries):
        e = entries[key]
        apk = (e.get("apk") or "").strip()
        if not apk:
            continue
        url = f"https://github.com/{repo_slug}/releases/latest/download/{apk}"
        rows.append({
            "app": e.get("app_name", ""),
            "arch": e.get("arch", ""),
            "version": e.get("built_version", ""),
            "apk": apk,
            "url": url,
        })

    parts = [
        "<!doctype html>",
        '<html lang="en">',
        "<head>",
        '<meta charset="utf-8">',
        "<title>APK-Morpher — Downloads</title>",
        '<meta name="viewport" content="width=device-width, initial-scale=1">',
        "</head>",
        "<body>",
        "<h1>APK-Morpher — APK Downloads</h1>",
        "<p>Machine-readable catalog for update trackers. One link per published APK.</p>",
    ]
    for r in rows:
        parts.append(
            f'<section data-app="{html.escape(r["app"])}" '
            f'data-arch="{html.escape(r["arch"])}" '
            f'data-version="{html.escape(r["version"])}">'
            f'<a class="apk" href="{html.escape(r["url"])}" '
            f'data-version="{html.escape(r["version"])}" '
            f'data-arch="{html.escape(r["arch"])}">'
            f'{html.escape(r["apk"])}</a> '
            f'<span class="version">{html.escape(r["version"])}</span>'
            f"</section>"
        )
    parts += ["</body>", "</html>", ""]
    return "\n".join(parts)


# ── obtainium.json ───────────────────────────────────────────────────────

def generate_obtainium_json(manifest: dict, repo_slug: str) -> dict:
    author = repo_slug.split("/")[0] if "/" in repo_slug else repo_slug
    repo_name = repo_slug.split("/")[1] if "/" in repo_slug else repo_slug
    pages_url = f"https://{author}.github.io/{repo_name}/downloads.html"

    entries = manifest.get("entries", {})
    apps = []
    for key, entry in entries.items():
        apk = (entry.get("apk") or "").strip()
        if not apk:
            continue
        if not entry.get("built_version"):
            m = re.search(r"-v([0-9][\w.+]*)\.apk$", apk)
            if m:
                entry["built_version"] = m.group(1)
            else:
                entry["built_version"] = "latest"
        try:
            app_obj = build_obtainium_app(entry, pages_url, author)
            apps.append(app_obj)
        except Exception as e:
            print(f"  [WARN] Skipping {key}: {e}")

    return {"apps": apps}


# ── index.html ───────────────────────────────────────────────────────────

def generate_index_html(manifest: dict, obtainium_bundle: dict, repo_slug: str) -> str:
    """Generate a beautiful, self-contained dark-mode catalog page."""
    author = repo_slug.split("/")[0] if "/" in repo_slug else repo_slug
    repo_name = repo_slug.split("/")[1] if "/" in repo_slug else repo_slug
    pages_url = f"https://{author}.github.io/{repo_name}"

    entries = manifest.get("entries", {})
    built_apps = []
    for key in sorted(entries):
        e = entries[key]
        apk = (e.get("apk") or "").strip()
        if not apk:
            continue
        if not e.get("built_version"):
            m = re.search(r"-v([0-9][\w.+]*)\.apk$", apk)
            e["built_version"] = m.group(1) if m else "latest"
        # Find matching obtainium app for deep link
        deep_link = ""
        for obt_app in obtainium_bundle.get("apps", []):
            if obt_app.get("id") == e.get("package"):
                _, redirect = make_deep_links(obt_app)
                deep_link = redirect
                break
        built_apps.append({
            "name": e.get("display_name") or e.get("app_name", "").replace("-", " ").title(),
            "package": e.get("package", ""),
            "version": e.get("built_version", ""),
            "arch": e.get("arch", ""),
            "source": e.get("source", ""),
            "apk": apk,
            "download_url": f"https://github.com/{repo_slug}/releases/latest/download/{apk}",
            "obtainium_url": deep_link,
        })

    obtainium_import_url = f"https://raw.githubusercontent.com/{repo_slug}/main/public/obtainium.json"

    # Build the app cards HTML
    cards_html = ""
    for app in built_apps:
        obt_btn = ""
        if app["obtainium_url"]:
            obt_btn = (
                f'<a href="{html.escape(app["obtainium_url"])}" class="btn btn-obtainium" '
                f'title="Add to Obtainium">+ Obtainium</a>'
            )
        cards_html += f"""
      <div class="app-card">
        <div class="app-header">
          <h3 class="app-name">{html.escape(app["name"])}</h3>
          <span class="app-version">v{html.escape(app["version"])}</span>
        </div>
        <div class="app-meta">
          <span class="tag">{html.escape(app["arch"])}</span>
          <span class="tag tag-source">{html.escape(app["source"])}</span>
        </div>
        <p class="app-package">{html.escape(app["package"])}</p>
        <div class="app-actions">
          <a href="{html.escape(app["download_url"])}" class="btn btn-download">Download APK</a>
          {obt_btn}
        </div>
      </div>"""

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>APK-Morpher — Self-Hosted Patched APKs</title>
  <meta name="description" content="Self-hosted, auto-built patched Android APKs with Obtainium integration.">
  <style>
    *, *::before, *::after {{ box-sizing: border-box; margin: 0; padding: 0; }}

    :root {{
      --bg: #0a0a0f;
      --surface: #12121a;
      --surface-hover: #1a1a28;
      --border: #2a2a3a;
      --text: #e4e4ed;
      --text-dim: #8888a0;
      --accent: #7c6aef;
      --accent-hover: #9584ff;
      --green: #34d399;
      --green-hover: #4aeab0;
      --radius: 12px;
      --font: 'Inter', -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
    }}

    @import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&display=swap');

    body {{
      font-family: var(--font);
      background: var(--bg);
      color: var(--text);
      line-height: 1.6;
      min-height: 100vh;
    }}

    .container {{
      max-width: 960px;
      margin: 0 auto;
      padding: 2rem 1.5rem;
    }}

    /* Header */
    .hero {{
      text-align: center;
      padding: 3rem 0 2rem;
    }}
    .hero h1 {{
      font-size: 2.2rem;
      font-weight: 700;
      background: linear-gradient(135deg, var(--accent), var(--green));
      -webkit-background-clip: text;
      -webkit-text-fill-color: transparent;
      background-clip: text;
      margin-bottom: 0.5rem;
    }}
    .hero p {{
      color: var(--text-dim);
      font-size: 1.05rem;
      max-width: 600px;
      margin: 0 auto;
    }}
    .hero-actions {{
      margin-top: 1.5rem;
      display: flex;
      gap: 0.75rem;
      justify-content: center;
      flex-wrap: wrap;
    }}

    /* Buttons */
    .btn {{
      display: inline-flex;
      align-items: center;
      gap: 0.4rem;
      padding: 0.55rem 1.1rem;
      border-radius: 8px;
      font-size: 0.85rem;
      font-weight: 600;
      text-decoration: none;
      border: none;
      cursor: pointer;
      transition: all 0.2s ease;
    }}
    .btn-primary {{
      background: var(--accent);
      color: #fff;
    }}
    .btn-primary:hover {{ background: var(--accent-hover); transform: translateY(-1px); }}
    .btn-outline {{
      background: transparent;
      color: var(--text);
      border: 1px solid var(--border);
    }}
    .btn-outline:hover {{ border-color: var(--accent); color: var(--accent); }}
    .btn-download {{
      background: var(--green);
      color: #0a0a0f;
    }}
    .btn-download:hover {{ background: var(--green-hover); transform: translateY(-1px); }}
    .btn-obtainium {{
      background: transparent;
      color: var(--accent);
      border: 1px solid var(--accent);
    }}
    .btn-obtainium:hover {{ background: var(--accent); color: #fff; }}

    /* Grid */
    .grid {{
      display: grid;
      grid-template-columns: repeat(auto-fill, minmax(280px, 1fr));
      gap: 1rem;
      margin-top: 2rem;
    }}

    /* Cards */
    .app-card {{
      background: var(--surface);
      border: 1px solid var(--border);
      border-radius: var(--radius);
      padding: 1.25rem;
      transition: all 0.25s ease;
    }}
    .app-card:hover {{
      border-color: var(--accent);
      background: var(--surface-hover);
      transform: translateY(-2px);
      box-shadow: 0 8px 24px rgba(124, 106, 239, 0.08);
    }}
    .app-header {{
      display: flex;
      justify-content: space-between;
      align-items: center;
      margin-bottom: 0.5rem;
    }}
    .app-name {{ font-size: 1.05rem; font-weight: 600; }}
    .app-version {{
      font-size: 0.78rem;
      color: var(--green);
      font-weight: 500;
      background: rgba(52, 211, 153, 0.1);
      padding: 0.15rem 0.5rem;
      border-radius: 20px;
    }}
    .app-meta {{
      display: flex;
      gap: 0.4rem;
      margin-bottom: 0.5rem;
    }}
    .tag {{
      font-size: 0.7rem;
      padding: 0.15rem 0.45rem;
      border-radius: 4px;
      background: rgba(255,255,255,0.06);
      color: var(--text-dim);
    }}
    .tag-source {{ color: var(--accent); background: rgba(124, 106, 239, 0.1); }}
    .app-package {{
      font-size: 0.75rem;
      color: var(--text-dim);
      margin-bottom: 0.75rem;
      font-family: 'SF Mono', Monaco, Consolas, monospace;
    }}
    .app-actions {{
      display: flex;
      gap: 0.5rem;
      flex-wrap: wrap;
    }}

    /* Footer */
    .footer {{
      text-align: center;
      padding: 3rem 0 2rem;
      color: var(--text-dim);
      font-size: 0.8rem;
    }}
    .footer a {{ color: var(--accent); text-decoration: none; }}
    .footer a:hover {{ text-decoration: underline; }}

    .count-badge {{
      display: inline-block;
      background: rgba(124, 106, 239, 0.15);
      color: var(--accent);
      font-weight: 600;
      padding: 0.2rem 0.6rem;
      border-radius: 20px;
      font-size: 0.85rem;
      margin-top: 0.5rem;
    }}
  </style>
</head>
<body>
  <div class="container">
    <div class="hero">
      <h1>APK-Morpher</h1>
      <p>Self-hosted, auto-built patched Android APKs — signed with your own key, updated automatically.</p>
      <span class="count-badge">{len(built_apps)} apps available</span>
      <div class="hero-actions">
        <a href="https://github.com/{html.escape(repo_slug)}/releases/latest" class="btn btn-primary">
          GitHub Releases
        </a>
        <a href="{html.escape(obtainium_import_url)}" class="btn btn-outline">
          Import All → Obtainium
        </a>
      </div>
    </div>

    <div class="grid">
      {cards_html}
    </div>

    <div class="footer">
      <p>
        Built with <a href="https://github.com/{html.escape(repo_slug)}">APK-Morpher</a> ·
        Powered by GitHub Actions · Auto-updated via Obtainium
      </p>
    </div>
  </div>
</body>
</html>"""


# ── Main ─────────────────────────────────────────────────────────────────

def main() -> int:
    out_dir = Path(sys.argv[1]) if len(sys.argv) > 1 else REPO_ROOT / "public"
    manifest_path = REPO_ROOT / "manifest.json"

    repo_slug = os.environ.get("GITHUB_REPOSITORY", "").strip()
    if not repo_slug:
        repo_slug = "user/apk-morpher"
        print(f"[WARN] GITHUB_REPOSITORY not set; using '{repo_slug}'")

    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except Exception as e:
        print(f"[ERROR] Cannot read {manifest_path}: {e}")
        return 1

    out_dir.mkdir(parents=True, exist_ok=True)

    # 1. downloads.html (Obtainium target)
    downloads_html = generate_downloads_html(manifest, repo_slug)
    (out_dir / "downloads.html").write_text(downloads_html, encoding="utf-8", newline="\n")

    # 2. obtainium.json
    obt_bundle = generate_obtainium_json(manifest, repo_slug)
    (out_dir / "obtainium.json").write_text(
        json.dumps(obt_bundle, indent=2), encoding="utf-8", newline="\n"
    )

    # 3. index.html (beautiful catalog)
    index = generate_index_html(manifest, obt_bundle, repo_slug)
    (out_dir / "index.html").write_text(index, encoding="utf-8", newline="\n")

    print(f"[OK] Generated site in {out_dir} "
          f"({len(obt_bundle.get('apps', []))} apps in obtainium.json)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
