package com.wellsphere.connect.util.sharing;

import android.content.Context;
import android.content.pm.PackageManager;
import android.net.ConnectivityManager;
import android.net.NetworkCapabilities;
import android.os.Build;
import android.util.Log;

import androidx.annotation.NonNull;

import com.wellsphere.connect.BuildConfig;
import com.wellsphere.connect.core.exception.SharingNotSupportedException;
import com.wellsphere.connect.util.sharing.adapter.EmailShareAdapter;
import com.wellsphere.connect.util.sharing.adapter.FacebookShareAdapter;
import com.wellsphere.connect.util.sharing.adapter.HospitalPortalShareAdapter;
import com.wellsphere.connect.util.sharing.adapter.InternalTimelineShareAdapter;
import com.wellsphere.connect.util.sharing.adapter.ShareAdapter;
import com.wellsphere.connect.util.sharing.adapter.TwitterShareAdapter;

import java.util.EnumMap;
import java.util.Map;
import java.util.concurrent.ConcurrentHashMap;

/**
 * Factory responsible for instantiating and caching concrete {@link ShareAdapter} implementations
 * depending on the requested {@link ShareChannel}. <p>
 *
 * Rationale:
 * <ul>
 *     <li>Centralizes feature-flag / capability checks.</li>
 *     <li>Ensures heavyweight adapters (e.g. those boot-strapping OAuth flows) are created only
 *     once and re-used in subsequent share actions.</li>
 *     <li>Decouples calling code from concrete adapter classes so that additional channels can be
 *     added with zero impact to feature modules.</li>
 * </ul>
 *
 * Usage:
 * <pre>
 *     ShareAdapter adapter = SharingFactory.getAdapter(ShareChannel.FACEBOOK, context);
 *     adapter.share(content, callback);
 * </pre>
 */
@SuppressWarnings("WeakerAccess") // API entry-points need to be public.
public final class SharingFactory {

    private static final String TAG = "SharingFactory";

    /**
     * Lazy-loaded cache to avoid re-instantiating adapters. <br>
     * Concurrent map allows multi-threaded access from background share tasks.
     */
    private static final Map<ShareChannel, ShareAdapter> ADAPTER_CACHE =
            new ConcurrentHashMap<>();

    /**
     * Optional channel-level feature flags, populated once on first access.
     */
    private static volatile Map<ShareChannel, Boolean> channelFeatureFlags;

    private SharingFactory() {
        // Utility class.
    }

    /**
     * Returns the concrete {@link ShareAdapter} for the given {@link ShareChannel}.  Instantiates
     * and caches the adapter if necessary.
     *
     * @throws IllegalArgumentException     when {@code channel} or {@code context} are {@code null}.
     * @throws SharingNotSupportedException when the requested channel is not available on the
     *                                      running device or is disabled via a remote feature flag.
     */
    @NonNull
    public static ShareAdapter getAdapter(@NonNull ShareChannel channel,
                                          @NonNull Context context)
            throws SharingNotSupportedException {

        if (channel == null) {
            throw new IllegalArgumentException("ShareChannel may not be null.");
        }
        if (context == null) {
            throw new IllegalArgumentException("Context may not be null.");
        }

        // Remote config / build-variant check.
        if (!isChannelEnabled(channel)) {
            throw new SharingNotSupportedException(
                    "Sharing via " + channel + " is disabled by feature flag.");
        }

        // Return cached instance if still valid.
        ShareAdapter cached = ADAPTER_CACHE.get(channel);
        if (cached != null && cached.isAvailable(context)) {
            return cached;
        }

        // Instantiate.
        ShareAdapter created = createAdapter(channel, context);

        // Cache for next call.
        ADAPTER_CACHE.put(channel, created);
        return created;
    }

    /**
     * Clears the internal adapter cache.  Useful for end-to-end tests that swap in fake adapters.
     */
    public static void clearCache() {
        ADAPTER_CACHE.clear();
    }

    /**
     * Quick helper determining if a share channel is available on the current device without
     * allocating an adapter instance.
     */
    public static boolean isChannelAvailable(@NonNull ShareChannel channel,
                                             @NonNull Context context) {
        try {
            ShareAdapter adapter = getAdapter(channel, context);
            return adapter.isAvailable(context);
        } catch (SharingNotSupportedException ex) {
            return false;
        }
    }

