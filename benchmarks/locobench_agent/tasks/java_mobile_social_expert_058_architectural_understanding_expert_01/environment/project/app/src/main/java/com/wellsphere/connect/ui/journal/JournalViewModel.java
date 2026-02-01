```java
package com.wellsphere.connect.ui.journal;

import android.app.Application;

import androidx.annotation.NonNull;
import androidx.lifecycle.AndroidViewModel;
import androidx.lifecycle.LiveData;
import androidx.lifecycle.MediatorLiveData;
import androidx.lifecycle.MutableLiveData;
import androidx.lifecycle.ViewModel;
import androidx.lifecycle.ViewModelProvider;

import com.wellsphere.connect.data.model.JournalEntry;
import com.wellsphere.connect.data.repository.JournalRepository;
import com.wellsphere.connect.sync.SyncManager;
import com.wellsphere.connect.util.SingleLiveEvent;

import java.util.Collections;
import java.util.List;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;

/**
 * ViewModel responsible for managing Journal related UI state.
 * <p>
 * Handles local CRUD operations, optimistic UI updates, and delegates
 * background sync to {@link SyncManager}. Exposes immutable {@link LiveData}
 * objects for the view layer to observe.
 */
public class JournalViewModel extends AndroidViewModel {

    /**
     * Represents the current loading state.
     */
    public enum UiStatus {
        IDLE,
        LOADING,
        SUCCESS,
        ERROR
    }

    private final JournalRepository journalRepository;
    private final SyncManager syncManager;

    private final MediatorLiveData<List<JournalEntry>> journalEntries = new MediatorLiveData<>();
    private final MutableLiveData<UiStatus> status = new MutableLiveData<>(UiStatus.IDLE);
    private final SingleLiveEvent<Throwable> errorEvent = new SingleLiveEvent<>();

    private final ExecutorService ioExecutor = Executors.newSingleThreadExecutor();

    public JournalViewModel(
            @NonNull Application application,
            @NonNull JournalRepository journalRepository,
            @NonNull SyncManager syncManager) {
        super(application);
        this.journalRepository = journalRepository;
        this.syncManager = syncManager;

        // Observe repository stream
        journalEntries.addSource(this.journalRepository.getAllEntries(), entries -> {
            journalEntries.setValue(entries == null ? Collections.emptyList() : entries);
            status.setValue(UiStatus.SUCCESS);
        });

        // Trigger a sync whenever connectivity is regained.
        this.syncManager.registerOnConnectivityRestoredListener(this::scheduleSync);
    }

    /* ------------------------------------------------------------------------
     * Public LiveData getters
     * --------------------------------------------------------------------- */

    /**
     * Returns immutable {@link LiveData} containing the latest journal list.
     */
    public LiveData<List<JournalEntry>> getJournalEntries() {
        return journalEntries;
    }

    /**
     * Returns loading status
     */
    public LiveData<UiStatus> getStatus() {
        return status;
    }

    /**
     * One–shot error event, consumed by the UI for toasts / dialogs.
     */
    public LiveData<Throwable> getErrorEvent() {
        return errorEvent;
    }

    /* ------------------------------------------------------------------------
     * CRUD operations
     * --------------------------------------------------------------------- */

    /**
     * Forces refresh from local cache and, if online, from the remote store.
     */
    public void refresh() {
        status.setValue(UiStatus.LOADING);
        ioExecutor.execute(() -> {
            try {
                journalRepository.refresh(); // network + db
            } catch (Exception e) {
                postError(e);
            }
        });
    }

    /**
     * Persists a new journal entry.
     *
     * @param entry Entry to be created
     */
    public void addEntry(@NonNull JournalEntry entry) {
        status.setValue(UiStatus.LOADING);
        ioExecutor.execute(() -> {
            try {
                journalRepository.insert(entry);
                scheduleSync(); // optimistic update gets synced later
            } catch (Exception e) {
                postError(e);
            }
        });
    }

    /**
     * Deletes the supplied entry.
     *
     * @param entry Entry to be removed
     */
    public void deleteEntry(@NonNull JournalEntry entry) {
        status.setValue(UiStatus.LOADING);
        ioExecutor.execute(() -> {
            try {
                journalRepository.delete(entry);
                scheduleSync();
            } catch (Exception e) {
                postError(e);
            }
        });
    }

    /**
     * Updates an existing entry. The provided entry must have a valid primary key.
     */
    public void updateEntry(@NonNull JournalEntry entry) {
        status.setValue(UiStatus.LOADING);
        ioExecutor.execute(() -> {
            try {
                journalRepository.update(entry);
                scheduleSync();
            } catch (Exception e) {
                postError(e);
            }
        });
    }

    /* ------------------------------------------------------------------------
     * Internal helpers
     * --------------------------------------------------------------------- */

    private void scheduleSync() {
        syncManager.scheduleJournalSync();
    }

    private void postError(Throwable throwable) {
        errorEvent.postValue(throwable);
        status.postValue(UiStatus.ERROR);
    }

    @Override
    protected void onCleared() {
        super.onCleared();
        ioExecutor.shutdown();
        syncManager.unregisterOnConnectivityRestoredListener(this::scheduleSync);
    }

    /* ------------------------------------------------------------------------
     * Factory (dependency injection entry-point)
     * --------------------------------------------------------------------- */

    public static class Factory implements ViewModelProvider.Factory {
        private final Application application;
        private final JournalRepository journalRepository;
        private final SyncManager syncManager;

        public Factory(@NonNull Application application,
                       @NonNull JournalRepository journalRepository,
                       @NonNull SyncManager syncManager) {
            this.application = application;
            this.journalRepository = journalRepository;
            this.syncManager = syncManager;
        }

        @NonNull
        @Override
        @SuppressWarnings("unchecked")
        public <T extends ViewModel> T create(@NonNull Class<T> modelClass) {
            if (modelClass.isAssignableFrom(JournalViewModel.class)) {
                return (T) new JournalViewModel(application, journalRepository, syncManager);
            }
            throw new IllegalArgumentException("Unknown ViewModel class: " + modelClass.getName());
        }
    }
}
```