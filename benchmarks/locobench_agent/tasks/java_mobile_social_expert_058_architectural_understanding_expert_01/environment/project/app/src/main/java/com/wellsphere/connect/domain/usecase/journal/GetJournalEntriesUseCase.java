package com.wellsphere.connect.domain.usecase.journal;

import androidx.annotation.NonNull;
import androidx.annotation.Nullable;

import com.wellsphere.connect.common.Resource;
import com.wellsphere.connect.common.SchedulerProvider;
import com.wellsphere.connect.data.network.NetworkStateManager;
import com.wellsphere.connect.data.repository.journal.JournalRepository;
import com.wellsphere.connect.domain.model.journal.JournalEntry;

import java.time.LocalDate;
import java.util.Collections;
import java.util.List;
import java.util.concurrent.TimeUnit;

import io.reactivex.rxjava3.core.Flowable;
import io.reactivex.rxjava3.core.Single;
import io.reactivex.rxjava3.disposables.CompositeDisposable;
import io.reactivex.rxjava3.processors.BehaviorProcessor;
import io.reactivex.rxjava3.schedulers.Schedulers;

/**
 * Use-case responsible for retrieving the current user’s journal entries.
 *
 * Architectural notes:
 *  • Executes on an IO thread and emits values on the UI thread via the injected {@link SchedulerProvider}.
 *  • Always attempts an offline-first read; if network connectivity is present, an immediate
 *    remote refresh is triggered, the result of which is persisted and re-emitted.
 *  • Emits a {@link Resource} stream so that the UI can react to loading / success / error states.
 *
 * Typical usage from a ViewModel:
 *
 *      getJournalEntriesUseCase.execute(
 *              Params.forCurrentUser().withDateRange(startDate, endDate)
 *      ).subscribe(resource -> { ... });
 */
public class GetJournalEntriesUseCase {

    private static final long STALE_MS = TimeUnit.MINUTES.toMillis(15);

    private final JournalRepository journalRepository;
    private final NetworkStateManager networkStateManager;
    private final SchedulerProvider schedulers;
    private final CompositeDisposable disposables = new CompositeDisposable();

    /**
     * Internal stream that replays the latest resource so that multiple view subscribers
     * share the same data & side-effects.
     */
    private final BehaviorProcessor<Resource<List<JournalEntry>>> processor =
            BehaviorProcessor.createDefault(Resource.loading(null));

    public GetJournalEntriesUseCase(@NonNull JournalRepository journalRepository,
                                    @NonNull NetworkStateManager networkStateManager,
                                    @NonNull SchedulerProvider schedulers) {
        this.journalRepository = journalRepository;
        this.networkStateManager = networkStateManager;
        this.schedulers = schedulers;
    }

    /**
     * Execute the use-case.
     *
     * The returned {@link Flowable} is cold with respect to the public API but hot internally, meaning
     * that each distinct {@link Params} creates a unique backing subscription while additional
     * subscribers receive the last cached value immediately.
     */
    public Flowable<Resource<List<JournalEntry>>> execute(@NonNull Params params) {
        // Eagerly trigger the data load & return the shared processor.
        initIfNeeded(params);
        return processor
                .observeOn(schedulers.ui())
                .distinctUntilChanged();
    }

    private synchronized void initIfNeeded(@NonNull Params params) {
        if (!processor.hasSubscribers()) {
            disposables.add(
                    loadEntries(params)
                            .subscribeOn(schedulers.io())
                            .observeOn(schedulers.io())
                            .subscribe(
                                    processor::onNext,
                                    throwable -> processor.onNext(Resource.error(throwable, Collections.emptyList()))
                            )
            );
        }
    }

    private Flowable<Resource<List<JournalEntry>>> loadEntries(@NonNull Params params) {
        return journalRepository
                .getLocalEntries(params.userId, params.startDate, params.endDate)
                .first(Collections.emptyList())
                .flatMapPublisher(localEntries -> {
                    // Emit local data immediately.
                    processor.onNext(Resource.loading(localEntries));

                    boolean shouldRefresh = shouldRefresh(localEntries);
                    boolean hasConnectivity = networkStateManager.isConnected();

                    if (shouldRefresh && hasConnectivity) {
                        // Refresh from network and re-emit the merged result.
                        return refreshRemote(params)
                                .toFlowable();
                    } else if (!shouldRefresh && !localEntries.isEmpty()) {
                        // Data is fresh; emit success.
                        return Flowable.just(Resource.success(localEntries));
                    } else if (!hasConnectivity) {
                        // No connectivity and no cache → error.
                        return Flowable.just(Resource.error(
                                new IllegalStateException("Offline and no cached data available"),
                                localEntries));
                    } else {
                        // Fallback in unlikely edge-cases.
                        return Flowable.just(Resource.success(localEntries));
                    }
                });
    }

    private boolean shouldRefresh(@NonNull List<JournalEntry> localEntries) {
        if (localEntries.isEmpty()) return true;
        long newestTimestamp = localEntries.get(0).getUpdatedAtEpochMillis();
        long ageMs = System.currentTimeMillis() - newestTimestamp;
        return ageMs > STALE_MS;
    }

    private Single<Resource<List<JournalEntry>>> refreshRemote(@NonNull Params params) {
        return journalRepository
                .syncRemoteEntries(params.userId, params.startDate, params.endDate)
                .andThen(journalRepository.getLocalEntries(params.userId, params.startDate, params.endDate)
                        .first(Collections.emptyList()))
                .map(Resource::success)
                .onErrorReturn(throwable -> Resource.error(throwable, Collections.emptyList()));
    }

    /**
     * Clear internal subscriptions.
     * Should be called from the ViewModel’s onCleared().
     */
    public void clear() {
        disposables.clear();
        processor.onComplete();
    }

    /**
     * Parameters for executing the use-case.
     */
    public static final class Params {

        private final String userId;
        @Nullable
        private final LocalDate startDate;
        @Nullable
        private final LocalDate endDate;

        private Params(@NonNull String userId,
                       @Nullable LocalDate startDate,
                       @Nullable LocalDate endDate) {
            this.userId = userId;
            this.startDate = startDate;
            this.endDate = endDate;
        }

        public static Params forCurrentUser(@NonNull String userId) {
            return new Params(userId, null, null);
        }

        public Params withDateRange(@Nullable LocalDate start, @Nullable LocalDate end) {
            return new Params(this.userId, start, end);
        }
    }
}