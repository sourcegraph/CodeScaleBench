package com.wellsphere.connect.ui.capture;

import android.Manifest;
import android.content.ContentValues;
import android.content.Context;
import android.content.Intent;
import android.content.pm.PackageManager;
import android.net.Uri;
import android.os.Build;
import android.os.Bundle;
import android.provider.MediaStore;
import android.view.MenuItem;
import android.view.View;
import android.widget.Toast;

import androidx.activity.result.ActivityResultLauncher;
import androidx.activity.result.contract.ActivityResultContracts;
import androidx.annotation.NonNull;
import androidx.annotation.OptIn;
import androidx.appcompat.app.AlertDialog;
import androidx.appcompat.app.AppCompatActivity;
import androidx.camera.core.Camera;
import androidx.camera.core.CameraSelector;
import androidx.camera.core.ImageCapture;
import androidx.camera.core.ImageCaptureException;
import androidx.camera.core.ImageProxy;
import androidx.camera.core.Preview;
import androidx.camera.core.impl.utils.ExecutorUtils;
import androidx.camera.lifecycle.ProcessCameraProvider;
import androidx.camera.view.PreviewView;
import androidx.core.content.ContextCompat;
import androidx.lifecycle.ViewModelProvider;

import com.google.common.util.concurrent.ListenableFuture;
import com.google.android.material.snackbar.Snackbar;
import com.wellsphere.connect.R;
import com.wellsphere.connect.databinding.ActivityDocumentScannerBinding;

import java.io.File;
import java.text.SimpleDateFormat;
import java.util.Locale;
import java.util.Objects;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;

/**
 * Activity that provides camera-based document capture.
 *
 * The class relies on CameraX for camera access and follows MVVM
 * guidelines by delegating business logic to {@link DocumentScannerViewModel}.
 *
 * Captured document URIs are returned to the calling component via
 * {@link #EXTRA_RESULT_URI}.
 *
 * Usage:
 * <pre>
 * Intent intent = new Intent(context, DocumentScannerActivity.class);
 * startActivityForResult(intent, REQUEST_CODE);
 * </pre>
 * The resulting intent will contain the extra:
 * <pre>
 * intent.getParcelableExtra(DocumentScannerActivity.EXTRA_RESULT_URI);
 * </pre>
 *
 * Note: Make sure the caller has declared CAMERA permission in the Manifest.
 */
public class DocumentScannerActivity extends AppCompatActivity {

    public static final String EXTRA_RESULT_URI =
            "com.wellsphere.connect.EXTRAS.RESULT_URI";

    private static final String TAG = "DocumentScannerActivity";
    private static final String TIMESTAMP_FORMAT = "yyyy-MM-dd_HH-mm-ss-SSS";

    private ActivityDocumentScannerBinding binding;

    // CameraX components
    private ImageCapture imageCapture;
    private ExecutorService cameraExecutor;

    // ViewModel
    private DocumentScannerViewModel viewModel;

    // Permission launcher
    private final ActivityResultLauncher<String> cameraPermissionLauncher =
            registerForActivityResult(new ActivityResultContracts.RequestPermission(),
                    isGranted -> {
                        if (isGranted) {
                            startCamera();
                        } else {
                            showPermissionDeniedDialog();
                        }
                    });

