```csharp
// -----------------------------------------------------------------------------
//  TycoonVerse: Enterprise Empire Simulator
//  File:        Assets/Scripts/GameManager.cs
//  Author:      TycoonVerse Engineering Team
//
//  Description: Orchestrates the application-level life-cycle, boot-strapping
//               domain services (auth, storage, analytics, purchases, etc.),
//               coordinating online / offline state, and exposing a simple
//               event-driven API to the rest of the gameplay code-base.
//
//  NOTE:        This class purposefully depends only on service interfaces
//               declared in TycoonVerse.Core.* namespaces so that it can be
//               unit-tested outside of Unity when compiled as a standalone
//               .NET assembly.
// -----------------------------------------------------------------------------

#nullable enable
using System;
using System.Collections;
using System.Threading;
using System.Threading.Tasks;
using UnityEngine;
using UnityEngine.SceneManagement;
using TycoonVerse.Core.Events;
using TycoonVerse.Core.Infrastructure;
using TycoonVerse.Core.Services.Analytics;
using TycoonVerse.Core.Services.Auth;
using TycoonVerse.Core.Services.CrashReporting;
using TycoonVerse.Core.Services.Purchases;
using TycoonVerse.Core.Services.Storage;

namespace TycoonVerse.Unity
{
    /// <summary>
    /// Central façade that boot-straps all run-time systems and maintains global
    /// state while the application is alive. Implements the Singleton pattern
    /// in a Unity-friendly way (<c>DontDestroyOnLoad</c>, no public ctor, etc.).
    /// </summary>
    public sealed class GameManager : MonoBehaviour
    {
        // ---------------------------------------------------------------------
        // STATIC SINGLETON BOILER-PLATE
        // ---------------------------------------------------------------------
        private static readonly object _lock = new();
        private static GameManager? _instance;

        /// <summary>
        /// Global access to the <see cref="GameManager"/> instance.
        /// </summary>
        public static GameManager Instance
        {
            get
            {
                if (_quitting)
                    throw new InvalidOperationException(
                        "Trying to access GameManager while shutting down.");

                if (_instance == null)
                {
                    // Look for one already in the scene (unit tests, etc.)
                    _instance = FindObjectOfType<GameManager>();

                    // Lazily create if not present.
                    if (_instance == null)
                    {
                        var go = new GameObject(nameof(GameManager));
                        _instance = go.AddComponent<GameManager>();
                    }
                }

                return _instance;
            }
        }

        private static bool _quitting;

        // ---------------------------------------------------------------------
        // INTERNAL FIELDS / STATE
        // ---------------------------------------------------------------------
        private readonly CancellationTokenSource _cancellationSource = new();
        private IAuthService?            _authService;
        private ILocalStorageService?    _storageService;
        private IAnalyticsService?       _analyticsService;
        private IInAppPurchaseService?   _iapService;
        private ICrashReportingService?  _crashService;
        private IEventBus?               _eventBus;
        private bool                     _initialized;

        // Control flag to avoid multiple switch handling.
        private bool _isAppPaused;

        // ---------------------------------------------------------------------
        // UNITY LIFECYCLE
        // ---------------------------------------------------------------------
        private void Awake()
        {
            lock (_lock)
            {
                if (_instance == null)
                {
                    _instance = this;
                    DontDestroyOnLoad(gameObject);
                }
                else if (_instance != this)
                {
                    // There can be only one. Destroy duplicates.
                    Debug.LogWarning("[GameManager] Duplicate instance detected – destroying.");
                    Destroy(gameObject);
                    return;
                }
            }

            // Defer heavy initialization until Start() so that other
            // MonoBehaviours can register for events in Awake().
        }

        private async void Start()
        {
            if (_initialized) return;

            try
            {
                await BootstrapAsync(_cancellationSource.Token);
                _initialized = true;
            }
            catch (Exception ex)
            {
                Debug.LogException(ex);
                // We re-throw to crash so Crashlytics, etc. get the stack trace
                // before Unity swallows it in async contexts.
                throw;
            }
        }

        private void OnEnable()
        {
            SceneManager.sceneLoaded += OnSceneLoaded;
        }

        private void OnDisable()
        {
            SceneManager.sceneLoaded -= OnSceneLoaded;
        }

        private void OnApplicationPause(bool pauseStatus)
        {
            _isAppPaused = pauseStatus;

            if (_isAppPaused)
                HandleAppSuspended();
            else
                HandleAppResumed();
        }

        private void OnApplicationQuit()
        {
            _quitting = true;

            // Flush analytics and storage synchronously on quit where possible.
            try
            {
                _analyticsService?.FlushImmediately();
                _storageService?.SaveAll();
            }
            catch (Exception e)
            {
                Debug.LogWarning($"[GameManager] Error while flushing on quit: {e}");
            }

            _cancellationSource.Cancel();
        }

        // ---------------------------------------------------------------------
        // PUBLIC API
        // ---------------------------------------------------------------------

        /// <summary>
        /// Indicates whether the game has completed its start-up sequence.
        /// Useful when scenes that load additively need to delay game logic.
        /// </summary>
        public bool IsInitialized => _initialized;

        // ---------------------------------------------------------------------
        // BOOTSTRAP
        // ---------------------------------------------------------------------
        private async Task BootstrapAsync(CancellationToken ct)
        {
            Debug.Log("[GameManager] Boot-strapping services …");

            // 1. Resolve infrastructure (DI / Service Locator).
            await ResolveServicesAsync(ct);

            // 2. Register error handlers *before* doing anything else.
            _crashService!.RegisterGlobalHandlers();

            // 3. Authentication & user profile.
            var profile = await _authService!.SignInAsync(ct);

            // 4. Load user-specific data from local storage.
            await _storageService!.LoadAsync(profile.UserId, ct);

            // 5. Initialize analytics after we have user id.
            _analyticsService!.Initialize(profile);
            _analyticsService!.TrackEvent(AnalyticsEvents.GameLaunched);

            // 6. Initialize IAP catalog (remote configs / AB tests).
            await _iapService!.InitializeAsync(ct);

            // 7. Notify domain listeners that boot-strap has finished.
            _eventBus!.Publish(new GameInitializedEvent(profile));

            Debug.Log("[GameManager] Initialization complete.");
        }

        private async Task ResolveServicesAsync(CancellationToken ct)
        {
            // In production we could use Zenject, UniRx DI, or our custom
            // ServiceLocator. Here we mock the async retrieval to showcase the
            // pattern (e.g., loading external DLLs, warm-up operations, etc.).
            await Task.Yield();

            _authService      = ServiceLocator.Resolve<IAuthService>();
            _storageService   = ServiceLocator.Resolve<ILocalStorageService>();
            _analyticsService = ServiceLocator.Resolve<IAnalyticsService>();
            _iapService       = ServiceLocator.Resolve<IInAppPurchaseService>();
            _crashService     = ServiceLocator.Resolve<ICrashReportingService>();
            _eventBus         = ServiceLocator.Resolve<IEventBus>();

            // Validate that critical dependencies exist.
            if (_authService      == null ||
                _storageService   == null ||
                _analyticsService == null ||
                _iapService       == null ||
                _crashService     == null ||
                _eventBus         == null)
            {
                throw new InvalidOperationException(
                    "One or more critical services failed to resolve.");
            }
        }

        // ---------------------------------------------------------------------
        // APPLICATION STATE HANDLING
        // ---------------------------------------------------------------------
        private void HandleAppSuspended()
        {
            Debug.Log("[GameManager] Application paused – saving state.");
            _eventBus?.Publish(AppLifecycleEvent.Paused);
            _storageService?.SaveAll();

            // We purposely don't flush analytics here; let them accumulate and
            // send in batch when the player returns (saves network).
        }

        private void HandleAppResumed()
        {
            Debug.Log("[GameManager] Application resumed – syncing data.");
            _eventBus?.Publish(AppLifecycleEvent.Resumed);

            // Fire and forget – we don't want to block UI thread.
            _ = AttemptDeferredSyncAsync();
        }

        private async Task AttemptDeferredSyncAsync()
        {
            if (!_initialized) return;

            try
            {
                // 1. Try to upload any offline analytics.
                await _analyticsService!.FlushAsync();

                // 2. Push local user mutations to the server.
                await _storageService!.PushPendingMutationsAsync();
            }
            catch (Exception e)
            {
                Debug.LogWarning($"[GameManager] Deferred sync failed: {e}");
            }
        }

        // ---------------------------------------------------------------------
        // SCENE MANAGEMENT
        // ---------------------------------------------------------------------
        private void OnSceneLoaded(Scene scene, LoadSceneMode mode)
        {
            // Basic instrumentation – helps with funnel analysis.
            _analyticsService?.TrackEvent(
                AnalyticsEvents.SceneLoaded, ("sceneName", scene.name));

            // Example: we could preload references required for the given scene.
        }
    }

    // -------------------------------------------------------------------------
    // DATA CONTRACTS / EVENTS
    // -------------------------------------------------------------------------
    internal static class AnalyticsEvents
    {
        public const string GameLaunched = "game_launched";
        public const string SceneLoaded  = "scene_loaded";
    }

    /// <summary>
    /// Dispatched globally once all start-up systems are ready. Provides the
    /// signed-in user profile so other systems can immediately personalize.
    /// </summary>
    public sealed class GameInitializedEvent : IEvent
    {
        public readonly IUserProfile UserProfile;

        public GameInitializedEvent(IUserProfile profile) =>
            UserProfile = profile;
    }

    /// <summary>
    /// Simplified representation of app life-cycle events. In production this
    /// would likely be an enum + payload or a more elaborate class hierarchy.
    /// </summary>
    public sealed class AppLifecycleEvent : IEvent
    {
        public static readonly AppLifecycleEvent Paused  = new("paused");
        public static readonly AppLifecycleEvent Resumed = new("resumed");

        public readonly string State;

        private AppLifecycleEvent(string state) => State = state;
    }
}
```
