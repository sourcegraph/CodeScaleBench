package com.commercesphere.enterprise.user.repository;

import com.commercesphere.enterprise.user.entity.UserEntity;
import org.springframework.cache.annotation.CacheConfig;
import org.springframework.cache.annotation.CacheEvict;
import org.springframework.cache.annotation.Cacheable;
import org.springframework.data.domain.Page;
import org.springframework.data.domain.Pageable;
import org.springframework.data.jpa.repository.EntityGraph;
import org.springframework.data.jpa.repository.JpaRepository;
import org.springframework.data.jpa.repository.Modifying;
import org.springframework.data.jpa.repository.Query;
import org.springframework.data.repository.query.Param;
import org.springframework.stereotype.Repository;
import org.springframework.transaction.annotation.Transactional;

import java.time.Instant;
import java.util.List;
import java.util.Optional;
import java.util.UUID;

/**
 * Repository that encapsulates all persistence logic around {@link UserEntity}.
 * Leverages Spring Data JPA to generate most CRUD queries automatically and exposes
 * domain-specific queries consumed by the authentication, authorization, and account
 * hierarchy workflows of CommerceSphere Enterprise Suite.
 *
 * <p>
 * The interface makes heavy use of declarative caching to offload repeated
 * credential and permission lookups. State-mutating operations are responsible
 * for evicting stale cache entries to guarantee data consistency.
 * </p>
 */
@Repository
@CacheConfig(cacheNames = "users")
public interface UserRepository extends JpaRepository<UserEntity, UUID> {

    /* =========================================================================
       READ-ONLY OPERATIONS
       ========================================================================= */

    /**
     * Finds a user by username, ignoring case.
     *
     * @param username canonical username
     * @return optional user
     */
    @Cacheable(key = "T(java.util.Locale).ROOT.toString() + ':' + #username?.toLowerCase()")
    Optional<UserEntity> findByUsernameIgnoreCase(String username);

    /**
     * Fetches a fully-hydrated user including roles and permissions. Uses an
     * {@link EntityGraph} to mitigate N+1 queries when traversing associations.
     *
     * @param id user identifier
     * @return optional user
     */
    @EntityGraph(attributePaths = {"roles", "roles.permissions"})
    @Cacheable(key = "#id")
    Optional<UserEntity> findDetailedById(UUID id);

    /**
     * Returns all active (non-deleted, enabled) users associated with a particular role.
     *
     * @param roleKey role identifier (case-insensitive)
     * @return list of users
     */
    @Query("""
            select distinct u
              from UserEntity u
              join u.roles r
             where lower(r.key) = lower(:roleKey)
               and u.deleted  = false
               and u.enabled  = true
            """)
    List<UserEntity> findActiveUsersByRole(@Param("roleKey") String roleKey);

    /**
     * Executes a paginated keyword search across first name, last name, email, and username.
     *
     * @param term     search keyword
     * @param pageable page request
     * @return page of matching users
     */
    @Query("""
            select u
              from UserEntity u
             where ( lower(u.firstName) like lower(concat('%', :term, '%'))
                  or lower(u.lastName)  like lower(concat('%', :term, '%'))
                  or lower(u.email)     like lower(concat('%', :term, '%'))
                  or lower(u.username)  like lower(concat('%', :term, '%')) )
               and u.deleted = false
            """)
    Page<UserEntity> search(@Param("term") String term, Pageable pageable);

    /* =========================================================================
       MUTATING OPERATIONS
       ========================================================================= */

    /**
     * Updates the last-login timestamp. Executed during authentication to avoid
     * fetching and merging the entire entity.
     *
     * @param id        user identifier
     * @param timestamp new timestamp
     */
    @Transactional
    @Modifying(clearAutomatically = true, flushAutomatically = true)
    @Query("update UserEntity u set u.lastLogin = :timestamp where u.id = :id")
    void updateLastLogin(@Param("id") UUID id, @Param("timestamp") Instant timestamp);

    /**
     * Performs a logical (soft) delete while preserving historical audit data.
     * Evicts the corresponding cache entry to maintain consistency.
     *
     * @param id user identifier
     * @param ts deletion timestamp
     */
    @Transactional
    @Modifying(clearAutomatically = true, flushAutomatically = true)
    @CacheEvict(key = "#id")
    @Query("""
            update UserEntity u
               set u.deleted   = true,
                   u.enabled   = false,
                   u.deletedAt = :ts
             where u.id = :id
            """)
    void softDelete(@Param("id") UUID id, @Param("ts") Instant ts);

    /* =========================================================================
       CONVENIENCE HELPERS
       ========================================================================= */

    /**
     * Returns the user or throws {@link UserNotFoundException}.
     *
     * @param id user identifier
     * @return persisted user
     */
    default UserEntity getRequired(UUID id) {
        return findById(id).orElseThrow(() -> new UserNotFoundException(id));
    }

    /**
     * Runtime exception raised when a user cannot be found. Wrapped inside the
     * repository to keep the public API surface small and cohesive.
     */
    class UserNotFoundException extends RuntimeException {
        private static final long serialVersionUID = 6965162756915345578L;

        public UserNotFoundException(UUID id) {
            super("User with id [" + id + "] could not be found.");
        }
    }
}