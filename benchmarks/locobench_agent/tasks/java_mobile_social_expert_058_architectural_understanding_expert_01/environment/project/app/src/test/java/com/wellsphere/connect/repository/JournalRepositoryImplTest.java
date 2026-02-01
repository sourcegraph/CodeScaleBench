package com.wellsphere.connect.repository;

import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.anyString;
import static org.mockito.Mockito.*;

import com.wellsphere.connect.data.local.JournalDao;
import com.wellsphere.connect.data.model.JournalEntry;
import com.wellsphere.connect.data.remote.JournalApiService;
import com.wellsphere.connect.util.NetworkStateProvider;
import io.reactivex.rxjava3.core.Completable;
import io.reactivex.rxjava3.core.Single;
import io.reactivex.rxjava3.observers.TestObserver;
import io.reactivex.rxjava3.schedulers.Schedulers;
import java.time.LocalDateTime;
import java.util.Arrays;
import java.util.List;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Nested;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.extension.ExtendWith;
import org.mockito.InjectMocks;
import org.mockito.Mock;
import org.mockito.junit.jupiter.MockitoExtension;

/**
 * Unit tests for {@link JournalRepositoryImpl}.
 * <p>
 * The repository orchestrates reads/writes between a local database and the remote
 * API service, taking current connectivity into account.  Because RxJava is used
 * throughout the data layer, tests rely on synchronous Trampoline schedulers to
 * make operations deterministic.
 */
@ExtendWith(MockitoExtension.class)
class JournalRepositoryImplTest {

    private static final String USER_ID = "patient-123";

    @Mock
    private JournalDao journalDao;

    @Mock
    private JournalApiService journalApiService;

    @Mock
    private NetworkStateProvider networkStateProvider;

    @InjectMocks
    private JournalRepositoryImpl repository;

    private JournalEntry localEntry1;
    private JournalEntry localEntry2;
    private JournalEntry unsyncedEntry1;
    private JournalEntry unsyncedEntry2;
    private JournalEntry remoteEntryWithServerId;

    @BeforeEach
    void setUp() {
        // Force RxJava to run synchronously for unit testing.
        repository = new JournalRepositoryImpl(
                journalDao,
                journalApiService,
                networkStateProvider,
                Schedulers.trampoline(),
                Schedulers.trampoline());

        // Pre-build reusable test fixtures.
        localEntry1 = new JournalEntry(
                "l-1",
                USER_ID,
                "Day 1 – felt dizzy.",
                LocalDateTime.now().minusDays(1),
                true);

        localEntry2 = new JournalEntry(
                "l-2",
                USER_ID,
                "Day 2 – no symptoms.",
                LocalDateTime.now(),
                true);

        unsyncedEntry1 = new JournalEntry(
                "u-1",
                USER_ID,
                "Unsynced 1",
                LocalDateTime.now().minusHours(3),
                false);

        unsyncedEntry2 = new JournalEntry(
                "u-2",
                USER_ID,
                "Unsynced 2",
                LocalDateTime.now().minusHours(1),
                false);

        remoteEntryWithServerId = new JournalEntry(
                "srv-77",
                USER_ID,
                "Remote copy",
                LocalDateTime.now(),
                true);
    }

    @Nested
    @DisplayName("getJournalEntries")
    class GetJournalEntries {

        @Test
        @DisplayName("when offline returns cached data from local database only")
        void getEntries_offline_returnsLocalData() {
            // GIVEN
            when(networkStateProvider.isOnline()).thenReturn(false);
            when(journalDao.getEntries(USER_ID)).thenReturn(Single.just(Arrays.asList(localEntry1, localEntry2)));

            // WHEN
            TestObserver<List<JournalEntry>> testObserver = repository.getJournalEntries(USER_ID).test();

            // THEN
            testObserver
                    .assertComplete()
                    .assertValue(entries -> entries.size() == 2
                            && entries.containsAll(Arrays.asList(localEntry1, localEntry2)));

            verify(journalDao).getEntries(USER_ID);
            verifyNoMoreInteractions(journalApiService); // Remote service must never be hit.
        }

