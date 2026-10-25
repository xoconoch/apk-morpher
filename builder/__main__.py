"""APK-Morpher build entry point.

Usage (from repo root):
    APP_NAME=youtube SOURCE=morphe python -m builder

Environment variables (set by the GitHub Actions workflow):
    APP_NAME   – app key from apps.yaml  (e.g. "youtube")
    SOURCE     – patch source key        (e.g. "morphe")
    ARCH       – target architecture     (default: from apps.yaml settings)
"""
from __future__ import annotations

import json
import logging
import re
import subprocess
from os import getenv
from pathlib import Path

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

from builder import utils, session
from builder import downloader
from builder.config import load_config


# ── Helpers ──────────────────────────────────────────────────────────────

def _should_retry_with_older_version(output: str | None) -> bool:
    """Detect patterns indicating the app version is incompatible with patches."""
    if not output:
        return False
    t = output.lower()
    return (
        "failed to match the fingerprint" in t
        or "patch.patchexception" in t
        or ("fingerprint" in t and "failed" in t)
        or "patching aborted" in t
    )


def _record_failed_patches(app_name: str, output: str):
    """Scan CLI output for failed patches and record them."""
    if not output:
        return
    failed_patches = []
    for line in output.splitlines():
        match = re.search(r'(?:FAILED:\s+|Failed to apply patch:\s*)(.+?)$', line, re.IGNORECASE)
        if match:
            patch_name = match.group(1).strip()
            if patch_name not in failed_patches:
                failed_patches.append(patch_name)
    if failed_patches:
        out_path = Path("build_records/failed_patches.json")
        out_path.parent.mkdir(parents=True, exist_ok=True)
        data = {}
        if out_path.exists():
            try:
                data = json.loads(out_path.read_text(encoding="utf-8"))
            except Exception:
                pass
        data[app_name] = failed_patches
        out_path.write_text(json.dumps(data, indent=2), encoding="utf-8")


# ── Core build function ─────────────────────────────────────────────────

