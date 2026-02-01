#include <arrow/api.h>
#include <arrow/io/api.h>
#include <arrow/result.h>
#include <arrow/status.h>

#include <parquet/arrow/reader.h>
#include <parquet/arrow/writer.h>
#include <parquet/properties.h>

#include <spdlog/spdlog.h>

#include <filesystem>
#include <mutex>
#include <shared_mutex>
#include <string>
#include <string_view>
#include <system_error>
#include <utility>
#include <vector>

namespace cardio::storage {

// -----------------------------------------------------------------------------
// Utility / Helper Declarations
// -----------------------------------------------------------------------------

// Naïve XOR encryption helper – placeholder ONLY.
// In production an AES-GCM or XChaCha20-Poly1305 implementation would be used
// via a vetted crypto library (e.g. libsodium or OpenSSL).
static void XOREncryptDecrypt(uint8_t* data, int64_t len, std::string_view key) {
    const auto key_len = static_cast<int64_t>(key.size());
    if (key_len == 0) { return; }

    for (int64_t i = 0; i < len; ++i) {
        data[i] ^= key[i % key_len];
    }
}

class ParquetIOException final : public std::runtime_error {
  public:
    explicit ParquetIOException(const std::string& msg)
        : std::runtime_error(msg) {}
};

// Convenience macro for Arrow status checks that throws engine-specific error.
#define CARDIO_RETURN_NOT_OK(_s)                                                      \
    do {                                                                              \
        ::arrow::Status _status = (_s);                                               \
        if (!_status.ok()) {                                                          \
            throw ::cardio::storage::ParquetIOException(_status.ToString());          \
        }                                                                             \
    } while (false)

// -----------------------------------------------------------------------------
// ParquetHandler
// -----------------------------------------------------------------------------
class ParquetHandler {
  public:
    struct WriteOptions {
        parquet::Compression::type compression = parquet::Compression::SNAPPY;
        bool overwrite                        = false;
        bool enable_encryption                = false;
        std::string encryption_key{};  // Ignored if enable_encryption == false
        int64_t target_file_size              = 512 * 1024 * 1024;  // 512 MiB
        int64_t row_group_size                = 64 * 1024;          // 64k rows
    };

    explicit ParquetHandler(std::filesystem::path root_dir = ".data-lake")
        : root_dir_(std::move(root_dir)) {
        try {
            std::filesystem::create_directories(root_dir_);
        } catch (const std::exception& ex) {
            throw ParquetIOException(
                fmt::format("Unable to create data-lake root '{}': {}",
                            root_dir_.string(), ex.what()));
        }
        spdlog::info("ParquetHandler initialised. Root path = '{}'",
                     root_dir_.string());
    }

    // Reads a Parquet file into an Arrow Table. If `encrypted == true`, `key`
    // must be provided. Throws ParquetIOException on error.
    std::shared_ptr<arrow::Table> Read(const std::filesystem::path& rel_uri,
                                       bool encrypted = false,
                                       std::string_view key = "") {
        const auto abs_uri = make_absolute(rel_uri);
        std::shared_lock guard(fs_mutex_);

        if (!std::filesystem::exists(abs_uri)) {
            throw ParquetIOException(
                fmt::format("File '{}' does not exist.", abs_uri.string()));
        }

        // If encryption is enabled, first mmap the file into memory,
        // decrypt in-place, then feed decrypted buffer to Arrow.
        if (encrypted) {
            return read_encrypted(abs_uri, key);
        }

        std::shared_ptr<arrow::io::ReadableFile> infile;
        CARDIO_RETURN_NOT_OK(
            arrow::io::ReadableFile::Open(abs_uri.string(),
                                          arrow::default_memory_pool())
                .Value(&infile));

        std::unique_ptr<parquet::arrow::FileReader> reader;
        CARDIO_RETURN_NOT_OK(parquet::arrow::OpenFile(
            infile, arrow::default_memory_pool(), &reader));
        std::shared_ptr<arrow::Table> table;
        CARDIO_RETURN_NOT_OK(reader->ReadTable(&table));
        return table;
    }

    // Writes `table` into `rel_uri`. Will create parent directories as needed.
    // Throws ParquetIOException on failure.
    void Write(const std::filesystem::path& rel_uri,
               const std::shared_ptr<arrow::Table>& table,
               const WriteOptions& opts = {}) {
        const auto abs_uri = make_absolute(rel_uri);

        {
            std::unique_lock guard(fs_mutex_);
            if (std::filesystem::exists(abs_uri) && !opts.overwrite) {
                throw ParquetIOException(fmt::format(
                    "File '{}' already exists and overwrite is disabled.",
                    abs_uri.string()));
            }
            std::filesystem::create_directories(abs_uri.parent_path());
        }

        // Write into in-memory buffer first if encryption is requested,
        // otherwise straight to disk.
        if (opts.enable_encryption) {
            write_encrypted(abs_uri, table, opts);
        } else {
            write_plain(abs_uri, table, opts);
        }

        spdlog::debug("Wrote Parquet file {}", abs_uri.string());
    }

