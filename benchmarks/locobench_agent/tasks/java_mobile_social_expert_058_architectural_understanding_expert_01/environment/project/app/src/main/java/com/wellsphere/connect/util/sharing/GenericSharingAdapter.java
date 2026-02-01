```java
/*
 *  WellSphere Connect
 *  Copyright (c) 2024
 *
 *  Licensed under the Apache License, Version 2.0 (the "License");
 *  you may not use this file except in compliance with the License.
 *  You may obtain a copy of the License at
 *
 *         http://www.apache.org/licenses/LICENSE-2.0
 *
 *  Unless required by applicable law or agreed to in writing, software
 *  distributed under the License is distributed on an "AS IS" BASIS,
 *  WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
 *  See the License for the specific language governing permissions and
 *  limitations under the License.
 */

package com.wellsphere.connect.util.sharing;

import android.content.ActivityNotFoundException;
import android.content.Context;
import android.content.Intent;
import android.content.pm.PackageManager;
import android.net.Uri;
import android.os.Bundle;
import android.os.Parcelable;
import android.text.TextUtils;

import androidx.annotation.NonNull;
import androidx.annotation.Nullable;
import androidx.core.content.FileProvider;

import com.wellsphere.connect.BuildConfig;
import com.wellsphere.connect.util.crash.CrashReporter;

import java.io.File;
import java.util.Collections;
import java.util.EnumMap;
import java.util.Map;
import java.util.Objects;
import java.util.concurrent.Executor;
import java.util.concurrent.Executors;

/**
 * GenericSharingAdapter is an adapter façade that hides the complexity of platform-specific
 * social-sharing implementations behind a single, thread-safe API.
 *
 * The adapter chooses the correct {@link SocialShareClient} implementation at runtime based on
 * the requested {@link TargetPlatform}.  If no dedicated client exists or the platform
 * application is not installed, the adapter gracefully falls back to Android’s native
 * {@link Intent#ACTION_SEND} mechanism.
 *
 * This class is production-ready: it is immutable, uses dependency-injection, implements robust
 * error handling, and reports non-fatal issues to the central crash-reporting subsystem.
 */
@SuppressWarnings("unused")
public final class GenericSharingAdapter {

    /* ****************************************************
     * Public API
     * ****************************************************/

    /**
     * Builder used to create {@link GenericSharingAdapter} instances.  This avoids a hard
     * dependency on any particular DI framework and keeps the constructor private.
     */
    public static final class Builder {
        private Context context;
        private Map<TargetPlatform, SocialShareClient> clients = Collections.emptyMap();
        private Executor ioExecutor;

        public Builder with(@NonNull final Context ctx) {
            this.context = ctx.getApplicationContext();
            return this;
        }

        public Builder addClient(@NonNull TargetPlatform platform,
                                 @NonNull SocialShareClient client) {
            if (clients.isEmpty()) {
                clients = new EnumMap<>(TargetPlatform.class);
            }
            clients.put(platform, client);
            return this;
        }

        public Builder ioExecutor(@NonNull Executor executor) {
            this.ioExecutor = executor;
            return this;
        }

        public GenericSharingAdapter build() {
            // Provide sane defaults
            if (ioExecutor == null) {
                ioExecutor = Executors.newSingleThreadExecutor();
            }
            return new GenericSharingAdapter(context, clients, ioExecutor);
        }
    }

    /**
     * Share arbitrary {@link SharePayload} to the given {@link TargetPlatform}.
     */
    public void share(@NonNull final SharePayload payload,
                      @NonNull final TargetPlatform platform,
                      @Nullable final SharingResultCallback callback) {

        Objects.requireNonNull(payload, "payload == null");
        Objects.requireNonNull(platform, "platform == null");

        SocialShareClient client = clientMap.get(platform);

        // Delegate I/O heavy work off the main thread
        ioExecutor.execute(() -> {
            try {
                // If a platform-specific client exists AND it is available, use it.
                if (client != null && client.isAvailable()) {
                    client.share(payload, appContext, callback);
                    return;
                }

                // Fallback: use Android's ACTION_SEND intent
                shareWithSystemIntent(payload, callback);
            } catch (Exception ex) {
                CrashReporter.logNonFatal(ex);
                if (callback != null) callback.onFailure(platform, ex);
            }
        });
    }

    /* ****************************************************
     * Internal implementation
     * ****************************************************/

    private final Context appContext;
    private final Map<TargetPlatform, SocialShareClient> clientMap;
    private final Executor ioExecutor;

    private GenericSharingAdapter(@NonNull Context context,
                                  @NonNull Map<TargetPlatform, SocialShareClient> clients,
                                  @NonNull Executor ioExecutor) {
        this.appContext = Objects.requireNonNull(context, "context == null");
        this.clientMap = new EnumMap<>(TargetPlatform.class);
        this.clientMap.putAll(clients); // copy
        this.ioExecutor = Objects.requireNonNull(ioExecutor, "ioExecutor == null");
    }

    /**
     * Fallback routine leveraging the Android Sharesheet.  This will run on the calling thread
     * (already off the main thread courtesy of {@link #share(SharePayload, TargetPlatform, SharingResultCallback)}).
     */
    private void shareWithSystemIntent(@NonNull SharePayload payload,
                                       @Nullable SharingResultCallback callback) {
        final Intent shareIntent = new Intent(Intent.ACTION_SEND);
        shareIntent.setType(payload.resolveMimeType());

        if (!TextUtils.isEmpty(payload.getText())) {
            shareIntent.putExtra(Intent.EXTRA_TEXT, payload.getText());
        }

        if (payload.getAttachmentUri() != null) {
            shareIntent.putExtra(Intent.EXTRA_STREAM, payload.getAttachmentUri());
            shareIntent.addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION);
        }

        Intent chooser = Intent.createChooser(shareIntent, payload.getChooserTitle(appContext));

        // We must start the activity from the main/UI thread.
        // Use the main looper to post the start activity request.
        AndroidThreadUtil.runOnUiThread(() -> {
            try {
                chooser.addFlags(Intent.FLAG_ACTIVITY_NEW_TASK);
                appContext.startActivity(chooser);
                if (callback != null) callback.onSuccess(TargetPlatform.NATIVE);
            } catch (ActivityNotFoundException anfe) {
                CrashReporter.logNonFatal(anfe);
                if (callback != null) callback.onFailure(TargetPlatform.NATIVE, anfe);
            }
        });
    }

    /* ****************************************************
     * Collaborators / Support types
     * ****************************************************/

    /**
     * Supported sharing targets.  ADD ONLY PUBLIC-FACING PLATFORMS HERE.
     */
    public enum TargetPlatform {
        FACEBOOK,
        TWITTER,
        LINKEDIN,
        WHATSAPP,
        NATIVE    // Android native chooser
    }

    /**
     * Callback invoked when a share action completes or fails.
     */
    public interface SharingResultCallback {
        @SuppressWarnings("unused")
        void onSuccess(TargetPlatform platform);

        @SuppressWarnings("unused")
        void onFailure(TargetPlatform platform, @NonNull Throwable throwable);
    }

    /**
     * Interface implemented by platform-specific sharing clients.
     */
    public interface SocialShareClient {
        /**
         * Returns {@code true} when the platform’s mobile application is installed and capable of
         * performing a share operation.
         */
        boolean isAvailable();

        /**
         * Perform the share operation.  Implementation MAY perform network operations.
         */
        void share(@NonNull SharePayload payload,
                   @NonNull Context context,
                   @Nullable SharingResultCallback callback);
    }

    /**
     * Value-class representing the information that should be shared.
     */
    public static final class SharePayload {

        @Nullable private final String text;
        @Nullable private final File attachment;
        @Nullable private final String explicitMimeType;
        @Nullable private Uri cachedContentUri; // lazy

        private SharePayload(Builder builder) {
            this.text = builder.text;
            this.attachment = builder.attachment;
            this.explicitMimeType = builder.mimeType;
        }

        public static class Builder {
            private String text;
            private File attachment;
            private String mimeType;

            public Builder setText(@Nullable String text) {
                this.text = text;
                return this;
            }

            public Builder setAttachment(@Nullable File attachment) {
                this.attachment = attachment;
                return this;
            }

            public Builder setMimeType(@Nullable String mimeType) {
                this.mimeType = mimeType;
                return this;
            }

            public SharePayload build() {
                return new SharePayload(this);
            }
        }

        @Nullable
        public String getText() {
            return text;
        }

        /**
         * Lazily convert the attachment {@link File} into a {@link Uri} using the app’s
         * {@link androidx.core.content.FileProvider}.
         */
        @Nullable
        public Uri getAttachmentUri() {
            if (attachment == null) return null;
            if (cachedContentUri == null) {
                final String authority = BuildConfig.APPLICATION_ID + ".fileprovider";
                cachedContentUri = FileProvider.getUriForFile(
                        AndroidContextUtil.getApplicationContext(),
                        authority,
                        attachment
                );
            }
            return cachedContentUri;
        }

        /**
         * Resolve a MIME-type for {@link Intent#setType(String)}: prefer an explicit MIME passed
         * by the caller.  Fallback to extension-based heuristics, defaulting to "text/plain".
         */
        @NonNull
        public String resolveMimeType() {
            if (!TextUtils.isEmpty(explicitMimeType)) return explicitMimeType;

            if (attachment != null) {
                final String name = attachment.getName();
                if (name.endsWith(".jpg") || name.endsWith(".jpeg")) return "image/jpeg";
                if (name.endsWith(".png")) return "image/png";
                if (name.endsWith(".pdf")) return "application/pdf";
            }
            return "text/plain";
        }

        /**
         * Provide a context-aware title for the Android sharesheet.
         */
        @NonNull
        public CharSequence getChooserTitle(@NonNull Context context) {
            return context.getString(text != null
                    ? com.wellsphere.connect.R.string.share
                    : com.wellsphere.connect.R.string.share_attachment);
        }

        @Override
        public String toString() {
            return "SharePayload{" +
                    "text='" + text + '\'' +
                    ", attachment=" + attachment +
                    ", explicitMimeType='" + explicitMimeType + '\'' +
                    '}';
        }
    }

    /* ****************************************************
     * Example concrete SocialShareClient implementation
     * ****************************************************/

    /**
     * A minimal Facebook client leveraging the Facebook SDK (if present).  Implementation is
     * intentionally concise; real-world code would handle authentication scopes, user cancellation,
     * SSO tokens, etc.
     */
    public static final class FacebookShareClient implements SocialShareClient {

        private static final String FACEBOOK_PACKAGE = "com.facebook.katana";
        private final PackageManager pm;

        public FacebookShareClient(@NonNull Context context) {
            this.pm = context.getPackageManager();
        }

        @Override
        public boolean isAvailable() {
            try {
                pm.getPackageInfo(FACEBOOK_PACKAGE, 0);
                return true;
            } catch (PackageManager.NameNotFoundException ignored) {
                return false;
            }
        }

        @Override
        public void share(@NonNull SharePayload payload,
                          @NonNull Context context,
                          @Nullable SharingResultCallback callback) {
            Intent intent = new Intent(Intent.ACTION_SEND);
            intent.setPackage(FACEBOOK_PACKAGE);
            intent.setType(payload.resolveMimeType());

            Bundle extras = new Bundle();
            if (payload.getText() != null) {
                extras.putString(Intent.EXTRA_TEXT, payload.getText());
            }
            if (payload.getAttachmentUri() != null) {
                extras.putParcelable(Intent.EXTRA_STREAM, (Parcelable) payload.getAttachmentUri());
                intent.addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION);
            }
            intent.putExtras(extras);
            intent.addFlags(Intent.FLAG_ACTIVITY_NEW_TASK);

            try {
                context.startActivity(intent);
                if (callback != null) callback.onSuccess(TargetPlatform.FACEBOOK);
            } catch (ActivityNotFoundException anfe) {
                if (callback != null) callback.onFailure(TargetPlatform.FACEBOOK, anfe);
            }
        }
    }

    /* ****************************************************
     * Internal utility classes (concealed for brevity)
     * ****************************************************/

    /**
     * Thin wrapper around Android threading utilities to keep this file self-contained.
     * In production we delegate to a central Dispatcher backed by coroutines or RxJava.
     */
    private static final class AndroidThreadUtil {
        private static final android.os.Handler MAIN =
                new android.os.Handler(android.os.Looper.getMainLooper());

        static void runOnUiThread(@NonNull Runnable runnable) {
            if (android.os.Looper.getMainLooper().isCurrentThread()) {
                runnable.run();
            } else {
                MAIN.post(runnable);
            }
        }
    }

    /**
     * Simple context holder.  We avoid leaking Activity references by always using the application
     * context internally.
     */
    private static final class AndroidContextUtil {
        private static Context applicationContext;

        static void init(@NonNull Context context) {
            applicationContext = context.getApplicationContext();
        }

        @NonNull
        static Context getApplicationContext() {
            if (applicationContext == null) {
                throw new IllegalStateException("AndroidContextUtil not initialized");
            }
            return applicationContext;
        }
    }
}
```