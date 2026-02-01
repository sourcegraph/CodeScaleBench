package com.wellsphere.connect.core.base;

import android.Manifest;
import android.app.AlertDialog;
import android.content.Context;
import android.content.DialogInterface;
import android.content.pm.PackageManager;
import android.os.Bundle;
import android.os.Handler;
import android.view.LayoutInflater;
import android.view.View;
import android.view.inputmethod.InputMethodManager;
import android.widget.ProgressBar;
import android.widget.Toast;

import androidx.activity.result.ActivityResultLauncher;
import androidx.activity.result.contract.ActivityResultContracts;
import androidx.annotation.LayoutRes;
import androidx.annotation.NonNull;
import androidx.annotation.Nullable;
import androidx.appcompat.app.AppCompatActivity;
import androidx.appcompat.widget.AppCompatTextView;
import androidx.biometric.BiometricManager;
import androidx.biometric.BiometricPrompt;
import androidx.core.app.ActivityCompat;
import androidx.core.content.ContextCompat;
import androidx.databinding.DataBindingUtil;
import androidx.databinding.ViewDataBinding;
import androidx.lifecycle.LiveData;
import androidx.lifecycle.ViewModel;
import androidx.lifecycle.ViewModelProvider;

import com.google.android.material.snackbar.Snackbar;
import com.google.firebase.crashlytics.FirebaseCrashlytics;
import com.wellsphere.connect.BuildConfig;
import com.wellsphere.connect.R;
import com.wellsphere.connect.core.analytics.Analytics;
import com.wellsphere.connect.core.network.ConnectivityMonitor;

import java.util.concurrent.Executor;
import java.util.concurrent.Executors;

import javax.inject.Inject;

import timber.log.Timber;

/**
 * BaseActivity that wires common concerns such as:
 * • Data-/View-binding
 * • ViewModel instantiation through injected {@link ViewModelProvider.Factory}
 * • Runtime permissions delegation
 * • Biometric-gated flows
 * • Crash-reporting hooks
 * • Connectivity toasts and basic loading indicators
 *
 * Every Activity in the application should inherit from this class unless an
 * explicit architectural reason prohibits it.
 *
 * @param <VB> ViewBinding/DataBinding type for the activity’s layout
 * @param <VM> ViewModel extending {@link BaseViewModel}
 */
