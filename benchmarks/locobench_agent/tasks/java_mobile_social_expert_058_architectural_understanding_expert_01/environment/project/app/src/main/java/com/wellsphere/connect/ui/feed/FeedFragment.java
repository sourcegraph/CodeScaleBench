package com.wellsphere.connect.ui.feed;

import android.app.Activity;
import android.content.Context;
import android.content.res.Configuration;
import android.os.Bundle;
import android.os.CancellationSignal;
import android.util.Log;
import android.view.LayoutInflater;
import android.view.View;
import android.view.ViewGroup;
import android.view.accessibility.AccessibilityManager;
import android.widget.Toast;

import androidx.activity.result.ActivityResultLauncher;
import androidx.activity.result.IntentSenderRequest;
import androidx.annotation.NonNull;
import androidx.annotation.Nullable;
import androidx.biometric.BiometricPrompt;
import androidx.core.content.ContextCompat;
import androidx.fragment.app.Fragment;
import androidx.lifecycle.ViewModelProvider;
import androidx.recyclerview.widget.DiffUtil;
import androidx.recyclerview.widget.ListAdapter;
import androidx.recyclerview.widget.RecyclerView;
import androidx.swiperefreshlayout.widget.SwipeRefreshLayout;

import com.google.android.material.snackbar.Snackbar;
import com.wellsphere.connect.R;
import com.wellsphere.connect.analytics.CrashReporter;
import com.wellsphere.connect.databinding.FragmentFeedBinding;
import com.wellsphere.connect.databinding.ItemFeedBinding;
import com.wellsphere.connect.domain.model.FeedItem;
import com.wellsphere.connect.util.NetworkUtils;
import com.wellsphere.connect.util.TimeUtils;

import java.util.List;
import java.util.concurrent.Executor;

/**
 * FeedFragment is responsible for rendering the social feed and reacting to user actions,
 * biometric authentication events, and connectivity changes. The fragment follows the MVVM
 * pattern by delegating state management and business logic to {@link FeedViewModel}.
 */
public class FeedFragment extends Fragment {

    private static final String TAG = FeedFragment.class.getSimpleName();

    private FragmentFeedBinding binding;
    private FeedAdapter adapter;
    private FeedViewModel viewModel;
    private Executor uiExecutor;
    private BiometricPrompt biometricPrompt;
    private BiometricPrompt.PromptInfo promptInfo;

    private final NetworkUtils.ConnectionLiveData connectionLiveData =
            new NetworkUtils.ConnectionLiveData(requireContext());

