```markdown
# TycoonVerse ─ Build & Deployment Guide  
_Last updated: 2024-06-05_

This document is the single source of truth for compiling, packaging, and shipping **TycoonVerse: Enterprise Empire Simulator** across all supported platforms.  
It is intended for CI/CD engineers, build-farm maintainers, and any developer who needs to cut a production, QA, or internal build.

> NOTE  
> All CLI examples assume **Unity 2022.3 LTS** and **.NET 6 SDK** are installed on the build host.

---

## 1. Prerequisites

| Component            | Minimum Version | Install Guide                                 |
|----------------------|-----------------|----------------------------------------------|
| Unity Editor (LTS)   | 2022.3.4f1      | Unity Hub → Installs → Add → Android+iOS     |
| Android NDK          | r25c            | Installed via Unity Hub Modules              |
| Xcode                | 15.0            | `xcode-select --install`                     |
| .NET SDK             | 6.0.414         | https://dotnet.microsoft.com/download        |
| Fastlane (iOS/Android)| 2.215.0        | `brew install fastlane` / `gem install`      |
| Git LFS              | 3.4.0           | `brew install git-lfs` / `choco install`     |
| Node.js (for tools)  | 20.x            | `nvm install 20`                             |

**Environment Variables**

```bash
# Signing
export ANDROID_KEYSTORE_PASSWORD=***
export ANDROID_KEY_ALIAS=tycoonverse
export APPLE_API_KEY=***/***/***
export APPLE_API_ISSUER=****************************

# Artifact storage
export AWS_ACCESS_KEY_ID=****
export AWS_SECRET_ACCESS_KEY=****
```

---

## 2. Repository Layout (build-relevant)

```
/TycoonVerse
  ├── Assets/
  ├── Packages/
  ├── Tools/
  │   └── Build/
  │       ├── BuildScript.cs        # Headless build entry point
  │       └── version.txt           # Human-readable version seed
  ├── Azure/
  │   └── pipelines.yml             # Azure DevOps pipeline
  ├── GitHub/
  │   └── workflows/
  │       └── ci.yml                # GitHub Actions
  ├── docs/
  │   └── guides/
  │       └── BUILD_AND_DEPLOY.md   # <── this file
  └── ...
```

---

## 3. Versioning Strategy

We apply **SemVer 2.0** + build metadata:

```
<MAJOR>.<MINOR>.<PATCH>-<channel>+<build_id>

Examples:
1.7.3-prod+8924       # Store release
1.8.0-beta+11037      # TestFlight / Closed Beta
1.8.1-dev+sha.7d9e7ab # Internal dev stream
```

`Tools/Build/Versioning.cs` increments the `build_id` in CI using the run number and Git commit.

---

## 4. Building Locally

### 4.1 One-off Android (APK + AAB)

```bash
# From repository root:
unity -batchmode -nographics \
  -projectPath "$(pwd)" \
  -executeMethod TycoonVerse.Tools.Build.BuildScript.PerformAndroidBuild \
  -buildTarget Android \
  -customBuildPath ./Builds/Android \
  -quit -logFile ./Logs/unity_android.log
```

### 4.2 One-off iOS (Xcode project)

```bash
unity -batchmode -nographics \
  -projectPath "$(pwd)" \
  -executeMethod TycoonVerse.Tools.Build.BuildScript.PerformiOSBuild \
  -buildTarget iOS \
  -customBuildPath ./Builds/iOS \
  -quit -logFile ./Logs/unity_ios.log
```

Generated Xcode project is then signed & uploaded via Fastlane:

```bash
cd Builds/iOS
fastlane ios beta    # or 'release' for App Store
```

---

## 5. Build Automation Script

`Tools/Build/BuildScript.cs`

```csharp
using System;
using System.IO;
using UnityEditor;
using UnityEditor.Build.Reporting;

