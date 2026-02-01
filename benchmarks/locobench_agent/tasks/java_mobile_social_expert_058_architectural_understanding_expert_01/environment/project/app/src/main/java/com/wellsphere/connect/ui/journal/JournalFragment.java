package com.wellsphere.connect.ui.journal;

import android.Manifest;
import android.content.DialogInterface;
import android.content.Intent;
import android.location.Location;
import android.os.Bundle;
import android.text.format.DateFormat;
import android.view.LayoutInflater;
import android.view.View;
import android.view.ViewGroup;

import androidx.activity.result.ActivityResultLauncher;
import androidx.activity.result.contract.ActivityResultContracts.RequestMultiplePermissions;
import androidx.annotation.NonNull;
import androidx.annotation.Nullable;
import androidx.appcompat.app.AlertDialog;
import androidx.biometric.BiometricPrompt;
import androidx.core.content.ContextCompat;
import androidx.fragment.app.Fragment;
import androidx.lifecycle.LiveData;
import androidx.lifecycle.MutableLiveData;
import androidx.lifecycle.ViewModel;
import androidx.lifecycle.ViewModelProvider;
import androidx.recyclerview.widget.DiffUtil;
import androidx.recyclerview.widget.LinearLayoutManager;
import androidx.recyclerview.widget.RecyclerView;

import com.google.android.material.snackbar.Snackbar;
import com.wellsphere.connect.R;
import com.wellsphere.connect.databinding.FragmentJournalBinding;

import java.text.ParseException;
import java.text.SimpleDateFormat;
import java.util.ArrayList;
import java.util.Date;
import java.util.List;
import java.util.Locale;
import java.util.concurrent.Executor;

/**
 * JournalFragment displays the list of personal health–journal entries.
 * The fragment is gated behind biometric authentication and observes
 * {@link JournalViewModel} for reactive UI updates following MVVM best-practices.
 *
 * <p>Responsibilities:</p>
 * <ul>
 *     <li>Request biometric authentication on entry.</li>
 *     <li>Request runtime location permissions once per session.</li>
 *     <li>Render {@link JournalEntry} list with diffing adapter.</li>
 *     <li>Surface loading / error states to the user.</li>
 *     <li>Navigate to {@code JournalEditorActivity} for add / edit actions.</li>
 * </ul>
 */
public class JournalFragment extends Fragment implements JournalAdapter.JournalActionListener {

    // ------------- View / Binding -------------
    private FragmentJournalBinding binding;
    private JournalAdapter adapter;

    // ------------- ViewModel -------------
    private JournalViewModel viewModel;

    // ------------- Biometric -------------
    private Executor biometricExecutor;
    private BiometricPrompt biometricPrompt;
    private BiometricPrompt.PromptInfo biometricPromptInfo;

    // ------------- Permissions -------------
    private ActivityResultLauncher<String[]> locationPermissionLauncher;

    // -------------------- LIFECYCLE --------------------

    @Override
    public void onCreate(@Nullable Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);

        // Initialize ViewModel scoped to this fragment.
        viewModel = new ViewModelProvider(this).get(JournalViewModel.class);

        // Register permission callback.
        locationPermissionLauncher = registerForActivityResult(
                new RequestMultiplePermissions(),
                permissions -> {
                    Boolean fineGranted = permissions.getOrDefault(Manifest.permission.ACCESS_FINE_LOCATION, false);
                    Boolean coarseGranted = permissions.getOrDefault(Manifest.permission.ACCESS_COARSE_LOCATION, false);

                    if (Boolean.TRUE.equals(fineGranted) || Boolean.TRUE.equals(coarseGranted)) {
                        viewModel.fetchJournalEntries(true /* withLocation */);
                    } else {
                        Snackbar.make(requireView(), R.string.journal_location_denied, Snackbar.LENGTH_LONG).show();
                    }
                }
        );

