package com.wellsphere.connect.util.sharing;

import android.app.Activity;
import android.content.Context;
import android.content.res.Resources;
import android.net.Uri;

import androidx.annotation.MainThread;
import androidx.annotation.NonNull;
import androidx.annotation.Nullable;
import androidx.lifecycle.LiveData;

import io.reactivex.rxjava3.core.Completable;
import io.reactivex.rxjava3.core.Single;

import java.util.Collections;
import java.util.EnumSet;
import java.util.Objects;
import java.util.Set;

/**
 * Public contract for “social-sharing” adapters used by the WellSphere Connect
 * mobile application. Implementations translate the platform-agnostic {@link ShareRequest}
 * into provider-specific API calls (e.g., Facebook Graph, in-hospital FHIR endpoint),
 * deal with authentication / token life-cycle, and publish {@link ShareEvent share events}
 * for UI components or use-cases to observe.
 *
 * Adapters are discovered at runtime via {@link java.util.ServiceLoader} and injected
 * through Dagger/Hilt, making it trivial to add or remove integrations without touching
 * business logic. All methods are expected to be non-blocking; expensive work must be
 * performed off the UI-thread and surfaced through RxJava or LiveData.
 *
 * NOTE: Because the app is distributed to health-care professionals, adapters MUST be
 * HIPAA-compliant and encrypt data in transit. Validation should be performed in
 * {@link #validate(ShareRequest)} before leaving the device.
 */
public interface ISharingAdapter {

    /**
     * Unique, stable identifier for the adapter (e.g. "twitter", "hospital_portal").
     */
    @NonNull
    String getId();

    /**
     * Human-readable name shown in the UI (“Twitter”, “Epic MyChart”).
     */
    @NonNull
    String getDisplayName(@NonNull Resources resources);

    /**
     * Initializes the adapter instance. Called once from Application scope.
     *
     * @param context          application context
     * @param initializationId opaque value allowing a DI-framework to recreate the adapter
     */
    @MainThread
    void initialize(@NonNull Context context, @Nullable String initializationId);

    /**
     * Returns {@code true} if the underlying SDK/service is available on device.
     * For example, a Google Fit adapter would return false on devices without
     * Play Services or when the feature flag is disabled remotely.
     */
    boolean isAvailable(@NonNull Context context);

    /**
     * Authenticates the user. For OAuth-based providers this typically means
     * launching a web flow inside {@link Activity} or a Chrome Custom Tab.
     *
     * @return Rx {@link Single} emitting true if authentication succeeded,
     *         false if user canceled. Terminates with {@link SharingException}
     *         on unrecoverable errors (e.g., network failure).
     */
    @NonNull
    Single<Boolean> authenticate(@NonNull Activity activity);

    /**
     * Revokes local credentials and, if supported, remote tokens.
     *
     * @return Completable signaling completion or error.
     */
    @NonNull
    Completable revokeAuthentication();

    /**
     * Checks if the adapter currently holds a valid session/token.
     */
    boolean isAuthenticated();

    /**
     * Primary entry point for content-sharing requests.
     *
     * @param request description of the content to share.
     * @return {@link Completable} that completes on success or forwards a
     *         {@link SharingException} on failure.
     */
    @NonNull
    Completable share(@NonNull ShareRequest request);

    /**
     * Simple, synchronous pre-validation to fail fast before executing
     * backend calls (e.g., missing mandatory data or unsupported mime-type).
     *
     * @throws ValidationException if request is malformed.
     */
    void validate(@NonNull ShareRequest request) throws ValidationException;

    /**
     * LiveData stream emitting state changes; may be used by ViewModels/Fragments
     * to update UI (progress bars, success toasts, etc.).
     */
    @NonNull
    LiveData<ShareEvent> getShareEvents();

    /**
     * Registers an imperative event listener in cases where LiveData cannot be used
     * (e.g. background worker without lifecycle). Weak-references are recommended
     * in implementation to prevent leaks.
     */
    void registerListener(@NonNull ShareEventListener listener);

    void unregisterListener(@NonNull ShareEventListener listener);

    /* -----------------------------------------------------------------------------------------
     * Helper types
     * ----------------------------------------------------------------------------------------- */

