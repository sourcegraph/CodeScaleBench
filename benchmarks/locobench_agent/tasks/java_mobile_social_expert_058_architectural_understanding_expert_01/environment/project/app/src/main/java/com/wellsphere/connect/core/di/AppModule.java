```java
package com.wellsphere.connect.core.di;

import android.app.Application;
import android.content.Context;

import androidx.annotation.NonNull;
import androidx.room.Room;

import com.google.firebase.crashlytics.FirebaseCrashlytics;
import com.google.gson.Gson;
import com.google.gson.GsonBuilder;
import com.wellsphere.connect.BuildConfig;
import com.wellsphere.connect.core.analytics.CrashReporter;
import com.wellsphere.connect.core.auth.BiometricAuthManager;
import com.wellsphere.connect.core.data.HealthDataRepository;
import com.wellsphere.connect.core.data.local.WellSphereDatabase;
import com.wellsphere.connect.core.data.local.dao.HealthEntryDao;
import com.wellsphere.connect.core.data.remote.ApiService;
import com.wellsphere.connect.core.location.LocationServiceProvider;
import com.wellsphere.connect.core.share.SocialShareAdapterFactory;
import com.wellsphere.connect.core.util.NetworkConnectionInterceptor;

import java.io.File;
import java.util.concurrent.TimeUnit;

import dagger.Binds;
import dagger.Module;
import dagger.Provides;
import dagger.hilt.InstallIn;
import dagger.hilt.components.SingletonComponent;
import io.reactivex.rxjava3.schedulers.Schedulers;
import okhttp3.Cache;
import okhttp3.OkHttpClient;
import okhttp3.logging.HttpLoggingInterceptor;
import retrofit2.Retrofit;
import retrofit2.adapter.rxjava3.RxJava3CallAdapterFactory;
import retrofit2.converter.gson.GsonConverterFactory;

import javax.inject.Singleton;

/**
 * Centralized application-level dependency graph.
 * All singletons live as long as the process does.
 */
@Module
@InstallIn(SingletonComponent.class)
public abstract class AppModule {

    // region Application / Context --------------------------------------------------------------

    @Provides
    @Singleton
    static Context provideApplicationContext(@NonNull Application app) {
        return app.getApplicationContext();
    }

    // endregion

    // region Networking -------------------------------------------------------------------------

    @Provides
    @Singleton
    static Cache provideOkHttpCache(Context context) {
        File cacheDir = new File(context.getCacheDir(), "http_cache");
        // 20MiB cache
        return new Cache(cacheDir, 20 * 1024 * 1024L);
    }

    @Provides
    @Singleton
    static OkHttpClient provideOkHttpClient(Cache cache,
                                            NetworkConnectionInterceptor networkInterceptor) {

        OkHttpClient.Builder builder = new OkHttpClient.Builder()
                .cache(cache)
                .connectTimeout(15, TimeUnit.SECONDS)
                .readTimeout(20, TimeUnit.SECONDS)
                .addInterceptor(networkInterceptor);

        if (BuildConfig.DEBUG) {
            HttpLoggingInterceptor logInterceptor = new HttpLoggingInterceptor();
            logInterceptor.setLevel(HttpLoggingInterceptor.Level.BODY);
            builder.addInterceptor(logInterceptor);
        }
        return builder.build();
    }

    @Provides
    @Singleton
    static Gson provideGson() {
        return new GsonBuilder()
                .setDateFormat("yyyy-MM-dd'T'HH:mm:ss.SSS'Z'")
                .serializeNulls()
                .create();
    }

    @Provides
    @Singleton
    static Retrofit provideRetrofit(OkHttpClient okHttpClient, Gson gson) {
        return new Retrofit.Builder()
                .client(okHttpClient)
                .baseUrl(BuildConfig.API_ENDPOINT)
                .addCallAdapterFactory(RxJava3CallAdapterFactory.createWithScheduler(Schedulers.io()))
                .addConverterFactory(GsonConverterFactory.create(gson))
                .build();
    }

    @Provides
    @Singleton
    static ApiService provideApiService(Retrofit retrofit) {
        return retrofit.create(ApiService.class);
    }

    // endregion

    // region Local Persistence ------------------------------------------------------------------

    @Provides
    @Singleton
    static WellSphereDatabase provideDatabase(Context context) {
        return Room.databaseBuilder(context, WellSphereDatabase.class, "wellsphere.db")
                .fallbackToDestructiveMigration() // safe because sync with EHR is authoritative
                .build();
    }

    @Provides
    @Singleton
    static HealthEntryDao provideHealthEntryDao(WellSphereDatabase db) {
        return db.healthEntryDao();
    }

    // endregion

    // region Repository -------------------------------------------------------------------------

    @Provides
    @Singleton
    static HealthDataRepository provideHealthDataRepository(ApiService apiService,
                                                            HealthEntryDao dao,
                                                            CrashReporter crashReporter) {
        return new HealthDataRepository(apiService, dao, crashReporter);
    }

    // endregion

    // region Crash Reporting --------------------------------------------------------------------

    @Provides
    @Singleton
    static CrashReporter provideCrashReporter() {
        FirebaseCrashlytics core = FirebaseCrashlytics.getInstance();
        return new CrashReporter(core);
    }

    // endregion

    // region Location Services ------------------------------------------------------------------

    @Provides
    @Singleton
    static LocationServiceProvider provideLocationServiceProvider(Context context, CrashReporter reporter) {
        return new LocationServiceProvider(context, reporter);
    }

    // endregion

    // region Biometric Authentication -----------------------------------------------------------

    @Provides
    @Singleton
    static BiometricAuthManager provideBiometricAuthManager(Context context, CrashReporter reporter) {
        return new BiometricAuthManager(context, reporter);
    }

    // endregion

    // region Social Sharing ---------------------------------------------------------------------

    @Provides
    @Singleton
    static SocialShareAdapterFactory provideSocialShareAdapterFactory(Context context) {
        return new SocialShareAdapterFactory(context);
    }

    // endregion

    // region Utilities --------------------------------------------------------------------------

    /**
     * NetworkConnectionInterceptor provides offline-aware behavior. If there is no connectivity and
     * an API request does not have okHttp cache headers allowing stale reads, we proactively abort
     * the request to prevent Retrofit from throwing obscure exceptions.
     */
    @Binds
    abstract NetworkConnectionInterceptor bindNetworkConnectionInterceptor(NetworkConnectionInterceptor impl);

    // endregion
}
```