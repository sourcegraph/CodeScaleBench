```csharp
// File: TycoonVerse/src/TycoonVerse.Infrastructure/Services/Sharing/NativeSocialSharingService.cs

using System;
using System.IO;
using System.Runtime.InteropServices;
using System.Threading;
using System.Threading.Tasks;
using Microsoft.Extensions.Logging;
using TycoonVerse.Application.Abstractions.Analytics;
using TycoonVerse.Application.Abstractions.Sharing;
using TycoonVerse.Domain.Enums;
using TycoonVerse.Infrastructure.Common;
using UnityEngine;

namespace TycoonVerse.Infrastructure.Services.Sharing
{
    /// <summary>
    /// Concrete implementation of <see cref="ISocialSharingService" /> that bridges Unity with the
    /// native Android / iOS share sheets.  Additional platforms fall back to opening the default browser.
    /// </summary>
    /// <remarks>
    /// Intended to be registered in DI as a singleton at game boot.
    /// </remarks>
    public sealed class NativeSocialSharingService : ISocialSharingService, IDisposable
    {
        private const string ScreenshotFileName = "tv_tmp_share.png";

        private readonly ILogger<NativeSocialSharingService> _logger;
        private readonly IAnalyticsService _analyticsService;
        private readonly ICoroutineRunner _coroutineRunner;
        private readonly string _cacheDirectory;

        private bool _disposed;

        public NativeSocialSharingService(
            ILogger<NativeSocialSharingService> logger,
            IAnalyticsService analyticsService,
            ICoroutineRunner coroutineRunner)
        {
            _logger = logger ?? throw new ArgumentNullException(nameof(logger));
            _analyticsService = analyticsService ?? throw new ArgumentNullException(nameof(analyticsService));
            _coroutineRunner = coroutineRunner ?? throw new ArgumentNullException(nameof(coroutineRunner));

            _cacheDirectory = Application.temporaryCachePath;
            _logger.LogInformation("NativeSocialSharingService initialized (cache: {Cache})", _cacheDirectory);
        }

        #region ISocialSharingService

        public async Task<ShareResult> ShareTextAsync(string message, CancellationToken ct = default)
        {
            message = message?.Trim() ?? string.Empty;

            if (string.IsNullOrEmpty(message))
            {
                _logger.LogWarning("ShareTextAsync invoked with empty message.");
                return ShareResult.InvalidParameters;
            }

            if (IsOffline())
            {
                _logger.LogWarning("ShareTextAsync aborted: offline.");
                return ShareResult.NoNetwork;
            }

            var result = await ShareInternalAsync(title: "TycoonVerse", message, imagePath: null, url: null, ct);
            TrackAnalytics("share_text", result);
            return result;
        }

        public async Task<ShareResult> ShareUrlAsync(string url, string message = null, CancellationToken ct = default)
        {
            url = url?.Trim();
            message = message?.Trim();

            if (string.IsNullOrEmpty(url))
            {
                _logger.LogWarning("ShareUrlAsync invoked with empty URL.");
                return ShareResult.InvalidParameters;
            }

            if (IsOffline())
            {
                _logger.LogWarning("ShareUrlAsync aborted: offline.");
                return ShareResult.NoNetwork;
            }

            var result = await ShareInternalAsync(title: "TycoonVerse", message, imagePath: null, url, ct);
            TrackAnalytics("share_url", result);
            return result;
        }

        public async Task<ShareResult> ShareScreenshotAsync(string message = null, CancellationToken ct = default)
        {
            if (IsOffline())
            {
                _logger.LogWarning("ShareScreenshotAsync aborted: offline.");
                return ShareResult.NoNetwork;
            }

            string filePath;
            try
            {
                filePath = await CaptureScreenshotAsync(ct);
            }
            catch (Exception ex)
            {
                _logger.LogError(ex, "Failed to capture screenshot.");
                return ShareResult.Failed;
            }

            var result = await ShareInternalAsync(
                title: "TycoonVerse",
                message: message,
                imagePath: filePath,
                url: null,
                ct);

            TrackAnalytics("share_screenshot", result);
            return result;
        }

        #endregion

        #region Private helpers

        private static bool IsOffline()
        {
            // Unity reports NotReachable even when on Wi-Fi without internet,
            // but any share operation will fail in those cases as well.
            return Application.internetReachability == NetworkReachability.NotReachable;
        }

        private void TrackAnalytics(string shareType, ShareResult result)
        {
            try
            {
                _analyticsService.CustomEvent("social_share", new()
                {
                    { "type", shareType },
                    { "result", result.ToString() }
                });
            }
            catch (Exception ex)
            {
                // Analytics failure should never break gameplay.
                _logger.LogDebug(ex, "Analytics tracking for social_share failed.");
            }
        }

        private async Task<ShareResult> ShareInternalAsync(
            string title,
            string message,
            string imagePath,
            string url,
            CancellationToken ct)
        {
            try
            {
#if UNITY_ANDROID
                return await ShareOnAndroidAsync(title, message, imagePath, url, ct);
#elif UNITY_IOS
                return await ShareOnIosAsync(title, message, imagePath, url, ct);
#else
                // Fallback: open default browser if we only have a URL.
                if (!string.IsNullOrEmpty(url))
                {
                    Application.OpenURL(url);
                    return ShareResult.Succeeded;
                }

                _logger.LogWarning("Social sharing not supported on this platform.");
                return ShareResult.NotSupported;
#endif
            }
            catch (Exception ex)
            {
                if (ex is OperationCanceledException)
                    return ShareResult.Canceled;

                _logger.LogError(ex, "Unhandled exception during share.");
                return ShareResult.Failed;
            }
        }

        private async Task<string> CaptureScreenshotAsync(CancellationToken ct)
        {
            var tcs = new TaskCompletionSource<string>();

            _coroutineRunner.Run(CaptureRoutine());

            return await tcs.Task;

            IEnumerator CaptureRoutine()
            {
                yield return new WaitForEndOfFrame();

                var filePath = Path.Combine(_cacheDirectory, ScreenshotFileName);
                ScreenCapture.CaptureScreenshot(ScreenshotFileName);
#if UNITY_ANDROID
                // On Android, we need to wait for the file to hit disk.
                const float timeout = 5f;
                var timer = 0f;
                while (!File.Exists(filePath) && timer < timeout)
                {
                    timer += Time.deltaTime;
                    yield return null;
                }
#endif
                tcs.TrySetResult(filePath);
            }
        }

#if UNITY_ANDROID
        private async Task<ShareResult> ShareOnAndroidAsync(
            string title,
            string message,
            string imagePath,
            string url,
            CancellationToken ct)
        {
            // AndroidJavaObject must be called from the main thread.
            var tcs = new TaskCompletionSource<ShareResult>();

            _coroutineRunner.Run(ShareRoutine());
            return await tcs.Task.WaitAsync(ct);

            IEnumerator ShareRoutine()
            {
                using var intent = new AndroidJavaObject("android.content.Intent");
                intent.Call<AndroidJavaObject>("setAction", "android.intent.action.SEND");

                string mime = "text/plain";
                if (!string.IsNullOrEmpty(imagePath))
                {
                    mime = "image/png";
                    var uri = GetUriFromFile(imagePath);
                    intent.Call<AndroidJavaObject>("putExtra", "android.intent.extra.STREAM", uri);
                }

                var shareContent = BuildAndroidShareContent(message, url);
                intent.Call<AndroidJavaObject>("putExtra", "android.intent.extra.TEXT", shareContent);
                intent.Call<AndroidJavaObject>("setType", mime);

                var unityActivity = GetUnityActivity();
                var chooser = intent.CallStatic<AndroidJavaObject>(
                    "android.content.Intent",
                    "createChooser",
                    intent,
                    title);

                unityActivity.Call("startActivity", chooser);

                // There is no callback for Android share sheets; mark as success after launch.
                tcs.TrySetResult(ShareResult.Succeeded);
                yield break;
            }

            static AndroidJavaObject GetUnityActivity()
            {
                using var unityPlayer = new AndroidJavaClass("com.unity3d.player.UnityPlayer");
                return unityPlayer.GetStatic<AndroidJavaObject>("currentActivity");
            }

            static AndroidJavaObject GetUriFromFile(string filePath)
            {
                using var file = new AndroidJavaObject("java.io.File", filePath);
                using var intentClass = new AndroidJavaClass("androidx.core.content.FileProvider");
                var unityActivity = GetUnityActivity();
                var application = unityActivity.Call<AndroidJavaObject>("getApplicationContext");
                string authority = application.Call<string>("getPackageName") + ".provider";
                return intentClass.CallStatic<AndroidJavaObject>("getUriForFile", application, authority, file);
            }

            static string BuildAndroidShareContent(string msg, string link)
            {
                if (string.IsNullOrEmpty(msg))
                    return link ?? string.Empty;

                return string.IsNullOrEmpty(link)
                    ? msg
                    : $"{msg} {link}";
            }
        }
#endif

#if UNITY_IOS
        [DllImport("__Internal")]
        private static extern void _TVNativeShare(string message, string url, string imagePath);

        private async Task<ShareResult> ShareOnIosAsync(
            string title,  // not used on iOS but kept for signature parity
            string message,
            string imagePath,
            string url,
            CancellationToken ct)
        {
            if (ct.IsCancellationRequested)
                return ShareResult.Canceled;

            // iOS call must be on main thread.
            _coroutineRunner.Run(CallNative());

            return await Task.FromResult(ShareResult.Succeeded);

            IEnumerator CallNative()
            {
                yield return null; // next frame to ensure we are on main thread.
                _TVNativeShare(message ?? string.Empty, url ?? string.Empty, imagePath ?? string.Empty);
            }
        }
#endif

        #endregion

        #region IDisposable

        public void Dispose()
        {
            if (_disposed) return;
            _disposed = true;

            // Purge temporary screenshot file if present
            var filePath = Path.Combine(_cacheDirectory, ScreenshotFileName);
            try
            {
                if (File.Exists(filePath))
                    File.Delete(filePath);
            }
            catch (Exception ex)
            {
                _logger.LogDebug(ex, "Failed to clean up screenshot temp file.");
            }
        }

        #endregion
    }
}
```