    /**
     * Builder-style DTO used to transport share data across the app.
     * Instances should be treated as immutable once built.
     */
    final class ShareRequest {

        public enum Type {
            TEXT,
            IMAGE,
            VIDEO,
            DOCUMENT,
            MIXED
        }

        public enum Target {
            USER_FEED,
            DIRECT_MESSAGE,
            SECURE_PORTAL,
            STORY,
            OTHER
        }

        private final Type type;
        private final Set<Uri> mediaUris;
        private final String text;
        private final Target target;
        private final boolean isSensitive;

        private ShareRequest(Builder builder) {
            this.type = builder.type;
            this.mediaUris = Collections.unmodifiableSet(builder.mediaUris);
            this.text = builder.text;
            this.target = builder.target;
            this.isSensitive = builder.isSensitive;
        }

        public Type getType() {
            return type;
        }

        public Set<Uri> getMediaUris() {
            return mediaUris;
        }

        public String getText() {
            return text;
        }

        public Target getTarget() {
            return target;
        }

        public boolean isSensitive() {
            return isSensitive;
        }

        @Override
        public String toString() {
            return "ShareRequest{" +
                    "type=" + type +
                    ", mediaUris=" + mediaUris +
                    ", text='" + text + '\'' +
                    ", target=" + target +
                    ", isSensitive=" + isSensitive +
                    '}';
        }

        public static final class Builder {
            private Type type = Type.TEXT;
            private final Set<Uri> mediaUris = EnumSet.noneOf(Uri.class);
            private String text = "";
            private Target target = Target.USER_FEED;
            private boolean isSensitive = false;

            public Builder setType(@NonNull Type type) {
                this.type = Objects.requireNonNull(type);
                return this;
            }

            public Builder addMedia(@NonNull Uri uri) {
                mediaUris.add(Objects.requireNonNull(uri));
                return this;
            }

            public Builder setText(@Nullable String text) {
                this.text = text == null ? "" : text;
                return this;
            }

            public Builder setTarget(@NonNull Target target) {
                this.target = Objects.requireNonNull(target);
                return this;
            }

            public Builder setSensitive(boolean sensitive) {
                this.isSensitive = sensitive;
                return this;
            }

            public ShareRequest build() {
                if (mediaUris.isEmpty() && (text == null || text.trim().isEmpty())) {
                    throw new IllegalStateException("Either text or media content must be provided");
                }
                return new ShareRequest(this);
            }
        }
    }

    /**
     * Sealed set of domain-events describing share-operation life-cycle.
     */
    final class ShareEvent {
        public enum Status {
            QUEUED,
            IN_PROGRESS,
            SUCCESS,
            FAILED,
            CANCELED
        }

        private final Status status;
        private final long timestamp;
        @Nullable
        private final Throwable error;

        private ShareEvent(Status status, long timestamp, @Nullable Throwable error) {
            this.status = status;
            this.timestamp = timestamp;
            this.error = error;
        }

        public static ShareEvent of(Status status) {
            return new ShareEvent(status, System.currentTimeMillis(), null);
        }

        public static ShareEvent failure(@NonNull Throwable error) {
            return new ShareEvent(Status.FAILED, System.currentTimeMillis(), error);
        }

        public Status getStatus() {
            return status;
        }

        public long getTimestamp() {
            return timestamp;
        }

        @Nullable
        public Throwable getError() {
            return error;
        }
    }

    /**
     * Listener interface mirroring {@link ShareEvent} LiveData for
     * imperative subscription models (e.g., JobScheduler job).
     */
    interface ShareEventListener {
        void onShareEvent(@NonNull ShareEvent event);
    }

    /**
     * Common super-class for adapter-related failures.
     */
    class SharingException extends Exception {
        public SharingException(@NonNull String message) {
            super(message);
        }

        public SharingException(@NonNull String message, @NonNull Throwable cause) {
            super(message, cause);
        }
    }

    /**
     * Thrown by {@link #validate(ShareRequest)} on user-fixable problems
     * (e.g., file too large, unsupported mime-type).
     */
    class ValidationException extends SharingException {
        public ValidationException(@NonNull String message) {
            super(message);
        }

        public ValidationException(@NonNull String message, @NonNull Throwable cause) {
            super(message, cause);
        }
    }
}