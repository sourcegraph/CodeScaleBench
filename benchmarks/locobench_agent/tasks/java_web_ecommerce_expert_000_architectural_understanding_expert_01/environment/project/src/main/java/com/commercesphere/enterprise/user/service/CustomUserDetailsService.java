```java
package com.commercesphere.enterprise.user.service;

import com.commercesphere.enterprise.common.audit.AuditEventPublisher;
import com.commercesphere.enterprise.common.audit.AuditEvents;
import com.commercesphere.enterprise.common.exception.ServiceLayerException;
import com.commercesphere.enterprise.user.model.AuthenticatedUser;
import com.commercesphere.enterprise.user.model.UserAccount;
import com.commercesphere.enterprise.user.repository.UserAccountRepository;
import lombok.NonNull;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.cache.annotation.Cacheable;
import org.springframework.dao.DataAccessException;
import org.springframework.lang.Nullable;
import org.springframework.security.authentication.AccountExpiredException;
import org.springframework.security.authentication.CredentialsExpiredException;
import org.springframework.security.authentication.DisabledException;
import org.springframework.security.authentication.LockedException;
import org.springframework.security.core.userdetails.UserDetails;
import org.springframework.security.core.userdetails.UserDetailsService;
import org.springframework.security.core.userdetails.UsernameNotFoundException;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

import java.time.Clock;
import java.time.LocalDateTime;
import java.util.Optional;

/**
 * CustomUserDetailsService is the bridge between Spring-Security and our
 * domain user model (UserAccount). It enriches the retrieved user with
 * platform-specific data (e.g., tenant, role hierarchy) and enforces
 * pre-authentication checks such as lock-outs, password expiration,
 * and account validity windows.
 *
 * Instances are singletons managed by Spring's IoC container.
 */
@Slf4j
@Service
@RequiredArgsConstructor
public class CustomUserDetailsService implements UserDetailsService {

    private static final String CACHE_NAME = "auth.user-details";

    private final UserAccountRepository accountRepository;
    private final AuditEventPublisher auditPublisher;
    private final PasswordPolicyService passwordPolicyService;
    private final Clock clock;

    /**
     * Delegated entry-point used by Spring-Security.
     *
     * The result is cached to minimize DB round-trips during a flood
     * of concurrent login attempts (e.g., SSO token refresh).
     *
     * @param identifier username or corporate email address
     * @return a fully populated AuthenticatedUser
     * @throws UsernameNotFoundException if user does not exist or is soft-deleted
     */
    @Override
    @Cacheable(value = CACHE_NAME, key = "#identifier", unless = "#result == null")
    @Transactional(readOnly = true)
    public UserDetails loadUserByUsername(@NonNull String identifier)
            throws UsernameNotFoundException {

        try {
            UserAccount account = fetchActiveAccount(identifier)
                    .orElseThrow(() -> new UsernameNotFoundException(
                            "No account found for: " + identifier));

            performPreAuthenticationChecks(account);

            return new AuthenticatedUser(account);
        } catch (DataAccessException dae) {
            // Translate lower-level persistence exception into service layer exception
            log.error("Database error during authentication for '{}'", identifier, dae);
            throw new ServiceLayerException(
                    "Unable to authenticate due to an internal error", dae);
        }
    }

    /**
     * Retrieve a non-deleted account by username or email.
     */
    private Optional<UserAccount> fetchActiveAccount(String identifier) {
        return accountRepository.findActiveByUsernameOrEmail(identifier, identifier);
    }

    /**
     * Applies a chained set of validation rules **before** the user
     * continues through the Spring security filter chain.
     *
     * Rules enforced:
     *  1. Account enabled
     *  2. Account not locked
     *  3. Account not expired (start/end validity)
     *  4. Password not expired
     */
    private void performPreAuthenticationChecks(UserAccount account) {
        LocalDateTime now = LocalDateTime.now(clock);

        if (!account.isEnabled()) {
            auditPublisher.publish(AuditEvents.ACCOUNT_DISABLED, account.getId(), null);
            throw new DisabledException("Account is disabled");
        }

        if (account.isLocked()) {
            auditPublisher.publish(AuditEvents.ACCOUNT_LOCKED, account.getId(), null);
            throw new LockedException("Account is locked");
        }

        // Validity window check (for contractors / temporary accounts)
        if (isOutsideValidityWindow(account, now)) {
            auditPublisher.publish(AuditEvents.ACCOUNT_EXPIRED, account.getId(), null);
            throw new AccountExpiredException("Account is expired");
        }

        // Password expiration policy
        if (passwordPolicyService.isPasswordExpired(account, now)) {
            auditPublisher.publish(AuditEvents.PASSWORD_EXPIRED, account.getId(), null);
            throw new CredentialsExpiredException("Password is expired");
        }
    }

    private boolean isOutsideValidityWindow(UserAccount account, LocalDateTime now) {
        @Nullable LocalDateTime validFrom = account.getValidFrom();
        @Nullable LocalDateTime validUntil = account.getValidUntil();

        boolean beforeStart = validFrom != null && now.isBefore(validFrom);
        boolean afterEnd   = validUntil != null && now.isAfter(validUntil);

        return beforeStart || afterEnd;
    }
}
```