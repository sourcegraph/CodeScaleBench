```cpp
#ifndef CARDIOINSIGHT360_STORAGE_PARQUET_HANDLER_H
#define CARDIOINSIGHT360_STORAGE_PARQUET_HANDLER_H

/**
 *  CardioInsight360 – Unified Healthcare Analytics Engine
 *  ------------------------------------------------------
 *  File        : parquet_handler.h
 *  Description : Thin façade around Apache Arrow / Parquet that provides
 *                thread–safe, application–level semantics for storing and
 *                retrieving physiological datasets in columnar Parquet
 *                files.  The class is intentionally stateless with respect
 *                to individual datasets so that it can be used safely by
 *                multiple concurrent ETL pipelines as well as by the
 *                interactive analytics/visualisation layer.
 *
 *  Copyright   : (c) CardioInsight360
 *  License     : Proprietary – Not for external distribution
 *
 *  NOTE: Implementation is header–only because Arrow/Parquet methods are
 *        heavily templated and inlining reduces symbol-resolution issues
 *        when the entire analytics engine builds as a single binary.
 */

#include <arrow/api.h>
#include <arrow/io/api.h>
#include <parquet/arrow/writer.h>
#include <parquet/arrow/reader.h>
#include <parquet/encryption/encryption.h>

#include <filesystem>
#include <mutex>
#include <optional>
#include <shared_mutex>
#include <string>
#include <unordered_map>
#include <utility>
#include <vector>

namespace cardio::storage
{

enum class Compression
{
    UNCOMPRESSED,
    SNAPPY,
    GZIP,
    ZSTD
};

/**
 * Interface for publishing I/O metrics.  In production we use this to
 * feed the built-in monitoring subsystem through the Observer Pattern,
 * but the interface is light-weight so that unit-test builds can link
 * with a no-op implementation.
 */
class IMetricsPublisher
{
public:
    virtual ~IMetricsPublisher() = default;

    virtual void IncrementCounter(const std::string& name,
                                  std::uint64_t value = 1) noexcept = 0;

    virtual void RecordLatencyMs(const std::string& name,
                                 std::uint64_t elapsedMs) noexcept = 0;
};

/**
 * ParquetHandler
 * --------------
 * Provides synchronous CRUD operations on Parquet datasets residing
 * beneath a single root directory.  Thread safety is guaranteed per
 * dataset using a striped lock approach to maximise concurrency while
 * still protecting against race conditions between readers and writers.
 */
class ParquetHandler final
{
public:
    struct Options
    {
        Compression                  compression        = Compression::SNAPPY;
        std::size_t                  rowGroupSize       = 32 * 1024;   // 32k rows per RG
        bool                         overwriteIfExists  = true;
        std::shared_ptr<arrow::MemoryPool> memoryPool   = arrow::default_memory_pool();
        std::shared_ptr<IMetricsPublisher> metrics      = nullptr;
        // Transparent at-rest encryption using Parquet Crypto
        // (when compiled with parquet_encryption):
        std::shared_ptr<parquet::FileEncryptionProperties> encryption = nullptr;
    };

public:
    explicit ParquetHandler(std::filesystem::path rootDir,
                            Options              opts = Options{});

    ParquetHandler(const ParquetHandler&)            = delete;
    ParquetHandler& operator=(const ParquetHandler&) = delete;
    ParquetHandler(ParquetHandler&&)                 = delete;
    ParquetHandler& operator=(ParquetHandler&&)      = delete;

    ~ParquetHandler() = default;

    //------------------------------------------------------------------
    // Dataset-level operations
    //------------------------------------------------------------------

    /**
     * Write a table into <root>/<datasetName>.parquet.
     *
     * If overwriteIfExists == false and the dataset already exists,
     * arrow::Status::KeyError is returned.
     */
    arrow::Status WriteDataset(const std::string&           datasetName,
                               const std::shared_ptr<arrow::Table>& table,
                               std::optional<Options>       writeOpts = std::nullopt);

    /**
     * Append rows to an existing dataset, or create a new one if the file
     * does not yet exist.  Schema validation is performed and will fail if
     * the incoming table is not *exactly* the same as the on-disk schema.
     */
    arrow::Status AppendDataset(const std::string&                 datasetName,
                                const std::shared_ptr<arrow::Table>&   table,
                                std::optional<Options>             writeOpts = std::nullopt);

    /**
     * Read a dataset into memory.  The caller may optionally specify a list
     * of columns to project and/or a row limit.  When both are set, the
     * projection happens *before* the limit for maximum efficiency.
     */
    arrow::Result<std::shared_ptr<arrow::Table>>
    ReadDataset(const std::string& datasetName,
                const std::vector<std::string>& projection = {},
                std::optional<int64_t>          rowLimit   = std::nullopt) const;

    /**
     * Retrieve the schema of an on-disk dataset without loading the entire
     * file into memory.
     */
    arrow::Result<std::shared_ptr<arrow::Schema>>
    GetSchema(const std::string& datasetName) const;

    /**
     * Delete a dataset from permanent storage.  Returns Status::OK if the
     * file never existed.
     */
    arrow::Status RemoveDataset(const std::string& datasetName);

    /**
     * Return true iff the dataset exists on disk.
     */
    bool DatasetExists(const std::string& datasetName) const;

private:
    //------------------------------------------------------------------
    // Helpers
    //------------------------------------------------------------------
    parquet::WriterProperties::Builder
    BuildWriterPropertiesBuilder(const Options& effOpts) const;

    parquet::ArrowReaderProperties
    BuildReaderProperties() const;

    std::filesystem::path ResolvePath(const std::string& datasetName) const;

    void PublishMetric(const std::string& name, std::uint64_t value) const;

private:
    //------------------------------------------------------------------
    // Implementation state
    //------------------------------------------------------------------
    std::filesystem::path _rootDir;
    Options               _opts;

    // We use a striped lock array to minimise contention when multiple
    // datasets are accessed concurrently.
    static constexpr std::size_t kLockStripes = 64U;
    mutable std::shared_mutex _stripeLocks[kLockStripes];

    std::shared_mutex& StripeLock(const std::string& datasetName) const noexcept
    {
        std::size_t hash = std::hash<std::string>{}(datasetName);
        return _stripeLocks[hash % kLockStripes];
    }
};


//======================================================================
//                         IMPLEMENTATION
//======================================================================

inline ParquetHandler::ParquetHandler(std::filesystem::path rootDir,
                                      Options              opts)
    : _rootDir{std::move(rootDir)}
    , _opts {std::move(opts)}
{
    if (!_rootDir.empty())
    {
        std::error_code ec;
        std::filesystem::create_directories(_rootDir, ec);
        if (ec)
        {
            throw std::runtime_error(
                "ParquetHandler: Failed to create root directory '" +
                _rootDir.string() + "': " + ec.message());
        }
    }
    else
    {
        throw std::invalid_argument("ParquetHandler: rootDir may not be empty");
    }
}

inline parquet::WriterProperties::Builder
ParquetHandler::BuildWriterPropertiesBuilder(const Options& effOpts) const
{
    parquet::WriterProperties::Builder builder;

    switch (effOpts.compression)
    {
        case Compression::UNCOMPRESSED: builder.compression(parquet::Compression::UNCOMPRESSED); break;
        case Compression::SNAPPY:       builder.compression(parquet::Compression::SNAPPY);       break;
        case Compression::GZIP:         builder.compression(parquet::Compression::GZIP);         break;
        case Compression::ZSTD:         builder.compression(parquet::Compression::ZSTD);         break;
    }

    builder.max_row_group_length(static_cast<int64_t>(effOpts.rowGroupSize));

    if (effOpts.encryption)
    {
#ifdef PARQUET_ENCRYPTION
        builder.encryption(effOpts.encryption);
#else
        throw std::runtime_error("Parquet built without encryption support");
#endif
    }

    return builder;
}

inline parquet::ArrowReaderProperties
ParquetHandler::BuildReaderProperties() const
{
    parquet::ArrowReaderProperties props;
    props.set_use_threads(true);
    return props;
}

inline std::filesystem::path
ParquetHandler::ResolvePath(const std::string& datasetName) const
{
    return _rootDir / (datasetName + ".parquet");
}

inline void
ParquetHandler::PublishMetric(const std::string& name,
                              std::uint64_t      value) const
{
    if (_opts.metrics)
    {
        _opts.metrics->IncrementCounter(name, value);
    }
}

//------------------------------------------------------------------
// DatasetExists
//------------------------------------------------------------------
inline bool
ParquetHandler::DatasetExists(const std::string& datasetName) const
{
    const auto path = ResolvePath(datasetName);
    std::error_code ec;
    const bool exists = std::filesystem::exists(path, ec);
    // Failure to fetch status implies path does not exist
    return exists && !ec;
}


//------------------------------------------------------------------
// WriteDataset
//------------------------------------------------------------------
inline arrow::Status
ParquetHandler::WriteDataset(const std::string&           datasetName,
                             const std::shared_ptr<arrow::Table>& table,
                             std::optional<Options>       writeOpts)
{
    const Options effOpts = writeOpts.value_or(_opts);
    const auto path       = ResolvePath(datasetName);

    std::unique_lock lock{StripeLock(datasetName)};

    if (std::filesystem::exists(path) && !effOpts.overwriteIfExists)
    {
        return arrow::Status::KeyError("Dataset '", datasetName,
                                       "' already exists and overwrite disabled");
    }

    auto outputResult = arrow::io::FileOutputStream::Open(path.string(),
                                                          /* append = */false);
    if (!outputResult.ok())
    {
        return outputResult.status();
    }
    auto outStream = *outputResult;

    auto writerPropsBuilder = BuildWriterPropertiesBuilder(effOpts);
    auto writerProps        = writerPropsBuilder.build();

    PARQUET_ASSIGN_OR_RETURN(
        auto writer,
        parquet::arrow::FileWriter::Open(*table->schema(),
                                         arrow::default_memory_pool(),
                                         outStream,
                                         writerProps,
                                         /* arrow writer properties */ nullptr));

    arrow::Status st = writer->WriteTable(*table, effOpts.rowGroupSize);
    if (!st.ok())
    {
        return st;
    }

    st = writer->Close();
    PublishMetric("parquet.write.ops", 1);
    return st;
}


//------------------------------------------------------------------
// AppendDataset
//------------------------------------------------------------------
inline arrow::Status
ParquetHandler::AppendDataset(const std::string&             datasetName,
                              const std::shared_ptr<arrow::Table>& table,
                              std::optional<Options>         writeOpts)
{
    const Options effOpts = writeOpts.value_or(_opts);
    const auto path       = ResolvePath(datasetName);

    std::unique_lock lock{StripeLock(datasetName)};

    if (!std::filesystem::exists(path))
    {
        // Fast path: dataset does not exist – just write
        return WriteDataset(datasetName, table, effOpts);
    }

    // Open existing dataset for schema validation
    ARROW_ASSIGN_OR_RAISE(auto input,
        arrow::io::ReadableFile::Open(path.string(),
                                      /* memory mapped */ true));

    std::unique_ptr<parquet::arrow::FileReader> fileReader;
    auto st = parquet::arrow::OpenFile(input,
                                       arrow::default_memory_pool(),
                                       &fileReader);
    if (!st.ok()) return st;

    std::shared_ptr<arrow::Schema> diskSchema;
    st = fileReader->GetSchema(&diskSchema);
    if (!st.ok()) return st;

    if (!diskSchema->Equals(*table->schema(), /* check_metadata = */true))
    {
        return arrow::Status::Invalid("Schema mismatch while appending to dataset '",
                                      datasetName, "'.");
    }

    // Arrow/Parquet API does not support append-in-place; we must
    // perform a copy-on-write.  This is acceptable because datasets
    // are chunked by time interval (ETL stage), keeping files small.
    ARROW_ASSIGN_OR_RAISE(auto existingTable,
        fileReader->ReadTable());

    ARROW_ASSIGN_OR_RAISE(auto concatenated,
        existingTable->CombineChunks());

    ARROW_ASSIGN_OR_RAISE(auto newTable,
        concatenated->CombineChunks());

    // Concatenate
    std::vector<std::shared_ptr<arrow::Table>> tables = { newTable, table };
    ARROW_ASSIGN_OR_RAISE(auto fullTable,
        arrow::ConcatenateTables(tables));

    return WriteDataset(datasetName, fullTable, effOpts);
}


//------------------------------------------------------------------
// ReadDataset
//------------------------------------------------------------------
inline arrow::Result<std::shared_ptr<arrow::Table>>
ParquetHandler::ReadDataset(const std::string&         datasetName,
                            const std::vector<std::string>& projection,
                            std::optional<int64_t>     rowLimit) const
{
    const auto path = ResolvePath(datasetName);

    std::shared_lock lock{StripeLock(datasetName)};

    if (!std::filesystem::exists(path))
    {
        return arrow::Status::KeyError("Dataset '", datasetName, "' does not exist");
    }

    ARROW_ASSIGN_OR_RAISE(auto input,
        arrow::io::ReadableFile::Open(path.string(),
                                      /* memory mapped */ true));

    std::unique_ptr<parquet::arrow::FileReader> fileReader;
    auto st = parquet::arrow::OpenFile(input,
                                       arrow::default_memory_pool(),
                                       &fileReader);
    if (!st.ok()) return st;

    fileReader->set_use_threads(true);
    if (!projection.empty())
    {
        std::vector<int> columnIndices;
        const auto& schema = fileReader->parquet_reader()->metadata()->schema();
        for (const auto& col : projection)
        {
            int idx = schema->ColumnIndex(col);
            if (idx < 0)
            {
                return arrow::Status::KeyError("Column '", col,
                                               "' not found in dataset '",
                                               datasetName, "'");
            }
            columnIndices.push_back(idx);
        }
        fileReader->set_columns(columnIndices);
    }

    std::shared_ptr<arrow::Table> table;
    st = rowLimit
             ? fileReader->ReadTable(*rowLimit, &table)
             : fileReader->ReadTable(&table);
    if (!st.ok()) return st;

    PublishMetric("parquet.read.ops", 1);
    return table;
}


//------------------------------------------------------------------
// GetSchema
//------------------------------------------------------------------
inline arrow::Result<std::shared_ptr<arrow::Schema>>
ParquetHandler::GetSchema(const std::string& datasetName) const
{
    const auto path = ResolvePath(datasetName);

    std::shared_lock lock{StripeLock(datasetName)};

    if (!std::filesystem::exists(path))
    {
        return arrow::Status::KeyError("Dataset '", datasetName, "' does not exist");
    }

    ARROW_ASSIGN_OR_RAISE(auto input,
        arrow::io::ReadableFile::Open(path.string(),
                                      /* memory mapped */ true));

    std::unique_ptr<parquet::arrow::FileReader> fileReader;
    auto st = parquet::arrow::OpenFile(input,
                                       arrow::default_memory_pool(),
                                       &fileReader);
    if (!st.ok()) return st;

    std::shared_ptr<arrow::Schema> schema;
    st = fileReader->GetSchema(&schema);
    if (!st.ok()) return st;

    return schema;
}

//------------------------------------------------------------------
// RemoveDataset
//------------------------------------------------------------------
inline arrow::Status
ParquetHandler::RemoveDataset(const std::string& datasetName)
{
    const auto path = ResolvePath(datasetName);
    std::unique_lock lock{StripeLock(datasetName)};

    std::error_code ec;
    std::filesystem::remove(path, ec);
    if (ec)
    {
        return arrow::Status::IOError("Failed to delete dataset '", datasetName,
                                      "': ", ec.message());
    }
    PublishMetric("parquet.delete.ops", 1);
    return arrow::Status::OK();
}

} // namespace cardio::storage

#endif // CARDIOINSIGHT360_STORAGE_PARQUET_HANDLER_H
```