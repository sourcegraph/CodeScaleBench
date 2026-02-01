package com.wellsphere.connect.util;

import android.app.Application;

import androidx.annotation.NonNull;
import androidx.collection.ArrayMap;
import androidx.lifecycle.ViewModel;
import androidx.lifecycle.ViewModelProvider;

import com.wellsphere.connect.BuildConfig;
import com.wellsphere.connect.domain.auth.AuthRepository;
import com.wellsphere.connect.domain.healthdata.HealthDataRepository;
import com.wellsphere.connect.domain.social.SocialRepository;
import com.wellsphere.connect.sync.SyncManager;
import com.wellsphere.connect.ui.camera.CameraCaptureViewModel;
import com.wellsphere.connect.ui.journal.JournalViewModel;
import com.wellsphere.connect.ui.login.LoginViewModel;
import com.wellsphere.connect.ui.settings.SettingsViewModel;
import com.wellsphere.connect.ui.sync.SyncViewModel;

import java.util.Map;
import java.util.Objects;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;

import timber.log.Timber;

/**
 * Centralised {@link ViewModelProvider.Factory} implementation used across the application.
 * <p>
 *     - Guarantees a single source of truth for ViewModel construction<br>
 *     - Wires up all mandatory dependencies dedicated to each ViewModel<br>
 *     - Falls back to a robust error–handling path that never returns null<br>
 * </p>
 *
 * NOTE:
 * We intentionally keep reflection and generics to a minimum to simplify debugging
 * in a regulated healthcare environment (FDA 21 CFR Part 11).
 */
public final class ViewModelFactory implements ViewModelProvider.Factory {

    private static volatile ViewModelFactory instance;

    private final Application application;

    /* Domain-layer dependencies */
    private final AuthRepository authRepository;
    private final HealthDataRepository healthDataRepository;
    private final SocialRepository socialRepository;
    private final SyncManager syncManager;

    /* Infrastructure */
    private final ExecutorService ioExecutor;

    /* Cache to re-use already created ViewModels if Android reuses the Factory */
    private final Map<String, ViewModel> cache = new ArrayMap<>();

    /**
     * Obtain the singleton instance. Thread-safe & lazy-initialised.
     */
    public static ViewModelFactory getInstance(@NonNull Application application,
                                               @NonNull AuthRepository authRepository,
                                               @NonNull HealthDataRepository healthDataRepository,
                                               @NonNull SocialRepository socialRepository,
                                               @NonNull SyncManager syncManager) {

        if (instance == null) {
            synchronized (ViewModelFactory.class) {
                if (instance == null) {
                    instance = new ViewModelFactory(application,
                                                    authRepository,
                                                    healthDataRepository,
                                                    socialRepository,
                                                    syncManager);
                }
            }
        }
        return instance;
    }

    private ViewModelFactory(@NonNull Application application,
                             @NonNull AuthRepository authRepository,
                             @NonNull HealthDataRepository healthDataRepository,
                             @NonNull SocialRepository socialRepository,
                             @NonNull SyncManager syncManager) {

        this.application              = Objects.requireNonNull(application);
        this.authRepository           = Objects.requireNonNull(authRepository);
        this.healthDataRepository     = Objects.requireNonNull(healthDataRepository);
        this.socialRepository         = Objects.requireNonNull(socialRepository);
        this.syncManager              = Objects.requireNonNull(syncManager);

        /*
         * A dedicated IO executor ensures long-running DB / network work never blocks the Main thread.
         * For production we tune the thread-pool based on device capabilities.
         */
        ioExecutor = Executors.newFixedThreadPool(
                Runtime.getRuntime().availableProcessors() <= 2 ? 2 : 4
        );
    }

    @SuppressWarnings("unchecked")
    @NonNull
    @Override
    public <T extends ViewModel> T create(@NonNull Class<T> modelClass) {
        final String key = modelClass.getCanonicalName();
        if (key == null) {
            throw new IllegalArgumentException("Anonymous ViewModel classes are not supported");
        }

        /*
         * Fast path – return cached instance when available.
         */
        if (cache.containsKey(key)) {
            try {
                return (T) cache.get(key);
            } catch (ClassCastException e) {
                // Edge-case: underlying key collision with different ViewModel signature
                Timber.tag("ViewModelFactory")
                      .e(e, "ViewModel cache mismatch for %s", key);
                cache.remove(key);
            }
        }

        final T viewModel;

        /*
         * Manual wiring of dependencies keeps compile-time safety vs reflection-based factories.
         * Each new UI screen must be registered here.
         */
        if (modelClass.isAssignableFrom(LoginViewModel.class)) {
            viewModel = (T) new LoginViewModel(application,
                                               authRepository,
                                               ioExecutor);
        } else if (modelClass.isAssignableFrom(JournalViewModel.class)) {
            viewModel = (T) new JournalViewModel(application,
                                                 healthDataRepository,
                                                 socialRepository,
                                                 ioExecutor);
        } else if (modelClass.isAssignableFrom(SyncViewModel.class)) {
            viewModel = (T) new SyncViewModel(application,
                                              syncManager);
        } else if (modelClass.isAssignableFrom(CameraCaptureViewModel.class)) {
            viewModel = (T) new CameraCaptureViewModel(application,
                                                       healthDataRepository,
                                                       ioExecutor);
        } else if (modelClass.isAssignableFrom(SettingsViewModel.class)) {
            viewModel = (T) new SettingsViewModel(application,
                                                  authRepository,
                                                  socialRepository);
        } else {
            // Developer error – we forgot to add a mapping for the ViewModel in question.
            final String msg = "Unknown ViewModel class: " + modelClass.getSimpleName();
            Timber.tag("ViewModelFactory").wtf(msg);
            throw new IllegalArgumentException(msg);
        }

        /*
         * For configuration-change resilience we keep reference until Process death.
         * Life-cycle will be handled by ViewModelStoreOwner (Activity / Fragment).
         */
        cache.put(key, viewModel);

        if (BuildConfig.DEBUG) {
            Timber.tag("ViewModelFactory")
                  .d("Created ViewModel: %s (hash: %s)", key, Integer.toHexString(viewModel.hashCode()));
        }
        return viewModel;
    }

    /**
     * Clear the cached instances. Currently invoked on explicit user logout
     * or when an unrecoverable fatal error occurs which forces a cold start.
     */
    public void clearCache() {
        for (ViewModel vm : cache.values()) {
            vm.onCleared();
        }
        cache.clear();
    }
}