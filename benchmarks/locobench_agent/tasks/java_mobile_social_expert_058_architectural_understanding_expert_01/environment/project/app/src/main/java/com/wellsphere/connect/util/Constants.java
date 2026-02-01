package com.wellsphere.connect.util;

import android.Manifest;
import android.app.NotificationManager;
import android.util.Log;

import androidx.annotation.IntDef;
import androidx.annotation.NonNull;
import androidx.annotation.StringDef;

import com.wellsphere.connect.BuildConfig;

import java.lang.annotation.Retention;
import java.lang.annotation.RetentionPolicy;

/**
 * Centralised location for all compile-time constants used throughout
 * the WellSphere Connect Android application.  Constants are grouped
 * by domain to keep the file navigable and to avoid accidental key
 * collisions (e.g. preference names vs. Intent extras).
 *
 * The class is non-instantiable and non-extendable by design.
 */
@SuppressWarnings("unused")
public final class Constants {

    // Prevent instantiation.
    private Constants() {
        throw new UnsupportedOperationException("Do not instantiate Constants");
    }

    /* ===========================================================================
     *  Global / Generic
     * ======================================================================== */

    /** Root log-tag for logcat output (is automatically prefixed to module tags). */
    public static final String LOG_TAG = "WellSphereConnect";

    /** ISO-8601 date format used by the public REST API. */
    public static final String API_DATE_FORMAT = "yyyy-MM-dd'T'HH:mm:ss.SSS'Z'";

    /** Default support email. */
    public static final String SUPPORT_EMAIL = "support@wellsphere.com";

    /* ===========================================================================
     *  Network
     * ======================================================================== */
    public static final class Network {

        private Network() { }

        public static final String API_VERSION = "v1";

        /* *** Base URLs *** */
        public static final String BASE_URL_PRODUCTION   = "https://api.wellsphere.com/";
        public static final String BASE_URL_STAGING      = "https://staging-api.wellsphere.com/";
        public static final String BASE_URL_DEVELOPMENT  = "https://dev-api.wellsphere.com/";

        /* *** Timeouts *** */
        public static final int CONNECT_TIMEOUT_SEC = 60;
        public static final int READ_TIMEOUT_SEC    = 60;
        public static final int WRITE_TIMEOUT_SEC   = 60;

        /* *** Headers *** */
        public static final String HEADER_AUTHORIZATION   = "Authorization";
        public static final String HEADER_CLIENT_VERSION  = "X-Client-Version";
        public static final String HEADER_DEVICE_ID       = "X-Device-Id";

        /* *** Retrofit Qualifiers *** */
        @StringDef({ENV_PRODUCTION, ENV_STAGING, ENV_DEVELOPMENT})
        @Retention(RetentionPolicy.SOURCE)
        public @interface Environment {}
        public static final String ENV_PRODUCTION  = "production";
        public static final String ENV_STAGING     = "staging";
        public static final String ENV_DEVELOPMENT = "development";
    }

    /* ===========================================================================
     *  SharedPreferences (Encrypted)
     * ======================================================================== */
    public static final class Preferences {

        private Preferences() { }

        public static final String FILE_NAME = "wellsphere_preferences";

        public static final String KEY_ACCESS_TOKEN        = "pref_access_token";
        public static final String KEY_REFRESH_TOKEN       = "pref_refresh_token";
        public static final String KEY_LAST_SYNC_TIMESTAMP = "pref_last_sync_timestamp";
        public static final String KEY_BIOMETRIC_ENABLED   = "pref_biometric_enabled";
        public static final String KEY_FIRST_LAUNCH_DONE   = "pref_first_launch_done";
        public static final String KEY_APP_THEME           = "pref_app_theme";      // light / dark / system
    }

    /* ===========================================================================
     *  Intent / Bundle Extras
     * ======================================================================== */
    public static final class IntentKeys {

        private IntentKeys() { }

        public static final String EXTRA_USER_ID       = "extra_user_id";
        public static final String EXTRA_POST_ID       = "extra_post_id";
        public static final String EXTRA_SHARE_TYPE    = "extra_share_type";
        public static final String EXTRA_LAUNCH_SOURCE = "extra_launch_source";

        /* Compile-time constrained share-types */
        @StringDef({ShareType.LOCATION, ShareType.IMAGE, ShareType.DOCUMENT})
        @Retention(RetentionPolicy.SOURCE)
        public @interface ShareType {
            String LOCATION  = "share_type_location";
            String IMAGE     = "share_type_image";
            String DOCUMENT  = "share_type_document";
        }
    }

    /* ===========================================================================
     *  Android Runtime Permissions
     * ======================================================================== */
    public static final class Permissions {

        private Permissions() { }

        /* System Manifest strings */
        public static final String LOCATION       = Manifest.permission.ACCESS_FINE_LOCATION;
        public static final String CAMERA         = Manifest.permission.CAMERA;
        public static final String READ_STORAGE   = Manifest.permission.READ_EXTERNAL_STORAGE;
        public static final String WRITE_STORAGE  = Manifest.permission.WRITE_EXTERNAL_STORAGE;
        public static final String BLUETOOTH      = Manifest.permission.BLUETOOTH;

        /* Request codes (arbitrary, must be < 2^16) */
        public static final int REQUEST_LOCATION          = 2_001;
        public static final int REQUEST_CAMERA            = 2_002;
        public static final int REQUEST_STORAGE           = 2_003;
        public static final int REQUEST_BIOMETRIC_ENROLL  = 2_004;
    }

    /* ===========================================================================
     *  Notification Channels
     * ======================================================================== */
    public static final class NotificationChannels {

        private NotificationChannels() { }

