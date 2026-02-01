```java
package com.wellsphere.connect.ui.journal;

import android.Manifest;
import android.content.Context;
import android.content.Intent;
import android.content.pm.PackageManager;
import android.graphics.drawable.ColorDrawable;
import android.location.Location;
import android.net.Uri;
import android.os.Bundle;
import android.os.Parcelable;
import android.provider.MediaStore;
import android.view.MenuItem;
import android.view.View;
import android.widget.Toast;

import androidx.activity.result.ActivityResultCallback;
import androidx.activity.result.ActivityResultLauncher;
import androidx.activity.result.contract.ActivityResultContracts;
import androidx.annotation.ColorInt;
import androidx.annotation.NonNull;
import androidx.annotation.Nullable;
import androidx.appcompat.app.AppCompatActivity;
import androidx.biometric.BiometricPrompt;
import androidx.core.app.ActivityCompat;
import androidx.core.content.ContextCompat;
import androidx.core.content.FileProvider;
import androidx.lifecycle.ViewModelProvider;

import com.google.android.gms.location.FusedLocationProviderClient;
import com.google.android.gms.location.LocationServices;
import com.google.android.material.snackbar.Snackbar;
import com.wellsphere.connect.BuildConfig;
import com.wellsphere.connect.R;
import com.wellsphere.connect.databinding.ActivityNewJournalEntryBinding;
import com.wellsphere.connect.model.Attachment;
import com.wellsphere.connect.model.JournalEntry;
import com.wellsphere.connect.util.DateTimeUtils;
import com.wellsphere.connect.util.FileUtils;
import com.wellsphere.connect.util.ViewUtils;
import com.wellsphere.connect.viewmodel.journal.NewJournalEntryViewModel;

import java.io.File;
import java.util.ArrayList;
import java.util.List;
import java.util.concurrent.Executor;
import java.util.concurrent.Executors;

/**
 * Activity responsible for creating a new {@link JournalEntry}. Handles text entry,
 * media capture/selection, location tagging, biometric validation and persistence
 * through {@link NewJournalEntryViewModel}.
 *
 * The UI is fully driven by LiveData exposed from the ViewModel. Errors are surfaced
 * via Snackbars while critical errors are also logged through the crash-reporting
 * pipeline enabled in the application layer.
 */
public class NewJournalEntryActivity extends AppCompatActivity {

    //region Constants & Keys
    private static final String EXTRA_PHOTO_URI = "extra_photo_uri";
    private static final String KEY_PENDING_ATTACHMENTS = "key_pending_attachments";
    //endregion

    //region View / Binding
    private ActivityNewJournalEntryBinding binding;
    //endregion

    //region ViewModel
    private NewJournalEntryViewModel viewModel;
    //endregion

    //region Location
    private FusedLocationProviderClient fusedLocationClient;
    //endregion

    //region Launchers & Permissions
    private ActivityResultLauncher<Uri> takePictureLauncher;
    private ActivityResultLauncher<String> requestCameraPermissionLauncher;
    private ActivityResultLauncher<String> requestLocationPermissionLauncher;
    private ActivityResultLauncher<String> pickImageLauncher;
    //endregion

    //region Runtime state
    private Uri pendingCameraPhotoUri;
    private final List<Attachment> pendingAttachments = new ArrayList<>();
    //endregion

    //region Executors
    private final Executor biometricExecutor = Executors.newSingleThreadExecutor();
    //endregion

    @Override
    protected void onCreate(@Nullable Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);

        binding = ActivityNewJournalEntryBinding.inflate(getLayoutInflater());
        setContentView(binding.getRoot());

        supportPostponeEnterTransition(); // smooth shared element transition

        setSupportActionBar(binding.toolbar);
        getSupportActionBar().setDisplayHomeAsUpEnabled(true);

        initViewModel();
        initActivityResultLaunchers();
        initLocationClient();
        restoreInstanceState(savedInstanceState);
        initViewListeners();
        observeViewModel();

        supportStartPostponedEnterTransition();
    }

    //region Initialization helpers
    private void initViewModel() {
        viewModel = new ViewModelProvider(this,
                ViewModelProvider.AndroidViewModelFactory.getInstance(getApplication()))
                .get(NewJournalEntryViewModel.class);
    }

    private void initActivityResultLaunchers() {
        takePictureLauncher = registerForActivityResult(
                new ActivityResultContracts.TakePicture(),
                result -> {
                    if (result != null && result) {
                        addAttachment(Attachment.fromPhoto(pendingCameraPhotoUri));
                    } else {
                        // Delete temp file if capture was cancelled
                        FileUtils.safeDelete(getApplicationContext(), pendingCameraPhotoUri);
                    }
                });

        requestCameraPermissionLauncher = registerForActivityResult(
                new ActivityResultContracts.RequestPermission(),
                granted -> {
                    if (granted) {
                        launchCameraIntent();
                    } else {
                        showIndefiniteSnackbar(getString(R.string.camera_permission_required));
                    }
                });

        requestLocationPermissionLauncher = registerForActivityResult(
                new ActivityResultContracts.RequestPermission(),
                granted -> {
                    if (granted) {
                        fetchLastLocation();
                    } else {
                        showIndefiniteSnackbar(getString(R.string.location_permission_required));
                    }
                });

        pickImageLauncher = registerForActivityResult(
                new ActivityResultContracts.GetContent(),
                uri -> {
                    if (uri != null) {
                        addAttachment(Attachment.fromPhoto(uri));
                    }
                });
    }

    private void initLocationClient() {
        fusedLocationClient = LocationServices.getFusedLocationProviderClient(this);
    }

    private void restoreInstanceState(Bundle savedInstanceState) {
        if (savedInstanceState == null) return;
        final List<Attachment> restored =
                savedInstanceState.getParcelableArrayList(KEY_PENDING_ATTACHMENTS);
        if (restored != null) {
            pendingAttachments.addAll(restored);
            binding.attachmentPreview.setAttachments(pendingAttachments);
        }
    }

    private void initViewListeners() {
        binding.attachmentPreview.setOnRemoveListener(attachment -> {
            pendingAttachments.remove(attachment);
            FileUtils.safeDelete(getApplicationContext(), attachment.getUri());
        });

        binding.addPhotoFab.setOnClickListener(v -> checkCameraPermissionAndLaunch());

        binding.galleryChip.setOnClickListener(v ->
                pickImageLauncher.launch("image/*"));

        binding.addLocationChip.setOnClickListener(v ->
                checkLocationPermissionAndFetch());

        binding.saveEntryFab.setOnClickListener(v ->
                authenticateAndSaveEntry());
    }
    //endregion

    //region ViewModel observers
    private void observeViewModel() {
        viewModel.getSaveState().observe(this, state -> {
            switch (state.getStatus()) {
                case LOADING:
                    binding.progressOverlay.setVisibility(View.VISIBLE);
                    break;
                case SUCCESS:
                    binding.progressOverlay.setVisibility(View.GONE);
                    Toast.makeText(this, R.string.entry_saved, Toast.LENGTH_LONG).show();
                    setResult(RESULT_OK);
                    finishAfterTransition();
                    break;
                case ERROR:
                    binding.progressOverlay.setVisibility(View.GONE);
                    showIndefiniteSnackbar(state.getErrorMessage());
                    break;
            }
        });
    }
    //endregion

    //region Camera flow
    private void checkCameraPermissionAndLaunch() {
        if (ContextCompat.checkSelfPermission(this, Manifest.permission.CAMERA)
                == PackageManager.PERMISSION_GRANTED) {
            launchCameraIntent();
        } else {
            requestCameraPermissionLauncher.launch(Manifest.permission.CAMERA);
        }
    }

    private void launchCameraIntent() {
        try {
            File photoFile = FileUtils.createTempImageFile(this);
            pendingCameraPhotoUri = FileProvider.getUriForFile(
                    this, BuildConfig.APPLICATION_ID + ".provider", photoFile);

            takePictureLauncher.launch(pendingCameraPhotoUri);

        } catch (Exception e) {
            ViewUtils.reportNonFatalCrash(e);
            showIndefiniteSnackbar(getString(R.string.error_opening_camera));
        }
    }
    //endregion

    //region Location flow
    private void checkLocationPermissionAndFetch() {
        if (ContextCompat.checkSelfPermission(this, Manifest.permission.ACCESS_FINE_LOCATION)
                == PackageManager.PERMISSION_GRANTED) {
            fetchLastLocation();
        } else {
            requestLocationPermissionLauncher.launch(Manifest.permission.ACCESS_FINE_LOCATION);
        }
    }

    private void fetchLastLocation() {
        fusedLocationClient.getLastLocation()
                .addOnSuccessListener(this::handleLocationResult)
                .addOnFailureListener(e -> {
                    ViewUtils.reportNonFatalCrash(e);
                    showIndefiniteSnackbar(getString(R.string.error_fetching_location));
                });
    }

    private void handleLocationResult(@Nullable Location location) {
        if (location == null) {
            showIndefiniteSnackbar(getString(R.string.location_unavailable));
            return;
        }
        viewModel.setLocation(location);
        binding.addLocationChip.setText(
                getString(R.string.location_chip_pattern,
                        String.format("%.2f", location.getLatitude()),
                        String.format("%.2f", location.getLongitude())));
        binding.addLocationChip.setChipIconTint(
                ContextCompat.getColorStateList(this, R.color.stateful_chip_icon_tint));
    }
    //endregion

    //region Authentication & Save
    private void authenticateAndSaveEntry() {
        // Short circuit if device has no biometric hardware or user opted out
        if (!BiometricPromptUtils.isBiometricEnrollmentAvailable(this)) {
            persistEntry(); // fallback
            return;
        }

        BiometricPrompt.PromptInfo promptInfo = new BiometricPrompt.PromptInfo.Builder()
                .setTitle(getString(R.string.biometric_prompt_title))
                .setSubtitle(getString(R.string.biometric_prompt_subtitle))
                .setNegativeButtonText(getString(R.string.cancel))
                .build();

        new BiometricPrompt(this, biometricExecutor, new BiometricPrompt.AuthenticationCallback() {
            @Override
            public void onAuthenticationSucceeded(
                    @NonNull BiometricPrompt.AuthenticationResult result) {
                runOnUiThread(NewJournalEntryActivity.this::persistEntry);
            }

            @Override
            public void onAuthenticationError(int errorCode,
                                              @NonNull CharSequence errString) {
                runOnUiThread(() ->
                        showIndefiniteSnackbar(errString.toString()));
            }

            @Override
            public void onAuthenticationFailed() {
                runOnUiThread(() ->
                        showIndefiniteSnackbar(getString(R.string.biometric_auth_failed)));
            }
        }).authenticate(promptInfo);
    }

    private void persistEntry() {
        String content = binding.entryEditText.getText().toString().trim();
        if (content.isEmpty() && pendingAttachments.isEmpty()) {
            showIndefiniteSnackbar(getString(R.string.empty_entry_error));
            return;
        }

        JournalEntry entry = new JournalEntry.Builder()
                .setBody(content)
                .setTimestamp(DateTimeUtils.nowUtc())
                .setAttachments(pendingAttachments)
                .setLocation(viewModel.getLocationLive().getValue())
                .build();

        viewModel.save(entry);
    }
    //endregion

    //region Attachments
    private void addAttachment(@NonNull Attachment attachment) {
        pendingAttachments.add(attachment);
        binding.attachmentPreview.setAttachments(pendingAttachments);
    }
    //endregion

    //region Snackbar helper
    private void showIndefiniteSnackbar(@NonNull String message) {
        Snackbar.make(binding.getRoot(), message, Snackbar.LENGTH_INDEFINITE)
                .setAction(android.R.string.ok, v -> {
                })
                .show();
    }
    //endregion

    //region Toolbar back handling
    @Override
    public boolean onOptionsItemSelected(@NonNull MenuItem item) {
        if (item.getItemId() == android.R.id.home) {
            onBackPressedDispatcher.onBackPressed();
            return true;
        }
        return super.onOptionsItemSelected(item);
    }
    //endregion

    //region State persistence
    @Override
    protected void onSaveInstanceState(@NonNull Bundle outState) {
        outState.putParcelableArrayList(
                KEY_PENDING_ATTACHMENTS,
                new ArrayList<? extends Parcelable>(pendingAttachments));
        super.onSaveInstanceState(outState);
    }
    //endregion
}
```