public abstract class BaseActivity<VB extends ViewDataBinding, VM extends BaseViewModel>
        extends AppCompatActivity implements BaseNavigator {

    @Inject
    protected ViewModelProvider.Factory viewModelFactory;

    protected VB binding;
    protected VM viewModel;

    private AlertDialog progressDialog;
    private ConnectivityMonitor connectivityMonitor;
    private final Executor biometricExecutor = Executors.newSingleThreadExecutor();

    /**
     * Request launcher that handles a single dangerous permission at a time.
     * For multiple permissions use {@link #requestPermissionsCompat(String[], int)}.
     */
    private final ActivityResultLauncher<String> singlePermissionLauncher =
            registerForActivityResult(new ActivityResultContracts.RequestPermission(), isGranted -> {
                if (!isGranted) {
                    showSnackbar(getString(R.string.permission_denied_generic));
                }
            });

    // --------------------------- Activity Lifecycle --------------------------- //

    @Override
    protected void onCreate(@Nullable Bundle savedInstanceState) {
        inject();           // 1) DI graph
        super.onCreate(savedInstanceState);

        // 2) Inflate and bind contentView
        binding = DataBindingUtil.setContentView(this, getLayoutResId());
        binding.setLifecycleOwner(this);

        // 3) ViewModel
        viewModel = obtainViewModel(getViewModelClass());
        viewModel.setNavigator(this);
        registerDefaultObservers();

        // 4) Connectivity listener
        connectivityMonitor = new ConnectivityMonitor(this);
        connectivityMonitor.getIsConnectedLiveData().observe(this, this::onConnectivityChanged);

        // 5) Analytics – defer to subclasses for custom screen names
        Analytics.trackScreen(getScreenName());

        // 6) Crashlytics – tie Activity context for breadcrumbing
        FirebaseCrashlytics.getInstance().setCustomKey("current_activity", getClass().getSimpleName());
    }

    @Override
    protected void onDestroy() {
        if (progressDialog != null && progressDialog.isShowing()) {
            progressDialog.dismiss();
        }
        if (connectivityMonitor != null) {
            connectivityMonitor.unregister();
        }
        super.onDestroy();
    }

    // --------------------------- Abstract Contract --------------------------- //

    /**
     * Sub-classes must return their layout resource for {@link DataBindingUtil}.
     */
    @LayoutRes
    protected abstract int getLayoutResId();

    /**
     * The concrete ViewModel class to be provided through the injected factory.
     */
    @NonNull
    protected abstract Class<VM> getViewModelClass();

    /**
     * Human-readable screen identifier used for analytics.
     */
    @NonNull
    protected abstract String getScreenName();

    /**
     * Perform dependency injection (Hilt/Dagger/Anvil/…).
     * Empty default allows injection-less subclasses (tests).
     */
    protected void inject() {
        /* no-op */
    }

    // --------------------------- ViewModel Helpers --------------------------- //

    private VM obtainViewModel(Class<VM> clazz) {
        return new ViewModelProvider(this, viewModelFactory).get(clazz);
    }

    /**
     * Default observers for {@link BaseViewModel#loadingLiveData} and
     * {@link BaseViewModel#errorLiveData}. Override for additional hooks.
     */
    protected void registerDefaultObservers() {
        observe(viewModel.getLoadingLiveData(), this::toggleLoading);
        observe(viewModel.getErrorLiveData(), this::handleError);
    }

    protected <T> void observe(@NonNull LiveData<T> liveData, @NonNull androidx.lifecycle.Observer<T> observer) {
        liveData.observe(this, observer);
    }

    // --------------------------- Loading & Error --------------------------- //

    private void toggleLoading(Boolean isLoading) {
        if (Boolean.TRUE.equals(isLoading)) {
            showLoading();
        } else {
            hideLoading();
        }
    }

    private void handleError(Throwable throwable) {
        if (throwable == null) return;

        // Log verbosely in debug; report non-fatal in release
        if (BuildConfig.DEBUG) {
            Timber.e(throwable);
        } else {
            FirebaseCrashlytics.getInstance().recordException(throwable);
        }
        showSnackbar(throwable.getLocalizedMessage() != null
                ? throwable.getLocalizedMessage()
                : getString(R.string.error_unexpected));
    }

    public void showLoading() {
        if (progressDialog == null) {
            progressDialog = createProgressDialog();
        }
        if (!progressDialog.isShowing()) {
            progressDialog.show();
        }
    }

    public void hideLoading() {
        if (progressDialog != null && progressDialog.isShowing()) {
            // Defer dismiss to avoid “android.view.WindowLeaked” when Activity is finishing
            new Handler(getMainLooper()).post(progressDialog::dismiss);
        }
    }

    private AlertDialog createProgressDialog() {
        ProgressBar progressBar = new ProgressBar(this);
        progressBar.setIndeterminate(true);

        AlertDialog dialog = new AlertDialog.Builder(this, R.style.ProgressDialogTheme)
                .setView(progressBar)
                .setCancelable(false)
                .create();
        dialog.setCanceledOnTouchOutside(false);
        return dialog;
    }

    // --------------------------- Snackbar / Toast helpers --------------------------- //

    public void showSnackbar(@NonNull String message) {
        View root = binding.getRoot();
        Snackbar.make(root, message, Snackbar.LENGTH_LONG).show();
    }

    public void showToast(@NonNull String message) {
        Toast.makeText(this, message, Toast.LENGTH_SHORT).show();
    }

    // --------------------------- Connectivity --------------------------- //

    private void onConnectivityChanged(Boolean isConnected) {
        if (Boolean.FALSE.equals(isConnected)) {
            showSnackbar(getString(R.string.no_internet_connection));
        }
    }

    // --------------------------- Keyboard utils --------------------------- //

    public void hideKeyboard() {
        View view = getCurrentFocus();
        if (view == null) view = binding.getRoot();
        InputMethodManager imm =
                (InputMethodManager) getSystemService(Context.INPUT_METHOD_SERVICE);
        if (imm != null) imm.hideSoftInputFromWindow(view.getWindowToken(), 0);
    }

    // --------------------------- Runtime Permissions --------------------------- //

    protected void requestPermissionCompat(@NonNull String permission) {
        if (ContextCompat.checkSelfPermission(this, permission) == PackageManager.PERMISSION_GRANTED) {
            return;
        }
        singlePermissionLauncher.launch(permission);
    }

    protected void requestPermissionsCompat(@NonNull String[] permissions, int requestCode) {
        ActivityCompat.requestPermissions(this, permissions, requestCode);
    }

    protected boolean hasPermission(@NonNull String permission) {
        return ContextCompat.checkSelfPermission(this, permission) == PackageManager.PERMISSION_GRANTED;
    }

    // --------------------------- Biometric Auth --------------------------- //

    /**
     * Executes the supplied {@link Runnable} once the user has been positively
     * authenticated via biometrics.
     *
     * If device biometrics are unavailable or user cancels, an error snackbar is shown.
     *
     * @param onSuccess Task that requires authentication (e.g. opening journal).
     */
    protected void requireBiometric(@NonNull Runnable onSuccess) {
        BiometricManager biometricManager = BiometricManager.from(this);
        if (biometricManager.canAuthenticate(BiometricManager.Authenticators.BIOMETRIC_STRONG)
                != BiometricManager.BIOMETRIC_SUCCESS) {
            showSnackbar(getString(R.string.biometric_not_available));
            return;
        }

        BiometricPrompt.PromptInfo promptInfo = new BiometricPrompt.PromptInfo.Builder()
                .setTitle(getString(R.string.biometric_prompt_title))
                .setSubtitle(getString(R.string.biometric_prompt_subtitle))
                .setNegativeButtonText(getString(R.string.cancel))
                .build();

        new BiometricPrompt(this, biometricExecutor, new BiometricPrompt.AuthenticationCallback() {
            @Override
            public void onAuthenticationError(int errorCode,
                                              @NonNull CharSequence errString) {
                super.onAuthenticationError(errorCode, errString);
                showSnackbar(errString.toString());
            }

            @Override
            public void onAuthenticationSucceeded(
                    @NonNull BiometricPrompt.AuthenticationResult result) {
                super.onAuthenticationSucceeded(result);
                runOnUiThread(onSuccess);
            }

            @Override
            public void onAuthenticationFailed() {
                super.onAuthenticationFailed();
                showSnackbar(getString(R.string.biometric_failed));
            }
        }).authenticate(promptInfo);
    }

    // --------------------------- BaseNavigator implementation --------------------------- //

    @Override
    public void navigateBack() {
        onBackPressedDispatcher.onBackPressed();
    }

    @Override
    public void hideKeyboardBridge() {
        hideKeyboard();
    }

    // --------------------------- Misc --------------------------- //

    protected void openAppSettings() {
        // Opens system settings for the app to allow user to enable permissions
        startActivity(HelperIntents.createAppSettingsIntent(this));
    }
}

