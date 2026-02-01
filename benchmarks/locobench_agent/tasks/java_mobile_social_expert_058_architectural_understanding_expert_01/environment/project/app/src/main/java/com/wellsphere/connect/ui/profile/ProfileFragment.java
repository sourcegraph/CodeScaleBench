```java
package com.wellsphere.connect.ui.profile;

import android.content.Context;
import android.content.Intent;
import android.net.Uri;
import android.os.Bundle;
import android.os.Handler;
import android.os.Looper;
import android.view.LayoutInflater;
import android.view.Menu;
import android.view.MenuInflater;
import android.view.MenuItem;
import android.view.View;
import android.view.ViewGroup;
import android.widget.Toast;

import androidx.activity.result.ActivityResultLauncher;
import androidx.activity.result.contract.ActivityResultContracts;
import androidx.annotation.NonNull;
import androidx.annotation.Nullable;
import androidx.biometric.BiometricManager;
import androidx.biometric.BiometricPrompt;
import androidx.core.content.ContextCompat;
import androidx.fragment.app.Fragment;
import androidx.fragment.app.viewModels;
import androidx.lifecycle.Observer;

import com.google.android.material.snackbar.Snackbar;
import com.wellsphere.connect.R;
import com.wellsphere.connect.data.Result;
import com.wellsphere.connect.databinding.FragmentProfileBinding;
import com.wellsphere.connect.domain.profile.Profile;
import com.wellsphere.connect.ui.common.EventObserver;
import com.wellsphere.connect.ui.common.ViewBindingHolder;
import com.wellsphere.connect.ui.common.ViewBindingHolderDelegate;
import com.wellsphere.connect.ui.profile.share.SocialShareAdapter;
import com.wellsphere.connect.ui.profile.share.SocialShareAdapterFactory;

import java.util.concurrent.Executor;

import dagger.hilt.android.AndroidEntryPoint;
import javax.inject.Inject;

/**
 * Displays the signed-in user’s profile.
 * Gate-kept by biometric authentication when enabled in user settings.
 *
 * Architecture:
 * ┌──────────┐       LiveData        ┌────────────┐        callbacks       ┌───────────┐
 * │ ViewModel├──────────────────────>│  Fragment  ├───────────────────────>│   View    │
 * └──────────┘                       └────────────┘                        └───────────┘
 */
@AndroidEntryPoint
public class ProfileFragment extends Fragment
        implements ViewBindingHolder<FragmentProfileBinding> {

    /***************************
     * Dependencies – injected *
     ***************************/
    @Inject
    SocialShareAdapterFactory shareAdapterFactory;  // Factory Pattern for runtime share adapter
    @Inject
    BiometricManager biometricManager;              // Provided by app-level module

    /*************
     * ViewModel *
     *************/
    private final ProfileViewModel viewModel by viewModels();

    /**************************
     * Biometric prompt state *
     **************************/
    private BiometricPrompt biometricPrompt;
    private BiometricPrompt.PromptInfo promptInfo;

    /*******************
     * ViewBinding API *
     *******************/
    private final ViewBindingHolderDelegate<FragmentProfileBinding> _binding =
            new ViewBindingHolderDelegate<>();

    @Override
    public View getRoot() {
        return _binding.requireBinding().getRoot();
    }

    @Override
    public void onCreate(@Nullable Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);
        setHasOptionsMenu(true);
        initBiometricPrompt();
    }

    @Override
    public View onCreateView(
            @NonNull LayoutInflater inflater,
            @Nullable ViewGroup container,
            @Nullable Bundle savedInstanceState
    ) {
        _binding.bind(FragmentProfileBinding.inflate(inflater, container, false));
        return getRoot();
    }

    @Override
    public void onViewCreated(@NonNull View view, @Nullable Bundle savedInstanceState) {
        super.onViewCreated(view, savedInstanceState);

        // Handle share button clicks (navigation via adapter)
        _binding.requireBinding().fabShare.setOnClickListener(v -> {
            Profile profile = viewModel.getProfile().getValue();
            if (profile != null) {
                presentShareSheet(profile);
            } else {
                Snackbar.make(requireView(), R.string.profile_not_available, Snackbar.LENGTH_SHORT).show();
            }
        });

        subscribeUi();
        authenticateOrLoadProfile();
    }

    /****************
     * Menu actions *
     ****************/
    @Override
    public void onCreateOptionsMenu(@NonNull Menu menu, @NonNull MenuInflater inflater) {
        inflater.inflate(R.menu.menu_profile, menu);
    }

    @Override
    public boolean onOptionsItemSelected(@NonNull MenuItem item) {
        if (item.getItemId() == R.id.action_refresh) {
            viewModel.refreshProfile();
            return true;
        }
        return super.onOptionsItemSelected(item);
    }

    /**************************
     * Biometric integration  *
     **************************/
    private void initBiometricPrompt() {
        Executor executor = ContextCompat.getMainExecutor(requireContext());
        biometricPrompt = new BiometricPrompt(this, executor, new BiometricPrompt.AuthenticationCallback() {
            @Override
            public void onAuthenticationSucceeded(@NonNull BiometricPrompt.AuthenticationResult result) {
                super.onAuthenticationSucceeded(result);
                viewModel.loadProfile();
            }

            @Override
            public void onAuthenticationFailed() {
                super.onAuthenticationFailed();
                Snackbar.make(requireView(), R.string.biometric_failed, Snackbar.LENGTH_SHORT).show();
            }

            @Override
            public void onAuthenticationError(int errorCode, @NonNull CharSequence errString) {
                super.onAuthenticationError(errorCode, errString);
                // Fallback to login screen for fatal errors
                if (errorCode == BiometricPrompt.ERROR_LOCKOUT ||
                    errorCode == BiometricPrompt.ERROR_LOCKOUT_PERMANENT) {
                    navigateToSignOut();
                }
            }
        });

        promptInfo = new BiometricPrompt.PromptInfo.Builder()
                .setTitle(getString(R.string.biometric_title))
                .setSubtitle(getString(R.string.biometric_subtitle))
                .setNegativeButtonText(getString(android.R.string.cancel))
                .build();
    }

    private void authenticateOrLoadProfile() {
        if (biometricManager.canAuthenticate() == BiometricManager.BIOMETRIC_SUCCESS &&
            viewModel.isBiometricEnabled()) {
            biometricPrompt.authenticate(promptInfo);
        } else { // Biometric not enabled – go ahead and load profile
            viewModel.loadProfile();
        }
    }

    /****************************
     * Subscribe to LiveData    *
     ****************************/
    private void subscribeUi() {
        viewModel.getProfile().observe(getViewLifecycleOwner(), profile -> {
            if (profile != null) {
                renderProfile(profile);
            }
        });

        viewModel.getLoadingState().observe(getViewLifecycleOwner(), isLoading -> {
            _binding.requireBinding().progressBar.setVisibility(isLoading ? View.VISIBLE : View.GONE);
        });

        viewModel.getErrorEvent().observe(getViewLifecycleOwner(), new EventObserver<>(errorMsg ->
            Snackbar.make(requireView(), errorMsg, Snackbar.LENGTH_LONG).show()
        ));
    }

    private void renderProfile(@NonNull Profile profile) {
        FragmentProfileBinding b = _binding.requireBinding();
        b.tvName.setText(profile.getDisplayName());
        b.tvEmail.setText(profile.getEmail());
        b.tvLocation.setText(profile.getLocation());
        b.tvMemberSince.setText(getString(R.string.member_since, profile.getMemberSince()));
        // ... populate other views
    }

    /**************************
     * Social share workflow  *
     **************************/
    private void presentShareSheet(@NonNull Profile profile) {
        SocialShareAdapter shareAdapter = shareAdapterFactory.create(
                SocialShareAdapterFactory.Network.HOSPITAL_PORTAL /* default channel */
        );
        shareAdapter.shareProfile(profile, requireContext(), result -> {
            if (result instanceof Result.Error) {
                Snackbar.make(requireView(), ((Result.Error) result).getMessage(), Snackbar.LENGTH_LONG).show();
            }
        });
    }

    /*****************************
     * Navigation / Error routes *
     *****************************/
    private void navigateToSignOut() {
        // Replace with global NavController call when integrated
        Toast.makeText(requireContext(), R.string.logged_out, Toast.LENGTH_LONG).show();
        // AppNav.findNavController(this).navigate(R.id.action_global_to_auth);
    }

    /************************
     * Lifecycle override   *
     ************************/
    @Override
    public void onDestroyView() {
        _binding.unbind();
        super.onDestroyView();
    }

    /*******************************
     * Activity-result convenience *
     *******************************/
    private final ActivityResultLauncher<Intent> openUrlLauncher =
            registerForActivityResult(new ActivityResultContracts.StartActivityForResult(), result -> {
                // No-op: browser handles it
            });

    /*******************************************
     * Util: open external links / deep-links  *
     *******************************************/
    private void openExternalUrl(String url) {
        Intent intent = new Intent(Intent.ACTION_VIEW, Uri.parse(url));
        openUrlLauncher.launch(intent);
    }
}
```