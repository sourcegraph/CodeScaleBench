```markdown
# TycoonVerse – Local Developer Setup Guide
_Last updated: 2024-06-14_

Welcome to the TycoonVerse contributor on-boarding guide.  
Follow the steps below to go from a fresh clone to running the game on a physical device with hot-reload, analytics, and in-app purchases enabled.

---

## 1. Prerequisites

| Tool | Min. Version | Purpose |
| ---- | ------------ | ------- |
| Unity **LTS** | `2022.3.10f1` | 3-D engine & editor |
| .NET SDK | `8.0.x` | Unit / integration tests, code-gen |
| Git | `>= 2.40` | Source control |
| Git LFS | `>= 3.4` | Large binary assets |
| Android NDK | `r26b` | Android builds |
| Xcode | `15` | iOS builds |
| Node.js | `20` | Tools & asset pipeline scripts |
| OpenSSL | `1.1+` | Key generation for secure storage |

> 🛈  Windows users need the **WSL2** backend with Ubuntu 22.04 for shell scripts.  
> 🛈  macOS users need Rosetta installed when running certain Intel-only pre-built tools.

---

## 2. Clone & Bootstrap

```bash
# 1. Clone the repo and pull submodules (for external SDKs)
git clone --recurse-submodules https://github.com/TycoonVerse/TycoonVerse.git
cd TycoonVerse

# 2. Enable Git LFS & fetch assets
git lfs install
git lfs pull

# 3. Install editor tooling (pre-commit hooks, dotnet tools)
./build/bootstrap.sh
```

`bootstrap.sh` installs the following dotnet tools locally:

* `dotnet-format` (code style)
* `coverlet.console` (coverage)
* `dotnet-reportgenerator-globaltool` (coverage reports)

---

## 3. Environment Variables

Create a `.env.local` file in the repo root:

```bash
# .env.local
# Runtime
TYCOONVERSE_ENV=local
TYCOONVERSE_SQLITE_PATH=$HOME/.tycoonverse/local.db

# Security
TYCOONVERSE_ENCRYPTION_KEY=REPLACE_ME_WITH_32_BYTES_HEX
TYCOONVERSE_IAP_SANDBOX=true

# Analytics
TYCOONVERSE_FIREBASE_APP_ID=local-debug
TYCOONVERSE_ANALYTICS_DISABLED=false
```

Load it in your shell:

```bash
export $(grep -v '^#' .env.local | xargs)
```

The Unity project automatically picks up these variables at play-time via `UnityEngine.Environment`.

---

## 4. Installing Unity via CLI

We use the **Unity Hub CLI** so CI and developers share the same installation script.

```bash
# Example on macOS
unityhub -- --headless install \
    --version 2022.3.10f1 \
    --changeset 34b67ebb3e07 \
    --module android \
    --module ios \
    --module windows-mono
```

> 🔒   TycoonVerse is tested only against the _exact_ LTS version above.  
>      Mismatched patch releases can break deterministic offline sync.

---

## 5. Building & Running (Editor)

```bash
./build/run_editor.sh
```

The script:

1. Kills existing Unity processes
2. Launches Unity in **play-mode** with custom scripting define symbols:
   `LOCAL_DEV`, `IAP_SANDBOX`
3. Attaches the Unity Test Runner window for instant feedback

---

## 6. Automated Tests

| Layer | Cmd | Notes |
| ----- | --- | ----- |
| Domain (.NET) | `dotnet test src/Core.slnf` | Runs pure business logic (fast) |
| Unity PlayMode | `./build/run_tests.sh --playmode` | Instrumentation required |
| Unity EditMode | `./build/run_tests.sh --editmode` | No graphics required |

`run_tests.sh` merges coverage from all suites into `artifacts/coverage`  
Open `artifacts/coverage/index.html` to inspect the report.

---

## 7. Local SQLite Schema Upgrades

```bash
dotnet run \
  --project tools/DbMigrations \
  -- --storage "Data Source=$TYCOONVERSE_SQLITE_PATH"
```

The migrator uses **FluentMigrator** to evolve schema while preserving deterministic replay for offline mode.

---

## 8. Mobile Builds

### Android (Gradle)

```bash
./build/build_android.sh --flavor Development --aab
adb install -r "builds/android/Development/TycoonVerse.aab"
```

### iOS (Xcode)

```bash
./build/build_ios.sh --flavor Development
open builds/ios/Development/TycoonVerse.xcworkspace
```

Both scripts:

* Embed the **keystore / code-signing** certificates located in `~/.keystores/`
* Enable **Scriptable Render Pipeline** stripping to reduce binary size
* Inject a pre-configured in-app purchase catalog for the sandbox environment

---

## 9. In-App Purchase Sandbox

1. **Google Play**  
   * Add the test account to _License Testing_ in Play Console  
   * Upload the generated `.aab` under _Internal Test_ track

2. **Apple App Store**  
   * Create a _Sandbox Tester_ in App Store Connect  
   * Run the app via **TestFlight** or direct Xcode install

---

## 10. Analytics & Crash Reporting (Firebase)

Local builds route events to Firebase **DebugView**.

```bash
# Tail events
firebase analytics:debug --project tycoonverse-local
```

Crashlytics symbols are generated automatically; see `builds/**/symbols/`.

---

## 11. Biometric Authentication

The game uses the `Xamarin.Essentials` abstraction layer.

• Android: Ensure `android:requireDeviceUnlock="true"` is present in `AndroidManifest.xml`.  
• iOS: Add **Face ID Usage Description** to `Info.plist`.

---

## 12. Continuous Integration (GitHub Actions)

The pipeline lives in `.github/workflows/build.yml` and performs:

* Cache-aware Unity install
* Lint + format check (`dotnet format --verify-no-changes`)
* Full test matrix (Core, PlayMode, EditMode)
* Build AAB & IPA artifacts, attach to release draft
* Upload coverage to Codecov
* Slack notification on failure

Trigger manually with:

```bash
gh workflow run build.yml -f flavor=Release
```

---

## 13. Troubleshooting

| Symptom | Fix |
| ------- | --- |
| “Assembly re-loading locked” | Delete `Library/` + `obj/`, reopen project |
| `SQLiteException: database is locked` | Ensure no second instance of the game/editor is running |
| `InvalidChannel` when purchasing | Check `TYCOONVERSE_IAP_SANDBOX` and product IDs in Catalog |
| Build stalls at `Gradle preBuild` | Ensure Android Gradle Plugin installed (`7.3.0` min) |

---

## 14. Uninstall / Clean

```bash
./build/clean.sh --deep   # Wipes Library/, obj/, BuildCache/
rm -rf $TYCOONVERSE_SQLITE_PATH
unityhub -- --headless remove --version 2022.3.10f1
```

---

## 15. Need Help?

* Slack: `#tycoonverse-dev`
* Email: `dev@tycoonverse.io`
* Office Hours: Tue/Thu 15:00–17:00 UTC (Zoom link in Slack channel)

Happy empire building! 🚀
```