/**
 * Core responsibilities every ViewModel in the Connect app can rely on.
 * LiveData for loading/error states are centralized here to reduce boilerplate.
 * Concrete modules may extend this class with additional LiveData fields.
 */
abstract class BaseViewModel extends ViewModel {

    private final androidx.lifecycle.MutableLiveData<Boolean> loadingLiveData = new androidx.lifecycle.MutableLiveData<>();
    private final androidx.lifecycle.MutableLiveData<Throwable> errorLiveData = new androidx.lifecycle.MutableLiveData<>();

    protected BaseNavigator navigator;

    LiveData<Boolean> getLoadingLiveData() {
        return loadingLiveData;
    }

    LiveData<Throwable> getErrorLiveData() {
        return errorLiveData;
    }

    void setLoading(boolean loading) {
        loadingLiveData.postValue(loading);
    }

    void postError(Throwable throwable) {
        errorLiveData.postValue(throwable);
    }

    void setNavigator(BaseNavigator navigator) {
        this.navigator = navigator;
    }
}

/**
 * Navigation / UI side-effects that do not belong in ViewModels should go through this bridge.
 * Implemented by {@link BaseActivity}.
 */
interface BaseNavigator {
    void navigateBack();

    void hideKeyboardBridge();

    default void showToastBridge(@NonNull Context context, @NonNull String message) {
        Toast.makeText(context, message, Toast.LENGTH_SHORT).show();
    }
}