def run_build(app_name: str, source: str, arch: str = "arm64-v8a") -> str | None:
    """Build a patched APK for a single app.

    Returns the filename of the signed APK on success, or None on failure.
    """
    from builder import apkmirror
    apkmirror.reset_cloudflare_block()

    # Load config to get source definition
    config = load_config()
    app_cfg = config.get_app(app_name)
    source_cfg = config.get_source(source)

    if not source_cfg:
        logging.error(f"Source '{source}' not defined in apps.yaml")
        return None

    # Download CLI + patches from the source repos
    download_files = _download_tools(source_cfg)
    if not download_files:
        logging.error(f"Failed to download tools for source '{source}'")
        return None

    # Detect CLI type
    is_morphe, cli, patches, integrations = _detect_and_find_tools(download_files, source)

    if not cli:
        logging.error(f"CLI not found for source: {source}")
        return None
    if not patches:
        logging.error(f"Patches not found for source: {source}")
        return None

    logging.info(f"Using CLI: {cli.name}")
    logging.info(f"Using patches: {[p.name for p in patches]}")

    # Get package name for upstream version check (use download package if specified, else app package)
    dl_pkg = (app_cfg.download or {}).get("package") if app_cfg else None
    package_name = dl_pkg or (app_cfg.package if app_cfg else None)

    # Get supported versions from CLI
    supported_versions = utils.get_supported_versions(package_name, str(cli), patches) if package_name else []
    if not supported_versions and dl_pkg and dl_pkg != app_cfg.package:
        supported_versions = utils.get_supported_versions(app_cfg.package, str(cli), patches)
    if not supported_versions:
        supported_versions = [None]
        logging.warning("No supported versions found, will attempt to fetch latest.")

    # Load patch include/exclude from apps.yaml
    exclude_patches = list(app_cfg.patches_exclude) if app_cfg else []
    include_patches = list(app_cfg.patches_include) if app_cfg else []

    # Build the download config for scrapers
    dl_config = _build_download_config(app_cfg) if app_cfg else {}

    # Download method priority
    download_methods = [
        downloader.download_direct,
        downloader.download_playstore,
        downloader.download_apkmirror,
        downloader.download_uptodown,
        downloader.download_apkpure,
        downloader.download_apkcombo,
        downloader.download_aptoide,
        downloader.download_github,
    ]

    # Version loop: try each supported version, falling back on fingerprint mismatch
    for attempt_idx, ver in enumerate(supported_versions):
        if ver:
            logging.info(f"Targeting version: {ver}")

        input_apk = None
        version = None
        dl_method_name = None

        for method in download_methods:
            try:
                input_apk, dl_ver, _ = method(app_name, str(cli), patches, arch, override_version=ver)
                if input_apk:
                    version = dl_ver
                    dl_method_name = method.__name__
                    break
            except Exception as e:
                logging.debug(f"{method.__name__} failed: {e}")
                continue

        if not input_apk or not version:
            logging.warning(f"Failed to download version {ver or 'latest'} from all sources.")
            continue

        # Merge split APKs if needed
        if input_apk.suffix != ".apk":
            logging.warning("Input file is not .apk, using APKEditor to merge")
            apk_editor = downloader.download_apkeditor()
            merged_apk = input_apk.with_suffix(".apk")
            utils.run_process([
                "java", "-jar", apk_editor, "m",
                "-i", str(input_apk), "-o", str(merged_apk)
            ], silent=True)
            input_apk.unlink(missing_ok=True)
            if not merged_apk.exists():
                logging.error("Merged APK file not found")
                raise RuntimeError("Merged APK file not found")
            clean_name = re.sub(r'\(\d+\)', '', merged_apk.name)
            clean_name = re.sub(r'-\d{6,}_', '_', clean_name)
            if clean_name != merged_apk.name:
                clean_apk = merged_apk.with_name(clean_name)
                merged_apk.rename(clean_apk)
                merged_apk = clean_apk
            input_apk = merged_apk

        # Verify manifest version
        apk_manifest = utils.get_apk_manifest_info(input_apk)
        actual_vn = apk_manifest.get("versionName")
        if actual_vn:
            if ver and not utils.is_version_compatible(actual_vn, ver):
                logging.error(f"APK manifest version '{actual_vn}' incompatible with target '{ver}'.")
                input_apk.unlink(missing_ok=True)
                continue
            version = actual_vn

        # Strip non-target ABIs
        if arch == "arm64-v8a":
            keep_abis = {"arm64-v8a"}
        elif arch == "armeabi-v7a":
            keep_abis = {"armeabi-v7a", "armeabi"}
        else:
            keep_abis = {"arm64-v8a", "armeabi-v7a", "armeabi"}
        utils.strip_apk_abis(input_apk, keep_abis)

        # APK integrity check
        try:
            integrity = subprocess.run(
                ["zip", "-T", str(input_apk)], check=False, capture_output=True, text=True,
            )
            if integrity.returncode != 0:
                logging.warning("APK integrity check failed; attempting repair")
                fixed_apk = Path(f"{app_name}-fixed-v{version}.apk")
                subprocess.run(["zip", "-FF", str(input_apk), "--out", str(fixed_apk)],
                               check=False, capture_output=True)
                if fixed_apk.exists() and fixed_apk.stat().st_size > 0:
                    input_apk.unlink(missing_ok=True)
                    fixed_apk.rename(input_apk)
        except Exception as e:
            logging.warning(f"Could not check/fix APK: {e}")

        # Dynamic patch injection based on download source
        dynamic_includes = []
        patch_playstore = "Disable Play Store updates" if is_morphe else "disable-play-store-updates"
        patch_installer = "Change installer source" if is_morphe else "change-installer-source"
        if dl_method_name == "download_playstore":
            if patch_playstore not in include_patches and patch_playstore not in exclude_patches:
                dynamic_includes.append(patch_playstore)
        elif dl_method_name:
            if patch_installer not in include_patches and patch_installer not in exclude_patches:
                dynamic_includes.append(patch_installer)
        current_include_patches = include_patches + dynamic_includes

        safe_version = utils.strip_arch_suffix(version)
        output_apk = Path(f"{app_name}-{arch}-patch-v{safe_version}.apk")

        try:
            if is_morphe:
                logging.info("Using Morphe patching system...")
                morphe_cmd = ["java", "-jar", str(cli), "patch", "--continue-on-error"]
                for p in patches:
                    morphe_cmd.extend(["--patches", str(p)])
                for p in exclude_patches:
                    morphe_cmd.extend(["-d", str(p)])
                for p in current_include_patches:
                    morphe_cmd.extend(["-e", str(p)])
                morphe_cmd.extend(["--out", str(output_apk), str(input_apk)])
                output = utils.run_process(morphe_cmd, capture=True, stream=True)
                _record_failed_patches(app_name, output)
            else:
                logging.info("Using ReVanced patching system...")
                cli_name = Path(cli).name.lower()
                is_v6_plus = any(f'revanced-cli-{v}' in cli_name for v in ('6', '7', '8'))
                if is_v6_plus:
                    cmd = ["java", "-jar", str(cli), "patch"]
                    for p in patches:
                        cmd.extend(["-p", str(p)])
                    cmd.extend(["-b", "--out", str(output_apk), str(input_apk)])
                    for p in exclude_patches:
                        cmd.extend(["-e", str(p)])
                    for p in current_include_patches:
                        cmd.extend(["-i", str(p)])
                else:
                    cmd = ["java", "-jar", str(cli), "-m", str(integrations)]
                    for p in patches:
                        cmd.extend(["-b", str(p)])
                    cmd.extend(["-a", str(input_apk), "-o", str(output_apk)])
                    for p in exclude_patches:
                        cmd.extend(["-e", str(p)])
                    for p in current_include_patches:
                        cmd.extend(["-i", str(p)])
                output = utils.run_process(cmd, capture=True, stream=True)
                _record_failed_patches(app_name, output)

        except subprocess.CalledProcessError as e:
            input_apk.unlink(missing_ok=True)
            output_apk.unlink(missing_ok=True)
            if attempt_idx < len(supported_versions) - 1 and _should_retry_with_older_version(
                    getattr(e, "output", None)):
                continue
            raise

        # Patch succeeded → cleanup, strip again, align, sign
        input_apk.unlink(missing_ok=True)
        utils.strip_apk_abis(output_apk, keep_abis)

        # zipalign -P 16 for Android 15+ 16KB page support
        zipalign = utils.find_zipalign()
        if zipalign:
            aligned_apk = output_apk.with_name(f"{output_apk.stem}-aligned{output_apk.suffix}")
            try:
                utils.run_process(
                    [zipalign, "-f", "-P", "16", "4", str(output_apk), str(aligned_apk)],
                    capture=True,
                )
                output_apk.unlink(missing_ok=True)
                output_apk = aligned_apk
            except subprocess.CalledProcessError:
                aligned_apk.unlink(missing_ok=True)

        # Sign with the user's private keystore
        signed_apk = Path(f"{app_name}-{arch}-{source}-v{safe_version}.apk")
        _sign_apk(output_apk, signed_apk)

        output_apk.unlink(missing_ok=True)
        print(f"APK built: {signed_apk.name}")
        return str(signed_apk)

    return None


