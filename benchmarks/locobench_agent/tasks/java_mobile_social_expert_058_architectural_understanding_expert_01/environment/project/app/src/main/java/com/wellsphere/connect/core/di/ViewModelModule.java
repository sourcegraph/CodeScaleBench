package com.wellsphere.connect.core.di;

import androidx.annotation.NonNull;
import androidx.lifecycle.ViewModel;
import androidx.lifecycle.ViewModelProvider;

import com.wellsphere.connect.features.auth.AuthViewModel;
import com.wellsphere.connect.features.feed.FeedViewModel;
import com.wellsphere.connect.features.profile.ProfileViewModel;
import com.wellsphere.connect.features.settings.SettingsViewModel;
import com.wellsphere.connect.features.vitals.VitalsViewModel;

import java.util.Map;

import javax.inject.Inject;
import javax.inject.Provider;
import javax.inject.Singleton;

import dagger.Binds;
import dagger.Module;
import dagger.MapKey;
import dagger.Provides;
import dagger.multibindings.IntoMap;

/**
 * Aggregates every {@link ViewModel} used in the application and wires them into a single
 * {@link ViewModelProvider.Factory}. All ViewModels must be added here; otherwise they will not
 * be injectable through the {@link androidx.lifecycle.ViewModelProvider(androidx.lifecycle.ViewModelStoreOwner)}.
 *
 * This file intentionally houses the {@link ViewModelKey} annotation and the
 * {@link WellSphereViewModelFactory} to reduce boilerplate and keep DI–related classes grouped
 * together.
 */
@Module
public abstract class ViewModelModule {

    /* *********************************************************************************************
     * Bind individual ViewModels into the Dagger multibinding map.
     * ******************************************************************************************* */

    @Binds
    @IntoMap
    @ViewModelKey(AuthViewModel.class)
    abstract ViewModel bindAuthViewModel(AuthViewModel viewModel);

    @Binds
    @IntoMap
    @ViewModelKey(FeedViewModel.class)
    abstract ViewModel bindFeedViewModel(FeedViewModel viewModel);

    @Binds
    @IntoMap
    @ViewModelKey(ProfileViewModel.class)
    abstract ViewModel bindProfileViewModel(ProfileViewModel viewModel);

    @Binds
    @IntoMap
    @ViewModelKey(SettingsViewModel.class)
    abstract ViewModel bindSettingsViewModel(SettingsViewModel viewModel);

    @Binds
    @IntoMap
    @ViewModelKey(VitalsViewModel.class)
    abstract ViewModel bindVitalsViewModel(VitalsViewModel viewModel);

    /* *********************************************************************************************
     * Bind the custom ViewModelFactory so it can be injected wherever a ViewModelProvider.Factory
     * is required (Fragments, custom Views, Services, etc.).
     * ******************************************************************************************* */

    @Binds
    abstract ViewModelProvider.Factory bindViewModelFactory(WellSphereViewModelFactory factory);

    /* *********************************************************************************************
     * ViewModelKey annotation definition.
     * Used by Dagger to distinguish different ViewModels when multibinding into a Map.
     * ******************************************************************************************* */

    @MapKey
    @interface ViewModelKey {
        Class<? extends ViewModel> value();
    }

    /* *********************************************************************************************
     * The only ViewModelProvider.Factory used throughout the application.
     * It lazily instantiates ViewModels using the Providers supplied by Dagger so that each ViewModel
     * can have constructor injection of its dependencies.
     *
     * This factory is thread-safe and minimal, delegating heavy lifting to Dagger’s generated code.
     * ******************************************************************************************* */
    @Singleton
    public static final class WellSphereViewModelFactory implements ViewModelProvider.Factory {

        private final Map<Class<? extends ViewModel>, Provider<ViewModel>> providers;

        @Inject
        WellSphereViewModelFactory(Map<Class<? extends ViewModel>, Provider<ViewModel>> providers) {
            this.providers = providers;
        }

        @NonNull
        @Override
        @SuppressWarnings("unchecked")
        public <T extends ViewModel> T create(@NonNull Class<T> modelClass) {

            // Attempt fast path: exact class match.
            Provider<? extends ViewModel> creator = providers.get(modelClass);

            // Fallback: look for assignable classes (handles inheritance / overrides).
            if (creator == null) {
                for (Map.Entry<Class<? extends ViewModel>, Provider<ViewModel>> entry : providers.entrySet()) {
                    if (modelClass.isAssignableFrom(entry.getKey())) {
                        creator = entry.getValue();
                        break;
                    }
                }
            }

            if (creator == null) {
                throw new IllegalArgumentException(
                        "Unknown ViewModel class: " + modelClass.getName() +
                                ". Did you forget to add it to ViewModelModule?");
            }

            try {
                return (T) creator.get();
            } catch (Exception e) {
                // Wrap any runtime exception into a more descriptive one.
                throw new RuntimeException("Failed to create ViewModel: " + modelClass.getName(), e);
            }
        }
    }

    /* *********************************************************************************************
     * Optional: Provide WellSphereViewModelFactory via @Provides for granularity.
     * In most cases the @Binds above is sufficient, but this shows how to customize scope or logic.
     * ******************************************************************************************* */
    @Provides
    @Singleton
    static WellSphereViewModelFactory provideFactory(Map<Class<? extends ViewModel>, Provider<ViewModel>> providers) {
        return new WellSphereViewModelFactory(providers);
    }
}