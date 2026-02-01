package com.wellsphere.connect.util;

import android.content.ContentResolver;
import android.content.Context;
import android.database.Cursor;
import android.graphics.Bitmap;
import android.graphics.Bitmap.CompressFormat;
import android.graphics.BitmapFactory;
import android.graphics.Matrix;
import android.net.Uri;
import android.os.Build;
import android.os.Environment;
import android.provider.MediaStore;
import android.provider.OpenableColumns;
import android.util.Log;

import androidx.annotation.IntRange;
import androidx.annotation.NonNull;
import androidx.annotation.Nullable;
import androidx.exifinterface.media.ExifInterface;

import java.io.BufferedInputStream;
import java.io.BufferedOutputStream;
import java.io.Closeable;
import java.io.File;
import java.io.FileDescriptor;
import java.io.FileInputStream;
import java.io.FileOutputStream;
import java.io.IOException;

/**
 * Utility class that provides a collection of static helpers to perform common
 * image manipulation tasks (scaling, rotating, compression, etc.).<p>
 *
 * The code is optimised for the requirements of the WellSphere Connect app:
 * <ol>
 *     <li>Images coming from different sources (camera, gallery, cloud storage) may carry
 *     incorrect EXIF orientation data.</li>
 *     <li>Uploads to the backend EHR need to be throttled to a predictable file size, while
 *     still retaining diagnostic quality for wound-care review.</li>
 *     <li>Operations must be memory-safe on low-end devices.</li>
 * </ol>
 *
 * NOTE: All time-intensive methods are <b>synchronous</b>. Consider off-loading
 * execution to a worker thread / coroutine from the calling layer.
 */
@SuppressWarnings({"unused", "WeakerAccess"})
public final class ImageUtils {

    //region Public configuration defaults
    public static final int DEFAULT_MAX_WIDTH       = 1920; // px
    public static final int DEFAULT_MAX_HEIGHT      = 1080; // px
    public static final int DEFAULT_COMPRESS_QUALITY = 85;  // %
    public static final long DEFAULT_TARGET_FILE_SIZE = 500 * 1024; // 500 KiB
    //endregion

    private static final String TAG = "ImageUtils";
    private static final int IO_BUFFER_SIZE = 16 * 1024;

    private ImageUtils() {
        // Utility class
    }

    /**
     * High-level convenience API that takes an image {@link Uri}, applies down-scaling,
     * orientation correction, and iterative compression until the resulting file fits
     * inside <code>targetBytes</code>. The processed image is stored inside the app-specific
     * cache directory and returned as a {@link File} instance.
     *
     * @param context      Android context.
     * @param source       Original image Uri (content://, file://, etc.).
     * @param reqWidthPx   Desired maximum width after scaling.
     * @param reqHeightPx  Desired maximum height after scaling.
     * @param targetBytes  Target byte size. The algorithm will gradually reduce JPEG
     *                     quality until the file is smaller than this value or the
     *                     quality floor is reached.
     * @return A new {@link File} pointing to the processed image. <code>null</code> if the
     * image could not be processed.
     */
    @Nullable
    public static File prepareImageForUpload(@NonNull Context context,
                                             @NonNull Uri source,
                                             int reqWidthPx,
                                             int reqHeightPx,
                                             long targetBytes) {
        Bitmap decoded = null;
        File tempFile = null;

        try {
            decoded = decodeBitmapFromUri(context, source, reqWidthPx, reqHeightPx);
            if (decoded == null) {
                Log.w(TAG, "Bitmap decoding failed – bitmap is null");
                return null;
            }

            decoded = rotateBitmapIfRequired(context, decoded, source);

            String tmpName = "IMG_" + System.currentTimeMillis() + ".jpg";
            tempFile = createTempFile(context, tmpName);

            boolean success = compressBitmapToFile(decoded, tempFile, targetBytes, DEFAULT_COMPRESS_QUALITY);
            if (!success) {
                // Clean-up failed result
                if (tempFile != null && tempFile.exists() && !tempFile.delete()) {
                    Log.w(TAG, "Temp file deletion failed: " + tempFile.getAbsolutePath());
                }
                tempFile = null;
            }
            return tempFile;
        } catch (Exception e) {
            Log.e(TAG, "Image processing failed", e);
            if (tempFile != null && tempFile.exists()) {
                //noinspection ResultOfMethodCallIgnored
                tempFile.delete();
            }
            return null;
        } finally {
            if (decoded != null) {
                decoded.recycle();
            }
        }
    }

