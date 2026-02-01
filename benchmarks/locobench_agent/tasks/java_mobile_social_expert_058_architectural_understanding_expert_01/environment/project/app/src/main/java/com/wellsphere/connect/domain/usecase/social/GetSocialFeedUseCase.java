```java
package com.wellsphere.connect.domain.usecase.social;

import com.wellsphere.connect.domain.model.FeedItem;
import io.reactivex.rxjava3.core.Flowable;
import io.reactivex.rxjava3.core.Single;
import io.reactivex.rxjava3.core.Scheduler;
import io.reactivex.rxjava3.functions.Function;
import io.reactivex.rxjava3.schedulers.Schedulers;

import java.util.Collections;
import java.util.List;
import java.util.Objects;

/**
 * Use-case responsible for retrieving a paginated social feed for the currently
 * authenticated user.  The implementation transparently falls back to the local
 * cache whenever the device is offline or the remote call fails, ensuring the
 * caller always receives *something* to render.
 *
 * Threading:
 * ──────────
 * All heavy work is executed on {@code ioScheduler}.  The stream is observed on
 * {@code mainScheduler} so that callers (typically a ViewModel) can safely bind
 * to UI-aware observers.
 *
 * Error handling:
 * ───────────────
 * • Remote failures → cached feed + {@link Resource.Status#ERROR}
 * • No cache available → empty list + {@link Resource.Status#ERROR}
 * • Throwable never crashes the stream; it is converted into a {@link Resource}.
 */
public final class GetSocialFeedUseCase {

    private final SocialFeedRepository feedRepository;
    private final NetworkStateProvider networkStateProvider;
    private final Scheduler ioScheduler;
    private final Scheduler mainScheduler;

    public GetSocialFeedUseCase(
            SocialFeedRepository feedRepository,
            NetworkStateProvider networkStateProvider,
            Scheduler ioScheduler,
            Scheduler mainScheduler
    ) {
        this.feedRepository = Objects.requireNonNull(feedRepository);
        this.networkStateProvider = Objects.requireNonNull(networkStateProvider);
        this.ioScheduler = ioScheduler != null ? ioScheduler : Schedulers.io();
        this.mainScheduler = mainScheduler != null ? mainScheduler : Schedulers.trampoline();
    }

    /**
     * Executes the business logic and returns a cold {@link Flowable}.
     * The stream always starts with {@link Resource.Status#LOADING}.
     */
    public Flowable<Resource<List<FeedItem>>> execute(final Params params) {
        Objects.requireNonNull(params, "Params must not be null");

        return Flowable.defer(() -> {

            Single<List<FeedItem>> upstream;

            if (networkStateProvider.isNetworkAvailable()) {
                // ────────────────────────── ONLINE ──────────────────────────
                upstream = feedRepository.fetchRemoteFeed(
                                params.userId,
                                params.page,
                                params.pageSize,
                                params.filterTag
                        )
                        .flatMap(feedItems ->
                                // Persist to cache for future offline sessions
                                feedRepository
                                        .cacheFeed(params.userId, feedItems)
                                        .andThen(Single.just(feedItems))
                        )
                        .onErrorResumeNext(offlineFallback(params));
            } else {
                // ────────────────────────── OFFLINE ─────────────────────────
                upstream = feedRepository
                        .getCachedFeed(params.userId, params.page, params.pageSize)
                        .onErrorReturnItem(Collections.emptyList());
            }

            return upstream
                    .map(Resource::<List<FeedItem>>success)
                    .subscribeOn(ioScheduler)
                    .toFlowable()
                    .onErrorReturn(t -> Resource.error(t, Collections.emptyList()))
                    // caller will consume on main/UI thread
                    .observeOn(mainScheduler)
                    // Always emit LOADING first so UI can show a spinner
                    .startWithItem(Resource.loading());
        });
    }

    private Function<Throwable, Single<List<FeedItem>>> offlineFallback(final Params params) {
        return throwable ->
                feedRepository.getCachedFeed(params.userId, params.page, params.pageSize)
                        .onErrorReturnItem(Collections.emptyList());
    }

    // ─────────────────────────────────────────────────────────────────────────
    // Params
    // ─────────────────────────────────────────────────────────────────────────

    public static final class Params {
        public final String userId;
        public final int page;
        public final int pageSize;
        public final String filterTag;

        private Params(Builder builder) {
            this.userId = builder.userId;
            this.page = builder.page;
            this.pageSize = builder.pageSize;
            this.filterTag = builder.filterTag;
        }

        public static Builder builder(String userId) { return new Builder(userId); }

        public static final class Builder {
            private final String userId;
            private int page = 0;
            private int pageSize = 20;
            private String filterTag = null;

            private Builder(String userId) {
                this.userId = Objects.requireNonNull(userId);
            }

            public Builder page(int page) { this.page = page; return this; }
            public Builder pageSize(int pageSize) { this.pageSize = pageSize; return this; }
            public Builder filterTag(String filterTag) { this.filterTag = filterTag; return this; }
            public Params build() { return new Params(this); }
        }
    }

    // ─────────────────────────────────────────────────────────────────────────
    // Resource wrapper
    // ─────────────────────────────────────────────────────────────────────────

    public static final class Resource<T> {

        public enum Status { LOADING, SUCCESS, ERROR }

        public final Status status;
        public final T data;
        public final Throwable error;

        private Resource(Status status, T data, Throwable error) {
            this.status = status;
            this.data = data;
            this.error = error;
        }

        public static <T> Resource<T> loading()               { return new Resource<>(Status.LOADING, null, null); }
        public static <T> Resource<T> success(T data)         { return new Resource<>(Status.SUCCESS, data, null); }
        public static <T> Resource<T> error(Throwable err, T data) {
            return new Resource<>(Status.ERROR, data, err);
        }

        @Override public String toString() {
            return "Resource{status=" + status + ", data=" + data + ", error=" + error + '}';
        }
    }

    // ─────────────────────────────────────────────────────────────────────────
    // Dependencies — kept minimal for brevity.
    // In production these would be defined in their own files & modules.
    // ─────────────────────────────────────────────────────────────────────────

    /**
     * Repository abstraction — implemented by the data layer.
     */
    public interface SocialFeedRepository {

        /**
         * Remote source of truth.  Errors if the backend call fails.
         */
        Single<List<FeedItem>> fetchRemoteFeed(
                String userId,
                int page,
                int pageSize,
                String filterTag
        );

        /**
         * Persist a list of {@link FeedItem}s for the given user.  The returned
         * {@link io.reactivex.rxjava3.core.Completable} completes when the
         * transaction finishes.
         */
        io.reactivex.rxjava3.core.Completable cacheFeed(String userId, List<FeedItem> list);

        /**
         * Reads cached feed items.  Errors if the local store is unavailable.
         */
        Single<List<FeedItem>> getCachedFeed(String userId, int page, int pageSize);
    }

    /**
     * Provides the current connectivity status.
     */
    public interface NetworkStateProvider {
        boolean isNetworkAvailable();
    }
}
```