```java
package com.wellsphere.connect.core.base;

import android.Manifest;
import android.content.Context;
import android.content.pm.PackageManager;
import android.os.Bundle;
import android.view.LayoutInflater;
import android.view.View;
import android.view.ViewGroup;
import android.view.inputmethod.InputMethodManager;

import androidx.activity.result.ActivityResultCallback;
import androidx.activity.result.ActivityResultLauncher;
import androidx.activity.result.contract.ActivityResultContracts;
import androidx.annotation.LayoutRes;
import androidx.annotation.NonNull;
import androidx.annotation.Nullable;
import androidx.core.content.ContextCompat;
import androidx.databinding.DataBindingUtil;
import androidx.databinding.ViewDataBinding;
import androidx.fragment.app.Fragment;
import androidx.lifecycle.Observer;
import androidx.lifecycle.ViewModelProvider;

import com.google.android.material.snackbar.Snackbar;
import com.google.firebase.crashlytics.FirebaseCrashlytics;
import com.wellsphere.connect.R;
import com.wellsphere.connect.core.di.AppViewModelFactory;
import com.wellsphere.connect.core.uievent.UiEvent;
import com.wellsphere.connect.core.uievent.UiEvent.Loading;
import com.wellsphere.connect.core.uievent.UiEvent.ShowError;
import com.wellsphere.connect.core.uievent.UiEvent.ShowMessage;
import com.wellsphere.connect.core.util.EventObserver;
import com.wellsphere.connect.core.widget.LoadingDialog;

import java.lang.reflect.ParameterizedType;
import java.lang.reflect.Type;

import io.reactivex.rxjava3.disposables.CompositeDisposable;
import io.reactivex.rxjava3.disposables.Disposable;

/**
 * Base class that wires up DataBinding, ViewModel creation, Disposable
 * management, permission handling and common UI behaviours such as showing a
 * loading indicator or snackbar messages.
 *
 * All application Fragments must extend this class to guarantee a deterministic
 * life-cycle that is compatible with the app’s MVVM stack.
 *
 * @param <VM> ViewModel that extends {@link BaseViewModel}
 * @param <B>  Generated ViewBinding for the layout referenced by {@code layoutRes()}
 */
@SuppressWarnings({"unused", "WeakerAccess"})
public abstract class BaseFragment<VM extends BaseViewModel, B extends ViewDataBinding>
        extends Fragment {

    protected B binding;
    protected VM viewModel;

    private LoadingDialog loadingDialog;
    private final CompositeDisposable compositeDisposable = new CompositeDisposable();

    /* ---- Permission handling ------------------------------------------------------------- */

    private final ActivityResultLauncher<String[]> permissionLauncher =
            registerForActivityResult(
                    new ActivityResultContracts.RequestMultiplePermissions(),
                    result -> {
                        boolean allGranted = true;
                        for (Boolean granted : result.values()) {
                            allGranted &= granted != null && granted;
                        }
                        onPermissionResult(allGranted);
                    });

    /* ---- Fragment life-cycle ------------------------------------------------------------- */

    @Nullable
    @Override
    public View onCreateView(
            @NonNull LayoutInflater inflater,
            @Nullable ViewGroup container,
            @Nullable Bundle savedInstanceState) {

        binding = DataBindingUtil.inflate(inflater, layoutRes(), container, false);
        binding.setLifecycleOwner(getViewLifecycleOwner());

        initViewModel();
        observeViewModel();

        return binding.getRoot();
    }

    @Override
    public void onDestroyView() {
        safeHideKeyboard();
        compositeDisposable.clear();
        super.onDestroyView();
    }

    /* ---- Template methods ---------------------------------------------------------------- */

    /**
     * @return Layout resource id for {@link #binding}.
     */
    @LayoutRes
    protected abstract int layoutRes();

    /**
     * Override to observe exposed {@link androidx.lifecycle.LiveData}s from the {@link #viewModel}.
     * Call {@code viewModel.getXyz().observe(...)} here.
     */
    protected void observeViewModel() {
        // Sub-classes may override.
        viewModel.getUiEvents().observe(getViewLifecycleOwner(), new EventObserver<>(this::handleUiEvent));
    }

    /**
     * Callback executed when requested runtime permissions have been resolved.
     * Default implementation does nothing.
     */
    protected void onPermissionResult(boolean granted) {
        /* no-op */
    }

    /* ---- Public helper methods ----------------------------------------------------------- */

    /**
     * Add a {@link Disposable} to the internal {@link CompositeDisposable} so it is automatically
     * disposed when the Fragment is destroyed.
     */
    protected void autoDispose(Disposable disposable) {
        compositeDisposable.add(disposable);
    }

    /**
     * Request a group of permissions in a single aggregated flow.
     */
    protected void requestPermissionsSafely(String... permissions) {
        permissionLauncher.launch(permissions);
    }

    /**
     * Convenience wrapper to request location permission.
     */
    protected void requestLocationPermission() {
        requestPermissionsSafely(Manifest.permission.ACCESS_FINE_LOCATION,
                                 Manifest.permission.ACCESS_COARSE_LOCATION);
    }

    protected boolean hasPermission(String permission) {
        return ContextCompat.checkSelfPermission(requireContext(), permission)
                == PackageManager.PERMISSION_GRANTED;
    }

    /* ---- Private helpers ----------------------------------------------------------------- */

    private void initViewModel() {
        // ViewModel class is inferred via reflection if not overridden
        Class<VM> vmClass = getViewModelClass();
        ViewModelProvider.Factory factory = AppViewModelFactory.getInstance(requireActivity().getApplication());
        //noinspection unchecked
        viewModel = new ViewModelProvider(this, factory).get(vmClass);
    }

    @SuppressWarnings("unchecked")
    private Class<VM> getViewModelClass() {
        Type superclass = getClass().getGenericSuperclass();
        if (superclass instanceof ParameterizedType) {
            return (Class<VM>) ((ParameterizedType) superclass).getActualTypeArguments()[0];
        }
        throw new IllegalStateException("BaseFragment must be parametrised with generic ViewModel type");
    }

    private void handleUiEvent(@NonNull UiEvent event) {
        if (event instanceof Loading) {
            toggleLoading(((Loading) event).isLoading());
        } else if (event instanceof ShowMessage) {
            showMessage(((ShowMessage) event).getMessage());
        } else if (event instanceof ShowError) {
            showError(((ShowError) event).getThrowable());
        }
    }

    private void toggleLoading(boolean show) {
        if (show) {
            if (loadingDialog == null) {
                loadingDialog = new LoadingDialog(requireContext());
            }
            loadingDialog.show();
        } else if (loadingDialog != null && loadingDialog.isShowing()) {
            loadingDialog.dismiss();
        }
    }

    private void showMessage(@NonNull String message) {
        if (getView() != null) {
            Snackbar.make(getView(), message, Snackbar.LENGTH_LONG).show();
        }
    }

    private void showError(@NonNull Throwable throwable) {
        FirebaseCrashlytics.getInstance().recordException(throwable);
        String text = throwable.getLocalizedMessage() != null
                ? throwable.getLocalizedMessage()
                : getString(R.string.core_unknown_error);
        showMessage(text);
    }

    private void safeHideKeyboard() {
        View view = requireActivity().getCurrentFocus();
        if (view != null) {
            InputMethodManager imm =
                    (InputMethodManager) requireActivity().getSystemService(Context.INPUT_METHOD_SERVICE);
            if (imm != null) {
                imm.hideSoftInputFromWindow(view.getWindowToken(), 0);
            }
        }
    }
}
```