# ── Private helpers ──────────────────────────────────────────────────────

def _download_tools(source_cfg) -> list[Path]:
    """Download CLI and patch files from the source's GitHub repos."""
    downloaded = []
    cli_owner, cli_repo = source_cfg.cli_owner_repo()
    patches_owner, patches_repo = source_cfg.patches_owner_repo()
    tag = source_cfg.tag or "latest"

    for owner, repo in [(cli_owner, cli_repo), (patches_owner, patches_repo)]:
        if not owner or not repo:
            continue
        try:
            release = utils.detect_github_release(owner, repo, tag)
            for asset in release.get("assets", []):
                asset_name = asset["name"]
                if asset_name.endswith(".asc"):
                    continue
                if asset_name.endswith((".jar", ".mpp", ".rvp")):
                    downloaded.append(downloader.download_resource(asset["browser_download_url"]))
        except Exception as e:
            logging.error(f"Failed to download from {owner}/{repo}: {e}")

    return downloaded


def _detect_and_find_tools(download_files: list[Path], source: str):
    """Detect CLI type and locate CLI/patches/integrations files."""
    is_morphe = False
    for f in download_files:
        if "morphe-cli" in f.name.lower():
            is_morphe = True
            break
    if not is_morphe:
        for f in download_files:
            if f.suffix == ".mpp":
                is_morphe = True
                break
    if not is_morphe:
        is_morphe = "morphe" in source.lower()

    integrations = None
    if is_morphe:
        cli = utils.find_file(download_files, contains="morphe-cli", suffix=".jar", exclude=["dev"])
        if not cli:
            cli = utils.find_file(download_files, contains="morphe", suffix=".jar")
        if not cli:
            cli = utils.find_file(download_files, suffix=".jar")
        patches = utils.find_files(download_files, suffix=".mpp")
        if not patches:
            patches = utils.find_files(download_files, contains="patches", suffix=".mpp")
        # Ensure the global morphe-patches bundle is present
        has_global = any("morphe-patches" in p.name.lower() for p in patches)
        if not has_global:
            global_mpp = downloader.download_global_morphe_patches()
            if global_mpp and global_mpp not in patches:
                patches.append(global_mpp)
    else:
        cli = utils.find_file(download_files, contains="revanced-cli", suffix=".jar")
        patches = utils.find_files(download_files, contains="patches", suffix=".rvp")
        if not patches:
            patches = utils.find_files(download_files, contains="patches", suffix=".jar")
        integrations = utils.find_file(download_files, contains="integrations", suffix=".apk")

    return is_morphe, cli, patches, integrations


