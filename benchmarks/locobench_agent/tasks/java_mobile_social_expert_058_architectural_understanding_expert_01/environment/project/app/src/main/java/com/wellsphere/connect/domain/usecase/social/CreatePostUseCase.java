```java
package com.wellsphere.connect.domain.usecase.social;

import java.util.Objects;
import java.util.concurrent.TimeUnit;

import io.reactivex.rxjava3.core.Single;
import io.reactivex.rxjava3.schedulers.Schedulers;

import com.wellsphere.connect.domain.analytics.AnalyticsEvent;
import com.wellsphere.connect.domain.analytics.AnalyticsTracker;
import com.wellsphere.connect.domain.logging.Logger;
import com.wellsphere.connect.domain.model.social.Post;
import com.wellsphere.connect.domain.model.social.PostDraft;
import com.wellsphere.connect.domain.repository.SocialRepository;
import com.wellsphere.connect.domain.sync.OfflineSyncCoordinator;
import com.wellsphere.connect.domain.util.NetworkStatusProvider;

/**
 * Use-case responsible for creating a {@link Post}.
 *
 * <p>
 * The class encapsulates all business rules around post creation:
 * <ul>
 *     <li>Validates the supplied {@link PostDraft}</li>
 *     <li>Makes a remote call to create the post when online</li>
 *     <li>Queues the post for offline-sync when network is unavailable</li>
 *     <li>Tracks analytics and logs errors</li>
 * </ul>
 *
 * <p>
 * This implementation is RxJava-based so that callers can compose results
 * with other asynchronous streams in a predictable, testable manner.
 */
public final class CreatePostUseCase {

    /** Current maximum post length enforced by business rules. */
    private static final int MAX_CONTENT_LENGTH = 5_000;

    /* Collaborators injected via constructor */
    private final SocialRepository socialRepository;
    private final OfflineSyncCoordinator offlineSyncCoordinator;
    private final NetworkStatusProvider networkStatusProvider;
    private final AnalyticsTracker analyticsTracker;
    private final Logger logger;

    public CreatePostUseCase(
            SocialRepository socialRepository,
            OfflineSyncCoordinator offlineSyncCoordinator,
            NetworkStatusProvider networkStatusProvider,
            AnalyticsTracker analyticsTracker,
            Logger logger
    ) {
        this.socialRepository = Objects.requireNonNull(socialRepository, "socialRepository == null");
        this.offlineSyncCoordinator = Objects.requireNonNull(offlineSyncCoordinator, "offlineSyncCoordinator == null");
        this.networkStatusProvider = Objects.requireNonNull(networkStatusProvider, "networkStatusProvider == null");
        this.analyticsTracker = Objects.requireNonNull(analyticsTracker, "analyticsTracker == null");
        this.logger = Objects.requireNonNull(logger, "logger == null");
    }

    /**
     * Attempts to create a post based on the supplied {@link PostDraft}.
     * When offline, the draft is persisted locally and scheduled for sync.
     *
     * @param draft the content the user wishes to post.
     * @return a {@link Single} that emits the resulting {@link Post}.
     */
    public Single<Post> execute(final PostDraft draft) {
        return validateDraft(draft)
                .flatMap(validDraft -> {
                    if (networkStatusProvider.isOnline()) {
                        return createRemotePost(validDraft);
                    } else {
                        return queueOfflinePost(validDraft);
                    }
                })
                .doOnSuccess(post ->
                        analyticsTracker.track(new AnalyticsEvent.PostCreated(post, networkStatusProvider.isOnline())))
                .doOnError(e -> logger.e("Failed to create post", e))
                .subscribeOn(Schedulers.io());
    }

    /* -----------------------------------------------------------------------
     *  Internal helpers
     * -------------------------------------------------------------------- */

    /**
     * Performs client-side validation. Any failure yields a {@link ValidationException}.
     */
    private Single<PostDraft> validateDraft(PostDraft draft) {
        return Single.create(emitter -> {
            if (draft == null) {
                emitter.onError(new IllegalArgumentException("Post draft must not be null"));
                return;
            }

            final String content = draft.getContent();
            if (content == null || content.trim().isEmpty()) {
                emitter.onError(new ValidationException("Post content cannot be empty"));
                return;
            }

            if (content.length() > MAX_CONTENT_LENGTH) {
                emitter.onError(new ValidationException("Post content exceeds "
                        + MAX_CONTENT_LENGTH + " characters"));
                return;
            }

            // TODO: enforce media-size limits, location bounds, profanity filter, etc.

            emitter.onSuccess(draft);
        });
    }

    /**
     * Creates the post on the backend. A timeout is applied so that UI doesn’t
     * wait indefinitely for a response. Failures are logged, then execution
     * falls back to the offline queue.
     */
    private Single<Post> createRemotePost(PostDraft draft) {
        return socialRepository
                .createPost(draft)
                .timeout(15, TimeUnit.SECONDS)
                .onErrorResumeNext(throwable -> {
                    logger.w("Remote post creation failed; switching to offline queue", throwable);
                    return queueOfflinePost(draft);
                });
    }

    /**
     * Inserts the draft in the local queue and returns a {@link Post} marked
     * as “pending sync” so that the UI can reflect its transient state.
     */
    private Single<Post> queueOfflinePost(PostDraft draft) {
        return offlineSyncCoordinator
                .queuePostForSync(draft)
                .map(queuedPost -> {
                    logger.i("Post queued for offline sync: id=" + queuedPost.getId());
                    return queuedPost;
                });
    }

    /* -----------------------------------------------------------------------
     *  Local types
     * -------------------------------------------------------------------- */

    /**
     * Exception thrown when client-side validation fails.
     */
    public static final class ValidationException extends Exception {
        public ValidationException(String message) {
            super(message);
        }
    }
}
```