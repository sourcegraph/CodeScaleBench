package com.wellsphere.connect.ui.iap;

import android.app.Activity;
import android.app.Application;
import android.content.Context;
import android.util.Log;

import androidx.annotation.MainThread;
import androidx.annotation.NonNull;
import androidx.annotation.Nullable;
import androidx.annotation.WorkerThread;
import androidx.lifecycle.LiveData;
import androidx.lifecycle.MutableLiveData;

import com.android.billingclient.api.AcknowledgePurchaseParams;
import com.android.billingclient.api.AcknowledgePurchaseResponseListener;
import com.android.billingclient.api.BillingClient;
import com.android.billingclient.api.BillingClient.BillingResponseCode;
import com.android.billingclient.api.BillingClient.SkuType;
import com.android.billingclient.api.BillingClientStateListener;
import com.android.billingclient.api.BillingFlowParams;
import com.android.billingclient.api.BillingResult;
import com.android.billingclient.api.Purchase;
import com.android.billingclient.api.PurchasesUpdatedListener;
import com.android.billingclient.api.QueryProductDetailsParams;
import com.android.billingclient.api.ProductDetails;
import com.wellsphere.connect.BuildConfig;

import java.util.ArrayList;
import java.util.Collections;
import java.util.List;
import java.util.Objects;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;

/**
 * BillingManager is the single point of interaction with Google Play Billing.
 * It encapsulates the BillingClient, exposes lifecycle-aware observable data,
 * and hides threading details from the rest of the application.
 *
 * The class follows a thread-safe singleton pattern to guarantee exactly one
 * BillingClient instance throughout the process—this prevents leakage and is
 * compatible with the app’s modular MVVM architecture.
 */
@SuppressWarnings({"WeakerAccess", "unused"})
public final class BillingManager implements PurchasesUpdatedListener {

    //region Static Singleton Boilerplate ----------------------------------------------------------

    private static final String TAG = "BillingManager";
    private static volatile BillingManager instance;

    /**
     * Obtain the singleton BillingManager bound to the given Application.
     */
    public static BillingManager getInstance(@NonNull Application application) {
        if (instance == null) {
            synchronized (BillingManager.class) {
                if (instance == null) {
                    instance = new BillingManager(application.getApplicationContext());
                }
            }
        }
        return instance;
    }

    //endregion

    //region Public LiveData -----------------------------------------------------------------------

    /**
     * BillingServiceState reflects real-time availability of the Play billing service.
     */
    public enum BillingServiceState {
        DISCONNECTED,
        CONNECTING,
        CONNECTED,
        FAILED
    }

    /**
     * UI/Repository observers consume this entitlement to gate premium-feature flows.
     */
    public static class PremiumEntitlement {
        public final boolean isEntitled;
        @Nullable public final String purchaseToken;

        PremiumEntitlement(boolean entitled, @Nullable String token) {
            this.isEntitled  = entitled;
            this.purchaseToken = token;
        }
    }

    private final MutableLiveData<BillingServiceState> serviceStateLiveData =
            new MutableLiveData<>(BillingServiceState.DISCONNECTED);
    private final MutableLiveData<PremiumEntitlement> premiumEntitlementLiveData =
            new MutableLiveData<>(new PremiumEntitlement(false, null));

    public LiveData<BillingServiceState> getServiceState()       { return serviceStateLiveData; }
    public LiveData<PremiumEntitlement> getPremiumEntitlement()  { return premiumEntitlementLiveData; }

    //endregion

    //region Instance Fields -----------------------------------------------------------------------

    private final Context appContext;
    private final ExecutorService ioExecutor = Executors.newSingleThreadExecutor();
    private BillingClient billingClient;

    // SKU/Product constants. Real apps keep these in backend-controlled config.
    private static final String PRODUCT_PREMIUM_MONTHLY = "wellsphere_premium_monthly";

    //endregion

    private BillingManager(@NonNull Context context) {
        this.appContext = context;

        billingClient = BillingClient.newBuilder(context)
                .setListener(this)
                .enablePendingPurchases()
                .build();

        connectToPlayBillingService();
    }

    //region BillingClient Connection Lifecycle ----------------------------------------------------

    @MainThread
    private void connectToPlayBillingService() {
        if (billingClient.isReady()) return;

        serviceStateLiveData.postValue(BillingServiceState.CONNECTING);
        billingClient.startConnection(new BillingClientStateListener() {
            @Override public void onBillingSetupFinished(@NonNull BillingResult billingResult) {
                if (billingResult.getResponseCode() == BillingResponseCode.OK) {
                    Log.d(TAG, "Billing connection established");
                    serviceStateLiveData.postValue(BillingServiceState.CONNECTED);
                    // Query immediately to catch any pending entitlement the user already owns.
                    queryExistingPurchases();
                } else {
                    Log.e(TAG, "Billing setup failed: " + billingResult.getDebugMessage());
                    serviceStateLiveData.postValue(BillingServiceState.FAILED);
                }
            }

            @Override public void onBillingServiceDisconnected() {
                Log.w(TAG, "Billing service disconnected");
                serviceStateLiveData.postValue(BillingServiceState.DISCONNECTED);
                // Attempt reconnection in background to avoid UI block.
                retryConnectionWithBackoff();
            }
        });
    }

