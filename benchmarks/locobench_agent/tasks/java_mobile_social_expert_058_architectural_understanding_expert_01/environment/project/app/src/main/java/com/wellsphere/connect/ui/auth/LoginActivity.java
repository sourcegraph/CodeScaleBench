```java
package com.wellsphere.connect.ui.auth;

import android.content.Intent;
import android.os.Bundle;
import android.text.Editable;
import android.text.TextWatcher;
import android.view.inputmethod.EditorInfo;
import android.widget.Toast;

import androidx.activity.result.ActivityResultLauncher;
import androidx.activity.result.contract.ActivityResultContracts.StartActivityForResult;
import androidx.annotation.NonNull;
import androidx.annotation.VisibleForTesting;
import androidx.appcompat.app.AppCompatActivity;
import androidx.biometric.BiometricManager;
import androidx.biometric.BiometricPrompt;
import androidx.core.content.ContextCompat;
import androidx.lifecycle.ViewModelProvider;

import com.google.android.material.snackbar.Snackbar;
import com.wellsphere.connect.BuildConfig;
import com.wellsphere.connect.R;
import com.wellsphere.connect.databinding.ActivityLoginBinding;
import com.wellsphere.connect.ui.home.HomeActivity;
import com.wellsphere.connect.util.AnalyticsLogger;
import com.wellsphere.connect.util.DisabledClickListener;
import com.wellsphere.connect.util.NetworkUtils;
import com.wellsphere.connect.util.Resource;
import com.wellsphere.connect.util.ViewModelFactory;

import java.util.concurrent.Executor;

/**
 * LoginActivity is the entry point for authentication.  It supports both credential-based
 * and biometric authentication.  All UI logic is kept lean, delegating domain work to
 * {@link LoginViewModel}.
 */
public class LoginActivity extends AppCompatActivity {

    private ActivityLoginBinding binding;
    private LoginViewModel viewModel;

    private BiometricPrompt biometricPrompt;
    private BiometricPrompt.PromptInfo promptInfo;
    private Executor mainExecutor;

    /* ActivityResult API launcher for going to system settings when biometric is not set up */
    private final ActivityResultLauncher<Intent> biometricEnrollLauncher =
            registerForActivityResult(new StartActivityForResult(), result -> showBiometricPromptIfPossible());

    /* ------------------------- Activity lifecycle ------------------------- */

    @Override
    protected void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);

        // ViewBinding
        binding = ActivityLoginBinding.inflate(getLayoutInflater());
        setContentView(binding.getRoot());

        initViewModel();
        initBiometric();
        initListeners();
        initObservers();

        if (BuildConfig.DEBUG) {
            prefillDebugCredentials();
        }
    }

    /* ------------------------- Initialization ------------------------- */

    /**
     * Instantiate view model with factory to enable constructor injection.
     */
    private void initViewModel() {
        ViewModelFactory factory = ViewModelFactory.getInstance(getApplication());
        viewModel = new ViewModelProvider(this, factory).get(LoginViewModel.class);
    }

    /**
     * Prepare {@link BiometricPrompt} with callbacks.
     */
    private void initBiometric() {
        mainExecutor = ContextCompat.getMainExecutor(this);
        biometricPrompt = new BiometricPrompt(this, mainExecutor, new BiometricCallback());

        promptInfo = new BiometricPrompt.PromptInfo.Builder()
                .setTitle(getString(R.string.biometric_title))
                .setSubtitle(getString(R.string.biometric_subtitle))
                .setNegativeButtonText(getString(android.R.string.cancel))
                .build();

        // Show biometric prompt automatically when activity starts and user opted-in
        showBiometricPromptIfPossible();
    }

    /**
     * Set listeners on views.
     */
    private void initListeners() {
        binding.btnLogin.setOnClickListener(new DisabledClickListener(1000L) {
            @Override
            public void onSafeClick() {
                attemptLogin();
            }
        });

        binding.textForgotPassword.setOnClickListener(v ->
                Snackbar.make(binding.getRoot(), R.string.feature_coming_soon, Snackbar.LENGTH_LONG).show());

        // Trigger login from soft keyboard 'Done'
        binding.inputPassword.setOnEditorActionListener((v, actionId, event) -> {
            if (actionId == EditorInfo.IME_ACTION_DONE) {
                attemptLogin();
                return true;
            }
            return false;
        });

        // Enable/Disable login button dynamically
        TextWatcher textWatcher = new SimpleTextWatcher() {
            @Override
            public void onTextChanged(CharSequence s, int start, int before, int count) {
                toggleLoginButtonState();
            }
        };

        binding.inputEmail.addTextChangedListener(textWatcher);
        binding.inputPassword.addTextChangedListener(textWatcher);
    }

    /**
     * Observe LiveData from ViewModel.
     */
    private void initObservers() {
        viewModel.getLoginState().observe(this, resource -> {
            switch (resource.getStatus()) {
                case LOADING:
                    binding.progressCircular.show();
                    break;
                case SUCCESS:
                    binding.progressCircular.hide();
                    handleLoginSuccess();
                    break;
                case ERROR:
                    binding.progressCircular.hide();
                    handleLoginError(resource.getMessage());
                    break;
            }
        });
    }

    /* ------------------------- UI helpers ------------------------- */

    private void attemptLogin() {
        if (!NetworkUtils.isNetworkAvailable(this)) {
            Snackbar.make(binding.getRoot(), R.string.error_no_network, Snackbar.LENGTH_LONG).show();
            return;
        }

        String email = binding.inputEmail.getText() != null ? binding.inputEmail.getText().toString().trim() : "";
        String password = binding.inputPassword.getText() != null ? binding.inputPassword.getText().toString() : "";

        if (email.isEmpty() || password.isEmpty()) {
            Toast.makeText(this, R.string.error_empty_credentials, Toast.LENGTH_SHORT).show();
            return;
        }

        viewModel.login(email, password, binding.checkboxRememberMe.isChecked());
    }

    private void toggleLoginButtonState() {
        String email = binding.inputEmail.getText() != null ? binding.inputEmail.getText().toString().trim() : "";
        String password = binding.inputPassword.getText() != null ? binding.inputPassword.getText().toString() : "";
        binding.btnLogin.setEnabled(!email.isEmpty() && !password.isEmpty());
    }

    private void handleLoginSuccess() {
        AnalyticsLogger.logEvent("login_success");
        // Navigate to home screen and clear back stack.
        Intent intent = new Intent(this, HomeActivity.class);
        intent.setFlags(Intent.FLAG_ACTIVITY_NEW_TASK | Intent.FLAG_ACTIVITY_CLEAR_TASK);
        startActivity(intent);
    }

    private void handleLoginError(String message) {
        Snackbar.make(binding.getRoot(),
                message != null ? message : getString(R.string.error_generic),
                Snackbar.LENGTH_LONG)
                .setAction(R.string.retry, v -> attemptLogin())
                .show();
        AnalyticsLogger.logEvent("login_error", "message", message);
    }

    /* ------------------------- Biometric helpers ------------------------- */

    /**
     * Checks biometric availability & user preference, then opens system prompts accordingly.
     */
    private void showBiometricPromptIfPossible() {
        if (!viewModel.isBiometricEnabled()) {
            return; // user disabled in settings
        }

        BiometricManager biometricManager = BiometricManager.from(this);
        switch (biometricManager.canAuthenticate(BiometricManager.Authenticators.BIOMETRIC_STRONG)) {
            case BiometricManager.BIOMETRIC_SUCCESS:
                biometricPrompt.authenticate(promptInfo);
                break;
            case BiometricManager.BIOMETRIC_ERROR_NONE_ENROLLED:
                // Ask user to enroll biometrics
                Intent enrollIntent = new Intent(android.provider.Settings.ACTION_BIOMETRIC_ENROLL);
                biometricEnrollLauncher.launch(enrollIntent);
                break;
            case BiometricManager.BIOMETRIC_ERROR_NO_HARDWARE:
            case BiometricManager.BIOMETRIC_ERROR_HW_UNAVAILABLE:
            default:
                // No-op; fallback to password
                break;
        }
    }

    /* ------------------------- Utility ------------------------- */

    /**
     * Pre-fill debug credentials for faster QA cycles.
     */
    private void prefillDebugCredentials() {
        binding.inputEmail.setText("john.doe@wellsphere.dev");
        binding.inputPassword.setText("Password123!");
        toggleLoginButtonState();
    }

    /* ------------------------- Inner classes ------------------------- */

    /**
     * Handle biometric authentication callbacks.
     */
    private class BiometricCallback extends BiometricPrompt.AuthenticationCallback {
        @Override
        public void onAuthenticationSucceeded(@NonNull BiometricPrompt.AuthenticationResult result) {
            super.onAuthenticationSucceeded(result);
            AnalyticsLogger.logEvent("biometric_auth_success");
            viewModel.loginWithBiometrics();
        }

        @Override
        public void onAuthenticationError(int errorCode, @NonNull CharSequence errString) {
            super.onAuthenticationError(errorCode, errString);
            if (errorCode != BiometricPrompt.ERROR_NEGATIVE_BUTTON) {
                Snackbar.make(binding.getRoot(), errString, Snackbar.LENGTH_LONG).show();
                AnalyticsLogger.logEvent("biometric_auth_error", "code", String.valueOf(errorCode));
            }
        }

        @Override
        public void onAuthenticationFailed() {
            super.onAuthenticationFailed();
            Snackbar.make(binding.getRoot(), R.string.biometric_failed, Snackbar.LENGTH_SHORT).show();
            AnalyticsLogger.logEvent("biometric_auth_failed");
        }
    }

    /**
     * Simplified TextWatcher which delivers only onTextChanged callback.
     */
    private abstract static class SimpleTextWatcher implements TextWatcher {
        @Override public void beforeTextChanged(CharSequence s, int start, int count, int after) {}
        @Override public void afterTextChanged(Editable s) {}
    }

    /* ------------------------- Testing helpers ------------------------- */

    @VisibleForTesting
    @NonNull
    BiometricPrompt getBiometricPrompt() {
        return biometricPrompt;
    }
}
```