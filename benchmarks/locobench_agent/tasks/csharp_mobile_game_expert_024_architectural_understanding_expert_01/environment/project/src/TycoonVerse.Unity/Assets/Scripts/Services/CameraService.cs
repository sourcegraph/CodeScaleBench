```csharp
// -----------------------------------------------------------------------------
//  TycoonVerse: Enterprise Empire Simulator
//  File:    TycoonVerse.Unity/Assets/Scripts/Services/CameraService.cs
//  Author:  TycoonVerse Engineering
//  Purpose: Centralised runtime service that manages every in-game camera
//           operation (blending, zoom, shake, orientation compensation).  The
//           service exposes a clean API for gameplay systems (dashboards,
//           mini-games, cut-scenes) while hiding Cinemachine specifics and
//           ensuring analytics/telmetry events are emitted whenever the visual
//           context changes.
// -----------------------------------------------------------------------------

#nullable enable
using System;
using System.Collections.Generic;
using System.Threading;
using System.Threading.Tasks;
using Cinemachine;
using UnityEngine;
using UnityEngine.Assertions;

namespace TycoonVerse.Unity.Services
{
    /// <summary>
    /// A strongly-typed logical context for where the camera currently is.
    /// </summary>
    public enum CameraContext
    {
        Unknown           = 0,
        CorporateDashboard,
        FactoryFloor,
        WorldMap,
        ProductScannerMiniGame,
        Cutscene
    }

    /// <summary>
    /// The camera service owns all <see cref="CinemachineVirtualCamera"/> instances
    /// and is responsible for blending between them, handling run-time
    /// registrations (e.g., dynamically loaded level cameras),
    /// maintaining persistent state, and forwarding user events to analytics.
    ///
    /// Pattern(s):
    ///     ‑ Singleton  (single runtime instance)
    ///     ‑ Observer   (CameraContextChanged)
    /// </summary>
    [DisallowMultipleComponent]
    public sealed class CameraService : MonoBehaviour
    {
        //----------------------------------------------------------------------
        // Public API
        //----------------------------------------------------------------------

        /// <summary>
        /// Global accessor. Throws if accessed before initialisation.
        /// </summary>
        public static CameraService Instance
        {
            get
            {
                if (_instance == null)
                    throw new InvalidOperationException(
                        "CameraService accessed before it was initialised.");

                return _instance;
            }
        }

        /// <summary>
        /// Raised after a transition has completed and <see cref="CurrentContext"/>
        /// has been updated.  Use to react to camera changes without polling.
        /// </summary>
        public event Action<CameraContext>? CameraContextChanged;

        /// <summary>
        /// Current high-level camera context.
        /// </summary>
        public CameraContext CurrentContext { get; private set; } = CameraContext.Unknown;

        /// <summary>
        /// Register a Cinemachine virtual camera that represents the supplied
        /// logical context.  Existing registration for the same context is
        /// overwritten.  The virtual camera must already exist in the scene.
        /// </summary>
        /// <remarks>
        /// Use this in additive scene loads, e.g. factory scene spawns its own
        /// cameras then registers them with the core service.
        /// </remarks>
        public void RegisterPreset(CameraContext context, CinemachineVirtualCamera vCam)
        {
            if (vCam == null)
                throw new ArgumentNullException(nameof(vCam), "Attempted to register a null virtual camera.");

            _presets[context] = vCam;
            vCam.gameObject.SetActive(true); // Ensure it participates in blends.

            // Keep all non-active presets at priority 0 so they don’t take over
            if (context != CurrentContext)
                vCam.Priority = 0;
        }

        /// <summary>
        /// Unregisters a context. Safe to call repeatedly; silent if context
        /// isn’t registered.
        /// </summary>
        public void UnregisterPreset(CameraContext context)
        {
            if (_presets.TryGetValue(context, out var vCam))
            {
                Destroy(vCam.gameObject); // Clean-up object
                _presets.Remove(context);
            }
        }

        /// <summary>
        /// Asynchronously transition to the desired camera context.  The virtual
        /// camera associated with <paramref name="context"/> must have been
        /// registered previously.
        /// </summary>
        /// <param name="context">Target logical context.</param>
        /// <param name="blendSeconds">
        /// Override default blend time.  ‑1 uses the brain setting.
        /// </param>
        /// <param name="token">Cancellation token (optional).</param>
        public async Task SwitchToAsync(
            CameraContext context,
            float blendSeconds = -1f,
            CancellationToken token = default)
        {
            if (context == CurrentContext)
                return;

            if (!_presets.TryGetValue(context, out var targetVcam) || targetVcam == null)
            {
                Debug.LogError(
                    $"CameraService: requested context '{context}' has no registered virtual camera.");
                return;
            }

            // Raise priority so it becomes the active one
            targetVcam.Priority = _activePriority;
            _activePriority ^= 1; // Flip between 10/11 to keep continuous blend

            // Optionally override brain blend
            float originalBlend = _brain.m_DefaultBlend.m_Time;
            if (blendSeconds >= 0f)
                _brain.m_DefaultBlend.m_Time = blendSeconds;

            // Await until the brain reports the active vcam changed
            await WaitForBrainSwitchAsync(targetVcam, token).ConfigureAwait(false);

            // Restore original blend
            if (blendSeconds >= 0f)
                _brain.m_DefaultBlend.m_Time = originalBlend;

            // Notify listeners + analytics
            CurrentContext = context;
            CameraContextChanged?.Invoke(context);
            _analytics?.TrackCameraContextChanged(context.ToString());
        }

        /// <summary>
        /// Small helper to perform a camera shake effect on the current active
        /// CinemachineVirtualCamera.  Works by injecting noise for a given
        /// duration.  Intended for minor feedback (e.g., supply chain breakdown).
        /// </summary>
        public async Task ShakeAsync(
            float amplitude     = 2f,
            float frequency     = 2.5f,
            float durationSecs  = 0.35f,
            CancellationToken token = default)
        {
            var currentVcam = _brain.ActiveVirtualCamera as CinemachineVirtualCamera;
            if (currentVcam == null)
                return;

            // Get perlin noise component
            var noise = currentVcam.GetCinemachineComponent<CinemachineBasicMultiChannelPerlin>();
            if (noise == null)
                noise = currentVcam.AddCinemachineComponent<CinemachineBasicMultiChannelPerlin>();

            float originalAmplitude = noise.m_AmplitudeGain;
            float originalFrequency = noise.m_FrequencyGain;

            noise.m_AmplitudeGain = amplitude;
            noise.m_FrequencyGain = frequency;

            float t = 0f;
            while (t < durationSecs && !token.IsCancellationRequested)
            {
                await Task.Yield();
                t += Time.deltaTime;
            }

            // Restore
            noise.m_AmplitudeGain = originalAmplitude;
            noise.m_FrequencyGain = originalFrequency;
        }

        //----------------------------------------------------------------------
        // MonoBehaviour lifecycle
        //----------------------------------------------------------------------

        private void Awake()
        {
            if (_instance != null && _instance != this)
            {
                Debug.LogError("Duplicate CameraService detected; destroying.");
                Destroy(gameObject);
                return;
            }

            _instance = this;
            DontDestroyOnLoad(gameObject);

            _brain = Camera.main?.GetComponent<CinemachineBrain>();
            Assert.IsNotNull(_brain,
                "MainCamera is missing a CinemachineBrain; the CameraService requires this component.");
        }

        private void OnDestroy()
        {
            if (_instance == this)
                _instance = null;
        }

        //----------------------------------------------------------------------
        // Private helpers
        //----------------------------------------------------------------------

        private async Task WaitForBrainSwitchAsync(
            CinemachineVirtualCamera target,
            CancellationToken token)
        {
            // No special async library here – simple awaited loop.
            while (_brain.ActiveVirtualCamera != target && !token.IsCancellationRequested)
            {
                await Task.Yield(); // Continue next frame
            }
        }

        //----------------------------------------------------------------------
        // Internal state
        //----------------------------------------------------------------------

        private static CameraService? _instance;
        private readonly Dictionary<CameraContext, CinemachineVirtualCamera> _presets =
            new Dictionary<CameraContext, CinemachineVirtualCamera>(8);

        private CinemachineBrain? _brain;

        // We flip between these priorities for deterministic blending without
        // reinstantiating cameras.
        private int _activePriority = 11;

        //----------------------------------------------------------------------
        // Analytics integration (optional – resolved via Service Locator/DI)
        //----------------------------------------------------------------------

        private interface IAnalyticsService
        {
            void TrackCameraContextChanged(string contextName);
        }

        private IAnalyticsService? _analytics;

        // Optional setter used by dependency injection (e.g., Zenject)
        public void InjectAnalytics(IAnalyticsService analyticsService) =>
            _analytics = analyticsService;
    }
}
```