        @Test
        @DisplayName("when online merges remote and local results")
        void getEntries_online_mergesLocalAndRemoteData() {
            // GIVEN
            List<JournalEntry> remoteList = Arrays.asList(
                    new JournalEntry("srv-11", USER_ID, "Server entry A", LocalDateTime.now().minusDays(4), true),
                    new JournalEntry("srv-12", USER_ID, "Server entry B", LocalDateTime.now().minusDays(2), true)
            );

            when(networkStateProvider.isOnline()).thenReturn(true);
            when(journalDao.getEntries(USER_ID)).thenReturn(Single.just(Arrays.asList(localEntry1)));
            when(journalApiService.getJournalEntries(USER_ID)).thenReturn(Single.just(remoteList));
            when(journalDao.insertAll(remoteList)).thenReturn(Completable.complete());

            // WHEN
            TestObserver<List<JournalEntry>> testObserver = repository.getJournalEntries(USER_ID).test();

            // THEN
            testObserver.assertComplete()
                        .assertValue(entries -> entries.size() == 3);

            verify(journalApiService).getJournalEntries(USER_ID);
            verify(journalDao).insertAll(remoteList);
        }
    }

    @Nested
    @DisplayName("addJournalEntry")
    class AddJournalEntry {

        @Test
        @DisplayName("when online persists to remote API and local DB")
        void addEntry_online_persistsRemoteAndLocal() {
            // GIVEN
            when(networkStateProvider.isOnline()).thenReturn(true);
            when(journalApiService.postJournalEntry(localEntry1)).thenReturn(Single.just(remoteEntryWithServerId));
            when(journalDao.insert(remoteEntryWithServerId)).thenReturn(Completable.complete());

            // WHEN
            TestObserver<Void> testObserver = repository.addJournalEntry(localEntry1).test();

            // THEN
            testObserver.assertComplete();
            verify(journalApiService).postJournalEntry(localEntry1);
            verify(journalDao).insert(remoteEntryWithServerId);
        }

        @Test
        @DisplayName("when offline only stores entry locally as unsynced")
        void addEntry_offline_persistsLocallyOnly() {
            // GIVEN
            when(networkStateProvider.isOnline()).thenReturn(false);
            when(journalDao.insert(unsyncedEntry1)).thenReturn(Completable.complete());

            // WHEN
            TestObserver<Void> testObserver = repository.addJournalEntry(unsyncedEntry1).test();

            // THEN
            testObserver.assertComplete();
            verifyNoInteractions(journalApiService);
            verify(journalDao).insert(unsyncedEntry1);
        }
    }

    @Nested
    @DisplayName("syncPendingEntries")
    class SyncPendingEntries {

        @Test
        @DisplayName("uploads all unsynced entries and marks them synced")
        void syncPendingEntries_uploadsAndMarksSynced() {
            // GIVEN
            when(networkStateProvider.isOnline()).thenReturn(true);
            when(journalDao.getUnsyncedEntries()).thenReturn(Single.just(Arrays.asList(unsyncedEntry1, unsyncedEntry2)));

            // For each unsynced entry, emulate a successful server-side copy with a server ID.
            when(journalApiService.postJournalEntry(any()))
                    .thenReturn(Single.just(remoteEntryWithServerId));

            when(journalDao.markEntrySynced(anyString())).thenReturn(Completable.complete());

            // WHEN
            TestObserver<Void> testObserver = repository.syncPendingEntries().test();

            // THEN
            testObserver.assertComplete();
            verify(journalApiService, times(2)).postJournalEntry(any());
            verify(journalDao, times(2)).markEntrySynced(anyString());
        }

        @Test
        @DisplayName("gracefully no-ops when offline")
        void syncPendingEntries_offline_noOp() {
            // GIVEN
            when(networkStateProvider.isOnline()).thenReturn(false);

            // WHEN
            TestObserver<Void> testObserver = repository.syncPendingEntries().test();

            // THEN
            testObserver.assertComplete();
            verifyNoInteractions(journalApiService, journalDao);
        }
    }
}