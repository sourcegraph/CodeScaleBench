package com.wellsphere.connect.util.sharing;

import android.content.Context;
import android.net.Uri;
import android.text.TextUtils;

import androidx.annotation.NonNull;
import androidx.annotation.Nullable;

import com.wellsphere.connect.BuildConfig;

import java.io.File;
import java.io.IOException;
import java.security.GeneralSecurityException;
import java.util.Objects;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;

import okhttp3.Interceptor;
import okhttp3.MediaType;
import okhttp3.MultipartBody;
import okhttp3.OkHttpClient;
import okhttp3.Request;
import okhttp3.RequestBody;
import okhttp3.Response;
import okio.Buffer;
import retrofit2.Call;
import retrofit2.Callback;
import retrofit2.Retrofit;
import retrofit2.converter.gson.GsonConverterFactory;

/**
 * Adapter responsible for sharing user-generated or clinician-curated content to a
 * connected hospital portal (e.g., Epic MyChart, Cerner HealtheLife, or a proprietary API).
 *
 * <p>
 * Implementation highlights:
 * <ul>
 *     <li>Implements a thread-safe Singleton to ensure there is only one outbound sharing queue
 *     interacting with the hospital back-end.</li>
 *     <li>Leverages Retrofit2 for network I/O; all requests are executed off the UI thread.</li>
 *     <li>Per-item AES-256 encryption is applied before the payload leaves the device to meet HIPAA
 *     transport encryption requirements.</li>
 *     <li>Full error propagation and categorisation via {@link ShareCallback}.</li>
 * </ul>
 *
 * NOTE: Some lower-level classes—{@code CryptoUtil}, {@code FileUtil}, and build constants—are
 * expected to exist elsewhere in the codebase. They are referenced here to keep the snippet concise
 * yet production-ready.
 */
@SuppressWarnings("unused")
public final class HospitalPortalSharingAdapter implements SharingAdapter {

    // -----------------------------------------------------------------------------------------------------------------
    // Types
    // -----------------------------------------------------------------------------------------------------------------

    /**
     * An enum modelling the type of content being sent to the hospital portal.
     */
    public enum ShareContentType {
        TEXT("text/plain"),
        IMAGE("image/*"),
        DOCUMENT("application/pdf"),
        BINARY("*/*");

        private final String mimeType;

        ShareContentType(String mimeType) {
            this.mimeType = mimeType;
        }

        public String mimeType() {
            return mimeType;
        }
    }

    /**
     * Immutable payload describing what is to be shared.
     */
    public static final class SharePayload {

        private final ShareContentType type;
        private final String           text;
        private final Uri              contentUri;
        private final String           title;

        private SharePayload(Builder builder) {
            this.type       = builder.type;
            this.text       = builder.text;
            this.contentUri = builder.contentUri;
            this.title      = builder.title;
        }

        public ShareContentType type()       { return type;       }
        public String           text()       { return text;       }
        public Uri              contentUri() { return contentUri; }
        public String           title()      { return title;      }

        /**
         * Builder aiding creation of {@link SharePayload} instances.
         */
        public static class Builder {

            private ShareContentType type;
            private String           text;
            private Uri              contentUri;
            private String           title;

            public Builder setType(@NonNull ShareContentType type) {
                this.type = Objects.requireNonNull(type);
                return this;
            }

            public Builder setText(@NonNull String text) {
                this.text = text;
                return this;
            }

            public Builder setContentUri(@NonNull Uri uri) {
                this.contentUri = uri;
                return this;
            }

            public Builder setTitle(@Nullable String title) {
                this.title = title;
                return this;
            }

            public SharePayload build() {
                if (type == null) {
                    throw new IllegalStateException("type is required");
                }
                if (type == ShareContentType.TEXT && TextUtils.isEmpty(text)) {
                    throw new IllegalStateException("text is required for TEXT payloads");
                }
                if (type != ShareContentType.TEXT && contentUri == null) {
                    throw new IllegalStateException("contentUri is required for non-TEXT payloads");
                }
                return new SharePayload(this);
            }
        }
    }

    /**
     * Callback communicating success or error from a share attempt.
     */
    public interface ShareCallback {
        void onSuccess(@NonNull String serverItemId);

        void onError(@NonNull Throwable throwable);
    }

    // -----------------------------------------------------------------------------------------------------------------
    // Singleton plumbing
    // -----------------------------------------------------------------------------------------------------------------

    private static volatile HospitalPortalSharingAdapter INSTANCE;

    public static HospitalPortalSharingAdapter getInstance(@NonNull Context context) {
        if (INSTANCE == null) {
            synchronized (HospitalPortalSharingAdapter.class) {
                if (INSTANCE == null) {
                    INSTANCE = new HospitalPortalSharingAdapter(context.getApplicationContext());
                }
            }
        }
        return INSTANCE;
    }

    // -----------------------------------------------------------------------------------------------------------------
    // Context & state
    // -----------------------------------------------------------------------------------------------------------------

    private final Context          appContext;
    private final HospitalApi      api;
    private final ExecutorService  executor;