    /**
     * Decode a bitmap from a given Uri, respecting the supplied max width/height.
     * This method attempts to keep memory footprint minimal by first reading only
     * the bounds and calculating an <code>inSampleSize</code>.
     */
    @Nullable
    public static Bitmap decodeBitmapFromUri(@NonNull Context context,
                                             @NonNull Uri uri,
                                             int reqWidthPx,
                                             int reqHeightPx) throws IOException {

        ContentResolver resolver = context.getContentResolver();
        if (resolver == null) {
            return null;
        }

        BitmapFactory.Options options = new BitmapFactory.Options();
        options.inJustDecodeBounds = true;

        // First pass — read size only
        BufferedInputStream bis1 = new BufferedInputStream(resolver.openInputStream(uri));
        try {
            BitmapFactory.decodeStream(bis1, null, options);
        } finally {
            closeSilently(bis1);
        }

        // Calculate down-sampling ratio
        options.inSampleSize = calculateInSampleSize(options, reqWidthPx, reqHeightPx);

        // Second pass — read actual bitmap
        options.inJustDecodeBounds = false;
        options.inPreferredConfig = Bitmap.Config.ARGB_8888;

        BufferedInputStream bis2 = new BufferedInputStream(resolver.openInputStream(uri));
        try {
            return BitmapFactory.decodeStream(bis2, null, options);
        } finally {
            closeSilently(bis2);
        }
    }

    /**
     * Corrects the orientation of the bitmap based on the EXIF metadata embedded
     * either inside the file or provided by the MediaStore.
     */
    @NonNull
    public static Bitmap rotateBitmapIfRequired(@NonNull Context context,
                                                @NonNull Bitmap bitmap,
                                                @NonNull Uri srcUri) {

        int rotationDegrees = getImageRotationDegrees(context, srcUri);
        if (rotationDegrees == 0) {
            return bitmap;
        }

        Matrix matrix = new Matrix();
        matrix.postRotate(rotationDegrees);
        Bitmap rotated = Bitmap.createBitmap(bitmap, 0, 0,
                bitmap.getWidth(), bitmap.getHeight(), matrix, true);
        bitmap.recycle();
        return rotated;
    }

    /**
     * Tries to retrieve the rotation angle in degrees from both EXIF data (file path) and
     * MediaStore. Returns 0 if the information is unavailable.
     */
    private static int getImageRotationDegrees(@NonNull Context context, @NonNull Uri uri) {
        int orientation = 0;
        try {
            if ("content".equalsIgnoreCase(uri.getScheme())) {
                String[] projection = {MediaStore.Images.ImageColumns.ORIENTATION};
                Cursor cursor = context.getContentResolver().query(uri, projection, null, null, null);
                if (cursor != null) {
                    if (cursor.moveToFirst()) {
                        orientation = cursor.getInt(0);
                    }
                    cursor.close();
                }
            } else if ("file".equalsIgnoreCase(uri.getScheme())) {
                String path = uri.getPath();
                if (path != null) {
                    ExifInterface ei = new ExifInterface(path);
                    int exifOrientation = ei.getAttributeInt(ExifInterface.TAG_ORIENTATION,
                            ExifInterface.ORIENTATION_NORMAL);
                    switch (exifOrientation) {
                        case ExifInterface.ORIENTATION_ROTATE_90:
                            orientation = 90;
                            break;
                        case ExifInterface.ORIENTATION_ROTATE_180:
                            orientation = 180;
                            break;
                        case ExifInterface.ORIENTATION_ROTATE_270:
                            orientation = 270;
                            break;
                        default:
                            orientation = 0;
                    }
                }
            }
        } catch (Exception e) {
            Log.w(TAG, "Unable to obtain rotation for URI " + uri, e);
        }
        return orientation;
    }

    /**
     * Compresses a bitmap to the given file. The method will iterate over the quality
     * parameter (starting at <code>initialQuality</code>) until the file size
     * is ≤ <code>targetBytes</code> or quality falls below 40 %.
     *
     * @return <code>true</code> if the bitmap was successfully written to disk.
     */
    public static boolean compressBitmapToFile(@NonNull Bitmap bitmap,
                                               @NonNull File destFile,
                                               long targetBytes,
                                               @IntRange(from = 30, to = 100) int initialQuality) {
        if (targetBytes <= 0) {
            targetBytes = DEFAULT_TARGET_FILE_SIZE;
        }

        int quality = initialQuality;
        boolean success;
        FileOutputStream fos = null;

        try {
            do {
                fos = new FileOutputStream(destFile, false);
                bitmap.compress(CompressFormat.JPEG, quality, fos);
                fos.flush();
                long fileLen = destFile.length();

                if (fileLen <= targetBytes || quality <= 40) {
                    success = true;
                    break;
                } else {
                    // Retry with lower quality
                    quality -= 5;
                    fos.close();
                }
            } while (quality > 35);

            return success = destFile.exists() && destFile.length() <= targetBytes;
        } catch (IOException ioe) {
            Log.e(TAG, "Bitmap compression failed", ioe);
            return false;
        } finally {
            closeSilently(fos);
        }
    }

