```cpp
/**
 *  CardioInsight360 – Unified Healthcare Analytics Engine
 *  ------------------------------------------------------
 *  File        : storage/data_lake_facade.cpp
 *  Created     : 2024-05-26
 *  Author      : CardioInsight360 Core Team
 *
 *  Description :
 *      A façade for interacting with CardioInsight360’s hierarchical
 *      data-lake.  The implementation hides all low-level concerns such as
 *      directory layout, Parquet/Arrow serialisation, at-rest encryption,
 *      retention management, and coarse-grained parallelisation while
 *      exposing a concise, domain-specific C++17 API to the rest of the
 *      analytics engine.
 *
 *      Raw signals are persisted under:
 *              <root>/raw/<signal_type>/<patient_id>/YYYY/MM/DD/HHMMSS/part_*.parquet
 *
 *      Curated (post-ETL) datasets are persisted under:
 *              <root>/curated/<dataset_name>/YYYYMMDDThhmmssZ.parquet
 *
 *      The component is thread-safe and leverages Intel TBB for IO-bound
 *      fan-out whenever data can be sharded into multiple row-groups.
 *
 *      NOTE: This file intentionally contains implementation-only code.
 *            Public interface is declared in “storage/data_lake_facade.h”.
 */

#include "storage/data_lake_facade.h"

#include <arrow/api.h>
#include <arrow/io/api.h>
#include <arrow/result.h>
#include <arrow/table.h>
#include <parquet/arrow/reader.h>
#include <parquet/arrow/writer.h>

#include <tbb/parallel_for.h>
#include <tbb/task_arena.h>

#include <openssl/evp.h>
#include <openssl/rand.h>

#include <chrono>
#include <filesystem>
#include <fstream>
#include <iomanip>
#include <mutex>
#include <regex>
#include <sstream>
#include <stdexcept>
#include <string>
#include <system_error>
#include <vector>

namespace fs = std::filesystem;

namespace cardioinsight::storage
{

/* -------------------------------------------------------------------------- */
/*                         ———  Internal helpers   ———                        */
/* -------------------------------------------------------------------------- */

namespace
{

constexpr std::size_t kDefaultChunkRows = 65'536; // Row-group size ≈ 64 k rows.
constexpr int         kAesKeyBits       = 256;
constexpr int         kAesTagBytes      = 16;
constexpr int         kAesIvBytes       = 12;

/**
 * A very small RAII wrapper around OpenSSL’s EVP_CIPHER_CTX.
 */
class EvpCipherCtx final
{
public:
    EvpCipherCtx()
        : ctx_{ EVP_CIPHER_CTX_new() }
    {
        if (!ctx_) { throw std::runtime_error("EVP_CIPHER_CTX_new failed"); }
    }
    ~EvpCipherCtx() { EVP_CIPHER_CTX_free(ctx_); }
    EVP_CIPHER_CTX* get() noexcept { return ctx_; }

    EvpCipherCtx(const EvpCipherCtx&)            = delete;
    EvpCipherCtx& operator=(const EvpCipherCtx&) = delete;

private:
    EVP_CIPHER_CTX* ctx_;
};

/**
 * Encrypts `src` into `dst` using AES-256-GCM.
 * Layout of dst = [ IV | TAG | CIPHERTEXT ].
 */
void aes256_gcm_encrypt(const std::vector<std::uint8_t>& src,
                        const std::array<std::uint8_t, 32>& key,
                        std::vector<std::uint8_t>&        dst)
{
    std::array<std::uint8_t, kAesIvBytes> iv{};
    if (RAND_bytes(iv.data(), iv.size()) != 1) { throw std::runtime_error("RAND_bytes failed"); }

    const EVP_CIPHER* alg = EVP_aes_256_gcm();

    EvpCipherCtx ctx;
    if (EVP_EncryptInit_ex(ctx.get(), alg, nullptr, nullptr, nullptr) != 1)
        throw std::runtime_error("EVP_EncryptInit_ex failed (alg)");

    if (EVP_CIPHER_CTX_ctrl(ctx.get(), EVP_CTRL_GCM_SET_IVLEN, iv.size(), nullptr) != 1)
        throw std::runtime_error("EVP_CIPHER_CTX_ctrl failed (iv len)");

    if (EVP_EncryptInit_ex(ctx.get(), nullptr, nullptr, key.data(), iv.data()) != 1)
        throw std::runtime_error("EVP_EncryptInit_ex failed (key/iv)");

    std::vector<std::uint8_t> cipher(src.size() + EVP_CIPHER_block_size(alg));
    int                      out_len = 0;

    if (EVP_EncryptUpdate(ctx.get(), cipher.data(), &out_len, src.data(),
                          static_cast<int>(src.size())) != 1)
        throw std::runtime_error("EVP_EncryptUpdate failed");

    int tmp_len = 0;
    if (EVP_EncryptFinal_ex(ctx.get(), cipher.data() + out_len, &tmp_len) != 1)
        throw std::runtime_error("EVP_EncryptFinal_ex failed");

    out_len += tmp_len;
    cipher.resize(out_len);

    std::array<std::uint8_t, kAesTagBytes> tag{};
    if (EVP_CIPHER_CTX_ctrl(ctx.get(), EVP_CTRL_GCM_GET_TAG, tag.size(), tag.data()) != 1)
        throw std::runtime_error("EVP_CIPHER_CTX_ctrl failed (get tag)");

    // IV + TAG + CIPHER
    dst.resize(iv.size() + tag.size() + cipher.size());
    std::uint8_t* p = dst.data();
    std::memcpy(p, iv.data(), iv.size());
    p += iv.size();
    std::memcpy(p, tag.data(), tag.size());
    p += tag.size();
    std::memcpy(p, cipher.data(), cipher.size());
}

/**
 * Decrypts buffer produced by `aes256_gcm_encrypt`.
 */
void aes256_gcm_decrypt(const std::vector<std::uint8_t>& src,
                        const std::array<std::uint8_t, 32>& key,
                        std::vector<std::uint8_t>&        dst)
{
    if (src.size() < kAesIvBytes + kAesTagBytes)
        throw std::runtime_error("ciphertext too small");

    const std::uint8_t* iv    = src.data();
    const std::uint8_t* tag   = src.data() + kAesIvBytes;
    const std::uint8_t* ctext = src.data() + kAesIvBytes + kAesTagBytes;
    const auto          c_len = static_cast<int>(src.size() - kAesIvBytes - kAesTagBytes);

    const EVP_CIPHER* alg = EVP_aes_256_gcm();
    EvpCipherCtx      ctx;
    if (EVP_DecryptInit_ex(ctx.get(), alg, nullptr, nullptr, nullptr) != 1)
        throw std::runtime_error("EVP_DecryptInit_ex failed");

    if (EVP_CIPHER_CTX_ctrl(ctx.get(), EVP_CTRL_GCM_SET_IVLEN, kAesIvBytes, nullptr) != 1)
        throw std::runtime_error("EVP_CIPHER_CTX_ctrl failed (set iv len)");

    if (EVP_DecryptInit_ex(ctx.get(), nullptr, nullptr, key.data(), iv) != 1)
        throw std::runtime_error("EVP_DecryptInit_ex failed (key/iv)");

    dst.resize(c_len + EVP_CIPHER_block_size(alg)); // alloc
    int out_len = 0;
    if (EVP_DecryptUpdate(ctx.get(), dst.data(), &out_len, ctext, c_len) != 1)
        throw std::runtime_error("EVP_DecryptUpdate failed");

    if (EVP_CIPHER_CTX_ctrl(ctx.get(), EVP_CTRL_GCM_SET_TAG, kAesTagBytes,
                            const_cast<std::uint8_t*>(tag)) != 1)
        throw std::runtime_error("EVP_Decrypt ctrl (set tag) failed");

    int tmp_len = 0;
    if (EVP_DecryptFinal_ex(ctx.get(), dst.data() + out_len, &tmp_len) != 1)
        throw std::runtime_error("EVP_DecryptFinal_ex authentication failed");

    out_len += tmp_len;
    dst.resize(out_len);
}

/**
 * Formats a std::chrono::system_clock::time_point into YYYY/MM/DD/HHMMSS.
 */
inline std::string to_iso_path(const std::chrono::system_clock::time_point& tp)
{
    std::time_t          tt = std::chrono::system_clock::to_time_t(tp);
    std::tm              tm{};
#if defined(_WIN32)
    gmtime_s(&tm, &tt);
#else
    gmtime_r(&tt, &tm);
#endif
    std::ostringstream oss;
    oss << std::put_time(&tm, "%Y/%m/%d/%H%M%S");
    return oss.str();
}

/**
 * Formats a time_point to ISO-8601 basic: YYYYMMDDThhmmssZ
 */
inline std::string to_iso_basic(const std::chrono::system_clock::time_point& tp)
{
    std::time_t          tt = std::chrono::system_clock::to_time_t(tp);
    std::tm              tm{};
#if defined(_WIN32)
    gmtime_s(&tm, &tt);
#else
    gmtime_r(&tt, &tm);
#endif
    std::ostringstream oss;
    oss << std::put_time(&tm, "%Y%m%dT%H%M%SZ");
    return oss.str();
}

} // namespace

/* -------------------------------------------------------------------------- */
/*                     ———  DataLakeFacade implementation   ———               */
/* -------------------------------------------------------------------------- */

DataLakeFacade::DataLakeFacade(DataLakeOptions opts)
    : opts_{ std::move(opts) }
    , arena_{ static_cast<int>(opts_.concurrency) } // limit concurrency
{
    if (!fs::exists(opts_.root_directory))
    {
        fs::create_directories(opts_.root_directory);
    }

    if (opts_.encryption_enabled)
    {
        if (opts_.encryption_key.size() != 32)
            throw std::invalid_argument("encryption_key must be exactly 32 bytes (AES-256)");

        std::copy(opts_.encryption_key.begin(), opts_.encryption_key.end(),
                  encryption_key_.begin());
    }
}

/* ----  High-level façade API  -------------------------------------------- */

void DataLakeFacade::write_raw(const std::shared_ptr<arrow::Table>&            table,
                               std::string_view                                signal_type,
                               std::string_view                                patient_id,
                               const std::chrono::system_clock::time_point&    capture_time) const
{
    if (!table) throw std::invalid_argument("table is null");

    const fs::path base =
        opts_.root_directory / "raw" / signal_type / patient_id / to_iso_path(capture_time);

    fs::create_directories(base);

    // Split table into chunks so we can write multiple parquet files in parallel.
    const std::size_t total_rows = table->num_rows();
    const std::size_t rows_per_chunk =
        std::max<std::size_t>(kDefaultChunkRows, total_rows / arena_.max_concurrency());

    std::size_t chunks = (total_rows + rows_per_chunk - 1) / rows_per_chunk;

    arena_.execute([&] {
        tbb::parallel_for(std::size_t{ 0 }, chunks, [&](std::size_t chunk_idx) {
            const std::size_t offset = chunk_idx * rows_per_chunk;
            const std::size_t length =
                std::min<std::size_t>(rows_per_chunk, total_rows - offset);

            auto slice = table->Slice(offset, length);

            std::ostringstream fname;
            fname << "part_" << std::setfill('0') << std::setw(4) << chunk_idx << ".parquet";

            const fs::path file_path = base / fname.str();
            write_table_to_file(slice, file_path);
        });
    });
}

void DataLakeFacade::write_curated(const std::shared_ptr<arrow::Table>&        table,
                                   std::string_view                            dataset_name) const
{
    if (!table) throw std::invalid_argument("table is null");

    const fs::path dir = opts_.root_directory / "curated" / dataset_name;
    fs::create_directories(dir);

    const fs::path file = dir / (to_iso_basic(std::chrono::system_clock::now()) + ".parquet");
    write_table_to_file(table, file);
}

std::vector<fs::path> DataLakeFacade::list_datasets(const fs::path& subdir) const
{
    const fs::path dir = opts_.root_directory / subdir;
    if (!fs::exists(dir)) return {};

    std::vector<fs::path> result;
    for (auto& p : fs::recursive_directory_iterator(dir))
    {
        if (p.is_regular_file() && p.path().extension() == ".parquet")
        {
            result.emplace_back(p.path());
        }
    }
    return result;
}

arrow::Result<std::shared_ptr<arrow::Table>>
DataLakeFacade::read_dataset(const fs::path& file_path) const
{
    ARROW_ASSIGN_OR_RAISE(auto input_file, arrow::io::ReadableFile::Open(file_path.string()));

    if (opts_.encryption_enabled)
    {
        // Whole-file encryption – read into memory, decrypt, then open from buffer.
        ARROW_ASSIGN_OR_RAISE(auto buf, input_file->Read());
        std::vector<std::uint8_t> cipher(buf->size());
        std::memcpy(cipher.data(), buf->data(), buf->size());

        std::vector<std::uint8_t> plain;
        aes256_gcm_decrypt(cipher, encryption_key_, plain);

        auto plain_buf = std::make_shared<arrow::Buffer>(plain.data(), plain.size());
        auto stream    = std::make_shared<arrow::io::BufferReader>(plain_buf);
        return parquet::arrow::ReadTable(stream);
    }
    else
    {
        std::unique_ptr<parquet::arrow::FileReader> reader;
        PARQUET_THROW_NOT_OK(
            parquet::arrow::OpenFile(input_file, arrow::default_memory_pool(), &reader));

        std::shared_ptr<arrow::Table> table;
        PARQUET_THROW_NOT_OK(reader->ReadTable(&table));
        return table;
    }
}

void DataLakeFacade::enforce_retention(std::chrono::hours max_age) const
{
    const auto now = std::chrono::system_clock::now();

    std::regex ts_regex(R"((\d{8}T\d{6}Z))");

    for (auto& p : fs::recursive_directory_iterator(opts_.root_directory))
    {
        if (!p.is_regular_file()) continue;

        const auto& path = p.path();
        if (path.extension() != ".parquet") continue;

        std::smatch m;
        if (std::regex_search(path.string(), m, ts_regex))
        {
            std::tm tm{};
            std::istringstream ss(m.str());
            ss >> std::get_time(&tm, "%Y%m%dT%H%M%SZ");
            if (ss.fail()) continue;

            const auto ts = std::chrono::system_clock::from_time_t(timegm(&tm));
            if (now - ts > max_age)
            {
                std::error_code ec;
                fs::remove(path, ec);
                if (ec)
                {
                    // Logging is implemented elsewhere in the application.
                }
            }
        }
    }
}

/* ----  Private helpers  --------------------------------------------------- */

void DataLakeFacade::write_table_to_file(const std::shared_ptr<arrow::Table>& table,
                                         const fs::path&                     file_path) const
{
    if (opts_.encryption_enabled)
    {
        // First write into a buffer, encrypt, then flush to disk
        std::shared_ptr<arrow::io::BufferOutputStream> buffer =
            arrow::io::BufferOutputStream::Create().ValueOrDie();

        PARQUET_THROW_NOT_OK(
            parquet::arrow::WriteTable(*table, arrow::default_memory_pool(), buffer, 128 * 1024));

        ARROW_ASSIGN_OR_RAISE(auto buf, buffer->Finish());

        std::vector<std::uint8_t> plain(buf->size());
        std::memcpy(plain.data(), buf->data(), buf->size());

        std::vector<std::uint8_t> cipher;
        aes256_gcm_encrypt(plain, encryption_key_, cipher);

        std::ofstream ofs(file_path, std::ios::binary | std::ios::trunc);
        ofs.write(reinterpret_cast<const char*>(cipher.data()),
                  static_cast<std::streamsize>(cipher.size()));
        ofs.close();
    }
    else
    {
        ARROW_ASSIGN_OR_RAISE(auto out_file,
                              arrow::io::FileOutputStream::Open(file_path.string(), /*truncate*/true));
        PARQUET_THROW_NOT_OK(
            parquet::arrow::WriteTable(*table, arrow::default_memory_pool(), out_file, 128 * 1024));
        PARQUET_THROW_NOT_OK(out_file->Close());
    }
}

} // namespace cardioinsight::storage
```