    private HospitalPortalSharingAdapter(Context context) {
        this.appContext = context;
        this.executor   = Executors.newSingleThreadExecutor();

        OkHttpClient okHttpClient = new OkHttpClient.Builder()
                .addInterceptor(new EncryptionInterceptor())
                .build();

        Retrofit retrofit = new Retrofit.Builder()
                .baseUrl(BuildConfig.HOSPITAL_PORTAL_BASE_URL)
                .client(okHttpClient)
                .addConverterFactory(GsonConverterFactory.create())
                .build();

        this.api = retrofit.create(HospitalApi.class);
    }

    // -----------------------------------------------------------------------------------------------------------------
    // SharingAdapter contract
    // -----------------------------------------------------------------------------------------------------------------

    @Override
    public void share(@NonNull SharePayload payload, @NonNull ShareCallback callback) {
        Objects.requireNonNull(payload,  "payload == null");
        Objects.requireNonNull(callback, "callback == null");

        switch (payload.type()) {
            case TEXT:
                shareText(payload, callback);
                break;
            case IMAGE:
            case DOCUMENT:
            case BINARY:
                shareBinary(payload, callback);
                break;
            default:
                callback.onError(new IllegalArgumentException("Unsupported type: " + payload.type()));
        }
    }

    // -----------------------------------------------------------------------------------------------------------------
    // Internal helpers
    // -----------------------------------------------------------------------------------------------------------------

    private void shareText(SharePayload payload, ShareCallback callback) {
        api.postNote(new HospitalNoteRequest(payload.title(), payload.text()))
                .enqueue(wrapCallback(callback));
    }

    private void shareBinary(SharePayload payload, ShareCallback callback) {
        executor.execute(() -> {
            try {
                File file = FileUtil.from(appContext, payload.contentUri());
                RequestBody fileBody = RequestBody.create(file, MediaType.parse(payload.type().mimeType()));

                MultipartBody.Part part = MultipartBody.Part.createFormData(
                        "file",
                        file.getName(),
                        fileBody
                );

                Call<HospitalFileResponse> call = api.uploadFile(part);

                call.enqueue(wrapCallback(callback));
            } catch (IOException e) {
                callback.onError(e);
            }
        });
    }

    // -----------------------------------------------------------------------------------------------------------------
    // Retrofit callback wrapper
    // -----------------------------------------------------------------------------------------------------------------

    private <T extends HospitalBaseResponse> Callback<T> wrapCallback(ShareCallback callback) {
        return new Callback<T>() {
            @Override public void onResponse(@NonNull Call<T> call,
                                             @NonNull retrofit2.Response<T> response) {
                if (response.isSuccessful() && response.body() != null) {
                    callback.onSuccess(response.body().id);
                } else {
                    callback.onError(new IOException("Server error: " + response.code()));
                }
            }

            @Override public void onFailure(@NonNull Call<T> call, @NonNull Throwable t) {
                callback.onError(t);
            }
        };
    }

    // -----------------------------------------------------------------------------------------------------------------
    // Retrofit service definitions
    // -----------------------------------------------------------------------------------------------------------------

    private interface HospitalApi {

        @retrofit2.http.POST("/v1/notes")
        Call<HospitalNoteResponse> postNote(@retrofit2.http.Body HospitalNoteRequest body);

        @retrofit2.http.Multipart
        @retrofit2.http.POST("/v1/files")
        Call<HospitalFileResponse> uploadFile(@retrofit2.http.Part MultipartBody.Part file);
    }

    // -----------------------------------------------------------------------------------------------------------------
    // DTOs
    // -----------------------------------------------------------------------------------------------------------------

    private static class HospitalNoteRequest {
        final String title;
        final String body;

        HospitalNoteRequest(String title, String body) {
            this.title = title;
            this.body = body;
        }
    }

    private abstract static class HospitalBaseResponse {
        String id;   // unique identifier returned by the server
    }

    private static class HospitalNoteResponse extends HospitalBaseResponse { /* nothing extra */ }

    private static class HospitalFileResponse extends HospitalBaseResponse { /* nothing extra */ }

    // -----------------------------------------------------------------------------------------------------------------
    // Security: Transparent payload encryption interceptor
    // -----------------------------------------------------------------------------------------------------------------

    /**
     * Intercepts outgoing requests and encrypts the entire body using AES-256.
     *
     * The backend possesses the shared key and decrypts on arrival.
     */
    private static class EncryptionInterceptor implements Interceptor {

        @Override
        public Response intercept(@NonNull Chain chain) throws IOException {
            Request originalRequest = chain.request();

            // Only encrypt POST or PUT bodies
            if (originalRequest.body() == null ||
                (!"POST".equals(originalRequest.method()) && !"PUT".equals(originalRequest.method()))) {
                return chain.proceed(originalRequest);
            }

            try {
                Buffer buffer = new Buffer();
                originalRequest.body().writeTo(buffer);
                byte[] plainBytes = buffer.readByteArray();
                buffer.close();

                byte[] cipherBytes = CryptoUtil.encrypt(plainBytes); // AES-256/GCM

                RequestBody newBody = RequestBody.create(
                        cipherBytes,
                        MediaType.parse("application/octet-stream")
                );

                Request encryptedRequest = originalRequest.newBuilder()
                        .header("X-Encrypted", "AES256")
                        .method(originalRequest.method(), newBody)
                        .build();

                return chain.proceed(encryptedRequest);
            } catch (GeneralSecurityException e) {
                throw new IOException("Encryption failed", e);
            }
        }
    }
}