        // Prepare biometric.
        prepareBiometric();
    }

    @Override
    public View onCreateView(
            @NonNull LayoutInflater inflater,
            @Nullable ViewGroup container,
            @Nullable Bundle savedInstanceState
    ) {
        binding = FragmentJournalBinding.inflate(inflater, container, false);
        return binding.getRoot();
    }

    @Override
    public void onViewCreated(@NonNull View v, @Nullable Bundle savedInstanceState) {
        super.onViewCreated(v, savedInstanceState);

        setupRecyclerView();
        observeViewModel();
        setupFab();

        // Trigger Biometric auth.
        biometricPrompt.authenticate(biometricPromptInfo);
    }

    @Override
    public void onDestroyView() {
        binding = null;
        super.onDestroyView();
    }

    // -------------------- SETUP --------------------

    private void prepareBiometric() {
        biometricExecutor = ContextCompat.getMainExecutor(requireContext());
        biometricPrompt = new BiometricPrompt(
                this,
                biometricExecutor,
                new BiometricPrompt.AuthenticationCallback() {

                    @Override
                    public void onAuthenticationSucceeded(@NonNull BiometricPrompt.AuthenticationResult result) {
                        super.onAuthenticationSucceeded(result);
                        checkLocationPermissionsAndLoad();
                    }

                    @Override
                    public void onAuthenticationError(int errorCode, @NonNull CharSequence errString) {
                        super.onAuthenticationError(errorCode, errString);
                        new AlertDialog.Builder(requireContext())
                                .setTitle(R.string.journal_auth_failed_title)
                                .setMessage(errString)
                                .setPositiveButton(android.R.string.ok,
                                        (DialogInterface dialog, int which) -> requireActivity().finish())
                                .setOnDismissListener(dialog -> requireActivity().finish())
                                .show();
                    }

                    @Override
                    public void onAuthenticationFailed() {
                        super.onAuthenticationFailed();
                        Snackbar.make(requireView(), R.string.journal_auth_failed_retry, Snackbar.LENGTH_SHORT).show();
                    }
                });

        biometricPromptInfo = new BiometricPrompt.PromptInfo.Builder()
                .setTitle(getString(R.string.journal_biometric_title))
                .setSubtitle(getString(R.string.journal_biometric_subtitle))
                .setConfirmationRequired(false)
                .setNegativeButtonText(getString(android.R.string.cancel))
                .build();
    }

    private void setupRecyclerView() {
        adapter = new JournalAdapter(this);
        binding.recyclerView.setLayoutManager(new LinearLayoutManager(requireContext()));
        binding.recyclerView.setAdapter(adapter);
    }

    private void observeViewModel() {
        viewModel.getJournalEntries().observe(getViewLifecycleOwner(), resource -> {
            switch (resource.status) {
                case LOADING:
                    binding.progress.setVisibility(View.VISIBLE);
                    break;
                case SUCCESS:
                    binding.progress.setVisibility(View.GONE);
                    adapter.submitList(resource.data);
                    break;
                case ERROR:
                    binding.progress.setVisibility(View.GONE);
                    Snackbar.make(binding.getRoot(), resource.message, Snackbar.LENGTH_LONG).show();
                    break;
            }
        });
    }

    private void setupFab() {
        binding.fabAdd.setOnClickListener(v -> {
            Intent intent = new Intent(requireContext(), JournalEditorActivity.class);
            startActivity(intent);
        });
    }

    // -------------------- PERMISSIONS --------------------

    private void checkLocationPermissionsAndLoad() {
        if (ContextCompat.checkSelfPermission(requireContext(), Manifest.permission.ACCESS_FINE_LOCATION)
                == android.content.pm.PackageManager.PERMISSION_GRANTED
                || ContextCompat.checkSelfPermission(requireContext(), Manifest.permission.ACCESS_COARSE_LOCATION)
                == android.content.pm.PackageManager.PERMISSION_GRANTED) {

            viewModel.fetchJournalEntries(true /* withLocation */);
        } else {
            locationPermissionLauncher.launch(new String[]{
                    Manifest.permission.ACCESS_FINE_LOCATION,
                    Manifest.permission.ACCESS_COARSE_LOCATION
            });
        }
    }

    // -------------------- JournalAdapter Callback --------------------

    @Override
    public void onEntryClicked(@NonNull JournalEntry entry) {
        Intent intent = new Intent(requireContext(), JournalViewerActivity.class)
                .putExtra(JournalViewerActivity.EXTRA_ENTRY_ID, entry.id);
        startActivity(intent);
    }

    @Override
    public void onEntryShareRequested(@NonNull JournalEntry entry) {
        // Simple share intent; would be replaced by a HIPAA-aware share-flow.
        Intent share = new Intent(Intent.ACTION_SEND)
                .setType("text/plain")
                .putExtra(Intent.EXTRA_TEXT, entry.content);
        startActivity(Intent.createChooser(share, getString(R.string.share_chooser_title)));
    }

    // ========================================================================
    // ==================== SUPPORTING CLASSES =================================
    // ========================================================================

    /**
     * Simple model representing a journal entry.
     */
    public static final class JournalEntry {
        public final String id;
        public final String content;
        public final Date   createdAt;
        @Nullable public final Location location;

        public JournalEntry(
                @NonNull String id,
                @NonNull String content,
                @NonNull Date createdAt,
                @Nullable Location location
        ) {
            this.id = id;
            this.content = content;
            this.createdAt = createdAt;
            this.location = location;
        }

        // Util for parsing from ISO8601 if needed.
        public static Date parseIso(@NonNull String isoString) {
            try {
                return new SimpleDateFormat("yyyy-MM-dd'T'HH:mm:ss.SSS'Z'", Locale.US).parse(isoString);
            } catch (ParseException e) {
                return new Date(); // fallback to now; in production log to crashlytics.
            }
        }
    }

    /**
     * Generic container to represent loading / success / error states.
     */
    public static class Resource<T> {

        public enum Status {LOADING, SUCCESS, ERROR}

        public final Status status;
        @Nullable public final T data;
        @Nullable public final String message;

        private Resource(Status status, @Nullable T data, @Nullable String message) {
            this.status = status;
            this.data = data;
            this.message = message;
        }

        public static <T> Resource<T> loading() {
            return new Resource<>(Status.LOADING, null, null);
        }

        public static <T> Resource<T> success(@NonNull T data) {
            return new Resource<>(Status.SUCCESS, data, null);
        }

        public static <T> Resource<T> error(@NonNull String message) {
            return new Resource<>(Status.ERROR, null, message);
        }
    }

    /**
     * ViewModel responsible for retrieving and holding journal entries.
     * In production, this would delegate to a Repository that merges remote
     * and local caches with conflict-resolution logic.
     */
    public static class JournalViewModel extends ViewModel {

        private final MutableLiveData<Resource<List<JournalEntry>>> journalEntries = new MutableLiveData<>();

        public LiveData<Resource<List<JournalEntry>>> getJournalEntries() {
            return journalEntries;
        }

        /**
         * Fetches journal entries.  If {@code attachLocation} is true, the ViewModel
         * attempts to enrich entries with the last known location before publishing.
         */
        public void fetchJournalEntries(boolean attachLocation) {
            journalEntries.setValue(Resource.loading());

            // Simulate async fetch; replace with repository coroutine / Rx call.
            new Thread(() -> {
                try {
                    Thread.sleep(800); // pretend network delay
                    List<JournalEntry> dummy = generateDummyEntries();
                    journalEntries.postValue(Resource.success(dummy));
                } catch (InterruptedException ex) {
                    journalEntries.postValue(Resource.error(ex.getMessage()));
                }
            }).start();
        }

        private List<JournalEntry> generateDummyEntries() {
            List<JournalEntry> list = new ArrayList<>();
            for (int i = 1; i <= 10; i++) {
                list.add(
                        new JournalEntry(
                                "id_" + i,
                                "Entry " + i + " – Stay positive & hydrated!",
                                new Date(System.currentTimeMillis() - i * 3_600_000L),
                                null)
                );
            }
            return list;
        }
    }

    /**
     * RecyclerView Adapter leveraging ListAdapter & DiffUtil for efficient updates.
     */
    public static class JournalAdapter extends androidx.recyclerview.widget.ListAdapter<JournalEntry, JournalAdapter.EntryVH> {

        interface JournalActionListener {
            void onEntryClicked(@NonNull JournalEntry entry);
            void onEntryShareRequested(@NonNull JournalEntry entry);
        }

        private static final DiffUtil.ItemCallback<JournalEntry> DIFF_CALLBACK = new DiffUtil.ItemCallback<JournalEntry>() {
            @Override
            public boolean areItemsTheSame(@NonNull JournalEntry o1, @NonNull JournalEntry o2) {
                return o1.id.equals(o2.id);
            }

            @Override
            public boolean areContentsTheSame(@NonNull JournalEntry o1, @NonNull JournalEntry o2) {
                return o1.content.equals(o2.content) && o1.createdAt.equals(o2.createdAt);
            }
        };

        private final JournalActionListener listener;

        protected JournalAdapter(JournalActionListener listener) {
            super(DIFF_CALLBACK);
            this.listener = listener;
        }

        @NonNull
        @Override
        public EntryVH onCreateViewHolder(@NonNull ViewGroup parent, int viewType) {
            View itemView = LayoutInflater.from(parent.getContext())
                    .inflate(R.layout.list_item_journal_entry, parent, false);
            return new EntryVH(itemView);
        }

        @Override
        public void onBindViewHolder(@NonNull EntryVH holder, int position) {
            JournalEntry entry = getItem(position);
            holder.bind(entry);
        }

        class EntryVH extends RecyclerView.ViewHolder {
            private final View root;

            EntryVH(@NonNull View itemView) {
                super(itemView);
                this.root = itemView;
            }

            void bind(JournalEntry entry) {
                root.<android.widget.TextView>findViewById(R.id.txt_content).setText(entry.content);
                String date = DateFormat.getMediumDateFormat(root.getContext()).format(entry.createdAt);
                root.<android.widget.TextView>findViewById(R.id.txt_date).setText(date);

                root.setOnClickListener(v -> listener.onEntryClicked(entry));
                root.findViewById(R.id.btn_share).setOnClickListener(v -> listener.onEntryShareRequested(entry));
            }
        }
    }
}