def _build_download_config(app_cfg) -> dict:
    """Build the per-platform config dict from the app's download section in apps.yaml."""
    dl = app_cfg.download or {}
    # Map apps.yaml fields to the format expected by scrapers
    return {
        "org": dl.get("org", ""),
        "name": dl.get("repo_name", app_cfg.name),
        "type": dl.get("type", "APK"),
        "arch": dl.get("arch", app_cfg.arch),
        "dpi": dl.get("dpi", "nodpi"),
        "package": app_cfg.package,
        "version": dl.get("version", ""),
    }


def _sign_apk(input_apk: Path, output_apk: Path):
    """Sign the APK using the project's keystore."""
    apksigner = utils.find_apksigner()
    if not apksigner:
        raise RuntimeError("apksigner not found")

    # Look for keystore in standard locations
    ks_path = _find_keystore()
    ks_pass = getenv("SIGNING_KEY_PASS", "apk-morpher")
    ks_alias = getenv("SIGNING_KEY_ALIAS", "apk-morpher")

    try:
        utils.run_process([
            str(apksigner), "sign", "--verbose",
            "--ks", str(ks_path),
            "--ks-pass", f"pass:{ks_pass}",
            "--key-pass", f"pass:{ks_pass}",
            "--ks-key-alias", ks_alias,
            "--in", str(input_apk), "--out", str(output_apk)
        ], capture=True, stream=True)
    except Exception:
        logging.warning("Standard signing failed, trying with --min-sdk-version 21")
        utils.run_process([
            str(apksigner), "sign", "--verbose",
            "--min-sdk-version", "21",
            "--ks", str(ks_path),
            "--ks-pass", f"pass:{ks_pass}",
            "--key-pass", f"pass:{ks_pass}",
            "--ks-key-alias", ks_alias,
            "--in", str(input_apk), "--out", str(output_apk)
        ], capture=True, stream=True)


def _find_keystore() -> Path:
    """Locate the signing keystore, checking env var first, then common paths."""
    env_ks = getenv("SIGNING_KEYSTORE_PATH")
    if env_ks:
        p = Path(env_ks)
        if p.exists():
            return p

    candidates = [
        Path("keystore/release.jks"),
        Path("release.jks"),
        Path.home() / ".android" / "release.jks",
    ]
    for c in candidates:
        if c.exists():
            return c

    raise RuntimeError(
        "No signing keystore found. Run the setup-keystore workflow first, "
        "or set SIGNING_KEYSTORE_PATH to your .jks file."
    )


# ── Entry point ──────────────────────────────────────────────────────────

def main():
    app_name = getenv("APP_NAME")
    source = getenv("SOURCE")
    arch = getenv("ARCH", "arm64-v8a")

    if not app_name or not source:
        logging.error("APP_NAME and SOURCE environment variables are required")
        return 1

    logging.info(f"Building {app_name} with {source} for {arch}")

    try:
        result = run_build(app_name, source, arch)
        if result:
            logging.info(f"Build successful: {result}")
            return 0
        else:
            logging.error(f"Build failed for {app_name}")
            return 1
    except Exception as e:
        logging.error(f"Build error: {e}", exc_info=True)
        return 1


if __name__ == "__main__":
    exit(main())