        public static final String GROUP_DEFAULT = "wellsphere_default_group";

        public static final String CHANNEL_GENERAL   = "wellsphere_general_channel";
        public static final String CHANNEL_CRITICAL  = "wellsphere_critical_channel";
        public static final String CHANNEL_MESSAGING = "wellsphere_messaging_channel";

        /* Importance wrappers to avoid scattered direct references */
        @IntDef({
                NotificationManager.IMPORTANCE_NONE,
                NotificationManager.IMPORTANCE_MIN,
                NotificationManager.IMPORTANCE_LOW,
                NotificationManager.IMPORTANCE_DEFAULT,
                NotificationManager.IMPORTANCE_HIGH
        })
        @Retention(RetentionPolicy.SOURCE)
        public @interface Importance {}

        public static final int GENERAL_IMPORTANCE   = NotificationManager.IMPORTANCE_DEFAULT;
        public static final int CRITICAL_IMPORTANCE  = NotificationManager.IMPORTANCE_HIGH;
        public static final int MESSAGING_IMPORTANCE = NotificationManager.IMPORTANCE_HIGH;
    }

    /* ===========================================================================
     *  Analytics / Telemetry
     * ======================================================================== */
    public static final class Analytics {

        private Analytics() { }

        /* *** Event Names *** */
        public static final String EVENT_APP_LAUNCH        = "app_launch";
        public static final String EVENT_LOGIN_SUCCESS     = "login_success";
        public static final String EVENT_LOGIN_FAILURE     = "login_failure";
        public static final String EVENT_LOGOUT            = "logout";
        public static final String EVENT_POST_CREATED      = "post_created";
        public static final String EVENT_VITALS_RECORDED   = "vitals_recorded";
        public static final String EVENT_PREMIUM_PURCHASED = "premium_purchased";

        /* *** Parameter Keys *** */
        public static final String PARAM_USER_ID       = "user_id";
        public static final String PARAM_SCREEN_NAME   = "screen_name";
        public static final String PARAM_ERROR_MESSAGE = "error_message";
        public static final String PARAM_SOURCE        = "source";
    }

    /* ===========================================================================
     *  Local Database
     * ======================================================================== */
    public static final class Database {

        private Database() { }

        public static final String NAME    = "wellsphere.db";
        public static final int    VERSION = 3;

        /* Table names */
        public static final String TABLE_VITALS      = "vitals";
        public static final String TABLE_POSTS       = "posts";
        public static final String TABLE_USERS       = "users";
        public static final String TABLE_ATTACHMENTS = "attachments";

        /* Common column names */
        public static final String COLUMN_ID         = "_id";
        public static final String COLUMN_CREATED_AT = "created_at";
        public static final String COLUMN_UPDATED_AT = "updated_at";
    }

    /* ===========================================================================
     *  Disk / Memory Cache
     * ======================================================================== */
    public static final class Cache {

        private Cache() { }

        public static final String DISK_CACHE_DIR         = "cache_disk";
        public static final long   MAX_DISK_CACHE_BYTES   = 20 * 1024 * 1024L; // 20 MB
        public static final int    MEMORY_CACHE_RATIO     = 8;                 // 1/8th of available mem
    }

    /* ===========================================================================
     *  Feature Flags (remote-config compatible)
     * ======================================================================== */
    public static final class FeatureFlags {

        private FeatureFlags() { }

        public static final String FLAG_NEW_HOME_FEED   = "new_home_feed";
        public static final String FLAG_EKG_STREAM      = "ekg_stream";
        public static final String FLAG_CHAT_BOTS       = "chat_bots";
        public static final String FLAG_SMART_REMINDERS = "smart_reminders";
    }

    /* ===========================================================================
     *  Deep-Links
     * ======================================================================== */
    public static final class Deeplink {

        private Deeplink() { }

        public static final String URI_SCHEME = "wellsphere";
        public static final String HOST       = "connect";

        private static final String PATH_POST    = "/post";
        private static final String PATH_PROFILE = "/profile";
        private static final String QUERY_ID     = "id";

        /**
         * Builds a fully-qualified deep-link URI to a post that can be
         * consumed by both the app and compliant web clients.
         */
        @NonNull
        public static String buildPostUri(@NonNull String postId) {
            return URI_SCHEME + "://" + HOST + PATH_POST + '?' + QUERY_ID + '=' + postId;
        }

        /**
         * Builds a deep-link URI to a user profile in the Connect domain.
         */
        @NonNull
        public static String buildProfileUri(@NonNull String userId) {
            return URI_SCHEME + "://" + HOST + PATH_PROFILE + '?' + QUERY_ID + '=' + userId;
        }
    }

    /* ===========================================================================
     *  Miscellaneous Timeouts
     * ======================================================================== */
    public static final class Timeouts {
        private Timeouts() { }

        public static final long LOCATION_TIMEOUT_MS         = 15_000L; // 15 s
        public static final long BIOMETRIC_PROMPT_TIMEOUT_MS = 30_000L; // 30 s
    }

    /* ===========================================================================
     *  Logging helpers (debug-only where applicable)
     * ======================================================================== */

    /**
     * Outputs a debug-level log statement in debug builds only.
     * Avoids shipping verbose logs in production for HIPAA compliance.
     */
    public static void d(@NonNull String tag, @NonNull String message) {
        if (BuildConfig.DEBUG) {
            Log.d(LOG_TAG + '/' + tag, message);
        }
    }

    /**
     * Outputs an error-level log statement (always emitted).
     */
    public static void e(@NonNull String tag,
                         @NonNull String message,
                         Throwable throwable) {
        Log.e(LOG_TAG + '/' + tag, message, throwable);
    }
}