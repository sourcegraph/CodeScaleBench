#include "DatabaseManager.h"

#include <pqxx/pqxx>                    // PostgreSQL C++ driver
#include <filesystem>                   // C++17 filesystem utilities
#include <fstream>                      // std::ifstream
#include <iostream>                     // std::cerr / std::cout
#include <queue>                        // std::queue  (connection pool)
#include <thread>                       // hardware_concurrency
#include <chrono>                       // std::chrono utils
#include <condition_variable>           // std::condition_variable
#include <stdexcept>                    // std::runtime_error
#include <atomic>                       // std::atomic_bool

namespace mosaic::db
{

// ─────────────────────────────────────────────────────────────────────────────
//  Constants / Internal helpers
// ─────────────────────────────────────────────────────────────────────────────
namespace
{
constexpr auto kAcquireTimeout = std::chrono::seconds(10);
constexpr auto kDefaultPoolSize = 4;
} // namespace

// ─────────────────────────────────────────────────────────────────────────────
//  PooledConnection implementation
// ─────────────────────────────────────────────────────────────────────────────
DatabaseManager::PooledConnection::PooledConnection(DatabaseManager& mgr,
                                                    std::unique_ptr<pqxx::connection>&& conn) noexcept
    : _manager(&mgr)
    , _connection(std::move(conn))
{}

DatabaseManager::PooledConnection::PooledConnection(PooledConnection&& other) noexcept
    : _manager(other._manager)
    , _connection(std::move(other._connection))
{
    other._manager = nullptr;
}

DatabaseManager::PooledConnection::~PooledConnection() noexcept
{
    if (_manager && _connection)
    {
        _manager->release(std::move(_connection));
    }
}

pqxx::connection& DatabaseManager::PooledConnection::operator*() const noexcept
{
    return *_connection;
}

pqxx::connection* DatabaseManager::PooledConnection::operator->() const noexcept
{
    return _connection.get();
}

// ─────────────────────────────────────────────────────────────────────────────
//  DatabaseManager implementation
// ─────────────────────────────────────────────────────────────────────────────
DatabaseManager& DatabaseManager::instance()
{
    static DatabaseManager singleton;
    return singleton;
}

DatabaseManager::DatabaseManager()  = default;
DatabaseManager::~DatabaseManager() = default;

void DatabaseManager::initialize(DatabaseConfig cfg)
{
    std::unique_lock<std::mutex> lk(_initMutex);
    if (_initialized)
        throw std::runtime_error("DatabaseManager already initialized");

    _config        = std::move(cfg);
    _stopRequested = false;

    const std::size_t poolSize =
        _config.poolSize == 0 ? std::clamp(std::thread::hardware_concurrency(),
                                           static_cast<unsigned>(1U),
                                           static_cast<unsigned>(16U))
                              : _config.poolSize;

    for (std::size_t n = 0; n < poolSize; ++n)
    {
        auto conn = makeConnection(); // may throw
        _available.push(conn.get());
        _pool.emplace_back(std::move(conn));
    }

    _initialized = true;
}

DatabaseManager::PooledConnection DatabaseManager::acquire()
{
    if (!_initialized)
        throw std::runtime_error("DatabaseManager not initialized");

    std::unique_lock<std::mutex> lk(_cvMutex);
    if (!_cv.wait_for(lk, kAcquireTimeout, [&] { return !_available.empty() || _stopRequested; }))
        throw std::runtime_error("Timed-out while waiting for free DB connection");

    if (_stopRequested)
        throw std::runtime_error("Cannot acquire connection while shutdown is requested");

    auto* rawConn                      = _available.front();
    _available.pop();
    std::unique_ptr<pqxx::connection> c;

    // Find ownership wrapper for this pointer
    for (auto& ptr : _pool)
    {
        if (ptr.get() == rawConn)
        {
            c = std::move(ptr);
            break;
        }
    }
    if (!c)
        throw std::logic_error("Fatal: connection object not found in pool");

    // Ensure connection is alive
    if (!c->is_open())
    {
        // Re-create the connection on the fly
        c = makeConnection();
    }

    return PooledConnection(*this, std::move(c));
}

void DatabaseManager::release(std::unique_ptr<pqxx::connection>&& conn) noexcept
{
    try
    {
        std::lock_guard<std::mutex> lk(_cvMutex);
        _available.push(conn.get());

        // Place wrapper back into pool vector
        for (auto& ptr : _pool)
        {
            if (ptr == nullptr)
            {
                ptr = std::move(conn);
                break;
            }
        }
    }
    catch (...)
    {
        std::cerr << "Failed to release DB connection back to the pool\n";
    }

    _cv.notify_one();
}

void DatabaseManager::shutdown() noexcept
{
    {
        std::scoped_lock lk(_cvMutex, _initMutex);
        _stopRequested = true;
        _cv.notify_all();
    }

    // Give pending workers a chance to complete
    std::this_thread::sleep_for(std::chrono::milliseconds(50));

    _pool.clear();
    _initialized = false;
}

void DatabaseManager::runMigration(const std::filesystem::path& sqlFile)
{
    if (!std::filesystem::exists(sqlFile))
        throw std::invalid_argument("Migration file not found: " + sqlFile.string());

    std::ifstream in(sqlFile);
    if (!in)
        throw std::runtime_error("Cannot open migration file: " + sqlFile.string());

    std::string sql((std::istreambuf_iterator<char>(in)), std::istreambuf_iterator<char>());

    auto connectionHandle = acquire(); // RAII
    pqxx::work          txn(*connectionHandle);

    txn.exec(sql);
    txn.commit();
}

std::unique_ptr<pqxx::connection> DatabaseManager::makeConnection() const
{
    std::stringstream ss;
    ss << "host=" << _config.host;
    ss << " port=" << _config.port;
    ss << " dbname=" << _config.database;
    ss << " user=" << _config.user;
    ss << " password=" << _config.password;
    ss << " connect_timeout=10"; // seconds

    auto conn = std::make_unique<pqxx::connection>(ss.str());

    if (!conn->is_open())
        throw std::runtime_error("Failed to open DB connection");

    if (!conn->prepared("one"))
    { // warm-up simple prepared statement
        conn->prepare("one", "SELECT 1");
    }

    return conn;
}

// ─────────────────────────────────────────────────────────────────────────────
//  High-level helpers
// ─────────────────────────────────────────────────────────────────────────────
void DatabaseManager::logStatus(std::ostream& os) const
{
    std::lock_guard<std::mutex> lk(_cvMutex);
    os << "[DatabaseManager] poolSize=" << _pool.size()
       << ", available=" << _available.size()
       << ", shuttingDown=" << std::boolalpha << _stopRequested.load() << '\n';
}

} // namespace mosaic::db