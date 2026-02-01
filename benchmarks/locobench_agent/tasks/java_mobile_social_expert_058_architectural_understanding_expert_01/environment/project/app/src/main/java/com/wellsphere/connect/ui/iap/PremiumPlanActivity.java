package com.wellsphere.connect.ui.iap;

import android.os.Bundle;
import android.text.SpannableString;
import android.text.method.LinkMovementMethod;
import android.text.style.UnderlineSpan;
import android.view.LayoutInflater;
import android.view.View;
import android.view.ViewGroup;
import android.widget.Toast;

import androidx.activity.result.ActivityResultLauncher;
import androidx.activity.result.contract.ActivityResultContracts.StartIntentSenderForResult;
import androidx.annotation.NonNull;
import androidx.annotation.Nullable;
import androidx.appcompat.app.AppCompatActivity;
import androidx.core.app.ActivityOptionsCompat;
import androidx.lifecycle.Observer;
import androidx.lifecycle.ViewModelProvider;
import androidx.recyclerview.widget.DiffUtil;
import androidx.recyclerview.widget.LinearLayoutManager;
import androidx.recyclerview.widget.RecyclerView;

import com.android.billingclient.api.BillingResult;
import com.android.billingclient.api.ProductDetails;
import com.wellsphere.connect.R;
import com.wellsphere.connect.databinding.ActivityPremiumPlanBinding;
import com.wellsphere.connect.databinding.ItemPremiumPlanBinding;
import com.wellsphere.connect.ui.common.widget.ProgressDialogFragment;
import com.wellsphere.connect.util.EventObserver;

import java.text.NumberFormat;
import java.util.List;
import java.util.Locale;

/**
 * PremiumPlanActivity presents the list of available premium subscriptions and
 * forwards user selections to {@link PremiumPlanViewModel} to execute
 * Google Play Billing flows.  The activity is intentionally “dumb”—all
 * business logic is delegated to the ViewModel so that configuration changes
 * (e.g., rotation) do not interrupt an ongoing purchase flow.
 *
 * Activity       ->  ViewModel        -> Repository
 * ────────           ─────────            ─────────
 * UI events   →  Billing Flow   → Google Play Billing / Secure backend
 * LiveData    ←  UiState        ← Billing callbacks / Verification
 */