    @Override
    protected void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);
        binding = ActivityDocumentScannerBinding.inflate(getLayoutInflater());
        setContentView(binding.getRoot());

        setupActionBar();
        initViewModel();
        initListeners();
        cameraExecutor = Executors.newSingleThreadExecutor();

        // Request camera permissions
        if (hasCameraPermission()) {
            startCamera();
        } else {
            cameraPermissionLauncher.launch(Manifest.permission.CAMERA);
        }
    }

    @Override
    protected void onDestroy() {
        super.onDestroy();
        if (cameraExecutor != null) {
            cameraExecutor.shutdown();
        }
    }

    private void setupActionBar() {
        setSupportActionBar(binding.toolbar);
        Objects.requireNonNull(getSupportActionBar()).setDisplayHomeAsUpEnabled(true);
        getSupportActionBar().setTitle(R.string.document_scanner_title);
    }

    private void initViewModel() {
        viewModel = new ViewModelProvider(this).get(DocumentScannerViewModel.class);
        viewModel.getIsProcessing().observe(this, isProcessing ->
                binding.progressOverlay.setVisibility(isProcessing ? View.VISIBLE : View.GONE)
        );

        viewModel.getErrorMessage().observe(this, message ->
                Snackbar.make(binding.getRoot(), message, Snackbar.LENGTH_LONG).show()
        );
    }

    private void initListeners() {
        binding.captureButton.setOnClickListener(v -> takePhoto());
        binding.flashToggle.setOnCheckedChangeListener((buttonView, isChecked) -> {
            if (imageCapture != null && imageCapture.getCamera() != null) {
                imageCapture.getCamera().getCameraControl().enableTorch(isChecked);
            }
        });
    }

    /**
     * Returns whether CAMERA permission has been already granted.
     */
    private boolean hasCameraPermission() {
        return ContextCompat.checkSelfPermission(this, Manifest.permission.CAMERA)
                == PackageManager.PERMISSION_GRANTED;
    }

    /**
     * Initializes CameraX preview and capture use cases.
     */
    private void startCamera() {
        final ListenableFuture<ProcessCameraProvider> cameraProviderFuture =
                ProcessCameraProvider.getInstance(this);

        cameraProviderFuture.addListener(() -> {
            try {
                ProcessCameraProvider cameraProvider = cameraProviderFuture.get();

                // Preview
                Preview preview = new Preview.Builder().build();
                preview.setSurfaceProvider(binding.previewView.getSurfaceProvider());

                // Capture
                imageCapture = new ImageCapture.Builder()
                        .setCaptureMode(ImageCapture.CAPTURE_MODE_MINIMIZE_LATENCY)
                        .setTargetRotation(binding.previewView.getDisplay().getRotation())
                        .build();

                // Select back camera as a default
                CameraSelector cameraSelector = CameraSelector.DEFAULT_BACK_CAMERA;

                // Unbind before rebinding
                cameraProvider.unbindAll();
                Camera camera = cameraProvider.bindToLifecycle(
                        this,
                        cameraSelector,
                        preview,
                        imageCapture
                );

                // Sync flash button state
                binding.flashToggle.setChecked(camera.getCameraInfo().hasFlashUnit());
                binding.flashToggle.setEnabled(camera.getCameraInfo().hasFlashUnit());

            } catch (Exception e) {
                viewModel.postError(getString(R.string.document_scanner_camera_init_error));
            }
        }, ContextCompat.getMainExecutor(this));
    }

    /**
     * Captures the current image and delegates processing to {@link DocumentScannerViewModel}.
     */
    private void takePhoto() {
        ImageCapture capture = imageCapture;
        if (capture == null) {
            Snackbar.make(binding.getRoot(), R.string.document_scanner_error_capture_unavailable,
                    Snackbar.LENGTH_SHORT).show();
            return;
        }

        // Create file destination
        String filename = new SimpleDateFormat(TIMESTAMP_FORMAT, Locale.US)
                .format(System.currentTimeMillis());
        ContentValues metadata = new ContentValues();
        metadata.put(MediaStore.Images.Media.DISPLAY_NAME, filename);
        metadata.put(MediaStore.Images.Media.MIME_TYPE, "image/jpeg");

        ImageCapture.OutputFileOptions options;

        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.Q) {
            metadata.put(MediaStore.Images.Media.RELATIVE_PATH, "Pictures/WellSphere");
            options = new ImageCapture.OutputFileOptions.Builder(
                    getContentResolver(),
                    MediaStore.Images.Media.EXTERNAL_CONTENT_URI,
                    metadata
            ).build();
        } else {
            File photoDir = new File(getExternalFilesDir(null), "WellSphere");
            if (!photoDir.exists() && !photoDir.mkdirs()) {
                Snackbar.make(binding.getRoot(),
                        R.string.document_scanner_error_directory, Snackbar.LENGTH_LONG).show();
                return;
            }
            File photoFile = new File(photoDir, filename + ".jpg");
            options = new ImageCapture.OutputFileOptions.Builder(photoFile).build();
        }

        viewModel.setProcessing(true);

        capture.takePicture(options, cameraExecutor, new ImageCapture.OnImageSavedCallback() {
            @Override
            public void onImageSaved(@NonNull ImageCapture.OutputFileResults results) {
                viewModel.setProcessing(false);
                Uri savedUri = results.getSavedUri();

                if (savedUri == null) {
                    runOnUiThread(() ->
                            Snackbar.make(binding.getRoot(),
                                    R.string.document_scanner_error_uri, Snackbar.LENGTH_LONG).show()
                    );
                    return;
                }

                viewModel.processCapturedImage(savedUri, processedUri ->
                        runOnUiThread(() -> returnResult(processedUri))
                );
            }

            @Override
            public void onError(@NonNull ImageCaptureException exception) {
                viewModel.setProcessing(false);
                runOnUiThread(() ->
                        Snackbar.make(binding.getRoot(),
                                R.string.document_scanner_error_capture_failed,
                                Snackbar.LENGTH_LONG).show()
                );
            }
        });
    }

    /**
     * Returns the processed document URI to the caller and finishes Activity.
     *
     * @param resultUri Uri of the processed document
     */
    private void returnResult(@NonNull Uri resultUri) {
        Intent data = new Intent().putExtra(EXTRA_RESULT_URI, resultUri);
        setResult(RESULT_OK, data);
        finish();
    }

    /**
     * Shows a rationale dialog if permission is denied, or a snackbar if permanently denied.
     */
    private void showPermissionDeniedDialog() {
        if (shouldShowRequestPermissionRationale(Manifest.permission.CAMERA)) {
            new AlertDialog.Builder(this)
                    .setTitle(R.string.document_scanner_permission_title)
                    .setMessage(R.string.document_scanner_permission_rationale)
                    .setPositiveButton(android.R.string.ok,
                            (dialog, which) -> cameraPermissionLauncher.launch(Manifest.permission.CAMERA))
                    .setNegativeButton(android.R.string.cancel, (dialog, which) -> finish())
                    .show();
        } else {
            Snackbar.make(binding.getRoot(),
                    R.string.document_scanner_permission_denied, Snackbar.LENGTH_LONG)
                    .setAction(R.string.action_settings, v -> openAppSettings())
                    .show();
        }
    }

    /**
     * Opens app settings to let the user grant camera permission manually.
     */
    private void openAppSettings() {
        Intent intent = new Intent(android.provider.Settings.ACTION_APPLICATION_DETAILS_SETTINGS);
        Uri uri = Uri.fromParts("package", getPackageName(), null);
        intent.setData(uri);
        startActivity(intent);
    }

    @Override
    public boolean onOptionsItemSelected(@NonNull MenuItem item) {
        // Handle toolbar back button
        if (item.getItemId() == android.R.id.home) {
            onBackPressedDispatcher.onBackPressed();
            return true;
        }
        return super.onOptionsItemSelected(item);
    }
}