/// <summary>
/// Headless build orchestrator invoked by Unity CLI.
/// Add additional platform methods as needed (UWP, tvOS, etc.).
/// </summary>
public static class BuildScript
{
    private const string BuildFolder = "Builds";

    /* =======================================================================
     * Entrypoints (must be public for Unity -executeMethod)
     * =====================================================================*/

    public static void PerformAndroidBuild() =>
        Build(BuildTarget.Android, GetAndroidOptions());

    public static void PerformiOSBuild() =>
        Build(BuildTarget.iOS, GetiOSOptions());

    /* =======================================================================
     * Core build logic
     * =====================================================================*/

    private static void Build(BuildTarget target, BuildPlayerOptions options)
    {
        var started = DateTime.UtcNow;
        var report  = BuildPipeline.BuildPlayer(options);
        var elapsed = DateTime.UtcNow - started;

        if (report.summary.result != BuildResult.Succeeded)
        {
            Console.Error.WriteLine($"[Build] {target} failed in {elapsed.TotalMinutes:F1} min");
            foreach (var step in report.steps)
                Console.Error.WriteLine($"  ↳ {step.name}: {step.messages.Length} issues");

            throw new Exception($"Build failed: {report.summary.result}");
        }

        Console.WriteLine($"[Build] {target} succeeded in {elapsed.TotalMinutes:F1} min");
        Console.WriteLine($"        Output: {options.locationPathName}");
    }

    /* =======================================================================
     * Platform-specific settings
     * =====================================================================*/

    private static BuildPlayerOptions GetAndroidOptions()
    {
        string path = Path.Combine(BuildFolder, "Android", FileName("aab"));
        Directory.CreateDirectory(Path.GetDirectoryName(path)!);

        PlayerSettings.Android.bundleVersionCode = CalcBundleCode();
        PlayerSettings.bundleVersion              = Versioning.ResolveVersion();

        return new BuildPlayerOptions
        {
            scenes           = FindEnabledEditorScenes(),
            locationPathName = path,
            target           = BuildTarget.Android,
            options          = BuildOptions.CompressWithLz4HC | BuildOptions.Il2CPP
        };
    }

    private static BuildPlayerOptions GetiOSOptions()
    {
        string path = Path.Combine(BuildFolder, "iOS", FileName());
        Directory.CreateDirectory(path);

        PlayerSettings.iOS.buildNumber = CalcBundleCode().ToString();
        PlayerSettings.bundleVersion   = Versioning.ResolveVersion();

        return new BuildPlayerOptions
        {
            scenes           = FindEnabledEditorScenes(),
            locationPathName = path,
            target           = BuildTarget.iOS,
            options          = BuildOptions.Il2CPP
        };
    }

    /* =======================================================================
     * Helpers
     * =====================================================================*/

    private static string FileName(string extension = "") =>
        $"TycoonVerse_{Versioning.ResolveVersion()}{(string.IsNullOrEmpty(extension) ? "" : $".{extension}")}";

    private static int CalcBundleCode() =>
        int.TryParse(Environment.GetEnvironmentVariable("BUILD_BUILDID"), out var code) ? code : 1;

    private static string[] FindEnabledEditorScenes() =>
        EditorBuildSettings.scenes
                           .Where(s => s.enabled)
                           .Select(s => s.path)
                           .ToArray();
}
```

---

## 6. CI/CD Pipelines

### 6.1 GitHub Actions (`.github/workflows/ci.yml`)

```yaml
name: TycoonVerse CI

on:
  push:
    branches: [main, develop]
  pull_request:

