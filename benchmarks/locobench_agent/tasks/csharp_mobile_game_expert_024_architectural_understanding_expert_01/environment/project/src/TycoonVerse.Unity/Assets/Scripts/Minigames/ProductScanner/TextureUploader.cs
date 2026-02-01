```csharp
// File: TycoonVerse/src/TycoonVerse.Unity/Assets/Scripts/Minigames/ProductScanner/TextureUploader.cs

using System;
using System.Collections;
using System.Collections.Generic;
using System.IO;
using System.Text;
using System.Threading;
using System.Threading.Tasks;
using UnityEngine;
using UnityEngine.Networking;

namespace TycoonVerse.Minigames.ProductScanner
{
    /// <summary>
    /// Handles the persistence and upload of user–generated textures for the Product-Scanner mini-game.
    /// Textures are safely queued to disk while the device is offline and uploaded automatically
    /// once network connectivity is detected.
    ///
    /// • Implements a lightweight Singleton for ease of use inside the Unity scene.
    /// • Respects mobile constraints (memory / backgrounding) by streaming files from disk.
    /// • Emits analytics events and propagates meaningful errors without crashing the game-loop.
    /// </summary>
    public sealed class TextureUploader : MonoBehaviour
    {
        #region Singleton

        private static TextureUploader _instance;

        /// <summary>
        /// Global access point. Throws when called before <see cref="Awake"/>.
        /// </summary>
        public static TextureUploader Instance =>
            _instance != null
                ? _instance
                : throw new InvalidOperationException(
                    $"{nameof(TextureUploader)} has not been initialized in the active Scene.");

        private void Awake()
        {
            if (_instance != null && _instance != this)
            {
                Destroy(gameObject);
                return;
            }

            _instance = this;
            DontDestroyOnLoad(gameObject);
            InitializeServices();
            LoadPersistedQueue();
        }

        #endregion

        #region Serialized Fields (tweakable from the Unity Inspector)

        [Header("Networking")]
        [Tooltip("Fully qualified HTTPS endpoint that accepts multipart/form-data texture uploads.")]
        [SerializeField] private string uploadEndpoint = "https://api.tycoonverse.com/v1/textures";

        [Tooltip("Maximum concurrent uploads allowed to avoid saturating mobile bandwidth.")]
        [Range(1, 4)]
        [SerializeField] private int maxParallelUploads = 2;

        [Tooltip("Back-off (seconds) before retrying a failed upload.")]
        [SerializeField] private float retryBackoffSeconds = 5f;

        [Header("Disk")]
        [Tooltip("Local directory name (within Application.persistentDataPath) for queued texture files.")]
        [SerializeField] private string queueDirectory = "queued_textures";

        #endregion

        #region Dependencies (injected / located)

        private IConnectivityService _connectivity;
        private IAnalyticsService _analytics;
        private ITextureRepository _repository;

        #endregion

        #region Private State

        private readonly Queue<PendingTexture> _uploadQueue = new();
        private int _currentConcurrentUploads;
        private CancellationTokenSource _cts;

        #endregion

        #region Unity Callbacks

        private void OnEnable()
        {
            _cts = new CancellationTokenSource();
            StartCoroutine(UploadSchedulerCoroutine(_cts.Token));
        }

        private void OnDisable()
        {
            _cts?.Cancel();
        }

        #endregion

        #region Public API -----------------------------------------------------------------------

        /// <summary>
        /// Queues the specified texture for upload. When connected, the file will be sent immediately;
        /// otherwise it is persisted to disk for later transmission.
        /// </summary>
        /// <param name="texture">Raw texture (RGBA32) captured from the camera.</param>
        /// <param name="sku">Optional SKU identifier that the texture is associated with.</param>
        /// <param name="playerId">Current player's user identifier.</param>
        public async Task EnqueueTextureAsync(Texture2D texture, string sku, string playerId)
        {
            if (texture == null) throw new ArgumentNullException(nameof(texture));

            // Persist to disk as PNG to minimize memory footprint.
            var pngBytes = texture.EncodeToPNG();
            var fileId = Guid.NewGuid().ToString("N");
            var filePath = GetQueuedFilePath(fileId);

            await File.WriteAllBytesAsync(filePath, pngBytes);
            var pending = new PendingTexture(fileId, filePath, sku, playerId, DateTime.UtcNow);

            _repository.Save(pending);
            _uploadQueue.Enqueue(pending);

            _analytics?.Record(EventNames.TextureQueued, new Dictionary<string, object>
            {
                { "fileId", fileId },
                { "sku", sku }
            });

            // Kick off immediate upload attempt if network is available.
            if (_connectivity.IsConnected) TriggerUploadLoop();
        }

        #endregion

        #region Upload Loop ----------------------------------------------------------------------

        private IEnumerator UploadSchedulerCoroutine(CancellationToken token)
        {
            // Primary loop that continuously checks for connectivity and dispatches uploads.
            while (!token.IsCancellationRequested)
            {
                if (_connectivity.IsConnected && _uploadQueue.Count > 0)
                {
                    while (_currentConcurrentUploads < maxParallelUploads &&
                           _uploadQueue.Count > 0)
                    {
                        var pending = _uploadQueue.Dequeue();
                        _ = UploadTextureAsync(pending, token); // Fire-and-forget
                        _currentConcurrentUploads++;
                    }
                }

                yield return new WaitForSecondsRealtime(1f);
            }
        }

        private async Task UploadTextureAsync(PendingTexture pending, CancellationToken token)
        {
            try
            {
                using var request = FormulateRequest(pending);
                var operation = request.SendWebRequest();

#if UNITY_2020_1_OR_NEWER
                while (!operation.isDone && !token.IsCancellationRequested)
#else
                while (!request.isDone && !token.IsCancellationRequested)
#endif
                {
                    await Task.Yield();
                }

                if (token.IsCancellationRequested) return;

                if (request.result == UnityWebRequest.Result.Success)
                {
                    HandleUploadSuccess(pending);
                }
                else
                {
                    HandleUploadFailure(pending, request.error);
                }
            }
            catch (Exception ex)
            {
                HandleUploadFailure(pending, ex.Message);
            }
            finally
            {
                _currentConcurrentUploads--;
            }
        }

        private UnityWebRequest FormulateRequest(PendingTexture pending)
        {
            var form = new WWWForm();
            form.AddField("playerId", pending.PlayerId);
            form.AddField("sku", pending.Sku ?? string.Empty);
            form.AddField("timestamp", pending.CreatedUtc.ToString("o"));
            form.AddBinaryData("file", File.ReadAllBytes(pending.FilePath), $"{pending.FileId}.png", "image/png");

            var request = UnityWebRequest.Post(uploadEndpoint, form);
            request.SetRequestHeader("Authorization", $"Bearer {AuthTokenProvider.Current.AccessToken}");
            request.timeout = 15; // Seconds

            return request;
        }

        private void HandleUploadSuccess(PendingTexture pending)
        {
            // Remove from repository and delete file.
            _repository.Delete(pending.FileId);
            TryDeleteQuietly(pending.FilePath);

            _analytics?.Record(EventNames.TextureUploaded, new Dictionary<string, object>
            {
                { "fileId", pending.FileId },
                { "latencyMs", (DateTime.UtcNow - pending.CreatedUtc).TotalMilliseconds }
            });
        }

        private void HandleUploadFailure(PendingTexture pending, string reason)
        {
            Debug.LogWarning($"[TextureUploader] Upload failed for {pending.FileId}: {reason}");

            _analytics?.Record(EventNames.TextureUploadFailed, new Dictionary<string, object>
            {
                { "fileId", pending.FileId },
                { "reason", reason }
            });

            // Re-queue and back-off.
            _uploadQueue.Enqueue(pending);
            StartCoroutine(BackoffCoroutine());
        }

        private IEnumerator BackoffCoroutine()
        {
            // Pause scheduling loop for a short period when we encounter failures.
            enabled = false;
            yield return new WaitForSecondsRealtime(retryBackoffSeconds);
            enabled = true;
        }

        #endregion

        #region Initialization Helpers -----------------------------------------------------------

        private void InitializeServices()
        {
            // In production, these would be wired up via a proper DI container.
            _connectivity = ServiceLocator.Resolve<IConnectivityService>();
            _analytics = ServiceLocator.Resolve<IAnalyticsService>();
            _repository = new LocalTextureRepository(Path.Combine(Application.persistentDataPath, queueDirectory));

            // Listen for connectivity changes to flush queue immediately.
            _connectivity.ConnectivityChanged += isConnected =>
            {
                if (isConnected) TriggerUploadLoop();
            };
        }

        /// <summary>
        /// Loads any previously persisted textures into the in-memory queue.
        /// </summary>
        private void LoadPersistedQueue()
        {
            foreach (var pending in _repository.LoadAll())
            {
                _uploadQueue.Enqueue(pending);
            }
        }

        private void TriggerUploadLoop()
        {
            // Ensures the scheduler coroutine is running.
            enabled = true;
        }

        #endregion

        #region Utility --------------------------------------------------------------------------

        private string GetQueuedFilePath(string fileId) =>
            Path.Combine(Application.persistentDataPath, queueDirectory, $"{fileId}.png");

        private static void TryDeleteQuietly(string filePath)
        {
            try
            {
                if (File.Exists(filePath)) File.Delete(filePath);
            }
            catch (IOException ex)
            {
                Debug.LogError($"[TextureUploader] Failed to delete {filePath}: {ex}");
            }
        }

        #endregion

        #region Nested Types ---------------------------------------------------------------------

        /// <summary>
        /// Value object representing a texture waiting to be uploaded.
        /// </summary>
        [Serializable]
        internal sealed class PendingTexture
        {
            public string FileId;
            public string FilePath;
            public string Sku;
            public string PlayerId;
            public DateTime CreatedUtc;

            public PendingTexture(string fileId, string filePath, string sku, string playerId, DateTime createdUtc)
            {
                FileId = fileId;
                FilePath = filePath;
                Sku = sku;
                PlayerId = playerId;
                CreatedUtc = createdUtc;
            }
        }

        /// <summary>
        /// Abstraction over local persistence; facilitates future replacement by cloud cache or db.
        /// </summary>
        internal interface ITextureRepository
        {
            void Save(PendingTexture pending);
            void Delete(string fileId);
            IEnumerable<PendingTexture> LoadAll();
        }

        /// <summary>
        /// Simple repository implementation that serializes metadata to JSON on disk.
        /// </summary>
        internal sealed class LocalTextureRepository : ITextureRepository
        {
            private readonly string _directory;
            private const string IndexFile = "index.json";
            private readonly Dictionary<string, PendingTexture> _index = new();

            public LocalTextureRepository(string directory)
            {
                _directory = directory;
                Directory.CreateDirectory(_directory);
                LoadIndex();
            }

            public void Save(PendingTexture pending)
            {
                _index[pending.FileId] = pending;
                PersistIndex();
            }

            public void Delete(string fileId)
            {
                if (_index.Remove(fileId)) PersistIndex();
            }

            public IEnumerable<PendingTexture> LoadAll() => _index.Values;

            private void LoadIndex()
            {
                var path = GetIndexPath();
                if (!File.Exists(path)) return;

                var json = File.ReadAllText(path, Encoding.UTF8);
                try
                {
                    var list = JsonUtility.FromJson<PendingTextureCollection>(json);
                    if (list?.Items != null)
                    {
                        foreach (var item in list.Items) _index[item.FileId] = item;
                    }
                }
                catch (Exception e)
                {
                    Debug.LogError($"[TextureRepository] Corrupted index.json. Resetting. {e}");
                    File.Delete(path);
                }
            }

            private void PersistIndex()
            {
                var container = new PendingTextureCollection { Items = new List<PendingTexture>(_index.Values) };
                var json = JsonUtility.ToJson(container, prettyPrint: false);
                File.WriteAllText(GetIndexPath(), json, Encoding.UTF8);
            }

            private string GetIndexPath() => Path.Combine(_directory, IndexFile);

            [Serializable]
            private sealed class PendingTextureCollection
            {
                public List<PendingTexture> Items;
            }
        }

        #endregion
    }

    #region Support Infrastructure (Mocks / Adapters)

    /// <summary>
    /// Resolves game-wide services at runtime. In production this would integrate with Zenject or similar.
    /// </summary>
    public static class ServiceLocator
    {
        private static readonly Dictionary<Type, object> Map = new();

        public static void Register<T>(T service) where T : class => Map[typeof(T)] = service;

        public static T Resolve<T>() where T : class =>
            Map.TryGetValue(typeof(T), out var service)
                ? (T)service
                : throw new InvalidOperationException($"Service of type {typeof(T).Name} is not registered.");
    }

    public interface IConnectivityService
    {
        bool IsConnected { get; }
        event Action<bool> ConnectivityChanged;
    }

    public interface IAnalyticsService
    {
        void Record(string eventName, IDictionary<string, object> parameters = null);
    }

    internal static class EventNames
    {
        public const string TextureQueued = "texture_queued";
        public const string TextureUploaded = "texture_uploaded";
        public const string TextureUploadFailed = "texture_upload_failed";
    }

    /// <summary>
    /// Simplified auth provider used to decorate HTTP requests.
    /// </summary>
    internal static class AuthTokenProvider
    {
        public static AuthToken Current { get; private set; } = new("anonymous");

        public static void SetToken(string token) => Current = new AuthToken(token);

        internal readonly struct AuthToken
        {
            public readonly string AccessToken;

            public AuthToken(string accessToken)
            {
                AccessToken = accessToken;
            }
        }
    }

    #endregion
}
```