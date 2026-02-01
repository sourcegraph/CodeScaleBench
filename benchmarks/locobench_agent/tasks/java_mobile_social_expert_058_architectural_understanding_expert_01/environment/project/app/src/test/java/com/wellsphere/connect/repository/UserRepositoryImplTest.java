```java
package com.wellsphere.connect.repository;

import com.wellsphere.connect.datasource.local.UserLocalDataSource;
import com.wellsphere.connect.datasource.remote.UserRemoteDataSource;
import com.wellsphere.connect.model.Token;
import com.wellsphere.connect.model.User;
import com.wellsphere.connect.network.NetworkMonitor;
import com.wellsphere.connect.security.TokenManager;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Nested;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.extension.ExtendWith;
import org.mockito.InOrder;
import org.mockito.InjectMocks;
import org.mockito.Mock;
import org.mockito.Mockito;
import org.mockito.junit.jupiter.MockitoExtension;

import java.io.IOException;
import java.time.Instant;
import java.util.Optional;

import static org.junit.jupiter.api.Assertions.*;
import static org.mockito.Mockito.*;

/**
 * Unit-tests for {@link UserRepositoryImpl}.  These tests validate the repository’s behaviour
 * when interacting with its injected data-sources and utility collaborators.
 *
 * NOTE:  Although the implementation under test lives in “production” source-sets, the concrete
 *        classes referenced here (e.g. UserRemoteDataSource) could be interfaces or abstract
 *        classes in the real code-base.  The goal of these tests is to specify *behaviour*,
 *        not implementation details.
 */
@ExtendWith(MockitoExtension.class)
class UserRepositoryImplTest {

    private static final String USER_ID   = "user-1234";
    private static final String EMAIL     = "jane.doe@wellsphere.com";
    private static final String PASSWORD  = "SuperS3cret!";
    private static final String AUTH_TOKEN_VALUE = "eyJhbGciOiJIUzI1NiJ9.…";

    @Mock
    private UserRemoteDataSource remoteSource;

    @Mock
    private UserLocalDataSource  localSource;

    @Mock
    private NetworkMonitor       networkMonitor;

    @Mock
    private TokenManager         tokenManager;

    @InjectMocks
    private UserRepositoryImpl   repository;

    private User dummyRemoteUser;
    private User dummyCachedUser;

    @BeforeEach
    void setUp() {
        dummyRemoteUser = new User(
                USER_ID,
                "Jane",
                "Doe",
                EMAIL,
                Instant.parse("1980-05-27T00:00:00Z"),
                "+1-202-555-0199",
                "https://cdn.wellsphere.com/avatars/jane.png"
        );

        dummyCachedUser = new User(
                USER_ID,
                "Janey",
                "D",          // out-of-date lastname
                EMAIL,
                Instant.parse("1980-05-27T00:00:00Z"),
                "+1-202-555-0199",
                null
        );
    }

    /* ------------------------------------------------------------
     * getUserProfile(…)
     * ------------------------------------------------------------ */
    @Nested
    @DisplayName("getUserProfile")
    class GetUserProfile {

        @Test
        @DisplayName("returns remote user and caches it when network is available")
        void fetchesFromRemoteWhenOnline() throws Exception {
            when(networkMonitor.isConnected()).thenReturn(true);
            when(remoteSource.fetchUserProfile(USER_ID)).thenReturn(Optional.of(dummyRemoteUser));

            Optional<User> result = repository.getUserProfile(USER_ID);

            assertTrue(result.isPresent());
            assertEquals(dummyRemoteUser, result.get());

            // Verify call-order: first remote fetch then local cache.
            InOrder inOrder = inOrder(remoteSource, localSource);
            inOrder.verify(remoteSource).fetchUserProfile(USER_ID);
            inOrder.verify(localSource).saveUserProfile(dummyRemoteUser);

            verifyNoMoreInteractions(remoteSource, localSource);
        }

        @Test
        @DisplayName("falls back to local cache when network is unavailable")
        void fetchesFromLocalWhenOffline() {
            when(networkMonitor.isConnected()).thenReturn(false);
            when(localSource.getCachedUser(USER_ID)).thenReturn(Optional.of(dummyCachedUser));

            Optional<User> result = repository.getUserProfile(USER_ID);

            assertTrue(result.isPresent());
            assertEquals(dummyCachedUser, result.get());

            verify(localSource).getCachedUser(USER_ID);
            verifyNoInteractions(remoteSource);
        }

        @Test
        @DisplayName("propagates exception when remote fetch fails and no cache available")
        void propagatesExceptionWhenRemoteFails() throws Exception {
            when(networkMonitor.isConnected()).thenReturn(true);
            when(remoteSource.fetchUserProfile(USER_ID))
                    .thenThrow(new IOException("503 Service Unavailable"));

            when(localSource.getCachedUser(USER_ID)).thenReturn(Optional.empty());

            assertThrows(IOException.class, () -> repository.getUserProfile(USER_ID));

            verify(localSource).getCachedUser(USER_ID); // attempt to rescue with cache
        }
    }

    /* ------------------------------------------------------------
     * updateUserProfile(…)
     * ------------------------------------------------------------ */
    @Nested
    @DisplayName("updateUserProfile")
    class UpdateUserProfile {

        @Test
        @DisplayName("updates remote and local sources when network is available")
        void updatesBothSources() throws Exception {
            when(networkMonitor.isConnected()).thenReturn(true);
            when(remoteSource.updateUserProfile(dummyRemoteUser)).thenReturn(true);

            boolean success = repository.updateUserProfile(dummyRemoteUser);

            assertTrue(success);

            InOrder inOrder = inOrder(remoteSource, localSource);
            inOrder.verify(remoteSource).updateUserProfile(dummyRemoteUser);
            inOrder.verify(localSource).saveUserProfile(dummyRemoteUser);
        }

        @Test
        @DisplayName("returns false when remote update fails")
        void remoteUpdateFails() throws Exception {
            when(networkMonitor.isConnected()).thenReturn(true);
            when(remoteSource.updateUserProfile(dummyRemoteUser)).thenReturn(false);

            boolean success = repository.updateUserProfile(dummyRemoteUser);

            assertFalse(success);
            verify(localSource, never()).saveUserProfile(any());
        }

        @Test
        @DisplayName("throws IllegalStateException when offline")
        void throwsWhenOffline() {
            when(networkMonitor.isConnected()).thenReturn(false);

            assertThrows(IllegalStateException.class,
                    () -> repository.updateUserProfile(dummyRemoteUser));

            verifyNoInteractions(remoteSource);
        }
    }

    /* ------------------------------------------------------------
     * login(…)
     * ------------------------------------------------------------ */
    @Nested
    @DisplayName("login")
    class Login {

        @Test
        @DisplayName("returns token, stores it and pre-loads profile on success")
        void loginSuccess() throws Exception {
            Token token = new Token(AUTH_TOKEN_VALUE, Instant.now().plusSeconds(3600));
            when(remoteSource.login(EMAIL, PASSWORD)).thenReturn(Optional.of(token));
            when(remoteSource.fetchUserProfile(USER_ID)).thenReturn(Optional.of(dummyRemoteUser));
            when(tokenManager.decodeUserId(token)).thenReturn(USER_ID);
            when(networkMonitor.isConnected()).thenReturn(true);

            Optional<Token> result = repository.login(EMAIL, PASSWORD);

            assertTrue(result.isPresent());
            assertEquals(token, result.get());

            InOrder inOrder = inOrder(tokenManager, remoteSource, localSource);
            inOrder.verify(tokenManager).persistToken(token);
            inOrder.verify(remoteSource).fetchUserProfile(USER_ID);
            inOrder.verify(localSource).saveUserProfile(dummyRemoteUser);
        }

        @Test
        @DisplayName("returns empty Optional on authentication failure")
        void loginFailure() throws Exception {
            when(remoteSource.login(EMAIL, PASSWORD)).thenReturn(Optional.empty());

            Optional<Token> result = repository.login(EMAIL, PASSWORD);

            assertFalse(result.isPresent());
            verify(tokenManager, never()).persistToken(any());
        }
    }

    /* ------------------------------------------------------------
     * logout()
     * ------------------------------------------------------------ */
    @Test
    @DisplayName("logout clears cached user and token store")
    void logoutClearsEverything() {
        repository.logout();

        InOrder inOrder = inOrder(localSource, tokenManager);
        inOrder.verify(localSource).clear();
        inOrder.verify(tokenManager).clear();
        verifyNoInteractions(remoteSource);
    }
}
```