```java
package com.wellsphere.connect.ui.profile;

import android.app.Application;
import android.net.Uri;

import androidx.annotation.NonNull;
import androidx.lifecycle.AndroidViewModel;
import androidx.lifecycle.LiveData;
import androidx.lifecycle.MediatorLiveData;
import androidx.lifecycle.MutableLiveData;

import com.google.firebase.crashlytics.FirebaseCrashlytics;
import com.wellsphere.connect.data.Resource;
import com.wellsphere.connect.data.Resource.Status;
import com.wellsphere.connect.data.model.UserProfile;
import com.wellsphere.connect.data.profile.ProfileRepository;
import com.wellsphere.connect.util.ConcurrentExecutorProvider;
import com.wellsphere.connect.util.livedata.Event;
import com.wellsphere.connect.util.network.NetworkStateMonitor;

import java.util.Objects;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Future;

/**
 * ProfileViewModel is responsible for orchestrating all user–profile–related
 * use-cases such as:
 *  • loading the latest profile data (local db + remote refresh)
 *  • pushing profile updates while queuing them for offline sync
 *  • uploading / updating the user avatar
 *  • emitting one-time UI events (snackbars, navigation, etc.)
 *
 * The class purposely keeps no Android Context references other than
 * Application (granted to AndroidViewModel) to remain configuration-safe.
 */
public class ProfileViewModel extends AndroidViewModel {

    // region LiveData that the UI observes
    private final MediatorLiveData<Resource<UserProfile>> profileLiveData = new MediatorLiveData<>();
    private final MutableLiveData<Event<String>> toastEvents = new MutableLiveData<>();
    // endregion

    private final ProfileRepository repository;
    private final ExecutorService ioExecutor;
    private final FirebaseCrashlytics crashlytics;
    private final NetworkStateMonitor networkStateMonitor;

    private Future<?> ongoingRemoteCall;

    public ProfileViewModel(
            @NonNull Application application,
            @NonNull ProfileRepository repository,
            @NonNull NetworkStateMonitor networkStateMonitor) {

        super(application);
        this.repository = Objects.requireNonNull(repository);
        this.networkStateMonitor = Objects.requireNonNull(networkStateMonitor);
        this.ioExecutor = ConcurrentExecutorProvider.io(); // centralized executor
        this.crashlytics = FirebaseCrashlytics.getInstance();

        // observe repository cache (Room DB) so UI updates instantly
        profileLiveData.addSource(repository.getCachedProfile(), profileLiveData::postValue);
    }

    // region Public getters exposed to the UI

    /**
     * Emits the latest profile wrapped in a {@link Resource} to convey loading &
     * error states. As a rule of thumb, UI must differentiate between the
     * following:
     *   • Resource.loading()  ➔ show progress bar
     *   • Resource.success()  ➔ render data
     *   • Resource.error()    ➔ show error UI / snack
     */
    public LiveData<Resource<UserProfile>> getProfile() {
        return profileLiveData;
    }

    /** Emits one-off toast/snackbar events */
    public LiveData<Event<String>> getToastEvents() {
        return toastEvents;
    }

    // endregion

    // region ViewModel lifecycle

    @Override
    protected void onCleared() {
        super.onCleared();
        if (ongoingRemoteCall != null && !ongoingRemoteCall.isDone()) {
            ongoingRemoteCall.cancel(true);
        }
        ioExecutor.shutdown();
    }

    // endregion

    // region Business operations

    /**
     * Fetches the profile from the server if network is available, while always
     * returning whatever is persisted in the local cache first.
     */
    public void refreshProfile() {
        // Early-exit when there is already an active remote fetch
        if (ongoingRemoteCall != null && !ongoingRemoteCall.isDone()) return;

        // 1) Immediately expose loading state so UI can show spinner
        profileLiveData.postValue(Resource.loading());

        ongoingRemoteCall = ioExecutor.submit(() -> {
            try {
                if (!networkStateMonitor.isOnline()) {
                    postError(getApplication().getString(
                            com.wellsphere.connect.R.string.err_no_connectivity));
                    return;
                }

                Resource<UserProfile> remoteResult = repository.fetchProfileRemote();
                profileLiveData.postValue(remoteResult);

                if (remoteResult.getStatus() == Status.SUCCESS && remoteResult.getData() != null) {
                    repository.cacheProfile(remoteResult.getData()); // update Room DB
                }
            } catch (Exception ex) {
                crashlytics.recordException(ex);
                postError(ex.getMessage() != null ? ex.getMessage()
                                                   : getApplication().getString(
                                                           com.wellsphere.connect.R.string.generic_error));
            }
        });
    }

    /**
     * Attempts to update the user profile. The mutation is:
     *  ⌁ written to local database immediately for optimistic UI
     *  ⌁ enqueued to a WorkManager chain for server sync (with retries)
     */
    public void updateProfile(@NonNull UserProfile updatedProfile) {
        ioExecutor.execute(() -> {
            try {
                repository.cacheProfile(updatedProfile);          // optimistic
                repository.enqueueProfileUpdate(updatedProfile);  // offline-aware

                toastEvents.postValue(new Event<>(
                        getApplication().getString(
                                com.wellsphere.connect.R.string.profile_saved_offline)));
            } catch (Exception ex) {
                crashlytics.recordException(ex);
                postError(getApplication().getString(
                        com.wellsphere.connect.R.string.profile_save_failed)));
            }
        });
    }

    /**
     * Uploads a new avatar image to the remote server. If offline, the picture
     * is queued and uploaded later. On success, the profile is re-fetched so
     * the UI receives the updated avatar URL.
     */
    public void uploadAvatar(@NonNull Uri localImageUri) {
        // expose loading state to the UI
        profileLiveData.postValue(Resource.loading());

        ioExecutor.execute(() -> {
            try {
                if (!networkStateMonitor.isOnline()) {
                    // Queue the upload for later and inform user
                    repository.enqueueAvatarUpload(localImageUri);
                    toastEvents.postValue(new Event<>(
                            getApplication().getString(
                                    com.wellsphere.connect.R.string.avatar_upload_scheduled)));
                    profileLiveData.postValue(Resource.success(null)); // remove spinner
                    return;
                }

                Resource<UserProfile> uploadResult =
                        repository.uploadAvatarSync(localImageUri);

                if (uploadResult.getStatus() == Status.SUCCESS) {
                    repository.cacheProfile(uploadResult.getData());
                    profileLiveData.postValue(uploadResult);
                } else {
                    postError(uploadResult.getMessage());
                }

            } catch (Exception ex) {
                crashlytics.recordException(ex);
                postError(getApplication().getString(
                        com.wellsphere.connect.R.string.avatar_upload_failed)));
            }
        });
    }

    // endregion

    // region Helper utilities

    private void postError(String message) {
        profileLiveData.postValue(Resource.error(message, null));
        toastEvents.postValue(new Event<>(message));
    }

    // endregion
}
```