    /**
     * Simple linear back-off reconnection policy.
     */
    private void retryConnectionWithBackoff() {
        ioExecutor.execute(() -> {
            for (int attempt = 1; attempt <= 3; attempt++) {
                try {
                    Thread.sleep(1_000L * attempt);
                } catch (InterruptedException ignored) { /* NOP */ }

                if (billingClient != null && !billingClient.isReady()) {
                    Log.d(TAG, "Retrying billing connection, attempt " + attempt);
                    connectToPlayBillingService();
                } else {
                    return;
                }
            }
            Log.e(TAG, "Failed to reconnect to Billing after retries");
        });
    }

    //endregion

    //region Purchase Flow -------------------------------------------------------------------------

    /**
     * Launch Google Play purchase UI for the premium plan.
     *
     * @param activity Host activity
     */
    @MainThread
    public void launchPremiumPurchaseFlow(@NonNull Activity activity) {
        if (!billingClient.isReady()) {
            Log.w(TAG, "BillingClient not ready. Delaying purchase flow.");
            connectToPlayBillingService();
            return;
        }

        QueryProductDetailsParams params = QueryProductDetailsParams.newBuilder()
                .setProductList(Collections.singletonList(
                        QueryProductDetailsParams.Product.newBuilder()
                                .setProductId(PRODUCT_PREMIUM_MONTHLY)
                                .setProductType(SkuType.SUBS)
                                .build()))
                .build();

        billingClient.queryProductDetailsAsync(params, (billingResult, productDetailsList) -> {
            if (billingResult.getResponseCode() != BillingResponseCode.OK) {
                Log.e(TAG, "Product details query failed: " + billingResult.getDebugMessage());
                return;
            }

            if (productDetailsList == null || productDetailsList.isEmpty()) {
                Log.e(TAG, "No SKU details found for " + PRODUCT_PREMIUM_MONTHLY);
                return;
            }

            ProductDetails productDetails = productDetailsList.get(0);

            List<BillingFlowParams.ProductDetailsParams> productList = new ArrayList<>();
            productList.add(
                    BillingFlowParams.ProductDetailsParams.newBuilder()
                            .setProductDetails(productDetails)
                            .build());

            BillingFlowParams flowParams = BillingFlowParams.newBuilder()
                    .setProductDetailsParamsList(productList)
                    .build();

            BillingResult result = billingClient.launchBillingFlow(activity, flowParams);
            Log.d(TAG, "Billing flow launched: " + result);
        });
    }

    //endregion

    //region Purchase Handling ---------------------------------------------------------------------

    /**
     * Invoked by the Billing Library when a purchase is updated/finished.
     */
    @Override
    public void onPurchasesUpdated(@NonNull BillingResult billingResult,
                                   @Nullable List<Purchase> purchases) {
        int code = billingResult.getResponseCode();
        if (code == BillingResponseCode.OK && purchases != null) {
            handlePurchaseList(purchases);
        } else if (code == BillingResponseCode.USER_CANCELED) {
            Log.i(TAG, "Purchase canceled by user");
        } else {
            Log.e(TAG, "Purchase failed: " + billingResult.getDebugMessage());
        }
    }

    private void handlePurchaseList(@NonNull List<Purchase> purchases) {
        for (Purchase purchase : purchases) {
            if (purchase.getProducts().contains(PRODUCT_PREMIUM_MONTHLY)) {
                // Grant entitlement locally.
                premiumEntitlementLiveData.postValue(
                        new PremiumEntitlement(true, purchase.getPurchaseToken()));

                // Acknowledge if required to avoid auto-refunds.
                if (!purchase.isAcknowledged()) {
                    acknowledgePurchase(purchase);
                }
            }
        }
    }

    private void acknowledgePurchase(@NonNull Purchase purchase) {
        AcknowledgePurchaseParams params =
                AcknowledgePurchaseParams.newBuilder()
                        .setPurchaseToken(purchase.getPurchaseToken())
                        .build();

        billingClient.acknowledgePurchase(params, new AcknowledgePurchaseResponseListener() {
            @Override public void onAcknowledgePurchaseResponse(@NonNull BillingResult result) {
                if (result.getResponseCode() == BillingResponseCode.OK) {
                    Log.d(TAG, "Purchase acknowledged");
                } else {
                    Log.e(TAG, "Failed to acknowledge: " + result.getDebugMessage());
                }
            }
        });
    }

    /**
     * Queries Google Play for any active purchases the user already owns. This is mandatory
     * every time the app starts to ensure entitlement consistency across devices.
     */
    @MainThread
    public void queryExistingPurchases() {
        ioExecutor.execute(() -> {
            if (!billingClient.isReady()) return;

            List<Purchase> purchases =
                    billingClient.queryPurchasesAsync(
                                    QueryProductDetailsParams.ProductType.SUBS)
                            .getPurchasesList();

            if (purchases == null) purchases = Collections.emptyList();
            handlePurchaseList(purchases);

            if (BuildConfig.DEBUG) {
                Log.d(TAG, "Existing purchases queried: " + purchases.size());
            }
        });
    }

    //endregion

    //region Public Helper Methods -----------------------------------------------------------------

    /**
     * Helper used by ViewModels to quickly check entitlement without observing.
     */
    public boolean isPremiumActive() {
        PremiumEntitlement current = premiumEntitlementLiveData.getValue();
        return current != null && current.isEntitled;
    }

    //endregion

    //region Teardown ------------------------------------------------------------------------------

    /**
     * Must be called from Application.onTerminate or when user explicitly logs out.
     */
    public void destroy() {
        if (billingClient != null && billingClient.isReady()) {
            billingClient.endConnection();
        }
        ioExecutor.shutdownNow();
        instance = null;
    }

    //endregion
}