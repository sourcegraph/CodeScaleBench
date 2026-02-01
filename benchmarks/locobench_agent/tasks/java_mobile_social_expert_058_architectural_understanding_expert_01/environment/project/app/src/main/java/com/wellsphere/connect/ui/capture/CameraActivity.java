```java
package com.wellsphere.connect.ui.capture;

import android.Manifest;
import android.content.Intent;
import android.content.pm.PackageManager;
import android.net.Uri;
import android.os.Build;
import android.os.Bundle;
import android.provider.MediaStore;
import android.util.Log;
import android.view.View;
import android.widget.ImageButton;
import android.widget.Toast;

import androidx.activity.result.ActivityResultLauncher;
import androidx.activity.result.contract.ActivityResultContracts;
import androidx.annotation.MainThread;
import androidx.annotation.NonNull;
import androidx.annotation.Nullable;
import androidx.annotation.RequiresApi;
import androidx.appcompat.app.AppCompatActivity;
import androidx.camera.core.Camera;
import androidx.camera.core.CameraSelector;
import androidx.camera.core.ImageCapture;
import androidx.camera.core.ImageCapture.OutputFileOptions;
import androidx.camera.core.ImageCaptureException;
import androidx.camera.core.Preview;
import androidx.camera.lifecycle.ProcessCameraProvider;
import androidx.camera.view.PreviewView;
import androidx.core.content.ContextCompat;
import androidx.lifecycle.Observer;
import androidx.lifecycle.ViewModelProvider;

import com.google.common.util.concurrent.ListenableFuture;
import com.wellsphere.connect.R;

import java.io.File;
import java.text.SimpleDateFormat;
import java.util.Date;
import java.util.Locale;
import java.util.Objects;
import java.util.UUID;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;

/**
 * CameraActivity acts as a thin View layer in the MVVM stack for image capture.
 * It handles permission management and delegates business logic to CameraCaptureViewModel.
 *
 * The Activity returns a {@link android.net.Uri} pointing to the captured photo via setResult().
 * RESULT_OK   -> Media Uri is attached in {@link android.content.Intent#EXTRA_STREAM}
 * RESULT_CANCELED -> No photo captured
 *
 * Design assumptions:
 * 1. HIPAA compliance – no metadata is sent back until the ViewModel scrubs EXIF headers.
 * 2. Offline friendly – if network is unavailable, image is queued by the repository later.
 * 3. This Activity should be launched with startActivityForResult() or Activity Result API.
 *
 * Author: WellSphere Mobile Team
 */
public class CameraActivity extends AppCompatActivity {

    private static final String TAG = "CameraActivity";

    /** Name of Intent extra signalling which workflow invoked the camera (e.g., "WOUND_CARE") */
    public static final String EXTRA_CAPTURE_CONTEXT = "com.wellsphere.connect.extra.CAPTURE_CONTEXT";

    /** Permissions required for image capture flow */
    private static final String[] REQUIRED_PERMISSIONS =
            new String[]{Manifest.permission.CAMERA,
                         Manifest.permission.WRITE_EXTERNAL_STORAGE};

    private PreviewView previewView;
    private ImageButton shutterButton;
    private ImageButton closeButton;

    private ImageCapture imageCapture;
    private Camera camera;

    private ExecutorService cameraExecutor;
    private ActivityResultLauncher<String[]> permissionLauncher;

    private CameraCaptureViewModel viewModel;

    @Override
    protected void onCreate(@Nullable Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);
        setContentView(R.layout.activity_camera);

        previewView   = findViewById(R.id.camera_preview);
        shutterButton = findViewById(R.id.camera_shutter);
        closeButton   = findViewById(R.id.camera_close);

        cameraExecutor = Executors.newSingleThreadExecutor();

        initPermissionLauncher();
        initViewModel();
        initListeners();

        // Kick-off permission flow as early as possible
        permissionLauncher.launch(REQUIRED_PERMISSIONS);
    }

    /**
     * Initializes ActivityResultLauncher for runtime permission request.
     */
    private void initPermissionLauncher() {
        permissionLauncher = registerForActivityResult(
                new ActivityResultContracts.RequestMultiplePermissions(),
                result -> {
                    boolean allGranted = true;
                    for (Boolean granted : result.values()) {
                        allGranted &= granted;
                    }
                    if (allGranted) {
                        startCamera();
                    } else {
                        Toast.makeText(this,
                                R.string.error_camera_permission_denied,
                                Toast.LENGTH_LONG).show();
                        setResult(RESULT_CANCELED);
                        finish();
                    }
                });
    }

    /**
     * Initializes CameraCaptureViewModel and subscribes to its LiveData streams.
     * All domain behavior (e.g., EXIF scrubbing, repository enqueue) is deferred
     * to the ViewModel/Repository layer to maintain testability and separation of concerns.
     */
    private void initViewModel() {
        viewModel = new ViewModelProvider(this).get(CameraCaptureViewModel.class);

        // Observe when ViewModel finishes processing captured image
        viewModel.getCaptureResult().observe(this, uri -> {
            if (uri != null) {
                Intent data = new Intent()
                        .setData(uri)
                        .addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION);
                data.putExtra(Intent.EXTRA_STREAM, uri);
                setResult(RESULT_OK, data);
            } else {
                setResult(RESULT_CANCELED);
            }
            finish();
        });
    }

    /**
     * Wires UI listeners after basic inflation and ViewModel initialization.
     */
    private void initListeners() {
        shutterButton.setOnClickListener(v -> takePhoto());

        closeButton.setOnClickListener(v -> {
            setResult(RESULT_CANCELED);
            finish();
        });
    }

    /**
     * Starts CameraX by binding Preview + ImageCapture use cases to activity lifecycle.
     */
    private void startCamera() {
        ListenableFuture<ProcessCameraProvider> cameraProviderFuture =
                ProcessCameraProvider.getInstance(this);

        cameraProviderFuture.addListener(() -> {
            try {
                ProcessCameraProvider cameraProvider = cameraProviderFuture.get();

                // Preview Use Case
                Preview preview = new Preview.Builder()
                        .build();

                // Image Capture Use Case
                imageCapture = new ImageCapture.Builder()
                        .setCaptureMode(ImageCapture.CAPTURE_MODE_MINIMIZE_LATENCY)
                        .setJpegQuality(92) // Choose balance between quality and size
                        .build();

                // Select rear camera as default
                CameraSelector cameraSelector = CameraSelector.DEFAULT_BACK_CAMERA;

                // Unbind before rebinding
                cameraProvider.unbindAll();

                camera = cameraProvider.bindToLifecycle(
                        this,
                        cameraSelector,
                        preview,
                        imageCapture
                );

                preview.setSurfaceProvider(previewView.getSurfaceProvider());

            } catch (Exception e) {
                Log.e(TAG, "Unable to start camera: " + e.getMessage(), e);
                Toast.makeText(this,
                        R.string.error_camera_initialization,
                        Toast.LENGTH_LONG).show();
                setResult(RESULT_CANCELED);
                finish();
            }
        }, ContextCompat.getMainExecutor(this));
    }

    /**
     * Captures photo with CameraX, delegates post-processing to ViewModel.
     */
    @MainThread
    private void takePhoto() {
        // Guard clause – should never be null if camera initialised correctly
        if (imageCapture == null) {
            Log.w(TAG, "ImageCapture use-case has not been set up yet.");
            return;
        }

        File photoFile = createPhotoFile();

        OutputFileOptions outputOptions = new OutputFileOptions.Builder(photoFile).build();

        shutterButton.setEnabled(false); // De-bounce rapid taps

        imageCapture.takePicture(
                outputOptions,
                cameraExecutor,
                new ImageCapture.OnImageSavedCallback() {
                    @Override
                    public void onImageSaved(@NonNull OutputFileResults output) {
                        Uri savedUri = output.getSavedUri() != null
                                ? output.getSavedUri()
                                : Uri.fromFile(photoFile);

                        Log.d(TAG, "Photo captured: " + savedUri);

                        runOnUiThread(() -> shutterButton.setEnabled(true));

                        // Delegate heavy work (EXIF scrub, encryption, repository enqueue)
                        viewModel.onPhotoCaptured(savedUri,
                                getIntent().getStringExtra(EXTRA_CAPTURE_CONTEXT));
                    }

                    @Override
                    public void onError(@NonNull ImageCaptureException exception) {
                        Log.e(TAG, "Image capture failed: " + exception.getMessage(), exception);
                        runOnUiThread(() -> {
                            shutterButton.setEnabled(true);
                            Toast.makeText(CameraActivity.this,
                                    R.string.error_capture_failed,
                                    Toast.LENGTH_LONG).show();
                        });
                    }
                });
    }

    /**
     * Generates an immutable File for saving captured image.
     * Naming strategy: <context>_<yyyyMMdd_HHmmss>_<UUID>.jpg to ensure uniqueness.
     */
    @NonNull
    private File createPhotoFile() {
        String contextPrefix = Objects.requireNonNullElse(
                getIntent().getStringExtra(EXTRA_CAPTURE_CONTEXT),
                "IMG");

        String timeStamp = new SimpleDateFormat("yyyyMMdd_HHmmss", Locale.US)
                .format(new Date());

        String fileName = contextPrefix + "_" + timeStamp + "_" +
                UUID.randomUUID().toString().substring(0, 8) + ".jpg";

        File storageDir = getExternalFilesDir(null /* Pictures root inside app sandbox */);
        //noinspection ResultOfMethodCallIgnored
        storageDir.mkdirs();

        return new File(storageDir, fileName);
    }

    @Override
    protected void onDestroy() {
        super.onDestroy();
        if (cameraExecutor != null) {
            cameraExecutor.shutdown();
        }
    }
}
```