    /**
     * Creates an app-private temporary file inside the cache directory.
     */
    @NonNull
    public static File createTempFile(@NonNull Context context, @NonNull String fileName) throws IOException {
        File cacheDir = context.getCacheDir();
        if (!cacheDir.exists() && !cacheDir.mkdirs()) {
            throw new IOException("Unable to create cache directory at " + cacheDir.getAbsolutePath());
        }

        File tempFile = new File(cacheDir, fileName);
        if (tempFile.exists() && !tempFile.delete()) {
            Log.w(TAG, "Failed to delete existing temp file: " + tempFile.getAbsolutePath());
        }
        if (!tempFile.createNewFile()) {
            throw new IOException("Failed to create temp file at " + tempFile.getAbsolutePath());
        }
        return tempFile;
    }

    /**
     * Calculate an <code>inSampleSize</code> to be used with {@link BitmapFactory.Options}.
     * The goal is to load the smallest possible image into memory that is still big enough
     * for the requested display/processing size.
     */
    public static int calculateInSampleSize(@NonNull BitmapFactory.Options options,
                                            int reqWidthPx,
                                            int reqHeightPx) {

        int height = options.outHeight;
        int width = options.outWidth;
        int inSampleSize = 1;

        if (height > reqHeightPx || width > reqWidthPx) {
            final int halfHeight = height / 2;
            final int halfWidth = width / 2;

            // Calculate the largest inSampleSize that keeps both
            // height and width larger than the requested height and width.
            while ((halfHeight / inSampleSize) >= reqHeightPx
                    && (halfWidth / inSampleSize) >= reqWidthPx) {
                inSampleSize *= 2;
            }
        }
        return inSampleSize;
    }

    /**
     * Copies the contents of the provided {@link Uri} into <code>destination</code>.
     *
     * @return <code>true</code> if the copy operation succeeded.
     */
    public static boolean copyUriToFile(@NonNull Context context,
                                        @NonNull Uri source,
                                        @NonNull File destination) {

        ContentResolver resolver = context.getContentResolver();
        if (resolver == null) return false;

        try (BufferedInputStream in = new BufferedInputStream(resolver.openInputStream(source));
             BufferedOutputStream out = new BufferedOutputStream(new FileOutputStream(destination))) {

            byte[] buffer = new byte[IO_BUFFER_SIZE];
            int len;
            while ((len = in.read(buffer)) != -1) {
                out.write(buffer, 0, len);
            }
            out.flush();
            return true;
        } catch (IOException e) {
            Log.e(TAG, "Error copying URI to file", e);
            return false;
        }
    }

    /**
     * Retrieves the display name (file name) for a given {@link Uri}.
     * Returns <code>null</code> when unavailable.
     */
    @Nullable
    public static String getDisplayName(@NonNull Context context, @NonNull Uri uri) {
        if (!"content".equals(uri.getScheme())) {
            return new File(uri.getPath()).getName();
        }

        Cursor cursor = context.getContentResolver().query(
                uri, new String[]{OpenableColumns.DISPLAY_NAME}, null, null, null);

        if (cursor != null) {
            try {
                if (cursor.moveToFirst()) {
                    return cursor.getString(0);
                }
            } finally {
                cursor.close();
            }
        }
        return null;
    }

    /**
     * Deletes all files generated by {@link #prepareImageForUpload(Context, Uri, int, int, long)}
     * that are older than <code>maxAgeMillis</code>.
     *
     * @param maxAgeMillis Time-to-live in milliseconds.
     */
    public static void purgeStaleTempImages(@NonNull Context context, long maxAgeMillis) {
        File cacheDir = context.getCacheDir();
        if (cacheDir == null || !cacheDir.exists()) {
            return;
        }

        long now = System.currentTimeMillis();
        for (File file : cacheDir.listFiles()) {
            if (file == null) continue;
            if (!file.getName().startsWith("IMG_")) continue; // ours?
            long age = now - file.lastModified();
            if (age > maxAgeMillis) {
                //noinspection ResultOfMethodCallIgnored
                file.delete();
            }
        }
    }

    /**
     * Silently closes a {@link Closeable}, swallowing any unchecked exception.
     */
    private static void closeSilently(@Nullable Closeable c) {
        if (c != null) {
            try { c.close(); } catch (Exception ignored) { }
        }
    }
}