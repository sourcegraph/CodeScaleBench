```cpp
/**
 *  IntraLedger BlogSuite – module_80.cpp
 *
 *  Purpose:
 *      Implements the internal asynchronous job–dispatching facility that powers
 *      background processing such as e-mail delivery, image transformations,
 *      cache-warming, and other maintenance tasks.
 *
 *  This translation unit purposefully contains only *in-memory* routing logic.
 *  Queue back-ends (Redis, PostgreSQL LISTEN/NOTIFY, AMQP, …) feed JSON blobs
 *  to JobRouter::dispatch(..).  The router deserialises the manifest, instantiates
 *  an appropriate handler, and executes the workload on a detached std::async
 *  task, propagating exceptions through a std::future<void>.
 *
 *  Dependencies:
 *      - nlohmann/json (single header)
 *      - spdlog          (optional; falls back to std::cerr if unavailable)
 *
 *  Compile flags (example):
 *      g++ -std=c++20 -pthread -O2 -Wall -Wextra src/module_80.cpp -o blogsuite
 *
 *  © 2024 IntraLedger Ltd.  All rights reserved.
 */

#include <chrono>
#include <cstddef>
#include <exception>
#include <future>
#include <memory>
#include <mutex>
#include <sstream>
#include <string>
#include <thread>
#include <unordered_map>
#include <utility>
#include <vector>

#include <nlohmann/json.hpp>   // https://github.com/nlohmann/json
using json = nlohmann::json;

#ifdef BLOGSUITE_HAS_SPDLOG
    #include <spdlog/spdlog.h>
    namespace blog_log = spdlog;
#else
    #include <iostream>
    namespace blog_log
    {
        struct fallback_logger
        {
            template <typename... Args>
            void info(std::string_view fmt, Args&&... args) const noexcept
            {
                std::lock_guard<std::mutex> guard(io_);
                print("[ INFO ]", fmt, std::forward<Args>(args)...);
            }
            template <typename... Args>
            void error(std::string_view fmt, Args&&... args) const noexcept
            {
                std::lock_guard<std::mutex> guard(io_);
                print("[ERROR]", fmt, std::forward<Args>(args)...);
            }
            template <typename... Args>
            void warn(std::string_view fmt, Args&&... args) const noexcept
            {
                std::lock_guard<std::mutex> guard(io_);
                print("[ WARN]", fmt, std::forward<Args>(args)...);
            }
        private:
            template <typename... Args>
            void print(std::string_view level, std::string_view fmt, Args&&... args) const
            {
                std::ostringstream oss;
                (oss << ... << std::forward<Args>(args));
                std::cerr << level << ' ' << fmt << ' ' << oss.str() << '\n';
            }
            mutable std::mutex io_;
        };

        static fallback_logger default_logger;
    } // namespace blog_log
#endif // BLOGSUITE_HAS_SPDLOG

namespace intraledger::blogsuite::jobs
{
/*──────────────────────────────────────────────────────────────────────────────*/

class JobExecutionError : public std::runtime_error
{
public:
    explicit JobExecutionError(const std::string& msg)
        : std::runtime_error(msg) {}
};

/**
 *  Base interface – all concrete background job handlers must implement this
 *  polymorphic contract.
 */
class IJobHandler
{
public:
    virtual ~IJobHandler()                          = default;
    virtual void execute(const json& payload)          = 0;
};

/*──── Concrete Job Handlers ──────────────────────────────────────────────────*/

class EmailJobHandler final : public IJobHandler
{
public:
    void execute(const json& payload) override
    {
        const auto& to      = payload.at("to").get<std::string>();
        const auto& subject = payload.at("subject").get<std::string>();
        const auto& body    = payload.at("body").get<std::string>();

        // Placeholder: real implementation would enqueue to Mailer subsystem.
        blog_log::default_logger.info(
            "Sending e-mail → '{}', subject='{}'", to, subject);

        std::this_thread::sleep_for(std::chrono::milliseconds(120)); // simulate

        blog_log::default_logger.info("E-mail to '{}' sent.", to);
    }
};

class ImageTransformJobHandler final : public IJobHandler
{
public:
    void execute(const json& payload) override
    {
        const auto& imagePath   = payload.at("path").get<std::string>();
        const auto& operations  = payload.at("ops");

        blog_log::default_logger.info("Transforming image '{}'", imagePath);

        for (const auto& op : operations)
        {
            const auto& name = op.at("name").get<std::string>();
            blog_log::default_logger.info("Applying op '{}'", name);
            std::this_thread::sleep_for(std::chrono::milliseconds(75));
        }

        blog_log::default_logger.info("Image '{}' transformed.", imagePath);
    }
};

class CacheWarmJobHandler final : public IJobHandler
{
public:
    void execute(const json& payload) override
    {
        const auto& url = payload.at("url").get<std::string>();
        blog_log::default_logger.info("Cache-warming '{}'", url);

        // Simulate an HTTP request latency.
        std::this_thread::sleep_for(std::chrono::milliseconds(60));

        blog_log::default_logger.info("Cache prepared for '{}'", url);
    }
};

/*──── Job Registry & Factory ─────────────────────────────────────────────────*/

/**
 *  Thread-safe registry that maps a job-type string to a factory functor able to
 *  create its handler at runtime.
 */
class JobRegistry
{
public:
    using Factory = std::function<std::unique_ptr<IJobHandler>()>;

    static JobRegistry& instance()
    {
        static JobRegistry reg;
        return reg;
    }

    void registerHandler(std::string_view type, Factory factory)
    {
        std::lock_guard<std::mutex> lock(mutex_);
        if (!registry_.emplace(type, std::move(factory)).second)
        {
            throw std::logic_error("Job handler '" + std::string(type) +
                                   "' already registered.");
        }
    }

    std::unique_ptr<IJobHandler> makeHandler(std::string_view type) const
    {
        std::lock_guard<std::mutex> lock(mutex_);
        auto it = registry_.find(type);
        if (it == registry_.end())
        {
            throw JobExecutionError(
                "Unknown job-type '" + std::string(type) + "'.");
        }
        return it->second();
    }

private:
    JobRegistry()
    {
        // Pre-register built-in handlers.
        registerHandler("email", [] { return std::make_unique<EmailJobHandler>(); });
        registerHandler("image_transform",
                        [] { return std::make_unique<ImageTransformJobHandler>(); });
        registerHandler("cache_warm",
                        [] { return std::make_unique<CacheWarmJobHandler>(); });
    }

    mutable std::mutex                                      mutex_;
    std::unordered_map<std::string, Factory>                registry_;
};

/*──── Job Router ─────────────────────────────────────────────────────────────*/

/**
 *  Stateless utility class that parses JSON jobs, resolves their handlers and
 *  launches them on detached threads.  Exceptions are captured and stored in
 *  the std::future, allowing callers to react to failures.
 */
class JobRouter
{
public:
    /**
     * Dispatches a job JSON blob into the asynchronous pool.
     *
     * JSON schema (example):
     * {
     *   "type"    : "email",
     *   "payload" : { ... },
     *   "meta"    : { "request_id": "abc-123" }
     * }
     */
    [[nodiscard]] static std::future<void> dispatch(std::string_view jobJson)
    {
        try
        {
            const json doc = json::parse(jobJson);

            const std::string& type = doc.at("type");
            const json& payload     = doc.at("payload");

            auto handler = JobRegistry::instance().makeHandler(type);

            return std::async(std::launch::async,
                              [handler = std::move(handler), payload,
                               meta      = doc.value("meta", json::object())]
            {
                const auto startTs = std::chrono::steady_clock::now();
                try
                {
                    blog_log::default_logger.info(
                        "Job start → type='{}', meta={}", meta.dump(), type);
                    handler->execute(payload);
                    const auto dur =
                        std::chrono::duration_cast<std::chrono::milliseconds>(
                            std::chrono::steady_clock::now() - startTs)
                            .count();
                    blog_log::default_logger.info("Job '{}' completed in {} ms",
                                                   type, dur);
                }
                catch (const std::exception& ex)
                {
                    blog_log::default_logger.error(
                        "Job '{}' failed: {}", type, ex.what());
                    throw; // rethrow to future
                }
            });
        }
        catch (const std::exception& ex)
        {
            // Parsing or registry errors happen synchronously.
            throw JobExecutionError(
                std::string("Job dispatch failed: ") + ex.what());
        }
    }

private:
    JobRouter()  = delete;
    ~JobRouter() = delete;
};

} // namespace intraledger::blogsuite::jobs

/*───────────────────────── Test Harness (optional) ───────────────────────────
 *  To verify basic functionality compile with:
 *      g++ -std=c++20 -pthread src/module_80.cpp && ./a.out
 *  (Comment-out this section when linking into the main executable.)
 */
#ifdef BLOGSUITE_MODULE_80_STANDALONE
#include <iostream>

int main()
{
    using intraledger::blogsuite::jobs::JobRouter;

    // e-mail job
    const std::string job1 = R"({
        "type": "email",
        "payload": {
            "to"     : "alice@example.com",
            "subject": "Welcome!",
            "body"   : "Hello Alice, thanks for subscribing."
        },
        "meta": { "request_id": "req-1" }
    })";

    auto fut1 = JobRouter::dispatch(job1);

    // image transform
    const std::string job2 = R"({
        "type": "image_transform",
        "payload": {
            "path": "/images/hero.png",
            "ops": [
                { "name": "resize", "w": 1280 },
                { "name": "compress", "quality": 80 }
            ]
        }
    })";

    auto fut2 = JobRouter::dispatch(job2);

    fut1.get();
    fut2.get();

    std::cout << "All jobs finished.\n";
}
#endif
```