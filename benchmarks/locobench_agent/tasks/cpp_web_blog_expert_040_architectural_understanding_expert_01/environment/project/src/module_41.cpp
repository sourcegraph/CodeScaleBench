```cpp
/**
 *  IntraLedger BlogSuite
 *  ---------------------
 *  File:        src/module_41.cpp
 *  Author:      IntraLedger Engineering
 *
 *  Description:
 *      Core search subsystem responsible for parsing free-form user queries,
 *      translating them into safe SQL fragments understood by the ORM, executing
 *      the query, and finally scoring & highlighting the resulting documents.
 *
 *      The goal of this module is to keep search-related logic well‐encapsulated
 *      and agnostic to the underlying persistence implementation (MariaDB /
 *      PostgreSQL).  All DB interaction is performed through the generic
 *      `IArticleRepository` interface defined in the Repository layer.
 *
 *      Dependencies:
 *          – C++20 STL
 *          – fmt            (header-only; used for safe SQL construction)
 *          – utf8proc       (optional; compile-time flag SEARCH_UTF8_NORMALIZE)
 *          – spdlog         (header-only; logging)
 *
 *      Thread-safety:
 *          All public functions are thread-safe and may be accessed from the
 *          async job processor or regular request threads concurrently.  The
 *          service makes no global mutations and relies on immutable data
 *          structures as much as possible.
 *
 *      Build:
 *          # CMake
 *          target_link_libraries(web_blog
 *              PRIVATE fmt::fmt spdlog::spdlog)
 *
 *  License: MIT
 ********************************************************************/

#include <algorithm>
#include <cctype>
#include <charconv>
#include <chrono>
#include <memory>
#include <optional>
#include <ranges>
#include <regex>
#include <sstream>
#include <stdexcept>
#include <string>
#include <string_view>
#include <unordered_map>
#include <variant>
#include <vector>

#include <fmt/core.h>
#include <fmt/ranges.h>
#include <spdlog/spdlog.h>

#ifdef SEARCH_UTF8_NORMALIZE
    #include <utf8proc.h>
#endif

//------------------------------------------------------------------------------

namespace intraledger::blogsuite::search {

//------------------------------------------------------------------------------
// Helper utilities
//------------------------------------------------------------------------------

namespace util {

/**
 *  Convert string to lower-case in place (ASCII only).
 */
inline void ascii_to_lower(std::string& s)
{
    std::transform(s.begin(), s.end(), s.begin(),
                   [](unsigned char c) { return static_cast<char>(std::tolower(c)); });
}

/**
 *  Perform lightweight quoting to protect against SQL injection
 *  when constructing raw SQL fragments.  The ORM still binds the
 *  parameters using prepared statements, but defensive programming
 *  never hurts.
 *
 *  @note This is NOT a full SQL sanitizer.  For production code,
 *        always use parameter binding offered by the underlying
 *        database driver.
 */
inline std::string sql_escape(std::string_view raw)
{
    std::string out;
    out.reserve(raw.size() + 2); // cheap guess
    for (char ch : raw)
    {
        if (ch == '\'' || ch == '\"' || ch == '\\')
            out.push_back('\\');
        out.push_back(ch);
    }
    return out;
}

#ifdef SEARCH_UTF8_NORMALIZE
/**
 *  Normalize UTF-8 string into NFC.
 */
inline std::string normalize_utf8(std::string_view src)
{
    utf8proc_uint8_t const* data =
        reinterpret_cast<const utf8proc_uint8_t*>(src.data());
    utf8proc_uint8_t* result = nullptr;

    auto len = utf8proc_decompose(data, src.size(), &result,
                                  UTF8PROC_NULLTERM | UTF8PROC_COMPOSE);

    if (len < 0)
        throw std::runtime_error("utf8proc_decompose() failed");

    std::string normalized(reinterpret_cast<char*>(result), len);
    free(result);
    return normalized;
}
#endif

} // namespace util

//------------------------------------------------------------------------------
// Search query AST
//------------------------------------------------------------------------------

enum class BoolOperator
{
    And,
    Or
};

// Forward declaration
struct Node;

using NodePtr = std::shared_ptr<Node>;

/**
 *  Base search AST node
 */
struct Node
{
    virtual ~Node() = default;
    virtual std::string to_sql(std::vector<std::string>& out_params) const = 0;
};

/**
 *  Represents a single token (word, phrase) possibly preceded by NOT.
 */
struct TermNode final : public Node
{
    std::string  token;
    bool         negated { false };

    explicit TermNode(std::string token_, bool neg = false)
        : token(std::move(token_)), negated(neg) {}

    std::string to_sql(std::vector<std::string>& out_params) const override
    {
        std::string like_pattern = fmt::format("%{}%", util::sql_escape(token));
        out_params.push_back(like_pattern);

        if (negated)
            return "content NOT ILIKE ?";
        else
            return "content ILIKE ?";
    }
};

/**
 *  Logical grouping node (AND / OR)
 */
struct BoolNode final : public Node
{
    BoolOperator                op;
    std::vector<std::shared_ptr<Node>> children;

    BoolNode(BoolOperator op_, std::vector<NodePtr> ch)
        : op(op_), children(std::move(ch)) {}

    std::string to_sql(std::vector<std::string>& out_params) const override
    {
        if (children.empty())
            return "TRUE";

        std::string_view op_str = (op == BoolOperator::And) ? "AND" : "OR";

        std::vector<std::string> child_sql;
        child_sql.reserve(children.size());
        for (auto const& c : children)
            child_sql.push_back(c->to_sql(out_params));

        return fmt::format("({})",
                           fmt::join(child_sql, fmt::format(" {} ", op_str)));
    }
};

//------------------------------------------------------------------------------
// Recursive-descent parser for simple boolean query grammar
// Supports:
//      term           -> WORD | "PHRASE"
//      factor         -> [NOT] term
//      expr_and       -> factor { AND factor }
//      expr_or        -> expr_and { OR expr_and }
//      query          -> expr_or
//--------------------------------------------------------------------------

class QueryParser
{
public:
    explicit QueryParser(std::string_view q)
        : m_query(q)
    {
        util::ascii_to_lower(m_query); // case-folding
    }

    NodePtr parse()
    {
        m_pos = 0;
        NodePtr root = parse_or();
        consume_whitespace();
        if (m_pos != m_query.size())
            throw std::runtime_error("Unexpected trailing characters");
        return root;
    }

private:
    std::string m_query;
    std::size_t m_pos { 0 };

    [[nodiscard]] bool eof() const noexcept { return m_pos >= m_query.size(); }

    void consume_whitespace()
    {
        while (!eof() && std::isspace(static_cast<unsigned char>(m_query[m_pos])))
            ++m_pos;
    }

    bool match_keyword(std::string_view kw)
    {
        consume_whitespace();
        if (m_query.compare(m_pos, kw.size(), kw) == 0)
        {
            const auto next = m_pos + kw.size();
            if (next == m_query.size() || std::isspace(static_cast<unsigned char>(m_query[next])))
            {
                m_pos = next;
                return true;
            }
        }
        return false;
    }

    NodePtr parse_or()
    {
        std::vector<NodePtr> nodes;
        nodes.push_back(parse_and());
        while (match_keyword("or"))
            nodes.push_back(parse_and());

        if (nodes.size() == 1)
            return nodes.front();
        return std::make_shared<BoolNode>(BoolOperator::Or, std::move(nodes));
    }

    NodePtr parse_and()
    {
        std::vector<NodePtr> nodes;
        nodes.push_back(parse_factor());
        while (match_keyword("and"))
            nodes.push_back(parse_factor());

        if (nodes.size() == 1)
            return nodes.front();
        return std::make_shared<BoolNode>(BoolOperator::And, std::move(nodes));
    }

    NodePtr parse_factor()
    {
        consume_whitespace();
        bool neg = false;
        if (match_keyword("not"))
            neg = true;

        return parse_term(neg);
    }

    NodePtr parse_term(bool negated)
    {
        consume_whitespace();
        if (eof())
            throw std::runtime_error("Unexpected end of query");

        char ch = m_query[m_pos];
        if (ch == '"')
        {
            ++m_pos;
            std::size_t end = m_query.find('"', m_pos);
            if (end == std::string::npos)
                throw std::runtime_error("Unterminated quote");

            std::string phrase = m_query.substr(m_pos, end - m_pos);
            m_pos = end + 1;
            return std::make_shared<TermNode>(std::move(phrase), negated);
        }

        // Word
        std::size_t start = m_pos;
        while (!eof() && !std::isspace(static_cast<unsigned char>(m_query[m_pos])))
            ++m_pos;

        std::string word = m_query.substr(start, m_pos - start);
        return std::make_shared<TermNode>(std::move(word), negated);
    }
};

//------------------------------------------------------------------------------
// Result DTO & Repository interface  (part of broader system)
//------------------------------------------------------------------------------

struct ArticleDTO
{
    std::int64_t             id              {};
    std::string              title;
    std::string              content;        // raw HTML or Markdown
    std::chrono::system_clock::time_point published_at;
};

class IArticleRepository
{
public:
    virtual ~IArticleRepository() = default;

    virtual std::vector<ArticleDTO> search(
        std::string_view   sql_where_clause,
        const std::vector<std::string>& params,
        std::size_t        limit,
        std::size_t        offset) = 0;
};

//------------------------------------------------------------------------------
// Ranking & Snippet Extraction
//------------------------------------------------------------------------------

namespace ranking {

/**
 *  Very naive TF-IDF style scoring.  In production use, replace with proper
 *  full-text search (PostgreSQL tsvector/tsquery or Elasticsearch), but this
 *  algorithm is serviceable for demo purposes without extra dependencies.
 */
double score_document(std::string_view text,
                      const std::vector<std::string>& search_terms)
{
    if (search_terms.empty())
        return 0.0;

    std::unordered_map<std::string, int> word_freq;
    std::istringstream iss{std::string(text)};
    std::string word;
    while (iss >> word)
    {
        util::ascii_to_lower(word);
        ++word_freq[word];
    }

    int term_hits = 0;
    for (auto const& term : search_terms)
    {
        auto it = word_freq.find(term);
        if (it != word_freq.end())
            term_hits += it->second;
    }

    double score = static_cast<double>(term_hits) / static_cast<double>(word_freq.size() + 1);
    return score;
}

/**
 *  Retrieve a highlighted snippet around the first term hit.
 */
std::string make_snippet(std::string_view text,
                         const std::vector<std::string>& search_terms,
                         std::size_t context = 40)
{
    std::string lowercase{ text };
    util::ascii_to_lower(lowercase);

    std::size_t best_pos = std::string_view::npos;
    for (const auto& term : search_terms)
    {
        std::size_t pos = lowercase.find(term);
        if (pos != std::string_view::npos &&
            (best_pos == std::string_view::npos || pos < best_pos))
            best_pos = pos;
    }

    if (best_pos == std::string_view::npos)
        return std::string(text.substr(0, std::min(text.size(), context))) + "...";

    std::size_t start = (best_pos > context) ? best_pos - context : 0;
    std::size_t end   = std::min(text.size(), best_pos + context);

    std::string snippet = std::string(text.substr(start, end - start));
    // crude HTML highlight
    for (const auto& term : search_terms)
    {
        std::regex rgx(term, std::regex_constants::icase);
        snippet = std::regex_replace(snippet, rgx, "<mark>$&</mark>");
    }

    if (start != 0)
        snippet.insert(0, "...");
    if (end != text.size())
        snippet.append("...");
    return snippet;
}

} // namespace ranking

//------------------------------------------------------------------------------
// Search Service
//------------------------------------------------------------------------------

class SearchService
{
public:
    explicit SearchService(std::shared_ptr<IArticleRepository> repo)
        : m_repo(std::move(repo))
    {
        if (!m_repo)
            throw std::invalid_argument("SearchService requires a repository");
    }

    struct Result
    {
        ArticleDTO  article;
        double      score;
        std::string snippet;
    };

    std::vector<Result> search(std::string_view query,
                               std::size_t limit  = 50,
                               std::size_t offset = 0)
    {
        if (query.size() < 2)
            return {}; // ignore noise

#ifdef SEARCH_UTF8_NORMALIZE
        query = util::normalize_utf8(query);
#endif

        // Step 1: Parse
        std::vector<std::string> bound_params;
        auto ast  = QueryParser{query}.parse();
        auto where_clause = ast->to_sql(bound_params);

        // Step 2: Fetch data
        auto records = m_repo->search(where_clause, bound_params, limit, offset);

        // Step 3: Score + snippet
        std::vector<std::string> search_terms = collect_terms(ast);
        std::vector<Result> out;
        out.reserve(records.size());

        for (auto&& rec : records)
        {
            double sc = ranking::score_document(rec.content, search_terms);
            std::string snip = ranking::make_snippet(rec.content, search_terms);
            out.push_back(Result{std::move(rec), sc, std::move(snip)});
        }

        // Step 4: Sort by score desc, then published_at desc
        std::ranges::stable_sort(out, [](auto const& a, auto const& b)
        {
            if (a.score != b.score)
                return a.score > b.score;
            return a.article.published_at > b.article.published_at;
        });

        spdlog::info("Search for '{}' returned {} documents", query, out.size());
        return out;
    }

private:
    std::shared_ptr<IArticleRepository> m_repo;

    static void collect_terms_recursive(const NodePtr& node,
                                        std::vector<std::string>& dst)
    {
        if (!node)
            return;

        if (auto term = std::dynamic_pointer_cast<TermNode>(node))
        {
            dst.push_back(term->token);
            return;
        }

        if (auto group = std::dynamic_pointer_cast<BoolNode>(node))
        {
            for (auto const& ch : group->children)
                collect_terms_recursive(ch, dst);
        }
    }

    static std::vector<std::string> collect_terms(const NodePtr& ast)
    {
        std::vector<std::string> terms;
        collect_terms_recursive(ast, terms);
        return terms;
    }
};

//------------------------------------------------------------------------------
// Dummy repository for demonstration / unit tests
//------------------------------------------------------------------------------

#ifdef SEARCH_MODULE_SELFTEST

class InMemoryArticleRepo final : public IArticleRepository
{
public:
    std::vector<ArticleDTO> storage;

    std::vector<ArticleDTO> search(std::string_view   /*where_clause*/,
                                   const std::vector<std::string>& params,
                                   std::size_t        limit,
                                   std::size_t        offset) override
    {
        std::vector<ArticleDTO> out;
        for (auto const& a : storage)
        {
            bool match = true;
            for (auto const& p : params)
            {
                std::string needle = p;
                needle.erase(std::remove(needle.begin(), needle.end(), '%'),
                             needle.end());
                std::string content_lc = a.content;
                util::ascii_to_lower(content_lc);
                match &= content_lc.find(needle) != std::string::npos;
            }
            if (match)
                out.push_back(a);
        }

        if (offset >= out.size())
            return {};
        auto begin = out.begin() + offset;
        auto end   = (limit == 0) ? out.end() : begin + std::min(limit, out.size() - offset);
        return std::vector<ArticleDTO>(begin, end);
    }
};

#include <iostream>

static void run_selftest()
{
    auto repo = std::make_shared<InMemoryArticleRepo>();
    repo->storage = {
        {1, "Hello World",  "This is a test article about C++ and world news.",
         std::chrono::system_clock::now()},
        {2, "Cats & Dogs",  "All about pets and how to train dogs.",
         std::chrono::system_clock::now()},
        {3, "Advanced C++", "Templates, metaprogramming, and beyond.",
         std::chrono::system_clock::now()}
    };

    SearchService svc(repo);

    auto results = svc.search("C++ AND NOT pets");
    for (auto const& r : results)
        std::cout << r.article.id << " | " << r.article.title
                  << " | score=" << r.score << "\nSnippet:\n"
                  << r.snippet << "\n\n";
}

int main()
{
    run_selftest();
}

#endif // SEARCH_MODULE_SELFTEST

} // namespace intraledger::blogsuite::search
```