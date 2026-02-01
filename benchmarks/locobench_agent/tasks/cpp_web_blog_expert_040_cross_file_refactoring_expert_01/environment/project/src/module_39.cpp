```cpp
/***********************************************************************
*  IntraLedger BlogSuite – module_39.cpp
*
*  Component: RBAC (Role-Based Access-Control) Permission Evaluator
*  ---------------------------------------------------------------------
*  This module belongs to the Security / Authorization layer of
*  BlogSuite.  It is responsible for efficiently determining whether a
*  user possesses a specific permission by combining role membership
*  (fetched via Repository) with an in-memory, thread-safe cache that
*  features automatic time-to-live (TTL) expiry.
*
*  NOTE:
*    • This file is self-contained to keep example size reasonable; in
*      production it would be split into separate headers/sources.
*    • Any database access is simulated through an in-memory repository
*      (see `InMemoryRoleRepository`) so the file builds standalone.
*
*  Author : IntraLedger Engineering
*  License: Proprietary, All Rights Reserved
***********************************************************************/

#include <algorithm>
#include <bitset>
#include <chrono>
#include <cstdint>
#include <cstdlib>
#include <future>
#include <iostream>
#include <memory>
#include <mutex>
#include <shared_mutex>
#include <string>
#include <thread>
#include <unordered_map>
#include <utility>
#include <vector>

namespace ilbs   /* IntraLedger BlogSuite */
{
namespace rbac   /* Role-Based Access Control */
{

/* ------------------------------------------------------------------ */
/* 1. Permission Enumeration                                           */
/* ------------------------------------------------------------------ */

enum class Permission : std::uint16_t
{
    ReadArticle          = 0,
    WriteArticle         = 1,
    PublishArticle       = 2,
    DeleteArticle        = 3,
    ManageUsers          = 4,
    ManageSubscriptions  = 5,
    ViewAnalytics        = 6,
    SystemAdministration = 7,

    COUNT /* Keep this one last */
};

constexpr std::size_t kPermissionCount =
    static_cast<std::size_t>(Permission::COUNT);

/* ------------------------------------------------------------------ */
/* 2. Role Entity                                                      */
/* ------------------------------------------------------------------ */

struct Role
{
    std::uint32_t      id             = 0;
    std::string        name;
    std::bitset<kPermissionCount> permissions;
};

/* ------------------------------------------------------------------ */
/* 3. Repository Interface & Mock Implementation                       */
/* ------------------------------------------------------------------ */

class IUserRoleRepository
{
public:
    virtual ~IUserRoleRepository() = default;
    virtual std::vector<Role> fetchRolesForUser(std::uint32_t userId) = 0;
};

/*
 * A very small in-memory repository to simulate database calls.
 * Thread-safe and deliberately slow to help verify the cache path.
 */
class InMemoryRoleRepository final : public IUserRoleRepository
{
public:
    InMemoryRoleRepository()
    {
        // --- Seed demo roles ----------------------------------------
        Role author;
        author.id   = 1;
        author.name = "Author";
        author.permissions.set(static_cast<std::size_t>(Permission::ReadArticle));
        author.permissions.set(static_cast<std::size_t>(Permission::WriteArticle));
        author.permissions.set(static_cast<std::size_t>(Permission::PublishArticle));

        Role admin;
        admin.id   = 2;
        admin.name = "Administrator";
        admin.permissions.set(); // all bits to 1
        admin.permissions.reset(static_cast<std::size_t>(Permission::DeleteArticle)); // Example

        m_rolesByUser.emplace(1001U, std::vector<Role>{author});
        m_rolesByUser.emplace(  42U, std::vector<Role>{author, admin});
    }

    std::vector<Role> fetchRolesForUser(std::uint32_t userId) override
    {
        // Simulate I/O latency
        std::this_thread::sleep_for(std::chrono::milliseconds(25));

        const auto it = m_rolesByUser.find(userId);
        if (it == m_rolesByUser.end())
            return {};

        return it->second;
    }

private:
    std::unordered_map<std::uint32_t, std::vector<Role>> m_rolesByUser;
};

/* ------------------------------------------------------------------ */
/* 4. Permission Evaluator Service                                     */
/* ------------------------------------------------------------------ */

class PermissionEvaluator
{
public:
    explicit PermissionEvaluator(std::shared_ptr<IUserRoleRepository> repo,
                                 std::chrono::seconds cacheTtl = std::chrono::minutes(2))
        : m_repo(std::move(repo)), m_cacheTtl(cacheTtl)
    {
        if (!m_repo)
            throw std::invalid_argument("IUserRoleRepository cannot be null");

        // Schedule periodic cache pruning
        m_cleanerThread = std::thread(&PermissionEvaluator::housekeepingWorker, this);
    }

    ~PermissionEvaluator()
    {
        m_shutdownRequested.store(true);
        if (m_cleanerThread.joinable())
            m_cleanerThread.join();
    }

    PermissionEvaluator(const PermissionEvaluator&)            = delete;
    PermissionEvaluator& operator=(const PermissionEvaluator&) = delete;

    /* Evaluate whether the user has `perm`. Fast path hits the cache. */
    bool hasPermission(std::uint32_t userId, Permission perm)
    {
        const CacheKey key{userId, perm};

        // ---------- 1. Try cache hit (shared lock) -----------------
        {
            std::shared_lock<std::shared_mutex> rLock(m_cacheMutex);
            auto it = m_cache.find(key);
            if (it != m_cache.end() && !isExpired(it->second))
            {
                return it->second.granted;
            }
        }

        // ---------- 2. Slow path ‑ fetch from repository -----------
        bool granted = false;
        try
        {
            // Launch fetch asynchronously to prevent blocking for too long
            std::future<std::vector<Role>> fut =
                std::async(std::launch::async, &IUserRoleRepository::fetchRolesForUser, m_repo, userId);

            const std::vector<Role> roles = fut.get();
            granted                       = evaluateRoles(roles, perm);
        }
        catch (const std::exception& ex)
        {
            // Log & fall back to conservative denial; in real code route to logger
            std::cerr << "[RBAC] Repository access failed: " << ex.what() << '\n';
            granted = false;
        }

        // ---------- 3. Store in cache (unique lock) ----------------
        {
            std::unique_lock<std::shared_mutex> wLock(m_cacheMutex);
            m_cache[key] = CacheEntry{granted, std::chrono::steady_clock::now()};
        }

        return granted;
    }

    /* Explicitly invalidate all cached permissions for a user. */
    void invalidateUser(std::uint32_t userId)
    {
        std::unique_lock<std::shared_mutex> wLock(m_cacheMutex);
        for (auto it = m_cache.begin(); it != m_cache.end();)
        {
            if (it->first.userId == userId)
                it = m_cache.erase(it);
            else
                ++it;
        }
    }

private:
    /* --------------------- Internal Structures ------------------- */

    struct CacheKey
    {
        std::uint32_t userId;
        Permission    permission;

        bool operator==(const CacheKey& other) const noexcept
        {
            return userId == other.userId && permission == other.permission;
        }
    };

    struct CacheKeyHasher
    {
        std::size_t operator()(const CacheKey& k) const noexcept
        {
            return (static_cast<std::size_t>(k.userId) << 8) ^
                   static_cast<std::size_t>(k.permission);
        }
    };

    struct CacheEntry
    {
        bool granted;
        std::chrono::steady_clock::time_point ts;
    };

    /* --------------------- Helper Utilities ---------------------- */

    static bool evaluateRoles(const std::vector<Role>& roles, Permission perm)
    {
        const std::size_t index = static_cast<std::size_t>(perm);
        return std::any_of(roles.begin(), roles.end(),
                           [index](const Role& r) { return r.permissions.test(index); });
    }

    bool isExpired(const CacheEntry& e) const noexcept
    {
        return (std::chrono::steady_clock::now() - e.ts) > m_cacheTtl;
    }

    void housekeepingWorker()
    {
        using namespace std::chrono_literals;
        while (!m_shutdownRequested.load())
        {
            {
                std::unique_lock<std::shared_mutex> wLock(m_cacheMutex);
                for (auto it = m_cache.begin(); it != m_cache.end();)
                {
                    if (isExpired(it->second))
                        it = m_cache.erase(it);
                    else
                        ++it;
                }
            }
            std::this_thread::sleep_for(15s);
        }
    }

    /* --------------------- Data Members -------------------------- */

    std::shared_ptr<IUserRoleRepository> m_repo;
    std::chrono::seconds                 m_cacheTtl;

    std::unordered_map<CacheKey, CacheEntry, CacheKeyHasher> m_cache;
    mutable std::shared_mutex                                  m_cacheMutex;

    std::thread                     m_cleanerThread;
    std::atomic_bool                m_shutdownRequested{false};
};

/* ------------------------------------------------------------------ */
/* 5. Stand-Alone Test Harness                                         */
/* ------------------------------------------------------------------ */

#if defined(ILBS_RBAC_UNIT_TEST)
/*
 * A quick single-threaded functional check. Compile with:
 *   g++ -std=c++20 -DILBS_RBAC_UNIT_TEST module_39.cpp -lpthread
 */
int main()
{
    using namespace ilbs::rbac;

    auto repo     = std::make_shared<InMemoryRoleRepository>();
    PermissionEvaluator evaluator(repo, std::chrono::seconds(10));

    const std::uint32_t user = 1001;

    std::cout << "User " << user << " may publish? "
              << evaluator.hasPermission(user, Permission::PublishArticle) << '\n';

    std::cout << "User " << user << " may delete?  "
              << evaluator.hasPermission(user, Permission::DeleteArticle) << '\n';

    // Invalidate and recheck (should force repo fetch again)
    evaluator.invalidateUser(user);

    std::cout << "After invalidation: may publish? "
              << evaluator.hasPermission(user, Permission::PublishArticle) << '\n';

    return EXIT_SUCCESS;
}
#endif /* ILBS_RBAC_UNIT_TEST */

} // namespace rbac
} // namespace ilbs
```