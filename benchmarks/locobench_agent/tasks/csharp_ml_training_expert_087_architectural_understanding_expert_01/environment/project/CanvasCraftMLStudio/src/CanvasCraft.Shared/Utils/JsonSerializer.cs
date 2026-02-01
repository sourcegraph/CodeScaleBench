using System;
using System.IO;
using System.Threading;
using System.Threading.Tasks;
using Newtonsoft.Json;
using Newtonsoft.Json.Converters;
using Newtonsoft.Json.Linq;
using Newtonsoft.Json.Serialization;

namespace CanvasCraft.Shared.Utils
{
    /// <summary>
    /// Centralized, opinionated JSON serializer for CanvasCraft ML Studio.
    /// Wraps Newtonsoft.Json to provide consistent configuration, convenience helpers,
    /// and robust error handling throughout the solution.
    /// </summary>
    public static class JsonSerializer
    {
        /// <summary>
        /// The canonical JsonSerializerSettings used everywhere in the application.
        /// </summary>
        public static readonly JsonSerializerSettings DefaultSettings = CreateDefaultSettings();

        #region Public Convenience API

        /// <summary>
        /// Serializes a CLR object into a JSON string.
        /// </summary>
        /// <param name="value">Object to serialize.</param>
        /// <param name="indented">True for pretty-print, false for compact.</param>
        /// <param name="settings">Optional settings; falls back to <see cref="DefaultSettings"/>.</param>
        public static string Serialize(
            object? value,
            bool indented = false,
            JsonSerializerSettings? settings = null)
        {
            settings ??= DefaultSettings;

            var formatting = indented ? Formatting.Indented : settings.Formatting;

            try
            {
                return Newtonsoft.Json.JsonConvert.SerializeObject(value, formatting, settings);
            }
            catch (JsonException ex)
            {
                throw new JsonSerializationException(
                    "Failed to serialize object to JSON.",
                    ex);
            }
        }

        /// <summary>
        /// Deserializes a JSON string into the specified type.
        /// </summary>
        /// <typeparam name="T">Destination type.</typeparam>
        /// <param name="json">JSON payload.</param>
        /// <param name="settings">Optional settings; falls back to <see cref="DefaultSettings"/>.</param>
        public static T? Deserialize<T>(
            string json,
            JsonSerializerSettings? settings = null)
        {
            settings ??= DefaultSettings;

            try
            {
                return Newtonsoft.Json.JsonConvert.DeserializeObject<T>(json, settings);
            }
            catch (JsonException ex)
            {
                throw new JsonSerializationException(
                    $"Failed to deserialize JSON into {typeof(T).Name}.",
                    ex);
            }
        }

        /// <summary>
        /// Serializes an object and writes it to disk atomically.
        /// </summary>
        /// <param name="value">Object to serialize.</param>
        /// <param name="filePath">Destination path.</param>
        /// <param name="indented">Pretty-print output.</param>
        /// <param name="cancellationToken">Cancellation token.</param>
        /// <param name="settings">Optional JsonSerializerSettings.</param>
        public static async Task SerializeToFileAsync(
            object? value,
            string filePath,
            bool indented = false,
            CancellationToken cancellationToken = default,
            JsonSerializerSettings? settings = null)
        {
            cancellationToken.ThrowIfCancellationRequested();

            var json = Serialize(value, indented, settings);

            Directory.CreateDirectory(Path.GetDirectoryName(filePath)!);

            var tempPath = $"{filePath}.{Guid.NewGuid():N}.tmp";

            try
            {
                await File.WriteAllTextAsync(tempPath, json, cancellationToken).ConfigureAwait(false);

                // Replace ensures that a partially written file is never observed.
                File.Replace(tempPath, filePath, null);
            }
            catch
            {
                SafeDelete(tempPath);
                throw;
            }
        }

        /// <summary>
        /// Reads JSON from disk and deserializes it into the requested type.
        /// </summary>
        public static async Task<T?> DeserializeFromFileAsync<T>(
            string filePath,
            CancellationToken cancellationToken = default,
            JsonSerializerSettings? settings = null)
        {
            if (!File.Exists(filePath))
            {
                throw new FileNotFoundException("Could not locate JSON file.", filePath);
            }

            cancellationToken.ThrowIfCancellationRequested();

            try
            {
                var json = await File.ReadAllTextAsync(filePath, cancellationToken).ConfigureAwait(false);
                return Deserialize<T>(json, settings);
            }
            catch (JsonException ex)
            {
                throw new JsonSerializationException(
                    $"Failed to deserialize JSON file '{filePath}' into {typeof(T).Name}.",
                    ex);
            }
        }

        /// <summary>
        /// Attempts to parse the supplied JSON and returns <c>true</c> if it is valid.
        /// </summary>
        public static bool TryValidate(string json, out string? errorMessage)
        {
            try
            {
                _ = JToken.Parse(json);
                errorMessage = null;
                return true;
            }
            catch (JsonReaderException ex)
            {
                errorMessage = ex.Message;
                return false;
            }
        }

        /// <summary>
        /// Formats raw JSON into a human-readable, indented representation.
        /// </summary>
        public static string Format(string json)
        {
            try
            {
                var token = JToken.Parse(json);
                return token.ToString(Formatting.Indented);
            }
            catch (JsonReaderException ex)
            {
                throw new JsonSerializationException(
                    "Input is not valid JSON.",
                    ex);
            }
        }

        /// <summary>
        /// Performs a deep clone of the supplied object by round-tripping through JSON.
        /// </summary>
        public static T? DeepClone<T>(T source)
        {
            if (ReferenceEquals(source, null))
            {
                return default;
            }

            var json = Serialize(source);
            return Deserialize<T>(json);
        }

        /// <summary>
        /// Converts an arbitrary CLR object into a <see cref="JToken"/> using default settings.
        /// </summary>
        public static JToken? ToJToken(object? value)
        {
            if (value is null) return null;

            var serializer = Newtonsoft.Json.JsonSerializer.Create(DefaultSettings);
            return JToken.FromObject(value, serializer);
        }

        #endregion

        #region Internal Helpers

        private static JsonSerializerSettings CreateDefaultSettings()
        {
            var settings = new JsonSerializerSettings
            {
                NullValueHandling        = NullValueHandling.Ignore,
                MissingMemberHandling    = MissingMemberHandling.Ignore,
                DateParseHandling        = DateParseHandling.DateTimeOffset,
                Formatting               = Formatting.None,
                ContractResolver         = new CamelCasePropertyNamesContractResolver(),
            };

            settings.Converters.Add(new StringEnumConverter());

            return settings;
        }

        private static void SafeDelete(string path)
        {
            try
            {
                if (File.Exists(path))
                {
                    File.Delete(path);
                }
            }
            catch
            {
                // Swallow exceptions—best-effort cleanup.
            }
        }

        #endregion
    }
}