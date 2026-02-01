/*
 * SPDX-License-Identifier: MIT
 *
 *   IntraLedger BlogSuite – Search Index Updater
 *
 *   Copyright (c) 2023-2024 IntraLedger
 *
 *   This file is part of the IntraLedger BlogSuite codebase and is released
 *   under the MIT license.  See LICENSE.txt at the project root for details.
 */

#include <algorithm>
#include <chrono>
#include <cctype>
#include <exception>
#include <iterator>
#include <memory>
#include <regex>
#include <set>
#include <stdexcept>
#include <string>
#include <string_view>
#include <unordered_set>
#include <utility>
#include <vector>

#include "config/configuration.hpp"
#include "core/logger.hpp"
#include "jobs/job_context.hpp"
#include "repository/article_repository.hpp"
#include "repository/search_index_repository.hpp"
#include "util/clock.hpp"
#include "util/stopwatch.hpp"

namespace intra::blog::search {

/*─────────────────────────────────────────────────────────────────────────────+
 |  Utility helpers                                                           |
 +─────────────────────────────────────────────────────────────────────────────*/

/**
 * Convert ASCII characters to lower case.
 *
 * We avoid locale-aware tolower for predictable behaviour across
 * deployment environments. Non-ASCII characters are returned intact.
 */
static inline char ascii_tolower(char c) noexcept
{
    return static_cast<char>((c >= 'A' && c <= 'Z') ? c + 32 : c);
}

/**
 * Remove any leading/trailing non-alphanumeric punctuation.
 *
 * This is a fast pre-processing step to avoid feeding punctuation-heavy
 * tokens (e.g. “foo,” “bar.” “(baz)”) into the stemmer.
 */
static std::string_view trim_punctuation(std::string_view sv) noexcept
{
    const auto is_punct = [](char ch) noexcept {
        return !std::isalnum(static_cast<unsigned char>(ch));
    };

    std::size_t begin = 0;
    std::size_t end   = sv.size();

    while (begin < end && is_punct(sv[begin])) ++begin;
    while (end > begin && is_punct(sv[end - 1])) --end;

    return sv.substr(begin, end - begin);
}

/**
 * Very light Porter-Stemmer wrapper.
 *
 * In production we build with the `snowball` library; in test builds we fall
 * back to the identity implementation to keep the tool-chain minimal.
 */
static std::string stem_word(std::string_view word)
{
#ifdef INTRA_BLOG_USE_SNOWBALL
    return SnowballStemmer::Stem(word);
#else
    // Identity fallback. Good enough for CI but NOT for production search.
    return {word.begin(), word.end()};
#endif
}

/*─────────────────────────────────────────────────────────────────────────────+
 |  Tokenizer                                                                 |
 +─────────────────────────────────────────────────────────────────────────────*/

class Tokenizer final
{
public:
    explicit Tokenizer(std::size_t min_len = 2)
        : _minLen(min_len)
    {
    }

    /**
     * Tokenise input UTF-8 text into a deduplicated, stemmed set of tokens.
     *
     * The algorithm is simple but fast:
     *   1. Split on whitespace
     *   2. Trim leading/trailing punctuation
     *   3. Lower-case ASCII letters
     *   4. Stem
     * Tokens shorter than `_minLen` are discarded.
     */
    std::vector<std::string> run(std::string_view text) const
    {
        std::unordered_set<std::string> unique;
        unique.reserve(128);

        std::string current;
        current.reserve(32);

        auto flush_current = [&]() {
            if (current.size() >= _minLen) {
                unique.insert(stem_word(current));
            }
            current.clear();
        };

        for (char ch : text) {
            if (std::isspace(static_cast<unsigned char>(ch))) {
                flush_current();
            } else {
                current.push_back(ascii_tolower(ch));
            }
        }
        flush_current();

        std::vector<std::string> out;
        out.reserve(unique.size());
        std::move(unique.begin(), unique.end(), std::back_inserter(out));
        std::sort(out.begin(), out.end());
        return out;
    }

private:
    std::size_t _minLen;
};

/*─────────────────────────────────────────────────────────────────────────────+
 |  SearchIndexUpdater                                                        |
 +─────────────────────────────────────────────────────────────────────────────*/

/**
 * Background task responsible for synchronising the Full-Text Search index
 * with the latest article content.  Runs periodically via the internal
 * job-processor thread-pool.
 *
 * The linker will pull this translation unit into the final executable when
 * referenced from the job registry.
 */
class SearchIndexUpdater final : public jobs::Job
{
public:
    SearchIndexUpdater(std::shared_ptr<repository::ArticleRepository> articleRepo,
                       std::shared_ptr<repository::SearchIndexRepository> searchRepo,
                       std::shared_ptr<core::Logger>                     logger,
                       const config::Configuration&                      cfg)
        : _articleRepo(std::move(articleRepo))
        , _searchRepo(std::move(searchRepo))
        , _logger(std::move(logger))
        , _cfg(cfg)
        , _tokenizer(cfg.search().minTokenLen)
    {
        if (!_articleRepo || !_searchRepo || !_logger) {
            throw std::invalid_argument("SearchIndexUpdater – null dependency");
        }
    }

