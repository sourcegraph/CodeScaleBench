package com.commercesphere.enterprise.user.service;

import com.commercesphere.enterprise.common.exception.BusinessRuleViolationException;
import com.commercesphere.enterprise.common.exception.ResourceAlreadyExistsException;
import com.commercesphere.enterprise.common.exception.ResourceNotFoundException;
import com.commercesphere.enterprise.common.pagination.PageEnvelope;
import com.commercesphere.enterprise.user.domain.Role;
import com.commercesphere.enterprise.user.domain.User;
import com.commercesphere.enterprise.user.dto.RegistrationRequest;
import com.commercesphere.enterprise.user.dto.UserDto;
import com.commercesphere.enterprise.user.dto.UserSearchCriteria;
import com.commercesphere.enterprise.user.event.UserDeactivatedEvent;
import com.commercesphere.enterprise.user.event.UserRegisteredEvent;
import com.commercesphere.enterprise.user.mapper.UserMapper;
import com.commercesphere.enterprise.user.repository.RoleRepository;
import com.commercesphere.enterprise.user.repository.UserRepository;
import jakarta.validation.Valid;
import jakarta.validation.constraints.NotBlank;
import jakarta.validation.constraints.NotNull;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.apache.commons.lang3.StringUtils;
import org.springframework.cache.annotation.CacheEvict;
import org.springframework.cache.annotation.Cacheable;
import org.springframework.context.ApplicationEventPublisher;
import org.springframework.dao.DataIntegrityViolationException;
import org.springframework.data.domain.Page;
import org.springframework.data.domain.Pageable;
import org.springframework.security.crypto.password.PasswordEncoder;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

import java.time.OffsetDateTime;
import java.util.Objects;
import java.util.Optional;
import java.util.UUID;

/**
 * UserService is the primary boundary for manipulating User entities inside the
 * CommerceSphere Enterprise Suite.  All write-operations are executed inside a
 * transactional context and validated against business rules before the
 * persistence layer is invoked.
 *
 * <p>NOTE:  The actual controller layer should never operate directly on
 * JPA entities.  Therefore, this class exposes and consumes DTO objects to
 * decouple the transport and persistence layers.</p>
 */
@Slf4j
@Service
@RequiredArgsConstructor
public class UserService {

    public static final String CACHE_NAME_USER_BY_ID = "user.byId";

    private final UserRepository userRepository;
    private final RoleRepository roleRepository;
    private final PasswordEncoder passwordEncoder;
    private final ApplicationEventPublisher eventPublisher;
    private final UserMapper userMapper;

    /* -----------------------------------------------------------------------
     *  Read operations
     * --------------------------------------------------------------------- */

    @Cacheable(value = CACHE_NAME_USER_BY_ID, key = "#userId")
    @Transactional(readOnly = true)
    public UserDto getUserById(@NotNull UUID userId) {
        return userMapper.toDto(fetchExistingUser(userId));
    }

    @Transactional(readOnly = true)
    public PageEnvelope<UserDto> search(UserSearchCriteria criteria, Pageable pageable) {
        Objects.requireNonNull(criteria, "User search criteria must not be null");

        Page<User> page = userRepository.search(criteria, pageable);
        Page<UserDto> dtoPage = page.map(userMapper::toDto);

        return PageEnvelope.of(dtoPage);
    }

    /* -----------------------------------------------------------------------
     *  Write operations
     * --------------------------------------------------------------------- */

    /**
     * Registers a brand-new user, publishes a domain event, and evicts relevant
     * cache entries.  Duplicate email addresses are prohibited and will result
     * in a {@link ResourceAlreadyExistsException}.
     */
    @Transactional
    @CacheEvict(value = CACHE_NAME_USER_BY_ID, allEntries = true)
    public UserDto registerUser(@Valid RegistrationRequest request) {
        requireEmailNotRegistered(request.email());

        Role defaultRole = roleRepository
                .findByName(Role.DEFAULT_ROLE_CUSTOMER)
                .orElseThrow(() -> new ResourceNotFoundException("Default role not configured"));

        User user = User.builder()
                .id(UUID.randomUUID())
                .email(StringUtils.lowerCase(request.email()))
                .passwordHash(passwordEncoder.encode(request.rawPassword()))
                .firstName(request.firstName())
                .lastName(request.lastName())
                .active(true)
                .createdAt(OffsetDateTime.now())
                .role(defaultRole)
                .build();

        try {
            userRepository.save(user);
        } catch (DataIntegrityViolationException ex) {
            // In rare cases of race condition on unique key
            log.error("Integrity violation while saving user", ex);
            throw new ResourceAlreadyExistsException("Email is already registered");
        }

        eventPublisher.publishEvent(new UserRegisteredEvent(user.getId()));
        log.info("User [{}] successfully registered", user.getEmail());

        return userMapper.toDto(user);
    }

    /**
     * Changes a user's password after validating the current password matches.
     */
    @Transactional
    @CacheEvict(value = CACHE_NAME_USER_BY_ID, key = "#userId")
    public void changePassword(
            @NotNull UUID userId,
            @NotBlank String currentPassword,
            @NotBlank String newPassword
    ) {
        User user = fetchExistingUser(userId);

        boolean matches = passwordEncoder.matches(currentPassword, user.getPasswordHash());
        if (!matches) {
            throw new BusinessRuleViolationException("Current password is incorrect");
        }

        user.setPasswordHash(passwordEncoder.encode(newPassword));
        user.setUpdatedAt(OffsetDateTime.now());

        log.info("Password changed for user [{}]", user.getEmail());
    }

    /**
     * Deactivates a user account logically.  All authenticated tokens MUST be
     * revoked by the authentication subsystem (not handled here).
     */
    @Transactional
    @CacheEvict(value = CACHE_NAME_USER_BY_ID, key = "#userId")
    public void deactivateUser(@NotNull UUID userId, @NotBlank String reason) {
        User user = fetchExistingUser(userId);
        if (!user.isActive()) {
            log.debug("User [{}] already inactive; skipping", user.getEmail());
            return;
        }
        user.setActive(false);
        user.setDeactivatedReason(reason);
        user.setDeactivatedAt(OffsetDateTime.now());

        eventPublisher.publishEvent(new UserDeactivatedEvent(user.getId(), reason));

        log.info("User [{}] deactivated for reason: {}", user.getEmail(), reason);
    }

    /* -----------------------------------------------------------------------
     *  Internal helpers
     * --------------------------------------------------------------------- */

    private User fetchExistingUser(UUID userId) {
        return userRepository.findById(userId)
                .orElseThrow(() -> new ResourceNotFoundException("User not found: " + userId));
    }

    private void requireEmailNotRegistered(String email) {
        Optional<User> existing = userRepository.findByEmailIgnoreCase(email);
        if (existing.isPresent()) {
            throw new ResourceAlreadyExistsException("Email is already registered");
        }
    }
}