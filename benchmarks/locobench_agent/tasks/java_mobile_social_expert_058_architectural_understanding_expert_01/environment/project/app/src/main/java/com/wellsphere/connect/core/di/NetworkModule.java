```java
package com.wellsphere.connect.core.di;

import android.content.Context;
import android.net.ConnectivityManager;
import android.net.NetworkInfo;

import androidx.annotation.NonNull;

import com.google.gson.FieldNamingPolicy;
import com.google.gson.Gson;
import com.google.gson.GsonBuilder;
import com.wellsphere.connect.BuildConfig;
import com.wellsphere.connect.core.network.ApiService;
import com.wellsphere.connect.core.network.AuthTokenProvider;

import java.io.File;
import java.io.IOException;
import java.util.concurrent.TimeUnit;

import javax.inject.Singleton;

import dagger.Module;
import dagger.Provides;
import dagger.hilt.InstallIn;
import dagger.hilt.android.qualifiers.ApplicationContext;
import dagger.hilt.components.SingletonComponent;
import okhttp3.Cache;
import okhttp3.CertificatePinner;
import okhttp3.Interceptor;
import okhttp3.OkHttpClient;
import okhttp3.Request;
import okhttp3.Response;
import okhttp3.logging.HttpLoggingInterceptor;
import retrofit2.Retrofit;
import retrofit2.adapter.rxjava3.RxJava3CallAdapterFactory;
import retrofit2.converter.gson.GsonConverterFactory;

/**
 * Dagger-Hilt module responsible for providing all network-level dependencies.
 * It handles TLS pinning, offline caching, auth token injection, and environment-
 * specific configuration in a single, testable place.
 */
@Module
@InstallIn(SingletonComponent.class)
public class NetworkModule {

    /* ~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
     *  Retrofit / OkHttp providers
     * ~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~ */

    @Provides
    @Singleton
    static Gson provideGson() {
        return new GsonBuilder()
                .serializeNulls()
                .setFieldNamingPolicy(FieldNamingPolicy.LOWER_CASE_WITH_UNDERSCORES)
                .setLenient()
                .create();
    }

    @Provides
    @Singleton
    static Cache provideCache(@ApplicationContext Context context) {
        // 10-MB on-disk cache for responses
        File cacheDir = new File(context.getCacheDir(), "http_cache");
        return new Cache(cacheDir, 10 * 1024 * 1024);
    }

    @Provides
    @Singleton
    static OkHttpClient provideOkHttpClient(
            Cache cache,
            AuthTokenProvider tokenProvider,
            @ApplicationContext Context appContext
    ) {
        // Certificate pinning to mitigate MITM
        CertificatePinner certificatePinner = new CertificatePinner.Builder()
                .add(BuildConfig.API_HOST, "sha256/" + BuildConfig.API_CERT_PIN)
                .build();

        HttpLoggingInterceptor loggingInterceptor = new HttpLoggingInterceptor();
        loggingInterceptor.setLevel(
                BuildConfig.DEBUG ? HttpLoggingInterceptor.Level.BODY
                                  : HttpLoggingInterceptor.Level.NONE
        );

        return new OkHttpClient.Builder()
                .connectTimeout(20, TimeUnit.SECONDS)
                .readTimeout(20, TimeUnit.SECONDS)
                .writeTimeout(20, TimeUnit.SECONDS)
                .cache(cache)
                .addInterceptor(new OfflineCacheInterceptor(appContext))
                .addNetworkInterceptor(new NetworkCacheInterceptor())
                .addInterceptor(new AuthInterceptor(tokenProvider))
                .addInterceptor(loggingInterceptor)
                .certificatePinner(certificatePinner)
                .build();
    }

    @Provides
    @Singleton
    static Retrofit provideRetrofit(OkHttpClient client, Gson gson) {
        return new Retrofit.Builder()
                .baseUrl(BuildConfig.API_BASE_URL)
                .addConverterFactory(GsonConverterFactory.create(gson))
                .addCallAdapterFactory(RxJava3CallAdapterFactory.create())
                .client(client)
                .build();
    }

    @Provides
    @Singleton
    static ApiService provideApiService(Retrofit retrofit) {
        return retrofit.create(ApiService.class);
    }

    /* ~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
     *  Interceptors
     * ~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~ */

    /**
     * Injects the bearer token (if any) into the Authorization header.
     */
    private static final class AuthInterceptor implements Interceptor {

        private final AuthTokenProvider tokenProvider;

        AuthInterceptor(AuthTokenProvider tokenProvider) {
            this.tokenProvider = tokenProvider;
        }

        @Override
        public Response intercept(@NonNull Chain chain) throws IOException {
            Request originalRequest = chain.request();

            String token = tokenProvider.getAuthToken(); // may be null
            if (token == null || originalRequest.header("Authorization") != null) {
                return chain.proceed(originalRequest);
            }

            Request authorised = originalRequest.newBuilder()
                                                .header("Authorization", "Bearer " + token)
                                                .build();
            return chain.proceed(authorised);
        }
    }

    /**
     * Forces cache usage when there is no network available.
     */
    private static final class OfflineCacheInterceptor implements Interceptor {

        private final Context context;

        OfflineCacheInterceptor(Context context) {
            this.context = context;
        }

        @Override
        public Response intercept(@NonNull Chain chain) throws IOException {
            Request request = chain.request();
            if (!isNetworkAvailable()) {
                // Stale up to 7 days old is acceptable when offline.
                int maxStale = 60 * 60 * 24 * 7;
                request = request.newBuilder()
                                 .header("Cache-Control", "public, only-if-cached, max-stale=" + maxStale)
                                 .build();
            }
            return chain.proceed(request);
        }

        private boolean isNetworkAvailable() {
            ConnectivityManager cm =
                    (ConnectivityManager) context.getSystemService(Context.CONNECTIVITY_SERVICE);
            NetworkInfo info = cm != null ? cm.getActiveNetworkInfo() : null;
            return info != null && info.isConnected();
        }
    }

    /**
     * Adds standard caching headers for online requests/responses.
     */
    private static final class NetworkCacheInterceptor implements Interceptor {
        @Override
        public Response intercept(@NonNull Chain chain) throws IOException {
            Response originalResponse = chain.proceed(chain.request());
            // 1-minute freshness when online
            int maxAge = 60;
            return originalResponse.newBuilder()
                                   .header("Cache-Control", "public, max-age=" + maxAge)
                                   .build();
        }
    }
}
```