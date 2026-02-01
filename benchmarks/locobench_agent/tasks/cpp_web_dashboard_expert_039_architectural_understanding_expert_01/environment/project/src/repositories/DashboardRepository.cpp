```cpp
/*
 *  MosaicBoard Studio
 *  File: src/repositories/DashboardRepository.cpp
 *
 *  Description:
 *      Implementation of DashboardRepository – the data-access layer
 *      responsible for CRUD operations on the “dashboard” aggregate.
 *
 *      The repository uses:
 *          • orm::IDataContext      – abstract DB session/transaction wrapper
 *          • cache::ICacheProvider  – pluggable (Redis/LRU) cache interface
 *          • logging::ILogger       – structured logger
 *
 *      A soft-TTL cache is implemented to alleviate database load for the
 *      most frequent read queries (fetch by ID & owner).  Cache invalidation
 *      is automatically performed on create/update/delete.
 *
 *  NOTE:
 *      Interface declarations live in
 *      “include/repositories/DashboardRepository.h”.
 */

#include "repositories/DashboardRepository.h"

#include <fmt/format.h>
#include <nlohmann/json.hpp>
#include <soci/soci.h>
#include <soci/postgresql/soci-postgresql.h>
#include <utility>
#include <chrono>
#include <mutex>

using namespace std::chrono_literals;

namespace mosaic::repositories
{

// ─────────────────────────────────────────────────────────────────────────────
//  Helpers
// ─────────────────────────────────────────────────────────────────────────────

namespace
{
    /*
     * Convert a SOCI rowset into a strongly-typed Dashboard model.
     * Throws std::runtime_error when a required column is missing.
     */
    models::Dashboard toDashboard(const soci::row& row)
    {
        models::Dashboard d{};
        d.id            = uuids::uuid::from_string(row.get<std::string>("id"));
        d.name          = row.get<std::string>("name");
        d.ownerId       = uuids::uuid::from_string(row.get<std::string>("owner_id"));
        d.description   = row.get_indicator("description") == soci::i_ok
                        ? row.get<std::string>("description") : "";
        d.createdAt     = row.get<std::chrono::system_clock::time_point>("created_at");
        d.updatedAt     = row.get<std::chrono::system_clock::time_point>("updated_at");
        d.version       = row.get<uint32_t>("version");

        // tiles will be lazy-loaded by TileRepository
        return d;
    }

    /*
     * Serialize dashboard to JSON for caching.
     * Only the primitive scalar fields are cached; heavy nested data
     * such as tiles are intentionally excluded.
     */
    nlohmann::json toJson(const models::Dashboard& d)
    {
        return {
            { "id",           uuids::to_string(d.id)           },
            { "name",         d.name                           },
            { "owner_id",     uuids::to_string(d.ownerId)      },
            { "description",  d.description                    },
            { "created_at",   std::chrono::duration_cast<std::chrono::milliseconds>(
                                d.createdAt.time_since_epoch()).count() },
            { "updated_at",   std::chrono::duration_cast<std::chrono::milliseconds>(
                                d.updatedAt.time_since_epoch()).count() },
            { "version",      d.version                        }
        };
    }

    models::Dashboard jsonToDashboard(const nlohmann::json& j)
    {
        models::Dashboard d{};
        d.id          = uuids::uuid::from_string(j.at("id").get<std::string>());
        d.name        = j.at("name").get<std::string>();
        d.ownerId     = uuids::uuid::from_string(j.at("owner_id").get<std::string>());
        d.description = j.value("description", "");
        d.createdAt   = std::chrono::system_clock::time_point(
                            std::chrono::milliseconds(j.at("created_at").get<int64_t>()));
        d.updatedAt   = std::chrono::system_clock::time_point(
                            std::chrono::milliseconds(j.at("updated_at").get<int64_t>()));
        d.version     = j.at("version").get<uint32_t>();
        return d;
    }
} // namespace

// ─────────────────────────────────────────────────────────────────────────────
//  ctor / dtor
// ─────────────────────────────────────────────────────────────────────────────

DashboardRepository::DashboardRepository(std::shared_ptr<orm::IDataContext>        db,
                                         std::shared_ptr<cache::ICacheProvider>    cache,
                                         std::shared_ptr<logging::ILogger>         logger,
                                         std::chrono::seconds                      cacheTtl)
    : m_db        { std::move(db)    }
    , m_cache     { std::move(cache) }
    , m_logger    { std::move(logger)}
    , m_cacheTtl  { cacheTtl         }
{
    if (!m_db)    { throw std::invalid_argument("DashboardRepository: IDataContext is null"); }
    if (!m_cache) { throw std::invalid_argument("DashboardRepository: ICacheProvider is null"); }
    if (!m_logger){ throw std::invalid_argument("DashboardRepository: ILogger is null"); }
}

// ─────────────────────────────────────────────────────────────────────────────
//  Public API
// ─────────────────────────────────────────────────────────────────────────────

std::optional<models::Dashboard>
DashboardRepository::fetchById(const uuids::uuid& id)
{
    const std::string key = cacheKey(id);

    // Fast path: in-memory / Redis cache
    {
        std::scoped_lock lk { m_cacheMutex };
        if (auto jsonStr = m_cache->get(key); jsonStr)
        {
            m_logger->trace("DashboardRepository::fetchById – hit cache for {}", uuids::to_string(id));
            return jsonToDashboard(nlohmann::json::parse(*jsonStr));
        }
    }

    try
    {
        soci::row row;
        auto sql = m_db->session();
        sql->prepare << R"(
                SELECT  id, name, owner_id, description,
                        created_at, updated_at, version
                FROM    dashboards
                WHERE   id = :id
            )", soci::use(uuids::to_string(id)), soci::into(row);

        if (!sql->got_data())
        {
            return std::nullopt;
        }

        auto dash = toDashboard(row);

        // store in cache asynchronously
        {
            std::scoped_lock lk { m_cacheMutex };
            m_cache->set(key,
                         toJson(dash).dump(),
                         m_cacheTtl);
        }

        return dash;
    }
    catch (const std::exception& ex)
    {
        m_logger->error("DashboardRepository::fetchById – {}", ex.what());
        throw;  // bubble up; upper layer will translate to HTTP 500
    }
}

std::vector<models::Dashboard>
DashboardRepository::fetchByOwner(const uuids::uuid& ownerId,
                                  const utils::Pagination& pagination)
{
    try
    {
        std::vector<models::Dashboard> result;

        soci::rowset<soci::row> rows =
            (m_db->session()->prepare
                << R"(
                    SELECT  id, name, owner_id, description,
                            created_at, updated_at, version
                    FROM    dashboards
                    WHERE   owner_id = :owner
                    ORDER BY updated_at DESC
                    LIMIT   :limit
                    OFFSET  :offset
                )",
                soci::use(uuids::to_string(ownerId)),
                soci::use(pagination.limit),
                soci::use(pagination.offset));

        for (const auto& row : rows)
        {
            result.emplace_back(toDashboard(row));
        }
        return result;
    }
    catch (const std::exception& ex)
    {
        m_logger->error("DashboardRepository::fetchByOwner – {}", ex.what());
        throw;
    }
}

uuids::uuid
DashboardRepository::create(const models::DashboardCreateRequest& req)
{
    const uuids::uuid id = uuids::uuid_system_generator{}();

    try
    {
        (*m_db->session()) << R"(
                INSERT INTO dashboards
                (id, name, owner_id, description, created_at, updated_at, version)
                VALUES
                (:id, :name, :owner_id, :description, NOW(), NOW(), 1)
            )",
            soci::use(uuids::to_string(id)),
            soci::use(req.name),
            soci::use(uuids::to_string(req.ownerId)),
            soci::use(req.description);

        m_logger->info("DashboardRepository – Created dashboard {}", uuids::to_string(id));

        // Eagerly put in cache (prevents thundering herd on immediate redirect)
        {
            models::Dashboard dash {
                .id          = id,
                .name        = req.name,
                .ownerId     = req.ownerId,
                .description = req.description,
                .createdAt   = std::chrono::system_clock::now(),
                .updatedAt   = std::chrono::system_clock::now(),
                .version     = 1
            };
            std::scoped_lock lk{ m_cacheMutex };
            m_cache->set(cacheKey(id), toJson(dash).dump(), m_cacheTtl);
        }

        return id;
    }
    catch (const std::exception& ex)
    {
        m_logger->error("DashboardRepository::create – {}", ex.what());
        throw;
    }
}

bool
DashboardRepository::update(const models::DashboardUpdateRequest& req)
{
    try
    {
        int affected = 0;

        (*m_db->session()) << R"(
                UPDATE  dashboards
                SET     name        = :name,
                        description = :description,
                        updated_at  = NOW(),
                        version     = version + 1
                WHERE   id      = :id
                AND     version = :expectedVersion
            )",
            soci::use(req.name),
            soci::use(req.description),
            soci::use(uuids::to_string(req.id)),
            soci::use(req.expectedVersion),
            soci::exec(affected);

        const bool ok = affected == 1;

        if (ok)
        {
            m_logger->info("DashboardRepository – Updated dashboard {}", uuids::to_string(req.id));

            // Invalidate cache; will be lazily repopulated on next read
            std::scoped_lock lk { m_cacheMutex };
            m_cache->erase(cacheKey(req.id));
        }
        else
        {
            m_logger->warn("DashboardRepository::update – Optimistic lock failed for {}", uuids::to_string(req.id));
        }

        return ok;
    }
    catch (const std::exception& ex)
    {
        m_logger->error("DashboardRepository::update – {}", ex.what());
        throw;
    }
}

bool
DashboardRepository::remove(const uuids::uuid& id)
{
    try
    {
        int affected = 0;
        (*m_db->session()) << "DELETE FROM dashboards WHERE id = :id",
            soci::use(uuids::to_string(id)),
            soci::exec(affected);

        const bool ok = affected == 1;
        if (ok)
        {
            m_logger->info("DashboardRepository – Deleted dashboard {}", uuids::to_string(id));
            std::scoped_lock lk { m_cacheMutex };
            m_cache->erase(cacheKey(id));
        }
        return ok;
    }
    catch (const std::exception& ex)
    {
        m_logger->error("DashboardRepository::remove – {}", ex.what());
        throw;
    }
}

// ─────────────────────────────────────────────────────────────────────────────
//  Private helpers
// ─────────────────────────────────────────────────────────────────────────────

std::string
DashboardRepository::cacheKey(const uuids::uuid& id) const
{
    return fmt::format("dashboard:{}", uuids::to_string(id));
}

} // namespace mosaic::repositories
```