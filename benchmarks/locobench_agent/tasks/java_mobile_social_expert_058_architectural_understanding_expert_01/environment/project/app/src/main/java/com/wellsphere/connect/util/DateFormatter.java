package com.wellsphere.connect.util;

import android.content.Context;
import android.text.format.DateUtils;

import androidx.annotation.NonNull;
import androidx.annotation.Nullable;

import java.time.Instant;
import java.time.LocalDate;
import java.time.LocalDateTime;
import java.time.ZoneId;
import java.time.format.DateTimeFormatter;
import java.time.format.DateTimeParseException;
import java.time.format.FormatStyle;
import java.util.Locale;
import java.util.Objects;
import java.util.concurrent.ConcurrentHashMap;
import java.util.concurrent.ConcurrentMap;

/**
 * Thread-safe, locale-aware date/time utility used across the WellSphere Connect
 * codebase.  All public methods are static, and internal {@link DateTimeFormatter}
 * instances are cached to avoid the heavy cost of repeatedly building formatters
 * at runtime.
 *
 * <p>The class is built on top of java.time which is desugared for API &lt; 26
 * via the Android Gradle plugin, so it is safe to use on API 21 +</p>
 *
 * IMPORTANT: <b>Never</b> construct {@link java.text.SimpleDateFormat} or
 * {@link java.util.Calendar} directly in new code.  Stick to {@code java.time}.
 */
@SuppressWarnings("unused")
public final class DateFormatter {

    /* *******************************
     * Public API
     * *******************************/

    /**
     * Returns an ISO-8601 string (UTC) representing the supplied instant.
     */
    @NonNull
    public static String toIsoInstant(@NonNull Instant instant) {
        return ISO_INSTANT.format(instant);
    }

    /**
     * Parses an ISO-8601 timestamp (e.g., <i>2023-09-11T14:22:11Z</i>) into an {@link Instant}.
     *
     * @throws DateTimeParseException if the string is not a valid ISO-8601 instant
     */
    @NonNull
    public static Instant parseIsoInstant(@NonNull String isoString) {
        Objects.requireNonNull(isoString, "isoString == null");
        return Instant.parse(isoString);
    }

    /**
     * Parses an ISO-8601 date string (e.g., <i>2023-09-11</i>) into a {@link LocalDate}.
     *
     * @throws DateTimeParseException if the string is not a valid ISO-8601 date
     */
    @NonNull
    public static LocalDate parseIsoDate(@NonNull String isoDate) {
        Objects.requireNonNull(isoDate, "isoDate == null");
        return ISO_DATE.parse(isoDate, LocalDate::from);
    }

    /**
     * Formats a {@link LocalDateTime} into a localized string using the caller-supplied
     * style hints.  The client controls both date and time styles (e.g., SHORT, MEDIUM).
     *
     * Example: <i>Jan 2, 2024, 3:45 PM</i> (en-US, {@code FormatStyle.MEDIUM})
     *
     * @param dateTime  the local date/time to format
     * @param zoneId    target time zone for display
     * @param dateStyle {@link FormatStyle} for the date portion
     * @param timeStyle {@link FormatStyle} for the time portion
     * @param locale    target {@link Locale}
     */
    @NonNull
    public static String format(
            @NonNull LocalDateTime dateTime,
            @NonNull ZoneId zoneId,
            @NonNull FormatStyle dateStyle,
            @NonNull FormatStyle timeStyle,
            @NonNull Locale locale) {

        Objects.requireNonNull(dateTime, "dateTime == null");
        DateTimeFormatter formatter =
                FormatterCache.obtain(dateStyle, timeStyle, locale, zoneId);
        return formatter.format(dateTime.atZone(zoneId));
    }

    /**
     * Shortcut for {@link #format(LocalDateTime, ZoneId, FormatStyle, FormatStyle, Locale)}
     * using the device's default zone and locale.
     */
    @NonNull
    public static String format(
            @NonNull LocalDateTime dateTime,
            @NonNull FormatStyle dateStyle,
            @NonNull FormatStyle timeStyle) {

        return format(
                dateTime,
                ZoneId.systemDefault(),
                dateStyle,
                timeStyle,
                Locale.getDefault());
    }