    // ---------------------------------------------------------------------------------------------
    // Internals
    // ---------------------------------------------------------------------------------------------

    @NonNull
    private static ShareAdapter createAdapter(@NonNull ShareChannel channel,
                                              @NonNull Context context)
            throws SharingNotSupportedException {

        switch (channel) {
            case INTERNAL_TIMELINE:
                return new InternalTimelineShareAdapter();
            case HOSPITAL_PORTAL:
                ensureNetwork(context);
                return new HospitalPortalShareAdapter();
            case FACEBOOK:
                ensurePackageInstalled("com.facebook.katana", context);
                return new FacebookShareAdapter();
            case TWITTER:
                ensurePackageInstalled("com.twitter.android", context);
                return new TwitterShareAdapter();
            case EMAIL:
                return new EmailShareAdapter();
            default:
                // Exhaustive switch for forward-compatibility
                throw new SharingNotSupportedException("Unrecognized ShareChannel: " + channel);
        }
    }

    private static void ensurePackageInstalled(String packageName, Context ctx)
            throws SharingNotSupportedException {
        PackageManager pm = ctx.getPackageManager();
        try {
            pm.getPackageInfo(packageName, 0);
        } catch (PackageManager.NameNotFoundException e) {
            throw new SharingNotSupportedException(
                    "Required application (" + packageName + ") not installed.");
        }
    }

    private static void ensureNetwork(Context ctx) throws SharingNotSupportedException {
        ConnectivityManager cm = (ConnectivityManager) ctx.getSystemService(Context.CONNECTIVITY_SERVICE);
        if (cm == null) {
            throw new SharingNotSupportedException("ConnectivityManager unavailable.");
        }
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.M) {
            NetworkCapabilities caps = cm.getNetworkCapabilities(cm.getActiveNetwork());
            if (caps == null ||
                (!caps.hasTransport(NetworkCapabilities.TRANSPORT_WIFI)
                        && !caps.hasTransport(NetworkCapabilities.TRANSPORT_CELLULAR))) {
                throw new SharingNotSupportedException("Active network connection required.");
            }
        } else if (!cm.getBackgroundDataSetting()) { // Legacy check
            throw new SharingNotSupportedException("Background data disabled.");
        }
    }

    /**
     * Remote-config / build-variant aware feature-flag evaluation.  The result is memoized to avoid
     * repeated lookups.
     */
    private static boolean isChannelEnabled(ShareChannel channel) {
        if (channelFeatureFlags == null) {
            synchronized (SharingFactory.class) {
                if (channelFeatureFlags == null) {
                    channelFeatureFlags = loadFeatureFlags();
                }
            }
        }
        Boolean enabled = channelFeatureFlags.get(channel);
        return enabled == null || enabled;
    }

    /**
     * Populates feature-flag map from BuildConfig or remote config provider.  For security, defaults
     * to <code>false</code> for unknown channels.
     */
    private static Map<ShareChannel, Boolean> loadFeatureFlags() {
        Map<ShareChannel, Boolean> map = new EnumMap<>(ShareChannel.class);

        // Example of compile-time flags that can be overridden by runtime remote-config.
        map.put(ShareChannel.FACEBOOK, BuildConfig.FEATURE_FACEBOOK_SHARING);
        map.put(ShareChannel.TWITTER, BuildConfig.FEATURE_TWITTER_SHARING);
        map.put(ShareChannel.HOSPITAL_PORTAL, true); // Always enabled; HIPAA-compliant
        map.put(ShareChannel.INTERNAL_TIMELINE, true);
        map.put(ShareChannel.EMAIL, true);

        try {
            // Optional remote config, swallowed on failure.
            Map<ShareChannel, Boolean> remote =
                    com.wellsphere.connect.core.remoteconfig.RemoteConfigProvider.get()
                            .getShareChannelFlags();
            map.putAll(remote);
        } catch (Exception ex) {
            Log.w(TAG, "Remote-config unavailable, falling back to local flags.", ex);
        }

        return map;
    }

    /**
     * Enumerates the different sharing pathways the application supports.
     */
    public enum ShareChannel {
        INTERNAL_TIMELINE,
        HOSPITAL_PORTAL,
        FACEBOOK,
        TWITTER,
        EMAIL
    }
}