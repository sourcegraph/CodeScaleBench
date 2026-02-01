```csharp
// File: TycoonVerse/src/TycoonVerse.Unity/Assets/Scripts/Bootstrapper.cs
// Description: Centralized entry-point that wires up domain, infrastructure, and presentation layers
//              before the first scene finishes loading.  The class also exposes a completion task
//              so other MonoBehaviours can await a ready-state without resorting to polling.
//
// NOTE: In production these services live in their own files/assemblies.  They’re co-located here
//       solely to ensure this single-file excerpt compiles in isolation.

#nullable enable
using System;
using System.Collections.Generic;
using System.Threading;
using System.Threading.Tasks;
using UnityEngine;

namespace TycoonVerse.Unity
{
    /// <summary>
    /// Responsible for orchestrating the start-up sequence of critical game services.
    /// </summary>
    /// <remarks>
    ///  • Loads before the first frame through <see cref="RuntimeInitializeOnLoadMethodAttribute"/>.
    ///  • Guarantees singleton semantics even across scene reloads.
    ///  • Exposes <see cref="Initialization"/> so callers can <c>await</c> readiness in an async-safe way.
    /// </remarks>
    public sealed class Bootstrapper : MonoBehaviour
    {
        private static readonly object _gate = new();
        private static Bootstrapper? _instance;
        private CancellationTokenSource _cts = new();

        /// <summary>
        /// Gets the task that completes when all services are initialized and ready.
        /// </summary>
        public static Task Initialization => Instance._initializationTcs.Task;

        private readonly TaskCompletionSource<bool> _initializationTcs =
            new(TaskCreationOptions.RunContinuationsAsynchronously);

        #region Unity Lifecycle --------------------------------------------------

        [RuntimeInitializeOnLoadMethod(RuntimeInitializeLoadType.BeforeSceneLoad)]
        private static void CreateBootstrapper()
        {
            if (_instance != null) return; // Already created (domain reload in Editor?)
            var go = new GameObject(nameof(Bootstrapper));
            DontDestroyOnLoad(go);
            _instance = go.AddComponent<Bootstrapper>();
        }

        private void Awake()
        {
            // Ensure singleton even if manually placed in a scene.
            lock (_gate)
            {
                if (_instance != null && _instance != this)
                {
                    Debug.LogWarning($"{nameof(Bootstrapper)} duplicate detected; destroying.");
                    Destroy(gameObject);
                    return;
                }

                _instance ??= this;
            }
        }

        private void Start()
        {
            // Kick-off the async initialization pipeline.
            _ = InitializeAsync(_cts.Token);
        }

        private void OnDestroy()
        {
            _cts.Cancel();
            ServiceLocator.Reset(); // Gracefully tear down services.
        }

        #endregion

        #region Initialization Pipeline -----------------------------------------

        private async Task InitializeAsync(CancellationToken ct)
        {
            try
            {
                Debug.Log("[Bootstrapper] Starting service initialization…");

                // 1. Build infrastructure services.
                RegisterInfrastructure();

                // 2. Initialize services that need async boot.
                var initTasks = new List<Task>
                {
                    Resolve<ILocalStorageService>().InitializeAsync(ct),
                    Resolve<IBiometricAuthService>().WarmUpAsync(ct),
                    Resolve<IIapService>().InitializeAsync(ct),
                    Resolve<IAnalyticsService>().InitializeAsync(ct),
                    Resolve<ICrashReportingService>().InitializeAsync(ct)
                };

                await Task.WhenAll(initTasks).ConfigureAwait(false);

                Debug.Log("[Bootstrapper] All services initialized successfully.");

                _initializationTcs.TrySetResult(true);
            }
            catch (Exception ex)
            {
                Debug.LogException(ex);
                _initializationTcs.TrySetException(ex);
                // Failsafe: show a fatal error UI or fallback to offline mode here.
            }
        }

        private static void RegisterInfrastructure()
        {
            // Local storage must be first because other services depend on persisted config.
            ServiceLocator.Register<ILocalStorageService>(new SqliteLocalStorageService());
            ServiceLocator.Register<IBiometricAuthService>(new BiometricAuthService());
            ServiceLocator.Register<IIapService>(new UnityIapService());
            ServiceLocator.Register<IAnalyticsService>(new GameAnalyticsService());
            ServiceLocator.Register<ICrashReportingService>(new UnityCrashReportingService());
        }

        #endregion

        #region Helpers ----------------------------------------------------------

        private static T Resolve<T>() where T : class =>
            ServiceLocator.Resolve<T>();

        private static Bootstrapper Instance
        {
            get
            {
                if (_instance == null)
                    throw new InvalidOperationException(
                        $"{nameof(Bootstrapper)} accessed before initialization.");

                return _instance;
            }
        }

        #endregion
    }

    #region Lightweight Service Locator -----------------------------------------

    /// <summary>
    /// Minimalist service locator used during start-up.  Prefer DI containers for complex graphs.
    /// </summary>
    internal static class ServiceLocator
    {
        private static readonly Dictionary<Type, object> _services = new();

        public static void Register<T>(T implementation) where T : class
        {
            if (implementation == null) throw new ArgumentNullException(nameof(implementation));

            var type = typeof(T);
            if (_services.ContainsKey(type))
                throw new InvalidOperationException($"Service '{type.Name}' already registered.");

            _services[type] = implementation;
        }

        public static T Resolve<T>() where T : class
        {
            var type = typeof(T);
            if (_services.TryGetValue(type, out var service) && service is T typed)
                return typed;

            throw new KeyNotFoundException(
                $"Service '{type.Name}' has not been registered yet. Did you forget to call Register()?");
        }

        public static void Reset() => _services.Clear();
    }

    #endregion

    #region Service Contracts ----------------------------------------------------

    public interface ILocalStorageService
    {
        Task InitializeAsync(CancellationToken ct);
        Task SaveAsync(string key, string json, CancellationToken ct);
        Task<string?> LoadAsync(string key, CancellationToken ct);
    }

    public interface IBiometricAuthService
    {
        Task WarmUpAsync(CancellationToken ct);
        Task<bool> AuthenticateAsync(string promptMessage, CancellationToken ct);
    }

    public interface IIapService
    {
        Task InitializeAsync(CancellationToken ct);
        Task PurchaseAsync(string productId, CancellationToken ct);
    }

    public interface IAnalyticsService
    {
        Task InitializeAsync(CancellationToken ct);
        void LogEvent(string eventName, IDictionary<string, object>? parameters = null);
    }

    public interface ICrashReportingService
    {
        Task InitializeAsync(CancellationToken ct);
        void ReportException(Exception ex, IDictionary<string, object>? context = null);
    }

    #endregion

    #region Infrastructure Implementations (stubs) ------------------------------

    /// <summary>
    /// SQLite-backed implementation for persisting deterministic game state.
    /// </summary>
    internal sealed class SqliteLocalStorageService : ILocalStorageService
    {
        private bool _isReady;

        public async Task InitializeAsync(CancellationToken ct)
        {
            // Simulate SQLite initialization.
            await Task.Delay(150, ct);
            _isReady = true;
            Debug.Log("[LocalStorage] SQLite connection pool ready.");
        }

        public async Task SaveAsync(string key, string json, CancellationToken ct)
        {
            EnsureReady();
            await Task.Delay(30, ct); // Simulate I/O
            PlayerPrefs.SetString(key, json);
        }

        public async Task<string?> LoadAsync(string key, CancellationToken ct)
        {
            EnsureReady();
            await Task.Delay(30, ct);
            return PlayerPrefs.HasKey(key) ? PlayerPrefs.GetString(key) : null;
        }

        private void EnsureReady()
        {
            if (!_isReady)
                throw new InvalidOperationException("Local storage has not been initialized.");
        }
    }

    /// <summary>Wraps native biometric APIs (FaceID/TouchID/Android Biometrics).</summary>
    internal sealed class BiometricAuthService : IBiometricAuthService
    {
        private bool _prepared;

        public async Task WarmUpAsync(CancellationToken ct)
        {
            await Task.Delay(100, ct); // Warm-up native API.
            _prepared = true;
            Debug.Log("[BiometricAuth] Warm-up complete.");
        }

        public async Task<bool> AuthenticateAsync(string promptMessage, CancellationToken ct)
        {
            if (!_prepared)
                throw new InvalidOperationException("Service not warmed up.");

            // Replace with real biometric call.
            await Task.Delay(500, ct);
            Debug.Log($"[BiometricAuth] {promptMessage} — user authenticated.");
            return true;
        }
    }

    /// <summary>Unity IAP bridge with receipt validation.</summary>
    internal sealed class UnityIapService : IIapService
    {
        public async Task InitializeAsync(CancellationToken ct)
        {
            await Task.Delay(200, ct); // Simulate initialization
            Debug.Log("[IAP] Unity IAP initialized.");
        }

        public async Task PurchaseAsync(string productId, CancellationToken ct)
        {
            await Task.Delay(800, ct); // Simulate purchase flow
            Debug.Log($"[IAP] Purchase completed for product '{productId}'.");
        }
    }

    /// <summary>Analytics adapter that funnels events to multiple backends.</summary>
    internal sealed class GameAnalyticsService : IAnalyticsService
    {
        private bool _ready;

        public async Task InitializeAsync(CancellationToken ct)
        {
            await Task.Delay(120, ct); // Simulate SDK init
            _ready = true;
            Debug.Log("[Analytics] SDK initialized.");
        }

        public void LogEvent(string eventName, IDictionary<string, object>? parameters = null)
        {
            if (!_ready)
            {
                Debug.LogWarning($"[Analytics] Attempted to log '{eventName}' before initialization.");
                return;
            }

            var paramDump = parameters == null ? "∅" : string.Join(", ", parameters);
            Debug.Log($"[Analytics] Event '{eventName}' → {paramDump}");
        }
    }

    /// <summary>Crash reporting integration (e.g., Unity Cloud Diagnostics).</summary>
    internal sealed class UnityCrashReportingService : ICrashReportingService
    {
        private bool _ready;

        public async Task InitializeAsync(CancellationToken ct)
        {
            await Task.Delay(80, ct); // Simulate initialization
            _ready = true;
            Debug.Log("[CrashReporting] Service ready.");
        }

        public void ReportException(Exception ex, IDictionary<string, object>? context = null)
        {
            if (!_ready)
            {
                Debug.LogWarning("[CrashReporting] Tried to report crash before ready.");
                return;
            }

            // Forward to actual crash reporter.
            Debug.LogException(ex);
        }
    }

    #endregion
}
```