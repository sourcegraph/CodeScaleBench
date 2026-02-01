package com.wellsphere.connect.core.di;

import android.app.Application;

import androidx.annotation.NonNull;
import androidx.annotation.Nullable;

import com.wellsphere.connect.ConnectApplication;
import com.wellsphere.connect.core.analytics.CrashReporter;
import com.wellsphere.connect.core.auth.SessionManager;
import com.wellsphere.connect.core.config.AppConfig;
import com.wellsphere.connect.core.connectivity.ConnectivityMonitor;
import com.wellsphere.connect.ui.base.BaseActivity;
import com.wellsphere.connect.ui.base.BaseFragment;

import javax.inject.Singleton;

import dagger.BindsInstance;
import dagger.Component;
import dagger.android.AndroidInjectionModule;
import dagger.android.AndroidInjector;

/**
 * Top–level Dagger component whose lifetime is bound to the process.
 * <p>
 * The component composes together the object graph that backs the entire application,
 * wiring every {@code @Singleton} or process-wide dependency. All feature-specific
 * sub-components hang off this root in order to honour the single source of truth
 * principle and guarantee deterministic behaviour—critical in a regulated
 * healthcare setting.
 */
@Singleton
@Component(
        modules = {
                // Core dependency graph
                AndroidInjectionModule.class,
                AppModule.class,
                NetworkModule.class,
                DatabaseModule.class,
                RepositoryModule.class,

                // Presentation & background entry points
                ViewModelBindingModule.class,
                WorkerBindingModule.class,

                // Cross–cutting concerns
                FirebaseModule.class
        }
)
public interface AppComponent extends AndroidInjector<ConnectApplication> {

    // -------------------------------------------------------------------------
    // Factory
    // -------------------------------------------------------------------------

    /**
     * Factory that allows the application instance—and other runtime values that cannot
     * be constructed by Dagger—to be bound into the object graph at creation time.
     */
    @Component.Factory
    interface Factory {

        /**
         * Creates the {@link AppComponent}.
         *
         * @param application  the Android {@link Application} object
         * @param remoteConfig optional mutable configuration (e.g., A/B flags) fetched
         *                     before DI initialisation—may be {@code null}
         *                     when remote config is disabled or unreachable.
         */
        AppComponent create(
                @BindsInstance @NonNull Application application,
                @BindsInstance @Nullable AppConfig remoteConfig
        );
    }

    // -------------------------------------------------------------------------
    // Explicit graph exposures
    // -------------------------------------------------------------------------

    /**
     * Expose a subset of singletons to external, third-party entry points that do not
     * support constructor injection (e.g., Foreground Services started by the OS).
     */
    ConnectivityMonitor connectivityMonitor();

    SessionManager sessionManager();

    CrashReporter crashReporter();

    // -------------------------------------------------------------------------
    // Manual injection targets
    // -------------------------------------------------------------------------

    /**
     * Base classes are injected manually so that every subclass
     * automatically receives its dependencies without having to
     * call {@code AndroidInjection.inject(this)} in each class.
     */
    void inject(@NonNull BaseActivity baseActivity);

    void inject(@NonNull BaseFragment baseFragment);
}