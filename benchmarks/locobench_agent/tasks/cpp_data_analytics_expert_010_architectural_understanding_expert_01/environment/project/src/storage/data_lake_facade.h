```cpp
#pragma once
/*
 *  cardio_insight_360/src/storage/data_lake_facade.h
 *
 *  CardioInsight360 – Unified Healthcare Analytics Engine
 *  -------------------------------------------------------
 *  High-level façade that shields the rest of the application from
 *  low-level I/O details and on-disk layout conventions of the
 *  CardioInsight Data-Lake.
 *
 *  The façade offers:
 *     • Thread-safe, exception-aware read / write API
 *     • Hierarchical storage layout abstractions (raw, curated, meta)
 *     • Transparent Parquet serialization helpers
 *     • Simple Observer hook for run-time metrics
 *
 *  Copyright (c) 2024
 *  All rights reserved.
 */

#include <chrono>
#include <filesystem>
#include <future>
#include <memory>
#include <mutex>
#include <optional>
#include <shared_mutex>
#include <stdexcept>
#include <string>
#include <unordered_map>
#include <utility>
#include <vector>

namespace ci360::storage {

// ---------------------------------------------------------------------------------------------------------------------
// Forward declarations for implementation details that live in the .cpp / other subsystems.
// ---------------------------------------------------------------------------------------------------------------------

class ParquetWriter;
class ParquetReader;

// ---------------------------------------------------------------------------------------------------------------------
// DataLakeFacade
// ---------------------------------------------------------------------------------------------------------------------

/**
 * Thread-safe façade that exposes a minimal surface of the internal Data-Lake.
 *
 * The lake is organized as
 *    <root>/<tenant>/<yyyy>/<mm>/<dd>/<content_type>/<file.parquet>
 *
 * where:
 *    • tenant         – logical hospital network or research partner
 *    • yyyy/mm/dd     – acquisition date
 *    • content_type   – {raw, curated, meta}
 *
 * All public APIs are guaranteed not to throw on recoverable errors but instead
 * return std::optional<T> or propagate a typed std::system_error so that callers
 * can make robust decisions in high-availability environments.
 */
class DataLakeFacade final
{
public:
    // -----------------------------------------------------------------------------------------------------------------
    // Construction / destruction
    // -----------------------------------------------------------------------------------------------------------------
    explicit DataLakeFacade(std::filesystem::path root_directory,
                            std::shared_ptr<ParquetWriter>          parquet_writer,
                            std::shared_ptr<ParquetReader>          parquet_reader);

    ~DataLakeFacade() noexcept = default;
    DataLakeFacade(const DataLakeFacade&)            = delete;
    DataLakeFacade& operator=(const DataLakeFacade&) = delete;
    DataLakeFacade(DataLakeFacade&&)                 = delete;
    DataLakeFacade& operator=(DataLakeFacade&&)      = delete;

    // -----------------------------------------------------------------------------------------------------------------
    // Enumerations / structs
    // -----------------------------------------------------------------------------------------------------------------
    enum class ContentType
    {
        Raw,
        Curated,
        Metadata
    };

    struct Metrics
    {
        std::uint64_t bytes_written   = 0;
        std::uint64_t bytes_read      = 0;
        std::uint64_t parquet_rows    = 0;
        std::uint64_t parquet_files   = 0;
        std::uint64_t io_failures     = 0;
        std::chrono::steady_clock::time_point last_io = std::chrono::steady_clock::now();
    };

    // Observer callback: void(const Metrics& current)
    using MetricsObserver = std::function<void(const Metrics&)>;

    // -----------------------------------------------------------------------------------------------------------------
    // Public API
    // -----------------------------------------------------------------------------------------------------------------

    /**
     * Store an in-memory chunk of binary data inside the Raw or Curated zone of the lake.
     *
     * Strong exception safety: if an exception is thrown no partial file remains.
     *
     * @param tenant      – Logical tenant / hospital network
     * @param timestamp   – Acquisition timestamp
     * @param content     – Raw bytes
     * @param contentType – Raw / Curated
     * @return            – Full path written on success | std::nullopt on failure
     */
    [[nodiscard]]
    std::optional<std::filesystem::path>
    putBinary(const std::string&              tenant,
              std::chrono::system_clock::time_point timestamp,
              std::vector<std::uint8_t>       content,
              ContentType                     contentType = ContentType::Raw) noexcept;

    /**
     * Lightweight parquet writer helper.
     *
     * @param tenant        – Logical tenant
     * @param timestamp     – Acquisition timestamp
     * @param schema_json   – Spark/Arrow compatible schema as JSON string
     * @param column_data   – Column-major payload; ParquetWriter validates sizes
     * @return              – Path of the newly created parquet file
     */
    [[nodiscard]]
    std::optional<std::filesystem::path>
    putParquet(const std::string&                                tenant,
               std::chrono::system_clock::time_point             timestamp,
               std::string                                       schema_json,
               std::unordered_map<std::string, std::vector<int>> column_data) noexcept;

    /**
     * Retrieve a parquet file and hydrate the caller’s buffers.
     *
     * @return Tuple <schema_json, column_data>
     */
    [[nodiscard]]
    std::optional<std::pair<std::string,
                            std::unordered_map<std::string, std::vector<int>>>>
    getParquet(const std::filesystem::path& parquet_path) noexcept;

    /**
     * Returns the root directory the façade is bound to.
     */
    [[nodiscard]] const std::filesystem::path& root() const noexcept { return root_dir_; }

    /**
     * Observers will be called whenever Metrics are updated.
     * Thread-safe.
     */
    void addObserver(MetricsObserver cb);

    /**
     * Remove all observers – primarily for unit-testing teardown.
     */
    void clearObservers();

private:
    // -----------------------------------------------------------------------------------------------------------------
    // Helpers
    // -----------------------------------------------------------------------------------------------------------------
    [[nodiscard]]
    std::filesystem::path makePath(const std::string& tenant,
                                   std::chrono::system_clock::time_point tp,
                                   ContentType type,
                                   std::string_view extension) const;

    void notifyObservers();

    // -----------------------------------------------------------------------------------------------------------------
    // Members
    // -----------------------------------------------------------------------------------------------------------------
    const std::filesystem::path            root_dir_;
    std::shared_ptr<ParquetWriter>         parquet_writer_;
    std::shared_ptr<ParquetReader>         parquet_reader_;

    // Metrics & Observer infrastructure
    mutable std::shared_mutex              metrics_mtx_;
    Metrics                                metrics_;
    std::vector<MetricsObserver>           observers_;

    // File-system serialization mutex; ensures that directory creation is atomic-ish.
    std::mutex                             fs_mtx_;
};

// =====================================================================================================================
// Implementation  –  small inline helpers only; heavy lifting lives in data_lake_facade.cpp
// =====================================================================================================================

inline DataLakeFacade::DataLakeFacade(std::filesystem::path   root_directory,
                                      std::shared_ptr<ParquetWriter> writer,
                                      std::shared_ptr<ParquetReader> reader)
    : root_dir_(std::move(root_directory))
    , parquet_writer_(std::move(writer))
    , parquet_reader_(std::move(reader))
{
    if (!std::filesystem::exists(root_dir_))
    {
        std::error_code ec;
        std::filesystem::create_directories(root_dir_, ec);
        if (ec)
        {
            throw std::system_error(ec, "DataLakeFacade – unable to create root directory");
        }
    }
}

inline std::filesystem::path
DataLakeFacade::makePath(const std::string& tenant,
                         std::chrono::system_clock::time_point tp,
                         ContentType type,
                         std::string_view extension) const
{
    const std::time_t            tt = std::chrono::system_clock::to_time_t(tp);
    std::tm                      tm = *std::gmtime(&tt);
    char                         date_buf[11]{};
    std::strftime(date_buf, sizeof(date_buf), "%Y/%m/%d", &tm);

    const char* type_str = nullptr;
    switch (type)
    {
        case ContentType::Raw:      type_str = "raw";      break;
        case ContentType::Curated:  type_str = "curated";  break;
        case ContentType::Metadata: type_str = "meta";     break;
    }

    std::filesystem::path path = root_dir_ /
                                 tenant /
                                 date_buf /
                                 type_str;

    // Filename example: 20240515T120102Z.bin
    char ts_buf[17]{};
    std::strftime(ts_buf, sizeof(ts_buf), "%Y%m%dT%H%M%SZ", &tm);

    path /= std::string(ts_buf) + std::string(extension);

    return path;
}

inline void DataLakeFacade::addObserver(MetricsObserver cb)
{
    std::unique_lock lk(metrics_mtx_);
    observers_.emplace_back(std::move(cb));
}

inline void DataLakeFacade::clearObservers()
{
    std::unique_lock lk(metrics_mtx_);
    observers_.clear();
}

inline void DataLakeFacade::notifyObservers()
{
    std::shared_lock lk(metrics_mtx_);
    for (const auto& cb : observers_)
    {
        try { cb(metrics_); }
        catch (...) { /* Swallow – observers must not compromise main flow */ }
    }
}

} // namespace ci360::storage
```