    std::string_view name() const noexcept override { return "SearchIndexUpdater"; }

    /**
     * Called by the job-processor.
     */
    void run(jobs::JobContext& ctx) override
    {
        util::Stopwatch sw;
        sw.start();

        try {
            ctx.setStatus("Scanning for modified articles…");
            const auto modifiedSince = _searchRepo->lastIndexedAt();
            const auto batchSize     = _cfg.search().batchSize;

            _logger->debug("SearchIndexUpdater: last indexed at {}", modifiedSince);

            std::size_t updatedArticles = 0;
            std::vector<domain::Article> articles;

            for (;;) {
                if (ctx.isCancellationRequested()) {
                    _logger->warn("SearchIndexUpdater: cancelled after {}ms",
                                  sw.elapsedMs());
                    ctx.setCancelled();
                    return;
                }

                articles = _articleRepo->fetchModifiedSince(
                    modifiedSince, batchSize);

                if (articles.empty()) break;

                processBatch(articles, ctx);
                updatedArticles += articles.size();
                ctx.setProgress(static_cast<float>(updatedArticles),
                                std::numeric_limits<float>::quiet_NaN());
            }

            ctx.setStatus("Committing index changes…");
            _searchRepo->commit();
            _searchRepo->setLastIndexedAt(util::Clock::utcNow());

            _logger->info(
                "SearchIndexUpdater: completed – {} articles indexed in {}ms "
                "(peak mem: {} KiB)",
                updatedArticles,
                sw.elapsedMs(),
                util::Stopwatch::currentProcessMemoryKiB());

            ctx.setCompleted();
        } catch (const std::exception& ex) {
            _logger->error("SearchIndexUpdater: {}", ex.what());
            ctx.setFailed(ex.what());
            throw;  // allow job-processor to handle retry/backoff policy
        }
    }

private:
    void processBatch(const std::vector<domain::Article>& articles,
                      jobs::JobContext&                   ctx)
    {
        for (const auto& article : articles) {
            if (ctx.isCancellationRequested()) return;

            const std::string aggregated =
                article.title + ' ' + article.summary + ' ' + article.body;

            const auto tokens = _tokenizer.run(aggregated);

            _searchRepo->updateIndex(article.id, tokens);
        }
    }

    std::shared_ptr<repository::ArticleRepository>     _articleRepo;
    std::shared_ptr<repository::SearchIndexRepository> _searchRepo;
    std::shared_ptr<core::Logger>                      _logger;
    const config::Configuration&                       _cfg;
    Tokenizer                                          _tokenizer;
};

/*─────────────────────────────────────────────────────────────────────────────+
 |  Job Registration                                                          |
 +─────────────────────────────────────────────────────────────────────────────*/

static bool registerJob()
{
    jobs::JobRegistry::instance().addFactory(
        "index:update",
        [](jobs::JobArguments&& args) -> std::unique_ptr<jobs::Job> {
            return std::make_unique<SearchIndexUpdater>(
                args.serviceLocator.get<repository::ArticleRepository>(),
                args.serviceLocator.get<repository::SearchIndexRepository>(),
                args.serviceLocator.get<core::Logger>(),
                args.serviceLocator.get<config::Configuration>());
        });
    return true;
}

// Ensures the factory registration runs before main()
static const bool kRegistered = registerJob();

}  // namespace intra::blog::search