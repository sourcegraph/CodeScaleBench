package com.wellsphere.connect.core.di;

import android.content.Context;

import androidx.annotation.NonNull;

import com.wellsphere.connect.auth.data.datasource.AuthLocalDataSource;
import com.wellsphere.connect.auth.data.datasource.AuthRemoteDataSource;
import com.wellsphere.connect.auth.domain.AuthRepository;
import com.wellsphere.connect.auth.data.AuthRepositoryImpl;
import com.wellsphere.connect.common.coroutines.CoroutineDispatchers;
import com.wellsphere.connect.health.data.datasource.HealthLocalDataSource;
import com.wellsphere.connect.health.data.datasource.HealthRemoteDataSource;
import com.wellsphere.connect.health.domain.HealthRecordRepository;
import com.wellsphere.connect.health.data.HealthRecordRepositoryImpl;
import com.wellsphere.connect.image.data.datasource.ImageUploadRemoteDataSource;
import com.wellsphere.connect.image.domain.ImageUploadRepository;
import com.wellsphere.connect.image.data.ImageUploadRepositoryImpl;
import com.wellsphere.connect.offline.data.datasource.OfflineSyncLocalDataSource;
import com.wellsphere.connect.offline.domain.OfflineSyncRepository;
import com.wellsphere.connect.offline.data.OfflineSyncRepositoryImpl;
import com.wellsphere.connect.profile.data.datasource.UserProfileLocalDataSource;
import com.wellsphere.connect.profile.data.datasource.UserProfileRemoteDataSource;
import com.wellsphere.connect.profile.domain.UserProfileRepository;
import com.wellsphere.connect.profile.data.UserProfileRepositoryImpl;
import com.wellsphere.connect.storage.SecureStorage;
import com.wellsphere.connect.util.AppExecutors;

import javax.inject.Singleton;

import dagger.Module;
import dagger.Provides;
import dagger.hilt.InstallIn;
import dagger.hilt.android.qualifiers.ApplicationContext;
import dagger.hilt.components.SingletonComponent;

/**
 * RepositoryModule is responsible for wiring up Repository instances with their
 * respective data-sources, thread dispatchers, and any low-level dependencies.
 *
 * NOTE: Because repositories represent a boundary between the domain and data layers,
 * they should expose only domain models. Therefore only the Repository interface is
 * exported to the rest of the app – concrete implementations remain package-private.
 */
@Module
@InstallIn(SingletonComponent.class)
public final class RepositoryModule {

    // ---------------------------
    // Auth
    // ---------------------------

    @Provides
    @Singleton
    public AuthRepository provideAuthRepository(
            @NonNull AuthRemoteDataSource remoteDataSource,
            @NonNull AuthLocalDataSource localDataSource,
            @NonNull SecureStorage secureStorage,
            @NonNull CoroutineDispatchers dispatchers
    ) {
        return new AuthRepositoryImpl(remoteDataSource, localDataSource, secureStorage, dispatchers);
    }

    // ---------------------------
    // User Profile
    // ---------------------------

    @Provides
    @Singleton
    public UserProfileRepository provideUserProfileRepository(
            @NonNull UserProfileRemoteDataSource remoteDataSource,
            @NonNull UserProfileLocalDataSource localDataSource,
            @NonNull CoroutineDispatchers dispatchers
    ) {
        return new UserProfileRepositoryImpl(remoteDataSource, localDataSource, dispatchers);
    }

    // ---------------------------
    // Health Records
    // ---------------------------

    @Provides
    @Singleton
    public HealthRecordRepository provideHealthRecordRepository(
            @NonNull HealthRemoteDataSource remoteDataSource,
            @NonNull HealthLocalDataSource localDataSource,
            @NonNull OfflineSyncRepository offlineSyncRepository,
            @NonNull CoroutineDispatchers dispatchers
    ) {
        return new HealthRecordRepositoryImpl(
                remoteDataSource,
                localDataSource,
                offlineSyncRepository,
                dispatchers
        );
    }

    // ---------------------------
    // Image Upload
    // ---------------------------

    @Provides
    @Singleton
    public ImageUploadRepository provideImageUploadRepository(
            @NonNull ImageUploadRemoteDataSource remoteDataSource,
            @NonNull AppExecutors appExecutors,
            @ApplicationContext Context context
    ) {
        return new ImageUploadRepositoryImpl(remoteDataSource, appExecutors, context);
    }

    // ---------------------------
    // Offline Sync
    // ---------------------------

    @Provides
    @Singleton
    public OfflineSyncRepository provideOfflineSyncRepository(
            @NonNull OfflineSyncLocalDataSource localDataSource,
            @NonNull AuthRepository authRepository,
            @NonNull AppExecutors appExecutors
    ) {
        return new OfflineSyncRepositoryImpl(localDataSource, authRepository, appExecutors);
    }
}