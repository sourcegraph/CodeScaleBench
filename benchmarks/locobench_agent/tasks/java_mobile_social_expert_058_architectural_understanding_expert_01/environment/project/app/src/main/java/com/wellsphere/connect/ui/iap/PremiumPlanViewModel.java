```java
/*
 *  WellSphere Connect – Premium Plan View-Model
 *
 *  Copyright (c) 2024 WellSphere
 *
 *  Licensed under the Apache License, Version 2.0 (the "License");
 *  you may not use this file except in compliance with the License.
 *  You may obtain a copy of the License at
 *
 *       http://www.apache.org/licenses/LICENSE-2.0
 *
 *  Unless required by applicable law or agreed to in writing, software
 *  distributed under the License is distributed on an "AS IS" BASIS,
 *  WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
 *  See the License for the specific language governing permissions and
 *  limitations under the License.
 */

package com.wellsphere.connect.ui.iap;

import android.app.Activity;
import android.app.Application;
import android.util.Log;

import androidx.annotation.NonNull;
import androidx.lifecycle.AndroidViewModel;
import androidx.lifecycle.LiveData;
import androidx.lifecycle.MediatorLiveData;
import androidx.lifecycle.MutableLiveData;

import com.android.billingclient.api.BillingClient;
import com.android.billingclient.api.BillingResult;
import com.android.billingclient.api.ProductDetails;
import com.wellsphere.connect.BuildConfig;
import com.wellsphere.connect.data.iap.PremiumPlanRepository;
import com.wellsphere.connect.data.iap.SubscriptionStatus;
import com.wellsphere.connect.util.SingleLiveEvent;

import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;

/**
 * View-Model that orchestrates all interactions between the UI layer and
 * {@link PremiumPlanRepository}.  Handles purchase flow, restoration, error
 * propagation, analytics logging, and exposes reactive premium-state to the UI.
 *
 * This class must remain Java (not Kotlin) because of strict mixed-language
 * build constraints in several hospital deployments that still rely on
 * commercial static-analysis tools which only support Java.
 */
public class PremiumPlanViewModel extends AndroidViewModel {

    // region Public reactive UI API -------------------------------------------------------------

    /**
     * True when the user currently owns an active premium subscription.
     */
    public final LiveData<Boolean> isPremiumUser;

    /**
     * Emits granular progress & error information to be rendered in the
     * {@code PremiumPaywallFragment}.  Guaranteed to deliver distinct updates.
     */
    public final LiveData<PurchaseUiState> purchaseUiState;

    /**
     * Single-shot toast or snackbar messages.  Consumed only once by the UI.
     */
    public final SingleLiveEvent<String> oneShotMessage = new SingleLiveEvent<>();

    // endregion ---------------------------------------------------------------------------------


    // region Private fields ---------------------------------------------------------------------

    private static final String TAG = "PremiumPlanViewModel";

    private final PremiumPlanRepository repository;
    private final MediatorLiveData<PurchaseUiState> purchaseStateMerger = new MediatorLiveData<>();
    private final ExecutorService io = Executors.newSingleThreadExecutor();

    // endregion ---------------------------------------------------------------------------------


    public PremiumPlanViewModel(@NonNull Application app,
                                @NonNull PremiumPlanRepository repository) {
        super(app);
        this.repository = repository;

        /* -------------------------------------------------------------------------------------
         * Reactive wiring:
         *
         *  1. isPremiumUser      : derived directly from repository status
         *  2. purchaseUiState    : merges billing-events + local loading/error state
         * ----------------------------------------------------------------------------------- */
        this.isPremiumUser = repository.getSubscriptionStatusLive()
                .map(status -> status == SubscriptionStatus.ACTIVE);

        purchaseStateMerger.setValue(PurchaseUiState.idle());
        purchaseUiState = purchaseStateMerger;

        // Propagate repository billing events into the merged state
        purchaseStateMerger.addSource(repository.getBillingEvents(), this::handleBillingEvent);
    }


    // region Public API -------------------------------------------------------------------------

    /**
     * Initiates the Play Billing purchase flow for the premium plan.
     *
     * @param hostActivity Activity used by the BillingClient to display UI.
     *                     Must be in foreground and not finishing.
     */
    public void purchasePremium(@NonNull Activity hostActivity) {
        purchaseStateMerger.setValue(PurchaseUiState.loading());

        io.execute(() -> {
            // Pre-flight: check availability of product details
            ProductDetails details = repository.getCachedProductDetails();
            if (details == null) {
                oneShotMessage.postValue("Unable to connect to Play Store. Try again later.");
                purchaseStateMerger.postValue(PurchaseUiState.error());
                return;
            }

            BillingResult launchResult = repository.launchPurchaseFlow(hostActivity, details);
            if (launchResult.getResponseCode() != BillingClient.BillingResponseCode.OK) {
                // Launch failed synchronously: nothing was shown to the user.
                emitBillingError(launchResult);
            } // else: Billing flow launched; subsequent events will arrive via listener
        });
    }

    /**
     * Restores purchases (e.g., after re-install or device change).
     * Safe to call repeatedly; actual network call is rate-limited inside repository.
     */
    public void restorePurchases() {
        purchaseStateMerger.setValue(PurchaseUiState.loading());
        io.execute(() -> repository.queryAndSyncExistingPurchases());
    }

    // endregion ---------------------------------------------------------------------------------


    // region Internal: Billing callbacks --------------------------------------------------------

    private void handleBillingEvent(PremiumPlanRepository.BillingEvent event) {
        switch (event.type) {
            case PURCHASE_SUCCESS:
                purchaseStateMerger.setValue(PurchaseUiState.success());
                oneShotMessage.setValue("Welcome to Premium ✨");
                break;

            case PURCHASE_ALREADY_OWNED:
                purchaseStateMerger.setValue(PurchaseUiState.success());
                oneShotMessage.setValue("You already have Premium access.");
                break;

            case PURCHASE_CANCELLED:
                purchaseStateMerger.setValue(PurchaseUiState.idle());
                break;

            case PURCHASE_ERROR:
                emitBillingError(event.billingResult);
                break;

            case CONSUME_ERROR:
            case ACKNOWLEDGE_ERROR:
                // For consumables, we may show different UI; for subscription we treat as fatal.
                emitBillingError(event.billingResult);
                break;

            case RESTORE_STARTED:
                purchaseStateMerger.setValue(PurchaseUiState.loading());
                break;

            case RESTORE_COMPLETED:
                purchaseStateMerger.setValue(PurchaseUiState.idle());
                break;

            default:
                if (BuildConfig.DEBUG) {
                    Log.w(TAG, "Unhandled billing event: " + event.type);
                }
                break;
        }
    }

    private void emitBillingError(BillingResult billingResult) {
        String msg = repository.humanReadableError(billingResult);
        oneShotMessage.setValue(msg);
        purchaseStateMerger.setValue(PurchaseUiState.error());

        // Optional logging to crash-reporting backend
        if (BuildConfig.CRASH_REPORTING_ENABLED) {
            Log.e(TAG, "BillingError: " + billingResult + " | " + msg);
            // Crashlytics.logException(new PlayBillingException(billingResult));
        }
    }

    // endregion ---------------------------------------------------------------------------------


    // region View-Model lifecycle ---------------------------------------------------------------

    @Override
    protected void onCleared() {
        super.onCleared();
        repository.dispose();
        io.shutdownNow();
    }

    // endregion ---------------------------------------------------------------------------------


    // region Helper/DTO classes -----------------------------------------------------------------

    /**
     * Immutable value object representing the UI state of a purchase/restore operation.
     * Keeps the Fragment lean by handling all state transitions centrally.
     */
    public static final class PurchaseUiState {

        public enum Stage { IDLE, LOADING, SUCCESS, ERROR }

        public final Stage stage;

        private PurchaseUiState(Stage stage) { this.stage = stage; }

        public static PurchaseUiState idle()    { return new PurchaseUiState(Stage.IDLE);    }
        public static PurchaseUiState loading() { return new PurchaseUiState(Stage.LOADING); }
        public static PurchaseUiState success() { return new PurchaseUiState(Stage.SUCCESS); }
        public static PurchaseUiState error()   { return new PurchaseUiState(Stage.ERROR);   }

        @Override public String toString() { return "PurchaseUiState{" + stage + '}'; }
    }

    // endregion ---------------------------------------------------------------------------------
}
```

