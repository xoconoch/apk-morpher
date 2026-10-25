# apk-morpher

Automated Morphe & ReVanced patch, sign, and release pipeline for personal Obtainium repositories.

---

## Quick Setup

### 1. Use this Template
Click **Use this template** > **Create a new repository**.

### 2. Configure GitHub Settings

1. **Workflow Permissions**:  
   Go to **Settings** > **Actions** > **General** > **Workflow permissions**:
   - Select **Read and write permissions**
   - Check **Allow GitHub Actions to create and approve pull requests**
2. **GitHub Pages**:  
   Go to **Settings** > **Pages**:
   - Build and deployment source: **GitHub Actions**

### 3. Repository Secrets

Go to **Settings** > **Secrets and variables** > **Actions**.

#### Mandatory (Signing Key)
Android requires consistent APK signatures for in-place app updates.

On your **first build**, if no keystore exists, the workflow generates one and outputs the values in the `Prepare Build Plan` run log. Copy and save them as repository secrets:

| Secret | Description | Example / Command |
|---|---|---|
| `SIGNING_KEYSTORE_BASE64` | Base64-encoded keystore (`release.jks`) | `base64 -w0 keystore/release.jks` |
| `SIGNING_KEY_PASS` | Keystore & key password | 32-character string printed in the workflow log |
| `SIGNING_KEY_ALIAS` | Key alias in keystore | `apk-morpher` |

> **Note:** If your Actions permissions allow it, the workflow attempts to save `SIGNING_KEYSTORE_BASE64` and `SIGNING_KEY_PASS` automatically using GitHub CLI during the first run.

#### Optional Secrets
| Secret | Description |
|---|---|
| `PLAYSTORE_EMAIL` / `PLAYSTORE_PASSWORD` | Google account credentials (only if using the `playstore` download provider). |

---

## Adding or Editing Apps

Edit [`apps.yaml`](apps.yaml) in the root of the repository:

```yaml
sources:
  morphe:
    cli: "MorpheApp/morphe-cli"
    patches: "MorpheApp/morphe-patches"

apps:
  - name: "youtube"
    display_name: "YouTube"
    package: "com.google.android.youtube"
    source: "morphe"
    download:
      provider: "apkmirror"
      org: "google-inc"
      repo_name: "youtube"
      type: "BUNDLE"
```

Pushing changes to `apps.yaml` or running the workflow manually triggers a build. Builds also run automatically on the daily schedule specified in `apps.yaml`.

---

## Connect to Obtainium

Once the action finishes and GitHub Pages is deployed:

- **Bulk Import (All Apps)**:  
  In Obtainium: **Settings** > **Import/Export** > **Import from URL**:
  ```text
  https://<username>.github.io/<repo-name>/obtainium.json
  ```

- **Single App (HTML Track)**:  
  In Obtainium: **Add App** > URL:
  ```text
  https://<username>.github.io/<repo-name>/downloads.html
  ```
  Set source type to **HTML** and filter by app name.

---

## License

GPL-3.0
