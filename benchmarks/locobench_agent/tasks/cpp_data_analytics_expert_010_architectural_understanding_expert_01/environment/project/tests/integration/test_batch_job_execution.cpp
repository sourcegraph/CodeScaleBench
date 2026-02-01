```cpp
/**
 * CardioInsight360 – Unified Healthcare Analytics Engine
 * ------------------------------------------------------
 * Integration tests for the batch–processing execution path.
 *
 * This file exercises a realistic “happy-path” and a failure scenario for
 * the BatchJobExecutor component that orchestrates end-to-end ETL on large
 * collections of physiological data.  The *production* implementation is
 * considerably more sophisticated, but the scaffolding below captures its
 * observable behaviour so that the tests compile and run in isolation when
 * linked only against GoogleTest, Intel TBB and the standard library.
 *
 * NOTE:  Because this is an out-of-context integration test, a lightweight
 *        stub of the Data-Lake façade and the Executor is provided here—
 *        in a *real* repository these would be pulled in from the engine’s
 *        public headers and/or a dedicated test fixture library.
 */

#include <gtest/gtest.h>
#include <gmock/gmock.h>

#include <tbb/parallel_for.h>
#include <tbb/blocked_range.h>

#include <filesystem>
#include <fstream>
#include <iostream>
#include <random>
#include <sstream>
#include <stdexcept>
#include <string>
#include <thread>
#include <vector>

namespace fs = std::filesystem;

namespace {

/* ---------- Domain primitives ------------------------------------------------ */

enum class JobStatus
{
    Pending,
    Running,
    Completed,
    Failed
};

struct BatchJob
{
    std::string id;
    fs::path    sourceFile;
    fs::path    curatedRelPath;   // relative to data-lake root
    JobStatus   status           = JobStatus::Pending;
    std::string errorMessage;
};

/* ---------- Data-Lake façade -------------------------------------------------- */

class IDataLake
{
public:
    virtual ~IDataLake() = default;

    virtual fs::path root() const                                                    = 0;
    virtual bool     write(const fs::path& relative, std::string_view bytes)         = 0;
    virtual bool     exists(const fs::path& relative) const                          = 0;
    virtual std::string read(const fs::path& relative) const                         = 0;
};

/* Production façade is backed by (S3|Azure|POSIX) storage.  For tests we persist
 * to a temporary directory on the local file-system. */
class FileSystemDataLake final : public IDataLake
{
public:
    explicit FileSystemDataLake(fs::path rootDir)
        : rootDir_{ std::move(rootDir) }
    {
        if (!fs::exists(rootDir_))
        {
            fs::create_directories(rootDir_);
        }
    }

    fs::path root() const override { return rootDir_; }

    bool write(const fs::path& relative, std::string_view bytes) override
    {
        const fs::path fullPath = rootDir_ / relative;
        if (fullPath.native().find("..") != std::string::npos)
        {
            throw std::invalid_argument("path traversal detected");
        }

        fs::create_directories(fullPath.parent_path());
        std::ofstream out(fullPath, std::ios::binary);
        out.write(bytes.data(), static_cast<std::streamsize>(bytes.size()));
        return out.good();
    }

    bool exists(const fs::path& relative) const override
    {
        return fs::exists(rootDir_ / relative);
    }

    std::string read(const fs::path& relative) const override
    {
        std::ifstream in(rootDir_ / relative, std::ios::binary);
        std::ostringstream oss;
        oss << in.rdbuf();
        return oss.str();
    }

private:
    fs::path rootDir_;
};

/* ---------- Executor stub ----------------------------------------------------- */

class BatchJobExecutor
{
public:
    explicit BatchJobExecutor(std::shared_ptr<IDataLake> dataLake, std::size_t concurrency = std::thread::hardware_concurrency())
        : dataLake_{ std::move(dataLake) }, concurrency_{ concurrency }
    {
        if (!dataLake_)
        {
            throw std::invalid_argument("dataLake must not be null");
        }
    }

    /* Executes ETL pipeline.  Transformation is mocked as “uppercase conversion”
     * done in parallel using TBB.  Any line containing the token “FAIL” triggers
     * a pipeline failure. */
    void run(BatchJob& job) const
    {
        job.status = JobStatus::Running;

        try
        {
            // Read source
            const auto rawText = readFile(job.sourceFile);

            // Validate & transform
            const auto curated = transform(rawText);

            // Persist to data-lake
            if (!dataLake_->write(job.curatedRelPath, curated))
            {
                throw std::runtime_error("failed to persist curated artefact");
            }

            job.status = JobStatus::Completed;
        }
        catch (const std::exception& ex)
        {
            job.status       = JobStatus::Failed;
            job.errorMessage = ex.what();
        }
    }

private:
    std::shared_ptr<IDataLake> dataLake_;
    std::size_t               concurrency_;

    static std::string readFile(const fs::path& file)
    {
        std::ifstream in(file, std::ios::binary);
        if (!in)
        {
            throw std::runtime_error("cannot open source file: " + file.string());
        }
        std::ostringstream oss;
        oss << in.rdbuf();
        return oss.str();
    }

    std::string transform(const std::string& input) const
    {
        if (input.find("FAIL") != std::string::npos)
        {
            throw std::runtime_error("validation error: disallowed token detected");
        }

        // Upper-case conversion using TBB
        std::string output = input;  // copy
        tbb::parallel_for(
            tbb::blocked_range<std::size_t>(0, output.size()),
            [&](const tbb::blocked_range<std::size_t>& range)
            {
                for (size_t i = range.begin(); i != range.end(); ++i)
                {
                    output[i] = static_cast<char>(::toupper(static_cast<unsigned char>(output[i])));
                }
            });

        return output;
    }
};

/* ---------- Utilities --------------------------------------------------------- */

static std::string generateRandomId()
{
    std::array<char, 16> bytes{};
    std::random_device   rd;
    std::generate(bytes.begin(), bytes.end(), std::ref(rd));
    std::ostringstream oss;
    for (auto b : bytes)
    {
        oss << std::hex << std::setw(2) << std::setfill('0') << (static_cast<int>(b) & 0xff);
    }
    return oss.str();
}

/* Removes a directory tree on destruction.  Guarantees deterministic cleanup
 * even if an assertion inside TEST fails. */
class ScopedDir
{
public:
    explicit ScopedDir(fs::path p) : path_{ std::move(p) } {}
    ~ScopedDir() noexcept
    {
        std::error_code ec;
        fs::remove_all(path_, ec);
    }
    const fs::path& get() const { return path_; }

private:
    fs::path path_;
};

} // namespace

/* ============================================================================ */
/*                                Integration Tests                             */
/* ============================================================================ */

class BatchJobExecutionIntegrationTest : public ::testing::Test
{
protected:
    void SetUp() override
    {
        tmpDir_   = std::make_unique<ScopedDir>(fs::temp_directory_path() / ("ci360_itest_" + generateRandomId()));
        dataLake_ = std::make_shared<FileSystemDataLake>(tmpDir_->get() / "datalake");

        // Prepare source (raw HL7 message stub)
        rawDir_    = tmpDir_->get() / "incoming" / "2023-12-18";
        sampleFile_ = rawDir_ / "patient123.hl7";
        fs::create_directories(rawDir_);

        constexpr char samplePayload[] =
            "MSH|^~\\&|CI360|HOSPITAL|LAB|HOSPITAL|202312181200||ORU^R01|123|P|2.3\r"
            "PID|1||12345^^^HOSPITAL^MR||DOE^JOHN\r"
            "OBR|1||123|ECG^Electrocardiogram\r"
            "OBX|1|ST|HR^HeartRate||72|bpm|60-100|N|||F\r";

        std::ofstream out(sampleFile_);
        out << samplePayload;
    }

    void TearDown() override
    {
        // Unique-ptr ensures directory is purged even on exceptions.
        tmpDir_.reset();
    }

    std::unique_ptr<ScopedDir>      tmpDir_;
    std::shared_ptr<FileSystemDataLake> dataLake_;
    fs::path                        rawDir_;
    fs::path                        sampleFile_;
};

TEST_F(BatchJobExecutionIntegrationTest, HappyPath_CompletesSuccessfully)
{
    BatchJob job;
    job.id             = generateRandomId();
    job.sourceFile     = sampleFile_;
    job.curatedRelPath = fs::path{ "curated" } / "2023" / "12" / "18" / (job.id + ".parquet");

    BatchJobExecutor executor{ dataLake_ };
    executor.run(job);

    ASSERT_EQ(job.status, JobStatus::Completed) << job.errorMessage;
    EXPECT_TRUE(dataLake_->exists(job.curatedRelPath));

    // Verify transformation logic: output should be fully uppercase
    const auto curatedContent = dataLake_->read(job.curatedRelPath);
    EXPECT_THAT(curatedContent, ::testing::HasSubstr("ECG^ELECTROCARDIOGRAM"));
    EXPECT_THAT(curatedContent, ::testing::HasSubstr("72|BPM"));
}

TEST_F(BatchJobExecutionIntegrationTest, ValidationFailure_SetsJobStatusToFailed)
{
    // Corrupt the payload to trigger validation failure
    std::ofstream out(sampleFile_, std::ios::app);
    out << "\rNTE|1|FAIL THIS SHOULD BREAK\r";  // Token "FAIL" will be detected

    BatchJob job;
    job.id             = generateRandomId();
    job.sourceFile     = sampleFile_;
    job.curatedRelPath = fs::path{ "curated" } / job.id;

    BatchJobExecutor executor{ dataLake_ };
    executor.run(job);

    ASSERT_EQ(job.status, JobStatus::Failed);
    EXPECT_THAT(job.errorMessage, ::testing::HasSubstr("validation error"));

    // Nothing should have been materialised in the lake
    EXPECT_FALSE(dataLake_->exists(job.curatedRelPath));
}
```