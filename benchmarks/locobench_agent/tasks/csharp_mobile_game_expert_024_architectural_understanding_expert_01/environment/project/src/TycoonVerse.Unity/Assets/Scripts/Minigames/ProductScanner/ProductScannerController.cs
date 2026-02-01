```csharp
// File: TycoonVerse/src/TycoonVerse.Unity/Assets/Scripts/Minigames/ProductScanner/ProductScannerController.cs
// Project: TycoonVerse: Enterprise Empire Simulator
//
// This controller orchestrates the camera-enabled “Product Scanner” mini-game.
// It bridges Unity’s presentation layer with domain services (camera adapter,
// texture repository, connectivity, analytics).  The controller is resilient
// to offline mode, queues uploads, and surfaces state changes through events.
//
// Author: TycoonVerse Engineering Team

using System;
using System.Collections.Generic;
using System.Threading;
using System.Threading.Tasks;
using UnityEngine;
using UnityEngine.Events;
using UnityEngine.UI;

namespace TycoonVerse.Minigames.ProductScanner
{
    #region Supporting Types ---------------------------------------------------------------------

    /// <summary>
    /// Lifecycle states for the scanner mini-game.
    /// </summary>
    public enum ScannerState
    {
        Uninitialized,
        Idle,
        AwaitingCameraPermission,
        Capturing,
        Processing,
        Completed,
        Failed,
        Disabled
    }

    /// <summary>
    /// Result information returned from a successful scan.
    /// </summary>
    public readonly struct ScanResult
    {
        public readonly string TextureId;
        public readonly Texture2D Texture;
        public readonly DateTime ScannedAt;

        public ScanResult(string textureId, Texture2D texture, DateTime scannedAt)
        {
            TextureId  = textureId;
            Texture    = texture;
            ScannedAt  = scannedAt;
        }
    }

    /// <summary>
    /// UnityEvent wrapper for scan results, permitting visual wiring via the Inspector.
    /// </summary>
    [Serializable]
    public sealed class ScanResultEvent : UnityEvent<ScanResult> { }

    #endregion

    #region Interfaces (Adapters & Services) ------------------------------------------------------

    // All services live elsewhere in the domain layer; only interfaces are referenced here.
    // The implementation for Editor/Device is swapped by an IoC container (e.g., Zenject).

    public interface ICameraAdapter
    {
        /// <summary>True if camera permission is already granted.</summary>
        bool HasPermission { get; }

        /// <summary>Requests camera permission.  Resolves to ‘true’ when granted.</summary>
        Task<bool> RequestPermissionAsync();

        /// <summary>Launches the device camera and returns a captured Texture2D.</summary>
        Task<Texture2D> CapturePhotoAsync(CancellationToken token);
    }

    public interface ITextureRepository
    {
        /// <summary>Persists the scanned texture locally, returns generated ID.</summary>
        Task<string> SaveAsync(Texture2D texture, CancellationToken token);

        /// <summary>Attempts to upload pending textures when network is available.</summary>
        Task FlushQueuedUploadsAsync(CancellationToken token);
    }

    public interface IConnectivityService
    {
        bool IsOnline { get; }
        event Action<bool> OnConnectivityChanged;
    }

    public interface IAnalyticsService
    {
        void TrackEvent(string eventName, params (string Key, object Value)[] payload);
    }

    #endregion

    /// <summary>
    /// Main MonoBehaviour orchestrating the Product Scanner flow.
    /// </summary>
    public sealed class ProductScannerController : MonoBehaviour
    {
        #region Inspector -------------------------------------------------------------------------

        [Header("UI")]
        [SerializeField] private Button _scanButton;
        [SerializeField] private GameObject _progressSpinner;
        [SerializeField] private GameObject _errorBanner;

        [Header("Events")]
        public UnityEvent OnScannerStateChanged = new();
        public ScanResultEvent OnScanCompleted  = new();

        #endregion

        #region Dependencies ----------------------------------------------------------------------

        private ICameraAdapter       _camera;
        private ITextureRepository   _textureRepo;
        private IConnectivityService _connectivity;
        private IAnalyticsService    _analytics;

        #endregion

        #region State -----------------------------------------------------------------------------

        public ScannerState State { get; private set; } = ScannerState.Uninitialized;

        private readonly List<ScanResult> _offlineQueue = new();

        private CancellationTokenSource _cts;

        #endregion

        #region Unity Lifecycle -------------------------------------------------------------------

        private async void Awake()
        {
            // Resolve dependencies (via Service Locator or DI container)
            _camera       = ServiceLocator.Resolve<ICameraAdapter>();
            _textureRepo  = ServiceLocator.Resolve<ITextureRepository>();
            _connectivity = ServiceLocator.Resolve<IConnectivityService>();
            _analytics    = ServiceLocator.Resolve<IAnalyticsService>();

            _connectivity.OnConnectivityChanged += HandleConnectivityChanged;

            _scanButton.onClick.AddListener(() => _ = BeginScanAsync());

            _progressSpinner.SetActive(false);
            _errorBanner.SetActive(false);

            State = ScannerState.Idle;
            OnScannerStateChanged.Invoke();
            await FlushIfNeededAsync();
        }

        private void OnDestroy()
        {
            _connectivity.OnConnectivityChanged -= HandleConnectivityChanged;
            _scanButton.onClick.RemoveAllListeners();
            _cts?.Cancel();
            _cts?.Dispose();
        }

        #endregion

        #region Public API ------------------------------------------------------------------------

        /// <summary>
        /// Entry-point for UI or external callers to start a scan.
        /// </summary>
        public async Task BeginScanAsync()
        {
            if (!CanBeginScan())
                return;

            _cts?.Dispose();
            _cts = new CancellationTokenSource();

            try
            {
                await EnsureCameraPermissionAsync(_cts.Token);
                await CaptureAndProcessAsync(_cts.Token);
            }
            catch (OperationCanceledException) when (_cts.IsCancellationRequested)
            {
                // User aborted; revert state gracefully
                TransitionTo(ScannerState.Idle);
            }
            catch (Exception ex)
            {
                Debug.LogException(ex, this);
                _analytics.TrackEvent("scanner_error", ("reason", ex.Message));
                DisplayError("Unexpected error while scanning.");
                TransitionTo(ScannerState.Failed);
            }
        }

        #endregion

        #region Core Workflow ---------------------------------------------------------------------

        private bool CanBeginScan()
        {
            if (State is ScannerState.Capturing or ScannerState.Processing)
                return false;

            if (State == ScannerState.Disabled)
                return false;

            return true;
        }

        private async Task EnsureCameraPermissionAsync(CancellationToken token)
        {
            if (_camera.HasPermission)
                return;

            TransitionTo(ScannerState.AwaitingCameraPermission);
            bool granted = await _camera.RequestPermissionAsync();

            if (!granted)
                throw new InvalidOperationException("Camera permission denied.");
        }

        private async Task CaptureAndProcessAsync(CancellationToken token)
        {
            TransitionTo(ScannerState.Capturing);

            _progressSpinner.SetActive(true);
            Texture2D photo = await _camera.CapturePhotoAsync(token);

            TransitionTo(ScannerState.Processing);

            string textureId = await _textureRepo.SaveAsync(photo, token);
            var result = new ScanResult(textureId, photo, DateTime.UtcNow);

            if (!_connectivity.IsOnline)
            {
                _offlineQueue.Add(result);
                _analytics.TrackEvent("scanner_offline_queue", ("count", _offlineQueue.Count));
            }
            else
            {
                await _textureRepo.FlushQueuedUploadsAsync(token);
            }

            _analytics.TrackEvent("scanner_scan_completed", ("textureId", textureId));

            OnScanCompleted.Invoke(result);
            TransitionTo(ScannerState.Completed);

            _progressSpinner.SetActive(false);
            await FlushIfNeededAsync();
        }

        #endregion

        #region Connectivity Handling -------------------------------------------------------------

        private void HandleConnectivityChanged(bool isOnline)
        {
            if (isOnline)
                _ = FlushIfNeededAsync();
        }

        private async Task FlushIfNeededAsync()
        {
            if (!_connectivity.IsOnline || _offlineQueue.Count == 0)
                return;

            try
            {
                _progressSpinner.SetActive(true);
                await _textureRepo.FlushQueuedUploadsAsync(CancellationToken.None);

                _analytics.TrackEvent("scanner_offline_flush",
                    ("flushedCount", _offlineQueue.Count));

                _offlineQueue.Clear();
            }
            catch (Exception ex)
            {
                Debug.LogWarning($"Failed to flush queued uploads: {ex.Message}", this);
            }
            finally
            {
                _progressSpinner.SetActive(false);
            }
        }

        #endregion

        #region UI Helpers ------------------------------------------------------------------------

        private void DisplayError(string message)
        {
            _errorBanner.SetActive(true);
            // Optionally wire the banner text via GetComponentInChildren<TMP_Text>()
            Invoke(nameof(HideError), 3f);
        }

        private void HideError() => _errorBanner.SetActive(false);

        private void TransitionTo(ScannerState newState)
        {
            if (State == newState)
                return;

            State = newState;
            OnScannerStateChanged.Invoke();
            Debug.Log($"[ProductScanner] State changed to {State}", this);
        }

        #endregion
    }

    #region Simple Service Locator Stub -----------------------------------------------------------

    // For brevity, a naive service locator is included.  In production we use
    // an IoC container (Zenject/Extenject).  The locator lets unit tests
    // re-bind interfaces easily.

    internal static class ServiceLocator
    {
        private static readonly Dictionary<Type, object> _instances = new();

        public static T Resolve<T>() where T : class
        {
            var type = typeof(T);
            if (_instances.TryGetValue(type, out var obj) && obj is T t)
                return t;

            throw new InvalidOperationException($"Service {type.Name} not registered.");
        }

        public static void Register<T>(T instance) where T : class =>
            _instances[typeof(T)] = instance;
    }

    #endregion
}
```