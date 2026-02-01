```java
package com.wellsphere.connect.ui.auth;

import android.app.Application;
import android.content.Context;
import android.os.Build;
import android.text.TextUtils;

import androidx.annotation.NonNull;
import androidx.annotation.RequiresApi;
import androidx.biometric.BiometricManager;
import androidx.lifecycle.AndroidViewModel;
import androidx.lifecycle.LiveData;
import androidx.lifecycle.MutableLiveData;

import com.wellsphere.connect.core.analytics.Analytics;
import com.wellsphere.connect.core.connectivity.NetworkStateMonitor;
import com.wellsphere.connect.data.auth.AuthRepository;
import com.wellsphere.connect.data.auth.Session;
import com.wellsphere.connect.util.SingleLiveEvent;

import java.util.concurrent.TimeUnit;

import io.reactivex.Completable;
import io.reactivex.Single;
import io.reactivex.android.schedulers.AndroidSchedulers;
import io.reactivex.disposables.CompositeDisposable;
import io.reactivex.functions.Action;
import io.reactivex.schedulers.Schedulers;

/**
 * ViewModel that handles user authentication flows (email / password + biometric).
 * The class is lifecycle-aware and survives configuration changes.
 *
 * Responsibilities:
 * 1. Delegate authentication logic to {@link AuthRepository}
 * 2. Orchestrate biometric availability checks
 * 3. Publish UI state via LiveData
 * 4. Log relevant analytics
 * 5. Provide cancelation and proper cleanup
 */
public class LoginViewModel extends AndroidViewModel {

    // ----- Public immutable LiveData exposed to the View layer -----
    public LiveData<Boolean> loading()          { return isLoading; }
    public LiveData<Throwable> error()          { return errorEvent; }
    public LiveData<Session>   session()        { return sessionLiveData; }
    public LiveData<Boolean>   canUseBiometric(){ return biometricAvailable; }

    // ----- Private members -----
    private final AuthRepository  authRepository;
    private final Analytics       analytics;
    private final NetworkStateMonitor networkMonitor;

    private final MutableLiveData<Boolean> biometricAvailable = new MutableLiveData<>(false);
    private final MutableLiveData<Boolean> isLoading          = new MutableLiveData<>(false);
    private final MutableLiveData<Session> sessionLiveData    = new MutableLiveData<>();
    private final SingleLiveEvent<Throwable> errorEvent       = new SingleLiveEvent<>();

    private final CompositeDisposable disposables = new CompositeDisposable();

    public LoginViewModel(@NonNull Application application,
                          @NonNull AuthRepository authRepository,
                          @NonNull Analytics analytics,
                          @NonNull NetworkStateMonitor networkMonitor) {
        super(application);
        this.authRepository   = authRepository;
        this.analytics        = analytics;
        this.networkMonitor   = networkMonitor;

        // Asynchronously evaluate biometric availability once ViewModel is instantiated.
        checkBiometricSupport(application.getApplicationContext());
    }

    // ---------------------------------------------------------------------------------------------
    // Public API
    // ---------------------------------------------------------------------------------------------

    /**
     * Perform email / password authentication.
     *
     * @param email       user e-mail address
     * @param password    raw password (the repository hashes + salting)
     * @param rememberMe  whether user wants refresh tokens persisted
     */
    public void loginWithPassword(@NonNull String email,
                                  @NonNull String password,
                                  boolean rememberMe) {

        if (!validateCredentials(email, password)) return;

        setLoading(true);

        disposables.add(
                authRepository.signIn(email.trim(), password, rememberMe)
                              .timeout(20, TimeUnit.SECONDS)
                              .subscribeOn(Schedulers.io())
                              .observeOn(AndroidSchedulers.mainThread())
                              .doFinally(() -> setLoading(false))
                              .subscribe(
                                      this::onSessionAvailable,
                                      this::handleError)
        );
    }

    /**
     * Initiate biometric authentication. If cached refresh token exists the repository will
     * automatically exchange it for a fresh session on the backend.
     */
    public void loginWithBiometrics() {
        setLoading(true);
        disposables.add(
                authRepository.signInWithBiometrics()
                              .timeout(15, TimeUnit.SECONDS)
                              .subscribeOn(Schedulers.io())
                              .observeOn(AndroidSchedulers.mainThread())
                              .doFinally(() -> setLoading(false))
                              .subscribe(
                                      this::onSessionAvailable,
                                      this::handleError)
        );
    }

    /**
     * Revokes the session both locally and remotely. This is intentionally slow to reduce chances
     * of the logout request being lost when network is flaky.
     */
    public void logout() {
        setLoading(true);
        disposables.add(
                Completable.fromAction((Action) authRepository::logout)
                           .delay(250, TimeUnit.MILLISECONDS) // UX: fade-out animation window
                           .subscribeOn(Schedulers.io())
                           .observeOn(AndroidSchedulers.mainThread())
                           .doFinally(() -> setLoading(false))
                           .subscribe(
                                   () -> sessionLiveData.setValue(null),
                                   this::handleError
                           )
        );
    }

    /**
     * Re-evaluates if this device can offer biometric auth. Should be re-invoked when user changes
     * device settings (e.g., disables FaceID) or enrolls biometrics for the first time.
     */
    public void refreshBiometricCapability(Context context) {
        checkBiometricSupport(context.getApplicationContext());
    }

    @Override
    protected void onCleared() {
        disposables.clear();
    }

    // ---------------------------------------------------------------------------------------------
    // Private helpers
    // ---------------------------------------------------------------------------------------------

    private void onSessionAvailable(@NonNull Session session) {
        analytics.trackSuccessLogin(session.getUserId(), session.getLoginMethod());
        sessionLiveData.setValue(session);
    }

    private boolean validateCredentials(String email, String password) {

        if (TextUtils.isEmpty(email) || TextUtils.isEmpty(password)) {
            handleError(new IllegalArgumentException("Credentials must not be empty"));
            return false;
        }

        if (!android.util.Patterns.EMAIL_ADDRESS.matcher(email).matches()) {
            handleError(new IllegalArgumentException("Invalid e-mail address"));
            return false;
        }

        if (password.length() < 8) {
            handleError(new IllegalArgumentException("Password too short"));
            return false;
        }

        if (!networkMonitor.isOnline()) {
            handleError(new IllegalStateException("No internet connection"));
            return false;
        }

        return true;
    }

    private void setLoading(boolean inProgress) { isLoading.setValue(inProgress); }

    @RequiresApi(api = Build.VERSION_CODES.M)
    private void checkBiometricSupport(@NonNull Context context) {

        // Evaluate HW + enrolment
        BiometricManager manager = BiometricManager.from(context);
        boolean supported = manager.canAuthenticate(
                BiometricManager.Authenticators.BIOMETRIC_WEAK
                        | BiometricManager.Authenticators.BIOMETRIC_STRONG)
                == BiometricManager.BIOMETRIC_SUCCESS;

        biometricAvailable.postValue(supported && authRepository.hasBiometricKeyPair());
    }

    /**
     * Common place to handle every error case, map to user-friendly message, and log analytics.
     */
    private void handleError(@NonNull Throwable throwable) {

        analytics.trackLoginError(throwable);

        // Qualify authentication vs connectivity vs unknown
        if (!networkMonitor.isOnline()) {
            errorEvent.setValue(new IllegalStateException("Please check your internet connection"));
            return;
        }

        errorEvent.setValue(throwable);
    }
}
```