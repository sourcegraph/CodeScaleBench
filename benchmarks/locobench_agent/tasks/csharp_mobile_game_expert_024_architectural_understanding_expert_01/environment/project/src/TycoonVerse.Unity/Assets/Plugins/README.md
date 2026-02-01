```markdown
# TycoonVerse Unity Plugin :heart_on_fire:
Enterprise Empire Simulator &mdash; **Developer Guide**

[![Unity](https://img.shields.io/badge/Unity-2021.3%2B-black?logo=unity)]()
[![License](https://img.shields.io/badge/License-Apache%202.0-blue.svg)]()
[![CI](https://github.com/TycoonVerse/TycoonVerse/actions/workflows/ci.yml/badge.svg)]()

Welcome to the **TycoonVerse.Unity** plugin.  
This package contains the Unity-specific presentation layer, View-Models, and adapters that glue the simulation core to the game client.  
Everything in this folder is **100 % C#** and suitable for deterministic builds via **Unity 2021.3 LTS** or later.

---

## ✨ Features
| Layer                | Pattern            | Purpose                                                                           |
|----------------------|--------------------|-----------------------------------------------------------------------------------|
| Bootstrapping        | `Singleton`        | Deterministic lifecycle aligned with Unity’s scene loading                        |
| Messaging            | `Observer`         | Global, memory-safe event bus for telemetry & UI                                   |
| Persistence          | `Repository`       | Abstracted SQLite access + encrypted local-only fallback                          |
| Platform Adapters    | `Adapter`          | Bridges iOS/Android SDKs for IAP, biometrics, Push                                |
| UI                   | `MVVM`             | Scene-agnostic view models with editor-friendly bindings                          |

---

## 🚀 Quick Start

1. Import the package: `Assets → Import Package → Custom Package…`
2. Create an empty `Bootstrap` scene.
3. Add the `GameStartup` prefab (found in `Assets/Plugins/Prefabs`).
4. Hit **Play** – a fully wired simulation begins in under a second.

```csharp
// Assets/Plugins/Scripts/GameStartup.cs
using System;
using TycoonVerse.Core;
using TycoonVerse.Infrastructure;
using TycoonVerse.Unity.Analytics;
using UnityEngine;

[DefaultExecutionOrder(-999)]
public sealed class GameStartup : MonoBehaviour
{
    // Singleton ref (scene-persistent)
    public static GameStartup Instance { get; private set; }

    private readonly Lazy<IGameKernel> _kernel = new(() =>
        new GameKernel(
            new SqliteRepository(PathService.PersistantDataPath),
            new UnityAnalyticsProvider(),
            new DeviceAdapter())
    );

    private void Awake()
    {
        if (Instance != null)
        {
            Destroy(gameObject);
            return;
        }

        Instance = this;
        DontDestroyOnLoad(this);
        Initialize();
    }

    private async void Initialize()
    {
        try
        {
            Application.targetFrameRate = 60;

            await _kernel.Value.InitializeAsync();
            Debug.Log("TycoonVerse Kernel initialized.");

            SceneLoader.Load(SceneId.Hub);     // Kick off first scene
        }
        catch (Exception ex)
        {
            Debug.LogException(ex);
            CrashReporter.LogFatal(ex);
            // Optionally present a fallback UI here
        }
    }
}
```

---

## 🗂️ Directory Structure

```
Assets/
 └─ Plugins/
    ├─ Scripts/         // Public API surface
    ├─ Runtime/         // Internal runtime utilities
    ├─ Editor/          // Custom inspectors & build-time tools
    ├─ Prefabs/
    ├─ Resources/
    └─ Tests/
```

---

## 💾 Persistence Layer – Repository Pattern

```csharp
// Assets/Plugins/Scripts/Persistence/SqliteRepository.cs
using System;
using System.Collections.Generic;
using System.Threading.Tasks;
using TycoonVerse.Core.Domain;
using TycoonVerse.Core.Ports;
using UnityEngine;
using SQLite;

namespace TycoonVerse.Infrastructure
{
    public sealed class SqliteRepository : IRepository
    {
        private readonly SQLiteAsyncConnection _db;

        public SqliteRepository(string databasePath)
        {
            _db = new SQLiteAsyncConnection(databasePath);
        }

