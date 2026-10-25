# 🚀 APK-Morpher

**Self-hosted ReVanced/Morphe auto-build pipeline with an Obtainium-ready repository.**

Fork this repository, edit a single configuration file (`apps.yaml`), and get automated builds of patched Android APKs signed with your own keystore and served directly through GitHub Pages.

---

## ✨ Features

- **Single Configuration File**: Manage apps, architectures, and patch sources in [`apps.yaml`](file:///home/xoconoch/Projects/coding/Mophe-AutoBuilds/apps.yaml).
- **Automated Keystore Management**: Auto-generates a personal Android signing key on first CI run and stores it securely in GitHub Secrets.
- **Incremental CI Builds**: Automatically checks upstream tags and releases; only rebuilds apps with new updates to save GitHub Actions quota.
- **Obtainium Compatible**: Generates both an HTML download page (`downloads.html`) and an `obtainium.json` export for instant bulk import.
- **Zero-Node Static Catalog**: GitHub Pages site generated via a lightweight Python script without requiring Node, Vite, or external dependencies.
- **Multiple Upstream Scrapers**: Supports APKMirror, APKPure, Uptodown, APKCombo, Aptoide, GitHub Releases, and direct URLs.

---

## 🛠️ Quick Start

### 1. Use this Template
Click **"Use this template"** > **"Create a new repository"** on GitHub.

### 2. Configure Repository Secrets & Variables
Go to **Settings** > **Actions** > **General** > **Workflow permissions** and choose:
- ✅ **Read and write permissions**
- ✅ **Allow GitHub Actions to create and approve pull requests**

Under **Settings** > **Pages**:
- Source: **Deploy from a branch** or **GitHub Actions** (the workflow deploys via GitHub Actions artifacts).

*(Optional)* For automated APK downloading from APKMirror/Google Play if rate-limited:
- `PLAYSTORE_EMAIL` / `PLAYSTORE_PASSWORD` (if utilizing Play Store downloader features).

### 3. Customize [`apps.yaml`](file:///home/xoconoch/Projects/coding/Mophe-AutoBuilds/apps.yaml)
Add or remove apps you want built:

```yaml
sources:
  morphe:
    cli_repo: "MorpheApp/morphe-cli"
    patches_repo: "MorpheApp/morphe-patches"
    type: "revanced"

apps:
  youtube:
    name: "YouTube"
    package: "com.google.android.youtube"
    source: "morphe"
    dl_source: "apkmirror"
    arch: ["arm64-v8a"]
    include_patches: []
    exclude_patches: []
```

### 4. Trigger Your First Build
- Go to the **Actions** tab.
- Select **Build & Release**.
- Click **Run workflow** (optionally tick `force_full_rebuild`).

---

## 📱 Connecting to Obtainium

Once GitHub Pages finishes deployment:

### Method A: Single-App Tracking (HTML Source)
1. In Obtainium, tap **Add App**.
2. Enter your Pages URL:
   ```text
   https://<username>.github.io/<repo-name>/downloads.html
   ```
3. Set source to **HTML** with filter string matching your target app (e.g., `youtube`).

### Method B: Bulk Import
1. In Obtainium, go to **Settings** > **Import/Export**.
2. Import from URL:
   ```text
   https://<username>.github.io/<repo-name>/obtainium.json
   ```

---

## 📁 Repository Structure

```text
├── apps.yaml                 # ⚙️ Primary user config (apps, sources, builds)
├── .github/workflows/
│   └── build.yml             # 🔄 Single unified Actions workflow
├── builder/                  # 🐍 Core build & scraper engine
│   ├── __init__.py           # Session & GitHub API client
│   ├── __main__.py           # Build orchestration CLI
│   ├── config.py             # apps.yaml parser & validator
│   ├── updater.py            # Incremental build / tag checker
│   ├── site_generator.py     # Static site generator for Pages
│   └── [sources].py          # Scrapers (apkmirror, uptodown, etc.)
└── requirements.txt          # Python dependencies
```

---

## 🔒 Security & Privacy

- Patched APKs are signed with a unique key generated in your repository's workflow and stored in your private GitHub Actions secrets (`KEYSTORE_BASE64`).
- No pre-compiled binaries are bundled; all patching runs transparently in standard Ubuntu runners via GitHub Actions.

---

## 📄 License
This project is open-source under the MIT License.