    bool Exists(const std::filesystem::path& rel_uri) const {
        std::shared_lock guard(fs_mutex_);
        return std::filesystem::exists(make_absolute(rel_uri));
    }

  private:
    // -------------------------------------------------------------------------
    // Private helpers
    // -------------------------------------------------------------------------
    std::filesystem::path make_absolute(const std::filesystem::path& rel) const {
        if (rel.is_absolute()) { return rel; }
        return root_dir_ / rel;
    }

    std::shared_ptr<arrow::Table> read_encrypted(const std::filesystem::path& abs,
                                                 std::string_view key) {
        // Memory-map the whole file
        std::shared_ptr<arrow::io::MemoryMappedFile> mmap_file;
        CARDIO_RETURN_NOT_OK(
            arrow::io::MemoryMappedFile::Open(abs.string(), arrow::io::FileMode::READ,
                                              &mmap_file));

        auto size = mmap_file->size();
        std::shared_ptr<arrow::Buffer> encrypted_buf;
        CARDIO_RETURN_NOT_OK(mmap_file->ReadAt(0, size, &encrypted_buf));

        // Make a mutable copy for decryption
        std::shared_ptr<arrow::Buffer> decrypted_buf;
        CARDIO_RETURN_NOT_OK(arrow::AllocateBuffer(
            size, arrow::default_memory_pool(), &decrypted_buf));
        std::memcpy(decrypted_buf->mutable_data(), encrypted_buf->data(), size);
        XOREncryptDecrypt(decrypted_buf->mutable_data(), size, key);

        auto input =
            std::make_shared<arrow::io::BufferReader>(decrypted_buf);

        std::unique_ptr<parquet::arrow::FileReader> reader;
        CARDIO_RETURN_NOT_OK(parquet::arrow::OpenFile(
            input, arrow::default_memory_pool(), &reader));
        std::shared_ptr<arrow::Table> table;
        CARDIO_RETURN_NOT_OK(reader->ReadTable(&table));
        return table;
    }

    void write_plain(const std::filesystem::path& abs,
                     const std::shared_ptr<arrow::Table>& table,
                     const WriteOptions& opts) {
        std::shared_ptr<arrow::io::FileOutputStream> outfile;
        CARDIO_RETURN_NOT_OK(
            arrow::io::FileOutputStream::Open(abs.string(), &outfile));

        parquet::WriterProperties::Builder builder;
        builder.compression(opts.compression)
            ->max_row_group_length(opts.row_group_size)
            ->target_file_size(opts.target_file_size);
        auto props = builder.build();

        CARDIO_RETURN_NOT_OK(parquet::arrow::WriteTable(
            *table, arrow::default_memory_pool(), outfile,
            table->num_rows(), props));
        CARDIO_RETURN_NOT_OK(outfile->Close());
    }

    void write_encrypted(const std::filesystem::path& abs,
                         const std::shared_ptr<arrow::Table>& table,
                         const WriteOptions& opts) {
        // 1. Write Parquet to in-memory buffer
        std::shared_ptr<arrow::io::BufferOutputStream> buf_out;
        CARDIO_RETURN_NOT_OK(
            arrow::io::BufferOutputStream::Create(
                /*initial_capacity*/ 1024 * 1024, arrow::default_memory_pool(),
                &buf_out));

        parquet::WriterProperties::Builder builder;
        builder.compression(opts.compression)
            ->max_row_group_length(opts.row_group_size)
            ->target_file_size(opts.target_file_size);
        auto props = builder.build();

        CARDIO_RETURN_NOT_OK(parquet::arrow::WriteTable(
            *table, arrow::default_memory_pool(), buf_out,
            table->num_rows(), props));

        std::shared_ptr<arrow::Buffer> parquet_buf;
        CARDIO_RETURN_NOT_OK(buf_out->Finish(&parquet_buf));

        // 2. Mutate copy with XOR encryption
        std::shared_ptr<arrow::Buffer> encrypted_buf;
        CARDIO_RETURN_NOT_OK(arrow::AllocateBuffer(
            parquet_buf->size(), arrow::default_memory_pool(), &encrypted_buf));
        std::memcpy(encrypted_buf->mutable_data(), parquet_buf->data(),
                    parquet_buf->size());
        XOREncryptDecrypt(encrypted_buf->mutable_data(), encrypted_buf->size(),
                          opts.encryption_key);

        // 3. Flush to disk
        std::shared_ptr<arrow::io::FileOutputStream> outfile;
        CARDIO_RETURN_NOT_OK(
            arrow::io::FileOutputStream::Open(abs.string(), &outfile));
        CARDIO_RETURN_NOT_OK(
            outfile->Write(encrypted_buf->data(), encrypted_buf->size()));
        CARDIO_RETURN_NOT_OK(outfile->Close());
    }

    // -------------------------------------------------------------------------
    // Members
    // -------------------------------------------------------------------------
    std::filesystem::path root_dir_;
    mutable std::shared_mutex fs_mutex_;
};  // class ParquetHandler

}  // namespace cardio::storage

#undef CARDIO_RETURN_NOT_OK