```java
/*
 *  WellSphere Connect
 *  --------------------------------------------
 *  File: FeedViewModel.java
 *  Description: ViewModel that backs the social feed screen. Handles
 *  pagination, pull-to-refresh, optimistic updates, offline/online sync,
 *  and error propagation with HIPAA-grade safety checks.
 *
 *  Copyright (c) 2024
 *  WellSphere Health Inc. – All rights reserved.
 */

package com.wellsphere.connect.ui.feed;

import android.app.Application;

import androidx.annotation.MainThread;
import androidx.annotation.NonNull;
import androidx.lifecycle.AndroidViewModel;
import androidx.lifecycle.LiveData;
import androidx.lifecycle.MutableLiveData;
import androidx.lifecycle.Transformations;
import androidx.paging.Config;
import androidx.paging.LivePagedListBuilder;
import androidx.paging.PagedList;

import com.wellsphere.connect.data.feed.FeedItem;
import com.wellsphere.connect.data.feed.FeedRepository;
import com.wellsphere.connect.data.feed.datasource.FeedDataSource;
import com.wellsphere.connect.data.feed.datasource.FeedDataSourceFactory;
import com.wellsphere.connect.util.NetworkState;
import com.wellsphere.connect.util.SingleLiveEvent;

import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;

/**
 * FeedViewModel orchestrates data for the social feed screen following MVVM
 * and Android Architecture Components best practices. All heavy lifting is
 * encapsulated in the {@link FeedRepository}; the ViewModel merely composes
 * and exposes reactive streams to the UI layer.
 *
 * Thread-safety: read/write guarded by Architecture Components; additional
 * background work dispatched on a single-thread I/O executor to guarantee
 * ordering—important for conflict-free EHR merges.
 */
public final class FeedViewModel extends AndroidViewModel {

    /* --------------------------------- *
     * Dependencies / Executors
     * --------------------------------- */
    private final FeedRepository repository;
    private final ExecutorService ioExecutor;

    /* --------------------------------- *
     * Paging & LiveData
     * --------------------------------- */
    private final LiveData<PagedList<FeedItem>> feedPagedList;
    private final LiveData<NetworkState> networkState;
    private final LiveData<NetworkState> refreshState;

    /* --------------------------------- *
     * One-off UI events
     * --------------------------------- */
    private final SingleLiveEvent<String> toastEvent = new SingleLiveEvent<>();

    /* --------------------------------- *
     * Constructor
     * --------------------------------- */
    public FeedViewModel(
            @NonNull Application app,
            @NonNull FeedRepository repository
    ) {
        super(app);
        this.repository = repository;
        this.ioExecutor = Executors.newSingleThreadExecutor();

        // DataSource factory handles token refresh, offline cache, etc.
        FeedDataSourceFactory factory = repository.createDataSourceFactory(ioExecutor);

        // Build paged list configuration
        Config pagedListConfig = (new Config.Builder())
                .setEnablePlaceholders(false)
                .setPageSize(FeedRepository.PAGE_SIZE)
                .setPrefetchDistance(FeedRepository.PAGE_SIZE / 2)
                .setInitialLoadSizeHint(FeedRepository.PAGE_SIZE * 2)
                .build();

        feedPagedList = new LivePagedListBuilder<>(factory, pagedListConfig)
                .setFetchExecutor(ioExecutor) // fetch on I/O executor
                .build();

        // Map network states from DataSource
        networkState = Transformations.switchMap(factory.getSourceLiveData(), FeedDataSource::getNetworkState);
        refreshState = Transformations.switchMap(factory.getSourceLiveData(), FeedDataSource::getInitialLoad);

        // Observe unrecoverable auth errors centrally
        observeAuthFailures(factory);
    }

    /* --------------------------------------------------------------------- */
    /* Public API exposed to the View (Activity / Fragment)                  */
    /* --------------------------------------------------------------------- */

    /** Stream of paged feed items. */
    public LiveData<PagedList<FeedItem>> getFeed() {
        return feedPagedList;
    }

    /** Async state for endless scroll progress bar in the footer. */
    public LiveData<NetworkState> getNetworkState() {
        return networkState;
    }

    /** Async state for pull-to-refresh UI. */
    public LiveData<NetworkState> getRefreshState() {
        return refreshState;
    }

    /** One-off snack/toast messages. */
    public LiveData<String> getToastEvent() {
        return toastEvent;
    }

    /**
     * Retry the last failed operation (pagination or initial load).
     * Safe to call from configuration-changed UI.
     */
    @MainThread
    public void retry() {
        repository.retryLastFailedRequest();
    }

    /**
     * Force refresh: clears memory cache, triggers sync with local DB
     * and remote API. Used by pull-to-refresh.
     */
    @MainThread
    public void refresh() {
        // Post to executor to avoid blocking main thread
        ioExecutor.execute(repository::refresh);
    }

    /**
     * Optimistic post of a new {@link FeedItem}. Item is displayed immediately
     * and reconciled with the backend. Failures are surfaced via {@link #toastEvent}.
     */
    @MainThread
    public void createPost(@NonNull final FeedItem draft) {
        ioExecutor.execute(() -> {
            try {
                repository.submitPost(draft);
            } catch (Exception ex) {
                toastEvent.postValue("Unable to post: " + ex.getMessage());
            }
        });
    }

    /**
     * Biometric logout action clears caches while leaving encrypted
     * SharedPreferences intact (for future logins).
     */
    @MainThread
    public void performLogout() {
        ioExecutor.execute(() -> {
            repository.clearAllCaches();
            toastEvent.postValue("Signed out securely.");
        });
    }

    /* --------------------------------- *
     *  Clean-up
     * --------------------------------- */
    @Override
    protected void onCleared() {
        super.onCleared();
        ioExecutor.shutdownNow();
    }

    /* --------------------------------------------------------------------- */
    /* Internal helpers                                                      */
    /* --------------------------------------------------------------------- */

    /**
     * Observes fatal authentication failures from any DataSource and issues a
     * one-shot logout directive. Having a centralized ‘panic switch’ is
     * crucial in regulated environments where token misuse must trigger
     * immediate session termination.
     */
    private void observeAuthFailures(@NonNull FeedDataSourceFactory factory) {
        LiveData<Boolean> authFailure = Transformations.switchMap(
                factory.getSourceLiveData(),
                FeedDataSource::getAuthFailure
        );

        authFailure.observeForever(isFailed -> {
            if (Boolean.TRUE.equals(isFailed)) {
                performLogout();
            }
        });
    }
}
```