public class PremiumPlanActivity extends AppCompatActivity
        implements PremiumPlanAdapter.OnPlanClickListener {

    private ActivityPremiumPlanBinding binding;
    private PremiumPlanViewModel viewModel;
    private PremiumPlanAdapter adapter;
    private ProgressDialogFragment progressDialog;

    private final ActivityResultLauncher<android.content.IntentSenderRequest> billingIntentLauncher =
            registerForActivityResult(new StartIntentSenderForResult(), activityResult -> {
                // Forward result to the ViewModel so BillingClient can evaluate it.
                viewModel.handleActivityResult(activityResult);
            });

    @Override
    protected void onCreate(@Nullable Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);
        binding = ActivityPremiumPlanBinding.inflate(getLayoutInflater());
        setContentView(binding.getRoot());

        initToolbar();
        initRecyclerView();
        initViewModel();
        initUiObservers();
        viewModel.fetchAvailablePlans();
    }

    private void initToolbar() {
        setSupportActionBar(binding.toolbar);
        binding.toolbar.setNavigationOnClickListener(v -> finishAfterTransition());
    }

    private void initRecyclerView() {
        adapter = new PremiumPlanAdapter(this);
        binding.recyclerPlans.setLayoutManager(new LinearLayoutManager(this));
        binding.recyclerPlans.setAdapter(adapter);
        binding.recyclerPlans.setHasFixedSize(true);
    }

    private void initViewModel() {
        viewModel = new ViewModelProvider(this,
                ViewModelProvider.AndroidViewModelFactory.getInstance(getApplication()))
                .get(PremiumPlanViewModel.class);
    }

    private void initUiObservers() {
        // List of skus from Play Console
        viewModel.getAvailablePlans().observe(this, new Observer<List<ProductDetails>>() {
            @Override public void onChanged(List<ProductDetails> productDetails) {
                adapter.submitList(productDetails);
            }
        });

        // Purchase updates
        viewModel.getPurchaseCompletedEvent()
                 .observe(this, new EventObserver<>(this::onPurchaseSucceeded));

        // Error handling
        viewModel.getErrorEvent()
                 .observe(this, new EventObserver<>(this::onError));

        // In-progress indicator
        viewModel.getLoading()
                 .observe(this, isLoading -> {
                     if (isLoading) showLoading();
                     else hideLoading();
                 });
    }

    @Override
    public void onPlanClick(@NonNull ProductDetails plan) {
        viewModel.launchBillingFlow(this, plan, billingIntentLauncher);
    }

    private void onPurchaseSucceeded(ProductDetails productDetails) {
        hideLoading();
        String price = productDetails.getOneTimePurchaseOfferDetails() == null
                ? "" : productDetails.getOneTimePurchaseOfferDetails().getFormattedPrice();
        SpannableString message = new SpannableString(
                getString(R.string.premium_purchase_success, price));
        message.setSpan(new UnderlineSpan(), 0, message.length(), 0);
        Toast.makeText(this, message, Toast.LENGTH_LONG).show();

        // Return to the previous screen with a shared-element transition
        finishAfterTransition();
    }

    private void onError(@NonNull BillingResult billingResult) {
        hideLoading();
        Toast.makeText(
                this,
                getString(R.string.premium_purchase_error, billingResult.getDebugMessage()),
                Toast.LENGTH_LONG
        ).show();
    }

    private void showLoading() {
        if (progressDialog == null) {
            progressDialog = ProgressDialogFragment.newInstance(
                    getString(R.string.dialog_processing_payment));
        }
        if (!progressDialog.isAdded()) {
            progressDialog.show(getSupportFragmentManager(), ProgressDialogFragment.TAG);
        }
    }

    private void hideLoading() {
        if (progressDialog != null && progressDialog.isAdded()) {
            progressDialog.dismissAllowingStateLoss();
        }
    }

    // ───────────────────────────────────────────────────────────────────────────
    // Adapter
    // ───────────────────────────────────────────────────────────────────────────

    /**
     * Adapter rendering each premium plan row. The implementation is intentionally simple
     * and entirely stateless with a {@link DiffUtil} payload.
     */
    static final class PremiumPlanAdapter
            extends RecyclerView.Adapter<PremiumPlanAdapter.PlanViewHolder> {

        interface OnPlanClickListener {
            void onPlanClick(@NonNull ProductDetails plan);
        }

        private final DiffUtil.ItemCallback<ProductDetails> diffCallback =
                new DiffUtil.ItemCallback<ProductDetails>() {
                    @Override
                    public boolean areItemsTheSame(@NonNull ProductDetails oldItem,
                                                    @NonNull ProductDetails newItem) {
                        return oldItem.getProductId().equals(newItem.getProductId());
                    }

                    @Override
                    public boolean areContentsTheSame(@NonNull ProductDetails oldItem,
                                                      @NonNull ProductDetails newItem) {
                        return oldItem.equals(newItem);
                    }
                };

        private final androidx.recyclerview.widget.AsyncListDiffer<ProductDetails> differ =
                new androidx.recyclerview.widget.AsyncListDiffer<>(this, diffCallback);

        @NonNull
        private final OnPlanClickListener listener;

        PremiumPlanAdapter(@NonNull OnPlanClickListener listener) {
            this.listener = listener;
        }

        void submitList(@NonNull List<ProductDetails> newList) {
            differ.submitList(newList);
        }

        @NonNull
        @Override
        public PlanViewHolder onCreateViewHolder(@NonNull ViewGroup parent, int viewType) {
            ItemPremiumPlanBinding binding = ItemPremiumPlanBinding.inflate(
                    LayoutInflater.from(parent.getContext()), parent, false);
            return new PlanViewHolder(binding);
        }

        @Override
        public void onBindViewHolder(@NonNull PlanViewHolder holder, int position) {
            holder.bind(differ.getCurrentList().get(position));
        }

        @Override public int getItemCount() { return differ.getCurrentList().size(); }

        final class PlanViewHolder extends RecyclerView.ViewHolder {

            private final ItemPremiumPlanBinding binding;

            PlanViewHolder(@NonNull ItemPremiumPlanBinding binding) {
                super(binding.getRoot());
                this.binding = binding;
            }

            void bind(@NonNull ProductDetails details) {
                binding.txtPlanTitle.setText(details.getName());

                // Extract localized pricing from the best offer available.
                String priceString = "-";
                if (details.getOneTimePurchaseOfferDetails() != null) {
                    priceString = details.getOneTimePurchaseOfferDetails().getFormattedPrice();
                } else if (!details.getSubscriptionOfferDetails().isEmpty()) {
                    ProductDetails.SubscriptionOfferDetails offerDetails =
                            details.getSubscriptionOfferDetails().get(0);
                    priceString = offerDetails.getPricingPhases()
                                              .getPricingPhaseList()
                                              .get(0)
                                              .getFormattedPrice();
                }
                binding.txtPlanPrice.setText(priceString);
                binding.cardPlan.setOnClickListener(v -> listener.onPlanClick(details));
            }
        }
    }
}