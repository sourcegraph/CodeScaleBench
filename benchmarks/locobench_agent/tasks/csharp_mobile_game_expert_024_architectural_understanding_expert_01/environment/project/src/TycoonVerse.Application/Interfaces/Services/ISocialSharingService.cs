using System;
using System.Collections.Generic;
using System.Threading;
using System.Threading.Tasks;

namespace TycoonVerse.Application.Interfaces.Services
{
    /// <summary>
    /// Enumeration of the social-media platforms officially supported by TycoonVerse.
    /// New values may be appended as additional platform adapters are introduced.
    /// </summary>
    public enum SocialPlatform
    {
        Facebook,
        Twitter,
        Instagram,
        LinkedIn,
        TikTok,
        Snapchat,
        /// <summary>
        /// Catch-all for user-defined or unsupported destinations.
        /// </summary>
        Unknown
    }

    #region Request/Response Contracts

    /// <summary>
    /// Base contract for all shareable payloads.  Concrete requests derive from this
    /// type to guarantee a consistent auditing surface (PlayerId, Timestamp, etc.).
    /// </summary>
    public abstract record SocialShareRequest
    {
        protected SocialShareRequest(Guid playerId, IReadOnlyCollection<SocialPlatform> targetPlatforms)
        {
            PlayerId         = playerId;
            TargetPlatforms  = targetPlatforms ?? Array.Empty<SocialPlatform>();
            RequestUtc       = DateTime.UtcNow;
        }

        /// <summary>The unique identifier of the player initiating the share.</summary>
        public Guid PlayerId { get; }

        /// <summary>
        /// The platforms selected by the player.  The service implementation resolves the
        /// appropriate adapter(s) at runtime based on these values.
        /// </summary>
        public IReadOnlyCollection<SocialPlatform> TargetPlatforms { get; }

        /// <summary>Timestamp (UTC) captured client-side at request creation.</summary>
        public DateTime RequestUtc { get; }
    }

    public record AchievementShareRequest(
        Guid PlayerId,
        string AchievementId,
        string AchievementName,
        int Score,
        IReadOnlyCollection<SocialPlatform> TargetPlatforms
    ) : SocialShareRequest(PlayerId, TargetPlatforms);

    public record CompanyMilestoneShareRequest(
        Guid CompanyId,
        string CompanyName,
        string MilestoneName,
        decimal RevenueImpact,
        Guid PlayerId,
        IReadOnlyCollection<SocialPlatform> TargetPlatforms
    ) : SocialShareRequest(PlayerId, TargetPlatforms);

    public record ScreenshotShareRequest(
        Guid PlayerId,
        byte[] ImageData,
        string Caption,
        IReadOnlyCollection<SocialPlatform> TargetPlatforms
    ) : SocialShareRequest(PlayerId, TargetPlatforms);

    public record IPOAnnouncementRequest(
        Guid CompanyId,
        string Symbol,
        decimal OfferPrice,
        DateTime OfferDateUtc,
        Guid PlayerId,
        IReadOnlyCollection<SocialPlatform> TargetPlatforms
    ) : SocialShareRequest(PlayerId, TargetPlatforms);

    public record RichMediaShareRequest(
        Guid PlayerId,
        Uri MediaUri,
        string Title,
        string Description,
        IReadOnlyCollection<SocialPlatform> TargetPlatforms
    ) : SocialShareRequest(PlayerId, TargetPlatforms);

    /// <summary>
    /// Aggregated outcome of a share attempt, providing per-platform status messages.
    /// </summary>
    /// <param name="Success">True when all targeted platforms acknowledge success.</param>
    /// <param name="PlatformResponses">
    /// Key = Platform, Value = Service-specific response or error message.
    /// </param>
    public record ShareResult(
        bool Success,
        IReadOnlyDictionary<SocialPlatform, string> PlatformResponses
    );

    #endregion

    #region Event Args / Exceptions

    /// <summary>
    /// Raised whenever an asynchronous share workflow completes—successfully
    /// or otherwise.  Consumers (analytics layer, achievement system) subscribe
    /// to react to player-driven virality without coupling to concrete adapters.
    /// </summary>
    public sealed class ShareCompletedEventArgs : EventArgs
    {
        public ShareCompletedEventArgs(ShareResult result) =>
            Result = result ?? throw new ArgumentNullException(nameof(result));

        public ShareResult Result { get; }
    }

    /// <summary>
    /// Exception thrown when a specific platform adapter fails irrecoverably.
    /// </summary>
    public sealed class SocialPlatformIntegrationException : Exception
    {
        public SocialPlatformIntegrationException(
            SocialPlatform platform,
            string message,
            Exception? inner = null) : base(message, inner) =>
            Platform = platform;

        public SocialPlatform Platform { get; }
    }

    #endregion

    /// <summary>
    /// Application-layer abstraction responsible for propagating in-game events
    /// (achievements, IPO announcements, screenshots, etc.) to external social
    /// networks.  Concrete implementations are composed via the Adapter pattern
    /// and registered in DI to respect platform capabilities (e.g., iOS share
    /// sheet vs. Android intents).
    ///
    /// This interface deliberately avoids UI concerns; view-models call into
    /// these methods and react to the resulting <see cref="ShareCompleted"/>
    /// event or returned <see cref="ShareResult"/>.
    /// </summary>
    public interface ISocialSharingService
    {
        /// <summary>
        /// Publishes a player achievement to external social-media channels.
        /// </summary>
        /// <exception cref="ArgumentNullException">
        /// Thrown when <paramref name="achievement"/> is <c>null</c>.
        /// </exception>
        Task ShareAchievementAsync(
            AchievementShareRequest achievement,
            CancellationToken cancellationToken = default);

        /// <summary>
        /// Shares a high-profile company milestone (e.g., revenue threshold, ESG award).
        /// </summary>
        Task ShareCompanyMilestoneAsync(
            CompanyMilestoneShareRequest milestone,
            CancellationToken cancellationToken = default);

        /// <summary>
        /// Shares a user-captured screenshot, including the in-game watermark and
        /// optional caption supplied by the player.
        /// </summary>
        Task ShareCustomScreenshotAsync(
            ScreenshotShareRequest screenshot,
            CancellationToken cancellationToken = default);

        /// <summary>
        /// Broadcasts an IPO filing to social media, returning once all selected
        /// platforms have acknowledged or errored.
        /// </summary>
        Task PublishIPOAnnouncementAsync(
            IPOAnnouncementRequest ipoAnnouncement,
            CancellationToken cancellationToken = default);

        /// <summary>
        /// Generic mechanism for posting arbitrary rich media (videos, GIFs, 3-D
        /// model teasers, etc.).  Prefer the more specific overloads when possible.
        /// </summary>
        Task<ShareResult> ShareRichMediaAsync(
            RichMediaShareRequest request,
            CancellationToken cancellationToken = default);

        /// <summary>
        /// Event fired when a share workflow completes.  Always executes on a
        /// background thread; subscribers should marshal to the UI context if needed.
        /// </summary>
        event EventHandler<ShareCompletedEventArgs>? ShareCompleted;
    }
}