        public async Task InitializeAsync()
        {
            try
            {
                await _db.CreateTableAsync<CompanyDto>().ConfigureAwait(false);
                await _db.CreateTableAsync<InventoryDto>().ConfigureAwait(false);
            }
            catch (Exception e)
            {
                Debug.LogException(e);
                throw; // escalate for crash reporting
            }
        }

        public Task<int> UpsertAsync<T>(T item) where T : IDto
            => _db.InsertOrReplaceAsync(item);

        public Task<IReadOnlyList<T>> QueryAsync<T>(
            Func<TableQuery<T>, TableQuery<T>> query = null) where T : IDto
        {
            var table = _db.Table<T>();
            var finalQuery = query?.Invoke(table) ?? table;
            return finalQuery.ToListAsync()
                             .ContinueWith(t => (IReadOnlyList<T>)t.Result);
        }
    }
}
```

---

## 📊 Analytics – Observer Pattern

```csharp
// Assets/Plugins/Scripts/Analytics/UnityAnalyticsProvider.cs
using System.Collections.Generic;
using UnityEngine;
using UnityEngine.Analytics;
using TycoonVerse.Core.Events;

namespace TycoonVerse.Unity.Analytics
{
    public sealed class UnityAnalyticsProvider : IEventObserver
    {
        private readonly Dictionary<string, object> _buffer
            = new(capacity: 4);

        public void OnEvent(GameEvent e)
        {
            _buffer.Clear();
            foreach (var (k, v) in e.Payload)
                _buffer[k] = v;

            AnalyticsResult result = Analytics.CustomEvent(
                e.Name, _buffer);

            if (result != AnalyticsResult.Ok)
                Debug.LogWarning(
                    $"Analytics event '{e.Name}' failed: {result}");
        }
    }
}
```

---

## 🔐 Biometric Authentication – Adapter Pattern

```csharp
// Assets/Plugins/Scripts/Auth/DeviceAdapter.cs
using System.Threading.Tasks;
using TycoonVerse.Core.Ports;
using UnityEngine;

namespace TycoonVerse.Infrastructure
{
    public sealed class DeviceAdapter : IDeviceAuth
    {
        public async Task<AuthResult> AuthenticateAsync()
        {
#if UNITY_IOS
            bool ok = await IOSFaceId.AuthenticateAsync();
#elif UNITY_ANDROID
            bool ok = await AndroidBiometrics.AuthenticateAsync();
#else
            bool ok = true; // editor fallback
#endif
            return new AuthResult(ok,
                ok ? null : "Biometric authentication failed.");
        }
    }
}
```

---

## 🛠️ Unit Testing

All editor & runtime tests live under `Assets/Plugins/Tests`.  
We rely on **NUnit** + **Unity Test Runner** for automated play-mode coverage.

```csharp
// Assets/Plugins/Tests/Persistence/SqliteRepositoryTests.cs
using NUnit.Framework;
using TycoonVerse.Infrastructure;
using System.IO;
using System.Threading.Tasks;

public class SqliteRepositoryTests
{
    private string _dbPath;

    [SetUp]
    public void SetUp()
    {
        _dbPath = Path.Combine(Path.GetTempPath(), 
                               $"tycoonverse-test-{Random.Range(0,9999)}.db");
    }

    [TearDown]
    public void TearDown()
    {
        if (File.Exists(_dbPath))
            File.Delete(_dbPath);
    }

    [Test]
    public async Task UpsertAndQuery_WritesAndReadsData()
    {
        var repo = new SqliteRepository(_dbPath);
        await repo.InitializeAsync();

        var dto = new CompanyDto { Id = "TEST", Name = "Foo Corp" };
        await repo.UpsertAsync(dto);

        var results = await repo.QueryAsync<CompanyDto>(
            q => q.Where(x => x.Id == "TEST"));
        Assert.AreEqual(1, results.Count);
        Assert.AreEqual("Foo Corp", results[0].Name);
    }
}
```

---

## 📣 Contributing

1. Fork → Feature Branch → PR  
2. Respect the layered architecture; UI code must never reference infrastructure directly.  
3. All public methods require XML-doc comments.  
4. **CI must pass** (linting, tests, APK build) before review.

---

## 📝 License

```text
Copyright 2024 TycoonVerse

Licensed under the Apache License, Version 2.0 (the "License");
you may not use this file except in compliance with the License.
```
```