    /* -----------------------------------------------------------------------------------------
     * Lifecycle
     * ----------------------------------------------------------------------------------------- */
    @Override
    public void onCreate(@Nullable Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);
        uiExecutor = ContextCompat.getMainExecutor(requireContext());
        initBiometricPrompt();
        initViewModel();
        initObservers();
    }

    @Override
    public View onCreateView(
            @NonNull final LayoutInflater inflater,
            @Nullable final ViewGroup container,
            @Nullable final Bundle savedInstanceState
    ) {
        binding = FragmentFeedBinding.inflate(inflater, container, false);
        setupRecyclerView();
        setupSwipeToRefresh();
        return binding.getRoot();
    }

    @Override
    public void onResume() {
        super.onResume();
        requireActivity().setTitle(R.string.title_feed);
        // Gate access behind biometric auth each time user navigates here
        biometricPrompt.authenticate(promptInfo);
    }

    @Override
    public void onDestroyView() {
        super.onDestroyView();
        binding = null; // avoid memory leaks
    }

    /* -----------------------------------------------------------------------------------------
     * Initialisation
     * ----------------------------------------------------------------------------------------- */

    private void initViewModel() {
        viewModel = new ViewModelProvider(this).get(FeedViewModel.class);
    }

    private void initObservers() {
        // Feed state observer
        viewModel.getFeed().observe(this, feedResource -> {
            switch (feedResource.getStatus()) {
                case LOADING:
                    binding.swipeRefresh.setRefreshing(true);
                    break;
                case SUCCESS:
                    binding.swipeRefresh.setRefreshing(false);
                    onFeedLoaded(feedResource.getData());
                    break;
                case ERROR:
                    binding.swipeRefresh.setRefreshing(false);
                    onError(feedResource.getThrowable());
                    break;
            }
        });

        // Connectivity observer
        connectionLiveData.observe(this, isConnected -> {
            if (!isConnected) {
                Snackbar.make(binding.getRoot(),
                        R.string.error_offline,
                        Snackbar.LENGTH_LONG).show();
            }
        });
    }

    private void initBiometricPrompt() {
        biometricPrompt = new BiometricPrompt(
                this,
                uiExecutor,
                new BiometricPrompt.AuthenticationCallback() {
                    @Override
                    public void onAuthenticationSucceeded(
                            @NonNull BiometricPrompt.AuthenticationResult result
                    ) {
                        super.onAuthenticationSucceeded(result);
                        viewModel.fetchFeed(/*forceRefresh=*/false);
                    }

                    @Override
                    public void onAuthenticationError(
                            int errorCode,
                            @NonNull CharSequence errString
                    ) {
                        super.onAuthenticationError(errorCode, errString);
                        handleBiometricError(errorCode, errString);
                    }

                    @Override
                    public void onAuthenticationFailed() {
                        super.onAuthenticationFailed();
                        Toast.makeText(requireContext(),
                                R.string.biometric_auth_failed,
                                Toast.LENGTH_SHORT).show();
                    }
                }
        );

        promptInfo = new BiometricPrompt.PromptInfo.Builder()
                .setTitle(getString(R.string.biometric_title))
                .setSubtitle(getString(R.string.biometric_subtitle))
                .setDescription(getString(R.string.biometric_description))
                .setConfirmationRequired(false)
                .setNegativeButtonText(getString(R.string.biometric_negative))
                .build();
    }

    private void setupRecyclerView() {
        adapter = new FeedAdapter();
        binding.recyclerFeed.setHasFixedSize(true);
        binding.recyclerFeed.setAdapter(adapter);
    }

    private void setupSwipeToRefresh() {
        binding.swipeRefresh.setOnRefreshListener(() -> viewModel.fetchFeed(/*forceRefresh=*/true));
    }

    /* -----------------------------------------------------------------------------------------
     * UI Helpers
     * ----------------------------------------------------------------------------------------- */

    private void onFeedLoaded(@Nullable final List<FeedItem> feedItems) {
        if (feedItems == null || feedItems.isEmpty()) {
            binding.emptyState.setVisibility(View.VISIBLE);
            binding.recyclerFeed.setVisibility(View.GONE);
        } else {
            binding.emptyState.setVisibility(View.GONE);
            binding.recyclerFeed.setVisibility(View.VISIBLE);
            adapter.submitList(feedItems);
        }
    }

    private void onError(@NonNull final Throwable throwable) {
        Log.e(TAG, "Feed load failed", throwable);
        CrashReporter.logException(throwable);
        Snackbar.make(binding.getRoot(),
                R.string.error_generic,
                Snackbar.LENGTH_LONG).show();
    }

    private void handleBiometricError(int errorCode, CharSequence errString) {
        Log.w(TAG, "Biometric error (" + errorCode + "): " + errString);
        Snackbar.make(binding.getRoot(),
                getString(R.string.biometric_unavailable),
                Snackbar.LENGTH_INDEFINITE)
                .setAction(R.string.action_settings, v -> openSecuritySettings())
                .show();
        // Fall back to showing cached feed
        viewModel.fetchCachedFeed();
    }

    private void openSecuritySettings() {
        try {
            IntentSenderRequest request =
                    new IntentSenderRequest.Builder(
                            new Intent(android.provider.Settings.ACTION_SECURITY_SETTINGS))
                            .build();
            ActivityResultLauncher<IntentSenderRequest> launcher =
                    registerForActivityResult(
                            new androidx.activity.result.contract.ActivityResultContracts
                                    .StartIntentSenderForResult(), result -> {
                                // no-op
                            });
            launcher.launch(request);
        } catch (Exception ex) {
            Log.e(TAG, "Unable to open settings", ex);
            CrashReporter.logException(ex);
        }
    }

    /* -----------------------------------------------------------------------------------------
     * Adapter
     * ----------------------------------------------------------------------------------------- */

    /**
     * RecyclerView Adapter rendering {@link FeedItem}s.
     */
    private static class FeedAdapter extends ListAdapter<FeedItem, FeedAdapter.FeedViewHolder> {

        protected FeedAdapter() {
            super(DIFF_CALLBACK);
        }

        @NonNull
        @Override
        public FeedViewHolder onCreateViewHolder(
                @NonNull ViewGroup parent,
                int viewType
        ) {
            ItemFeedBinding itemBinding =
                    ItemFeedBinding.inflate(LayoutInflater.from(parent.getContext()), parent, false);
            return new FeedViewHolder(itemBinding);
        }

        @Override
        public void onBindViewHolder(@NonNull FeedViewHolder holder, int position) {
            holder.bind(getItem(position));
        }

        /* -----------------------------------------------------------------------------
         * ViewHolder
         * ----------------------------------------------------------------------------- */
        static class FeedViewHolder extends RecyclerView.ViewHolder {

            private final ItemFeedBinding binding;

            FeedViewHolder(@NonNull final ItemFeedBinding binding) {
                super(binding.getRoot());
                this.binding = binding;
            }

            void bind(@NonNull final FeedItem item) {
                binding.textUserName.setText(item.getUserDisplayName());
                binding.textTimestamp.setText(TimeUtils.getRelativeTime(item.getTimestamp()));
                binding.textContent.setText(item.getContent());

                // Show/hide attachments
                if (item.hasImageAttachment()) {
                    binding.imageAttachment.setVisibility(View.VISIBLE);
                    binding.imageAttachment.setImageURI(item.getImageUri());
                } else {
                    binding.imageAttachment.setVisibility(View.GONE);
                }

                // Accessibility
                binding.getRoot().setContentDescription(
                        binding.getRoot().getContext()
                                .getString(R.string.feed_item_description,
                                        item.getUserDisplayName(),
                                        TimeUtils.getRelativeTime(item.getTimestamp()),
                                        item.getContent())
                );
            }
        }

        /* -----------------------------------------------------------------------------
         * DiffUtil
         * ----------------------------------------------------------------------------- */
        private static final DiffUtil.ItemCallback<FeedItem> DIFF_CALLBACK =
                new DiffUtil.ItemCallback<FeedItem>() {
                    @Override
                    public boolean areItemsTheSame(
                            @NonNull FeedItem oldItem,
                            @NonNull FeedItem newItem
                    ) {
                        return oldItem.getId().equals(newItem.getId());
                    }

                    @Override
                    public boolean areContentsTheSame(
                            @NonNull FeedItem oldItem,
                            @NonNull FeedItem newItem
                    ) {
                        return oldItem.equals(newItem);
                    }
                };
    }
}