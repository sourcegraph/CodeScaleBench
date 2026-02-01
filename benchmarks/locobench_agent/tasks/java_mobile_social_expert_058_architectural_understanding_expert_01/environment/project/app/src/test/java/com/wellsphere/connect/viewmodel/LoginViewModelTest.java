package com.wellsphere.connect.viewmodel;

import static org.junit.Assert.assertEquals;
import static org.junit.Assert.assertTrue;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.eq;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;

import androidx.arch.core.executor.testing.InstantTaskExecutorRule;
import androidx.lifecycle.Observer;

import com.wellsphere.connect.model.User;
import com.wellsphere.connect.repository.AuthenticationRepository;
import com.wellsphere.connect.util.NetworkUnavailableException;

import org.junit.After;
import org.junit.Before;
import org.junit.Rule;
import org.junit.Test;
import org.junit.runner.RunWith;

import org.mockito.Mock;
import org.mockito.junit.MockitoJUnitRunner;

import java.util.concurrent.CountDownLatch;
import java.util.concurrent.TimeUnit;

import io.reactivex.Single;
import io.reactivex.plugins.RxJavaPlugins;
import io.reactivex.schedulers.Schedulers;

/**
 * Unit tests for {@link LoginViewModel}.
 * These tests verify that the ViewModel correctly translates repository
 * responses into publicly observable UI states.
 *
 * NOTE: The concrete domain classes (User, LoginState etc.) are part of the
 * production source-set.  Here we only care about the observable behaviour.
 */
@RunWith(MockitoJUnitRunner.class)
public class LoginViewModelTest {

    @Rule
    public final InstantTaskExecutorRule instantExecutorRule = new InstantTaskExecutorRule();

    /**
     * Forces RxJava to run synchronously for deterministic unit tests.
     */
    @Rule
    public final RxTrampolineSchedulerRule rxTrampolineSchedulerRule = new RxTrampolineSchedulerRule();

    @Mock
    private AuthenticationRepository authRepository;

    private LoginViewModel viewModel;

    @Before
    public void setUp() {
        viewModel = new LoginViewModel(authRepository);
    }

    @After
    public void tearDown() {
        // Reset RxJava plugins after each test to avoid side-effects across the test suite.
        RxJavaPlugins.reset();
    }

    @Test
    public void loginSuccess_emitsSuccessState() throws InterruptedException {
        // GIVEN
        final User expectedUser = new User("42", "pat@example.com", "Patient Patty");
        when(authRepository.login(eq("pat@example.com"), eq("correctHorseBatteryStaple")))
                .thenReturn(Single.just(expectedUser));

        // WHEN
        viewModel.login("pat@example.com", "correctHorseBatteryStaple");

        // THEN
        LoginViewModel.LoginState state = awaitNextState();
        assertTrue(state instanceof LoginViewModel.LoginState.Success);
        LoginViewModel.LoginState.Success success = (LoginViewModel.LoginState.Success) state;
        assertEquals(expectedUser, success.getUser());

        verify(authRepository).login("pat@example.com", "correctHorseBatteryStaple");
    }

    @Test
    public void loginFailure_invalidCredentials_emitsErrorState() throws InterruptedException {
        // GIVEN
        when(authRepository.login(eq("pat@example.com"), eq("wrongPassword")))
                .thenReturn(Single.error(new IllegalArgumentException("Invalid credentials")));

        // WHEN
        viewModel.login("pat@example.com", "wrongPassword");

        // THEN
        LoginViewModel.LoginState state = awaitNextState();
        assertTrue(state instanceof LoginViewModel.LoginState.Error);
        LoginViewModel.LoginState.Error error = (LoginViewModel.LoginState.Error) state;
        assertEquals(LoginViewModel.LoginError.INVALID_CREDENTIALS, error.getReason());
    }

    @Test
    public void loginFailure_networkUnavailable_emitsNetworkErrorState() throws InterruptedException {
        // GIVEN
        when(authRepository.login(any(), any()))
                .thenReturn(Single.error(new NetworkUnavailableException()));

        // WHEN
        viewModel.login("any@one.com", "irrelevant");

        // THEN
        LoginViewModel.LoginState state = awaitNextState();
        assertTrue(state instanceof LoginViewModel.LoginState.Error);
        LoginViewModel.LoginState.Error error = (LoginViewModel.LoginState.Error) state;
        assertEquals(LoginViewModel.LoginError.NO_NETWORK, error.getReason());
    }

    /**
     * Helper method that observes the LiveData under test and blocks until
     * the next value arrives or the timeout elapses (to avoid infinite wait).
     */
    private LoginViewModel.LoginState awaitNextState() throws InterruptedException {
        final CountDownLatch latch = new CountDownLatch(1);
        final LoginViewModel.LoginState[] box = new LoginViewModel.LoginState[1];

        Observer<LoginViewModel.LoginState> observer = state -> {
            box[0] = state;
            latch.countDown();
        };

        viewModel.getLoginState().observeForever(observer);

        // Wait at most 1 second; tests should complete synchronously anyway.
        if (!latch.await(1, TimeUnit.SECONDS)) {
            throw new AssertionError("LiveData value was never set.");
        }

        viewModel.getLoginState().removeObserver(observer);
        return box[0];
    }

    /**
     * JUnit TestRule that overrides all RxJava schedulers with trampoline
     * (queueing) implementation, ensuring Rx chains execute synchronously
     * on the current thread for unit tests.
     */
    static class RxTrampolineSchedulerRule implements org.junit.rules.TestRule {

        @Override
        public org.junit.runners.model.Statement apply(
                org.junit.runners.model.Statement base,
                org.junit.runner.Description description) {

            return new org.junit.runners.model.Statement() {
                @Override
                public void evaluate() throws Throwable {
                    RxJavaPlugins.setIoSchedulerHandler(scheduler -> Schedulers.trampoline());
                    RxJavaPlugins.setComputationSchedulerHandler(scheduler -> Schedulers.trampoline());
                    RxJavaPlugins.setNewThreadSchedulerHandler(scheduler -> Schedulers.trampoline());

                    try {
                        base.evaluate();   // Execute the actual test.
                    } finally {
                        RxJavaPlugins.reset();
                    }
                }
            };
        }
    }
}