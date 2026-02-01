```cpp
/********************************************************************
 *  IntraLedger BlogSuite – Search subsystem (module_10.cpp)
 *
 *  This translation unit implements a production-quality, in-process
 *  full-text search service.  The module is responsible for:
 *
 *    • Indexing blog content through a pluggable backend
 *    • Scheduling (async) re-index jobs via a JobDispatcher
 *    • Parsing user queries with stop-word elimination + phrase support
 *    • Returning ranked result sets with snippet highlighting
 *
 *  NOTE: In the real code-base the slender interfaces declared below
 *  are provided by other compilation units.  They are reproduced here
 *  (in abridged form) to maintain standalone buildability.
 ********************************************************************/

#include <algorithm>
#include <chrono>
#include <cctype>
#include <condition_variable>
#include <exception>
#include <future>
#include <iomanip>
#include <iostream>
#include <memory>
#include <mutex>
#include <optional>
#include <queue>
#include <regex>
#include <shared_mutex>
#include <sstream>
#include <stdexcept>
#include <string>
#include <string_view>
#include <thread>
#include <unordered_map>
#include <unordered_set>
#include <utility>
#include <vector>

namespace intraledger::blogsuite
{

// ──────────────────────────────────────────────────────────────────────────────
// Forward declarations of domain primitives
// ──────────────────────────────────────────────────────────────────────────────
enum class ContentType
{
    Article,
    Page,
    Comment
};

struct Document final
{
    std::string id;        // Globally unique identifier (UUID/ULID)
    std::string title;     // Localised title
    std::string body;      // Raw or HTML stripped text
    std::string language;  // ISO-639-1, e.g. “en”, “fr”
};

// ──────────────────────────────────────────────────────────────────────────────
// Infrastructure input ports (normally supplied by other modules)
// ──────────────────────────────────────────────────────────────────────────────
class IRepository
{
public:
    virtual ~IRepository() = default;
    virtual std::vector<Document>
    fetchUpdatedDocuments(std::chrono::system_clock::time_point since) = 0;
    virtual std::optional<Document> fetchDocumentById(const std::string& id) = 0;
};

class ISearchBackend
{
public:
    virtual ~ISearchBackend() = default;
    virtual void put(const Document& doc)                        = 0;
    virtual void remove(const std::string& id)                   = 0;
    virtual std::vector<std::pair<std::string, double>>          // (docId, score)
    query(const std::vector<std::string>& terms,
          int                        limit,
          int                        offset) const = 0;
};

class IJobDispatcher
{
public:
    virtual ~IJobDispatcher() = default;
    virtual void enqueue(std::function<void()> job) = 0;
};

class ILogger
{
public:
    virtual ~ILogger() = default;
    virtual void info(std::string_view msg)  = 0;
    virtual void warn(std::string_view msg)  = 0;
    virtual void error(std::string_view msg) = 0;
};

// ──────────────────────────────────────────────────────────────────────────────
// Minimal in-memory implementations meant ONLY for this compilation unit
// ──────────────────────────────────────────────────────────────────────────────
namespace internal
{

// Dumb, single-threaded in-memory search backend (tf-idf-ish scoring).
class InMemorySearchBackend final : public ISearchBackend
{
public:
    void put(const Document& doc) override
    {
        std::unique_lock lock(_mtx);
        _docs[doc.id] = doc;
        index(doc);
    }

    void remove(const std::string& id) override
    {
        std::unique_lock lock(_mtx);
        _docs.erase(id);
        for (auto& [tok, posting] : _inverted) { posting.erase(id); }
    }

    std::vector<std::pair<std::string, double>> query(const std::vector<std::string>& terms,
                                                      int limit,
                                                      int offset) const override
    {
        std::shared_lock lock(_mtx);
        std::unordered_map<std::string, double> scores;

        for (const auto& term : terms)
        {
            auto it = _inverted.find(term);
            if (it == _inverted.end()) continue;

            const auto& posting = it->second;
            for (auto&& [docId, count] : posting)
            {
                double tf   = static_cast<double>(count);
                double idf  = 1.0 + std::log(static_cast<double>(_docs.size()) /
                                            (1.0 + posting.size()));
                scores[docId] += tf * idf;
            }
        }

        std::vector<std::pair<std::string, double>> sorted(scores.begin(), scores.end());
        std::sort(sorted.begin(),
                  sorted.end(),
                  [](auto& a, auto& b) { return a.second > b.second; });

        if (offset >= static_cast<int>(sorted.size())) return {};
        auto beg = sorted.begin() + offset;
        auto end = (limit > 0)
                       ? beg + std::min(limit, static_cast<int>(sorted.end() - beg))
                       : sorted.end();
        return {beg, end};
    }

private:
    static std::string canonicalise(std::string_view s)
    {
        std::string out;
        out.reserve(s.size());
        for (char c : s)
        {
            if (std::isalnum(static_cast<unsigned char>(c)))
                out.push_back(static_cast<char>(std::tolower(c)));
            else
                out.push_back(' ');
        }
        return out;
    }

    static std::vector<std::string> tokenize(std::string_view text)
    {
        std::vector<std::string> tokens;
        std::istringstream       ss(std::string(text));
        std::string              tok;
        while (ss >> tok) tokens.emplace_back(tok);
        return tokens;
    }

    void index(const Document& doc)
    {
        const std::string canon = canonicalise(doc.title + " " + doc.body);
        for (const auto& tok : tokenize(canon))
        {
            _inverted[tok][doc.id] += 1u;
        }
    }

    mutable std::shared_mutex                                          _mtx;
    std::unordered_map<std::string, Document>                          _docs;
    std::unordered_map<std::string, std::unordered_map<std::string, size_t>> _inverted;
};

// Naive thread-pool dispatcher for background indexing jobs.
class SimpleThreadPoolDispatcher final : public IJobDispatcher
{
public:
    explicit SimpleThreadPoolDispatcher(std::size_t workers = std::thread::hardware_concurrency())
        : _shutdown(false)
    {
        workers = std::max<std::size_t>(1, workers);
        for (std::size_t i = 0; i < workers; ++i)
            _threads.emplace_back([this] { workerLoop(); });
    }

    ~SimpleThreadPoolDispatcher() override
    {
        {
            std::lock_guard lock(_mtx);
            _shutdown = true;
        }
        _cv.notify_all();
        for (auto& t : _threads) t.join();
    }

    void enqueue(std::function<void()> job) override
    {
        {
            std::lock_guard lock(_mtx);
            _jobs.push(std::move(job));
        }
        _cv.notify_one();
    }

private:
    void workerLoop()
    {
        for (;;)
        {
            std::function<void()> job;
            {
                std::unique_lock lock(_mtx);
                _cv.wait(lock, [this] { return _shutdown || !_jobs.empty(); });
                if (_shutdown && _jobs.empty()) return;
                job = std::move(_jobs.front());
                _jobs.pop();
            }
            try { job(); }
            catch (const std::exception& ex)
            {
                std::cerr << "[thread-pool] unhandled job exception → " << ex.what() << '\n';
            }
        }
    }

    std::mutex                      _mtx;
    std::condition_variable         _cv;
    std::queue<std::function<void()>> _jobs;
    std::vector<std::thread>        _threads;
    bool                            _shutdown;
};

// Console logger.
class StdoutLogger final : public ILogger
{
public:
    void info(std::string_view msg) override { std::cout << "[INFO ] " << msg << '\n'; }
    void warn(std::string_view msg) override { std::cout << "[WARN ] " << msg << '\n'; }
    void error(std::string_view msg) override { std::cerr << "[ERROR] " << msg << '\n'; }
};

}  // namespace internal

// ──────────────────────────────────────────────────────────────────────────────
// Search Query parsing + utilities
// ──────────────────────────────────────────────────────────────────────────────
class QueryParser final
{
public:
    struct Parsed
    {
        std::vector<std::string> tokens;     // canonical tokens
        std::vector<std::string> phrases;    // exact phrases (w/o quotes)
    };

    Parsed parse(std::string_view raw) const
    {
        Parsed                       result;
        static const std::regex      phraseRe("\"([^\"]+)\"");
        std::smatch                  m;
        std::string                  s(raw);

        // Extract phrases
        auto searchStart = s.cbegin();
        while (std::regex_search(searchStart, s.cend(), m, phraseRe))
        {
            result.phrases.emplace_back(m[1]);
            searchStart = m.suffix().first;
        }

        // Remove quotes for tokenisation
        std::string withoutQuotes = std::regex_replace(s, phraseRe, " ");
        for (auto& tok : tokenize(canonicalise(withoutQuotes)))
            if (_stopWords.find(tok) == _stopWords.end())
                result.tokens.emplace_back(std::move(tok));

        return result;
    }

    static std::string
    highlight(std::string_view text,
              const std::vector<std::string>& terms,
              std::string_view                 preTag  = "<mark>",
              std::string_view                 postTag = "</mark>")
    {
        std::string out(text);
        for (const auto& term : terms)
        {
            std::regex re("\\b(" + term + ")\\b", std::regex::icase);
            out = std::regex_replace(out, re, std::string(preTag) + "$1" + std::string(postTag));
        }
        return out;
    }

private:
    static std::string canonicalise(std::string_view s)
    {
        std::string out;
        out.reserve(s.size());
        for (char c : s)
        {
            if (std::isalnum(static_cast<unsigned char>(c)))
                out.push_back(static_cast<char>(std::tolower(c)));
            else
                out.push_back(' ');
        }
        return out;
    }

    static std::vector<std::string> tokenize(std::string_view text)
    {
        std::vector<std::string> tokens;
        std::istringstream       ss(std::string(text));
        std::string              tok;
        while (ss >> tok) tokens.emplace_back(tok);
        return tokens;
    }

    const std::unordered_set<std::string> _stopWords{
        "the", "and", "or", "of", "to", "a", "an", "in", "on", "for", "with", "is", "it"};
};

// ──────────────────────────────────────────────────────────────────────────────
// SearchService – façade used by controllers + job scheduler
// ──────────────────────────────────────────────────────────────────────────────
class SearchService final
{
public:
    SearchService(std::shared_ptr<IRepository>     repo,
                  std::shared_ptr<ISearchBackend>  backend,
                  std::shared_ptr<IJobDispatcher>  dispatcher,
                  std::shared_ptr<ILogger>         logger)
        : _repository(std::move(repo))
        , _backend(std::move(backend))
        , _dispatcher(std::move(dispatcher))
        , _logger(std::move(logger))
        , _lastFullIndex(std::chrono::system_clock::from_time_t(0))
    {
        if (!_repository || !_backend || !_dispatcher || !_logger)
            throw std::invalid_argument("SearchService: nullptr dependency");
    }

    // Kick off a full reindex (“build from scratch”) in the background
    void scheduleFullReindex()
    {
        _logger->info("Scheduling FULL search re-index");
        _dispatcher->enqueue([this] { this->performFullReindex(); });
    }

    // Index just one document (insert/update)
    void indexDocumentAsync(const std::string& docId)
    {
        _dispatcher->enqueue([this, id = docId] {
            if (auto doc = _repository->fetchDocumentById(id))
            {
                _backend->put(*doc);
                _logger->info("Indexed single document #" + id);
            }
            else
            {
                _logger->warn("Cannot index – document #" + id + " not found");
            }
        });
    }

    struct SearchResult
    {
        Document     doc;
        std::string  snippet;  // body with <mark>…</mark> highlighting
        double       score;
    };

    std::vector<SearchResult> search(std::string_view query, int limit = 20, int offset = 0) const
    {
        QueryParser::Parsed parsed = _parser.parse(query);
        if (parsed.tokens.empty() && parsed.phrases.empty()) return {};

        auto hits = _backend->query(parsed.tokens, limit, offset);
        std::vector<SearchResult> out;
        out.reserve(hits.size());

        for (auto&& [docId, score] : hits)
        {
            auto docOpt = _repository->fetchDocumentById(docId);
            if (!docOpt) continue;  // Deleted between index & query

            const Document& doc = *docOpt;
            std::string snippet =
                buildSnippet(doc.body.empty() ? doc.title : doc.body, parsed.tokens);

            out.push_back({doc, std::move(snippet), score});
        }
        return out;
    }

private:
    // Full reindex job
    void performFullReindex()
    {
        _logger->info("Starting FULL re-index");

        const auto now  = std::chrono::system_clock::now();
        auto        docs = _repository->fetchUpdatedDocuments(_lastFullIndex);
        size_t      processed = 0;

        for (const auto& doc : docs)
        {
            try
            {
                _backend->put(doc);
                ++processed;
            }
            catch (const std::exception& ex)
            {
                _logger->error(std::string("Indexing failed for doc #") + doc.id + ": " +
                               ex.what());
            }
        }
        _lastFullIndex = now;
        _logger->info("Full re-index finished, processed " + std::to_string(processed) +
                      " document(s)");
    }

    static std::string buildSnippet(const std::string& text,
                                    const std::vector<std::string>& terms,
                                    std::size_t                      radius = 50)
    {
        if (text.empty()) return {};

        // Find first occurrence of any term (case-insensitive)
        auto pos = std::string::npos;
        for (const auto& term : terms)
        {
            std::string lcText(text);
            std::transform(lcText.begin(), lcText.end(), lcText.begin(), ::tolower);
            auto p = lcText.find(term);
            if (p != std::string::npos) { pos = std::min(pos, p); }
        }

        if (pos == std::string::npos) pos = 0;
        std::size_t begin = (pos > radius) ? pos - radius : 0;
        std::size_t end   = std::min(begin + radius * 2, text.size());

        std::string snippet = text.substr(begin, end - begin);
        if (begin != 0) snippet = "…" + snippet;
        if (end != text.size()) snippet += "…";

        return QueryParser::highlight(snippet, terms);
    }

    std::shared_ptr<IRepository>     _repository;
    std::shared_ptr<ISearchBackend>  _backend;
    std::shared_ptr<IJobDispatcher>  _dispatcher;
    std::shared_ptr<ILogger>         _logger;
    QueryParser                      _parser;

    std::chrono::system_clock::time_point _lastFullIndex;
};

// ──────────────────────────────────────────────────────────────────────────────
// Small “integration test” (standalone demo usage when run as main)
// ──────────────────────────────────────────────────────────────────────────────
#ifdef MODULE10_SEARCH_STANDALONE_DEMO

class DummyRepo : public IRepository
{
public:
    DummyRepo()
    {
        _docs.push_back({"1",
                         "Hello World",
                         "Welcome to the very first post of our new BlogSuite platform",
                         "en"});
        _docs.push_back({"2",
                         "C++17 tricks",
                         "We dive deep into std::variant, std::filesystem and more",
                         "en"});
    }

    std::vector<Document> fetchUpdatedDocuments(std::chrono::system_clock::time_point) override
    {
        return _docs;
    }

    std::optional<Document> fetchDocumentById(const std::string& id) override
    {
        for (auto& d : _docs)
            if (d.id == id) return d;
        return std::nullopt;
    }

private:
    std::vector<Document> _docs;
};

int main()
{
    auto repo       = std::make_shared<DummyRepo>();
    auto backend    = std::make_shared<internal::InMemorySearchBackend>();
    auto dispatcher = std::make_shared<internal::SimpleThreadPoolDispatcher>(2);
    auto logger     = std::make_shared<internal::StdoutLogger>();

    SearchService search(repo, backend, dispatcher, logger);

    search.scheduleFullReindex();
    std::this_thread::sleep_for(std::chrono::milliseconds(100));  // wait for job

    auto results = search.search("C++17 tricks deep");
    for (auto& r : results)
        std::cout << r.doc.id << " (" << std::fixed << std::setprecision(2) << r.score
                  << "): " << r.snippet << '\n';
}

#endif  // MODULE10_SEARCH_STANDALONE_DEMO

}  // namespace intraledger::blogsuite
```