jobs:
  build:
    runs-on: ${{ matrix.os }}
    strategy:
      matrix:
        os: [ubuntu-latest, macos-14] # Linux → Android, macOS → iOS
        target: [Android, iOS]
        exclude:
          - os: ubuntu-latest
            target: iOS
          - os: macos-14
            target: Android

    steps:
      - uses: actions/checkout@v4
        with:
          lfs: true

      - name: Cache Unity
        uses: actions/cache@v4
        with:
          path: ~/.cache/unity
          key: Unity-${{ hashFiles('ProjectSettings/ProjectVersion.txt') }}

      - name: Unity build
        uses: game-ci/unity-builder@v4
        env:
          UNITY_LICENSE: ${{ secrets.UNITY_LICENSE }}
          ANDROID_KEYSTORE_PASSWORD: ${{ secrets.ANDROID_KEYSTORE_PASSWORD }}
          APPLE_API_KEY: ${{ secrets.APPLE_API_KEY }}
          APPLE_API_ISSUER: ${{ secrets.APPLE_API_ISSUER }}
        with:
          targetPlatform: ${{ matrix.target }}
          projectPath: .
          buildName: TycoonVerse
          allowDirtyBuild: true

      - name: Upload Artifact
        uses: actions/upload-artifact@v4
        with:
          name: TycoonVerse-${{ matrix.target }}
          path: Builds/${{ matrix.target }}
```

### 6.2 Azure DevOps (`/Azure/pipelines.yml`)

```yaml
trigger:
  branches:
    include: [main]

pool:
  vmImage: 'macos-latest'

variables:
  buildConfiguration: Release
  unityVersion: 2022.3.4f1

steps:
- checkout: self
  lfs: true

- task: UnityBuild@3
  displayName: 'Unity iOS Build'
  inputs:
    unityVersion: $(unityVersion)
    targetPlatform: iOS
    buildMethod: TycoonVerse.Tools.Build.BuildScript.PerformiOSBuild

- task: CmdLine@2
  displayName: 'Fastlane Enterprise Deploy'
  inputs:
    script: |
      cd $(Build.SourcesDirectory)/Builds/iOS
      bundle install
      fastlane ios enterprise
```

---

## 7. Deployment Channels

1. **Internal (Dev)**
   • Distributed via Firebase App Distribution using `fastlane ios dev` / `fastlane android dev`.  
   • Diagnostics & crash reporting pointed at staging endpoints.

2. **Beta**
   • TestFlight & Google Closed Beta.  
   • Monetization A/B toggled **on** with limited price tiers.

3. **Production**
   • Store releases; feature flags locked.  
   • All analytics & crash endpoints use production credentials.

---

## 8. Secrets & Credential Rotation

| Secret                        | Storage              | Rotation Policy |
|-------------------------------|----------------------|-----------------|
| `UNITY_LICENSE`               | GitHub/Azure Secrets | Monthly         |
| Android keystore (`.keystore`) | AWS Secrets Manager  | Quarterly       |
| Apple API key (`.p8`)          | 90-day TTL           | Automated via Fastlane |

> Do _not_ commit any signing artifacts to the repository.  
> Build agents fetch them on-demand at pipeline runtime.

---

## 9. Post-Build QA Checklist

- [ ] Build version matches `version.txt`.
- [ ] Size budget (`<300 MB`) respected.
- [ ] All Unity debug symbols stripped (`.debugInfo` excluded).
- [ ] Firebase Crashlytics test crash sent.
- [ ] IAP sandbox purchase verified.
- [ ] Offline play scenario executed (airplane mode).

---

## 10. Troubleshooting

| Symptom                          | Likely Cause                                | Fix |
|----------------------------------|---------------------------------------------|-----|
| `IL2CPP build failed`            | Xcode/NDK mismatch                          | Verify toolchain versions |
| Android install crash on launch  | ABI filter mis-configured                   | Ensure `arm64-v8a` only   |
| iOS TestFlight build rejected    | Missing NSLocationWhenInUse description      | Re-run `PrivacyPlistPatch` tool |

---

## 11. Contributing

All changes to build-time code (`Tools/Build`) require a pull request review by a member of the **BuildOps** team.  
Update this guide if your PR alters:

- Unity CLI arguments
- Versioning scheme
- Artifact storage location
- Any CI/CD pipeline steps

---

Happy shipping! 🚀
```