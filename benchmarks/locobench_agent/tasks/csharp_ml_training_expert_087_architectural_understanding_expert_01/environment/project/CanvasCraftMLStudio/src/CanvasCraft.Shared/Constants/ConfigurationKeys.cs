```csharp
// -----------------------------------------------------------------------------
// CanvasCraft ML Studio
// Copyright (c) CanvasCraft
// -----------------------------------------------------------------------------
// File:    ConfigurationKeys.cs
// Project: CanvasCraft.Shared
// Author:  CanvasCraft Engineering
// -----------------------------------------------------------------------------
// Description:
//     Strongly-typed configuration keys used throughout the CanvasCraft ML
//     Studio solution.  Centralising keys eliminates “magic strings” and
//     provides compile-time refactoring safety.
// -----------------------------------------------------------------------------

using System;
using System.Collections.Generic;
using System.Diagnostics.CodeAnalysis;
using Microsoft.Extensions.Configuration;

namespace CanvasCraft.Shared.Constants
{
    /// <summary>
    ///     A centralised registry of configuration keys designed to work with
    ///     <see cref="IConfiguration"/> and <c>appsettings*.json</c> files.
    ///     Keys follow the <c>Section:SubSection:Key</c> convention recommended
    ///     by Microsoft.Extensions.Configuration.
    /// </summary>
    [SuppressMessage("ReSharper", "MemberHidesStaticFromOuterClass")]
    public static class ConfigurationKeys
    {
        // ---------------------------------------------------------------------
        // Primary Sections
        // ---------------------------------------------------------------------

        public static class Application
        {
            public const string Name           = "Application:Name";
            public const string Environment    = "Application:Environment";
            public const string Version        = "Application:Version";
            public const string CommitSha      = "Application:CommitSha";
            public const string InstanceId     = "Application:InstanceId";
        }

        public static class Logging
        {
            public const string MinimumLevel   = "Logging:MinimumLevel";
            public const string SeqUrl         = "Logging:Seq:Url";
            public const string LogstashUrl    = "Logging:Logstash:Url";
            public const string EnableJson     = "Logging:EnableJson";
        }

        public static class ConnectionStrings
        {
            public const string SqlDb                  = "ConnectionStrings:SqlDb";
            public const string Postgres               = "ConnectionStrings:Postgres";
            public const string MongoDb                = "ConnectionStrings:MongoDb";
            public const string Redis                  = "ConnectionStrings:Redis";
            public const string FeatureStore           = "ConnectionStrings:FeatureStore";
            public const string ModelRegistry          = "ConnectionStrings:ModelRegistry";
            public const string ExperimentTrackingDb   = "ConnectionStrings:ExperimentTrackingDb";
        }

        public static class Services
        {
            public const string FeatureStoreUrl    = "Services:FeatureStore:Url";
            public const string ModelRegistryUrl   = "Services:ModelRegistry:Url";
            public const string ExperimentTracker  = "Services:ExperimentTracker:Url";
            public const string NotificationHub    = "Services:NotificationHub:Url";
        }

        public static class Auth
        {
            public const string Authority       = "Auth:Authority";
            public const string ClientId        = "Auth:ClientId";
            public const string ClientSecret    = "Auth:ClientSecret";
            public const string Audience        = "Auth:Audience";
            public const string RequireHttps    = "Auth:RequireHttps";
        }

        public static class FeatureFlags
        {
            public const string EnableRealtimeModelFeedback   = "FeatureFlags:EnableRealtimeModelFeedback";
            public const string Enable3DVisualization         = "FeatureFlags:Enable3DVisualization";
            public const string EnableAutoRetraining          = "FeatureFlags:EnableAutoRetraining";
            public const string EnableAIVoiceOver             = "FeatureFlags:EnableAIVoiceOver";
        }

        public static class MlOps
        {
            public const string PipelineWorkerConcurrency = "MlOps:PipelineWorker:Concurrency";
            public const string DefaultComputePool        = "MlOps:DefaultComputePool";
            public const string CheckpointRetentionDays   = "MlOps:CheckpointRetentionDays";

            public static class HyperParameterTuning
            {
                public const string MaxTrials      = "MlOps:HyperParameterTuning:MaxTrials";
                public const string SearchStrategy = "MlOps:HyperParameterTuning:SearchStrategy";
                public const string Metric         = "MlOps:HyperParameterTuning:Metric";
            }
        }

        // ---------------------------------------------------------------------
        // Helper Extensions
        // ---------------------------------------------------------------------

        /// <summary>
        ///     Retrieves a configuration value in a strongly-typed manner and throws
        ///     a descriptive <see cref="ConfigurationErrorsException"/> when the key
        ///     is missing or cannot be converted to the requested type.
        /// </summary>
        /// <typeparam name="T">Expected type.</typeparam>
        /// <param name="configuration">Injected <see cref="IConfiguration"/> instance.</param>
        /// <param name="key">Key as defined in <see cref="ConfigurationKeys"/>.</param>
        /// <param name="required">
        ///     If <c>true</c>, an exception is thrown when the key is missing.
        ///     If <c>false</c>, default(<typeparamref name="T"/>) is returned.
        /// </param>
        /// <exception cref="ConfigurationErrorsException">
        ///     Thrown when a required key is missing or cannot be converted.
        /// </exception>
        public static T GetValueOrThrow<T>(
            this IConfiguration configuration,
            string key,
            bool required = true)
        {
            if (configuration is null)
                throw new ArgumentNullException(nameof(configuration));

            try
            {
                var value = configuration.GetValue<T>(key);

                if (!required) return value;

                if (EqualityComparer<T>.Default.Equals(value, default!))
                    throw new ConfigurationErrorsException(
                        $"Required configuration key '{key}' is missing or empty.");

                return value;
            }
            catch (Exception ex) when (ex is InvalidCastException or FormatException)
            {
                throw new ConfigurationErrorsException(
                    $"Configuration key '{key}' could not be converted to type '{typeof(T).Name}'.", ex);
            }
        }

        /// <summary>
        ///     Safely attempt to get a configuration value.  If the key is not found
        ///     or cannot be converted, <paramref name="fallback"/> is returned.
        ///     Useful when a setting is optional and has a sane default.
        /// </summary>
        /// <typeparam name="T">Expected type.</typeparam>
        /// <param name="configuration">Injected configuration.</param>
        /// <param name="key">Configuration key to look up.</param>
        /// <param name="fallback">Default value when the key is absent or invalid.</param>
        public static T GetValueOrDefault<T>(
            this IConfiguration configuration,
            string key,
            T fallback)
        {
            if (configuration is null)
                throw new ArgumentNullException(nameof(configuration));

            try
            {
                var value = configuration.GetValue<T>(key);
                return EqualityComparer<T>.Default.Equals(value, default!)
                    ? fallback
                    : value;
            }
            catch
            {
                return fallback;
            }
        }
    }
}
```