    /**
     * Convenience wrapper around {@link android.text.format.DateUtils#getRelativeTimeSpanString}
     * that produces human-friendly strings such as
     * "Just now", "5 minutes ago", "Yesterday", etc.
     *
     * @param context   Android context
     * @param instant   the point in time to describe
     * @param abbreviateThresholdMillis  if &gt; 0, the method will abbreviate
     *                                   units when the delta is greater than
     *                                   the supplied value (e.g., "2 hrs" instead
     *                                   of "2 hours").  Pass 0 to disable.
     */
    @NonNull
    public static CharSequence toRelativeTime(
            @NonNull Context context,
            @NonNull Instant instant,
            long abbreviateThresholdMillis) {

        Objects.requireNonNull(context, "context == null");
        Objects.requireNonNull(instant, "instant == null");

        long now = System.currentTimeMillis();
        long time = instant.toEpochMilli();
        int flags = DateUtils.FORMAT_ABBREV_RELATIVE;
        if (abbreviateThresholdMillis <= 0) {
            flags = 0; // disable abbreviation
        }
        return DateUtils.getRelativeTimeSpanString(
                time,
                now,
                DateUtils.MINUTE_IN_MILLIS,
                flags);
    }

    /**
     * Same as {@link #toRelativeTime(Context, Instant, long)} with abbreviation enabled
     * after one hour.
     */
    @NonNull
    public static CharSequence toRelativeTime(@NonNull Context ctx, @NonNull Instant instant) {
        return toRelativeTime(ctx, instant, DateUtils.HOUR_IN_MILLIS);
    }

    /* *******************************
     * Private implementation details
     * *******************************/

    private DateFormatter() {
        // no-op
    }

    private static final DateTimeFormatter ISO_INSTANT = DateTimeFormatter.ISO_INSTANT;
    private static final DateTimeFormatter ISO_DATE    = DateTimeFormatter.ISO_LOCAL_DATE;

    /**
     * Light-weight cache for expensive {@link DateTimeFormatter} instances.
     * Keys are immutable and include date/time style, locale, and zone ID.
     */
    private static final class FormatterCache {

        private static final ConcurrentMap<Key, DateTimeFormatter> CACHE =
                new ConcurrentHashMap<>();

        private FormatterCache() {
        }

        @NonNull
        static DateTimeFormatter obtain(
                @NonNull FormatStyle dateStyle,
                @NonNull FormatStyle timeStyle,
                @NonNull Locale locale,
                @NonNull ZoneId zoneId) {

            Key key = new Key(dateStyle, timeStyle, locale, zoneId);

            // Return cached formatter or compute a new one atomically.
            return CACHE.computeIfAbsent(key, k ->
                    DateTimeFormatter
                            .ofLocalizedDateTime(k.dateStyle, k.timeStyle)
                            .withLocale(k.locale)
                            .withZone(k.zoneId));
        }

        /**
         * Immutable cache key
         */
        private static final class Key {
            final FormatStyle dateStyle;
            final FormatStyle timeStyle;
            final Locale locale;
            final ZoneId zoneId;

            Key(FormatStyle dateStyle,
                FormatStyle timeStyle,
                Locale locale,
                ZoneId zoneId) {

                this.dateStyle = dateStyle;
                this.timeStyle = timeStyle;
                this.locale = locale;
                this.zoneId = zoneId;
            }

            @Override
            public boolean equals(@Nullable Object o) {
                if (this == o) return true;
                if (!(o instanceof Key other)) return false;
                return dateStyle == other.dateStyle &&
                       timeStyle == other.timeStyle &&
                       locale.equals(other.locale) &&
                       zoneId.equals(other.zoneId);
            }

            @Override
            public int hashCode() {
                int result = dateStyle.hashCode();
                result = 31 * result + timeStyle.hashCode();
                result = 31 * result + locale.hashCode();
                result = 31 * result + zoneId.hashCode();
                return result;
            }
        }
    }
}