```cpp
/**
 *  IntraLedger BlogSuite – Search Module
 *
 *  File:        src/module_73.cpp
 *  Author:      IntraLedger Engineering
 *  Description: Provides a production–grade “SearchQueryBuilder” that parses
 *               user-supplied search strings, sanitises the input, applies
 *               additional high-level filters (date range, tags, language,
 *               author, publication state) and produces a prepared SQL query
 *               with a corresponding parameter vector ready to be consumed
 *               by the system’s ORM.
 *
 *  Note:        Although this file can be built stand-alone, it is intended
 *               to plug into the larger BlogSuite codebase.  All interfaces
 *               follow the conventions already established by the Repository
 *               and Service layers elsewhere in the project.
 */

#include <algorithm>
#include <chrono>
#include <cctype>
#include <iomanip>
#include <iostream>
#include <regex>
#include <sstream>
#include <stdexcept>
#include <string>
#include <unordered_set>
#include <utility>
#include <variant>
#include <vector>

namespace blog::search {

/* ────────────────────────────────────────────────────────────────────────── */
/*  Forward declarations                                                     */
/* ────────────────────────────────────────────────────────────────────────── */

class SearchQueryBuilder;

/* ────────────────────────────────────────────────────────────────────────── */
/*  Type helpers                                                             */
/* ────────────────────────────────────────────────────────────────────────── */

using SqlStatement  = std::string;
using SqlParameters = std::vector<std::string>;

enum class BooleanOperator : std::uint8_t
{
    And,
    Or,
    Not
};

struct TimeRange
{
    // Inclusive range with RFC-3339(ish) timestamps, e.g. “2023-01-01T00:00:00Z”
    std::string from;
    std::string to;
};

struct SearchFilters
{
    std::vector<std::string> tags;          // slugified tag names
    std::string              languageCode;  // ISO-639-1 (“en”, “de”, …)
    std::string              authorId;      // UUID or numeric PK
    std::optional<TimeRange> published;     // date range for publication time
    bool                     includeDrafts {false};
};

/**
 * Stop-word list, lightly curated.  In production this might be pluggable or
 * read from a configuration file or database table.
 */
static const std::unordered_set<std::string> kStopWords{
    "a",   "an",  "and", "are", "as",   "at",  "be",  "by",   "for",  "from",
    "has", "he",  "in",  "is",  "it",   "its", "of",  "on",   "that", "the",
    "to",  "was", "were","will","with",
};

/* ────────────────────────────────────────────────────────────────────────── */
/*  Exceptions                                                               */
/* ────────────────────────────────────────────────────────────────────────── */

class SearchQueryError final : public std::runtime_error
{
public:
    explicit SearchQueryError(const std::string& what)
        : std::runtime_error{"SearchQueryError: " + what}
    {}
};

/* ────────────────────────────────────────────────────────────────────────── */
/*  Tokeniser implementation                                                 */
/* ────────────────────────────────────────────────────────────────────────── */

struct Token
{
    std::string     lexeme;
    BooleanOperator op            = BooleanOperator::And;
    bool            isPhrase      = false;
    bool            hasWildcard   = false;
    bool            isNegated     = false;
};

namespace {

/**
 * Trim whitespace from both ends of a string.
 */
inline void trim(std::string& s)
{
    auto notSpace = [](unsigned char ch) { return !std::isspace(ch); };
    s.erase(s.begin(), std::find_if(s.begin(), s.end(), notSpace));
    s.erase(std::find_if(s.rbegin(), s.rend(), notSpace).base(), s.end());
}

/**
 * Convert string to lower-case using the C locale.  Fast enough for ASCII.
 */
inline void to_lower(std::string& s)
{
    std::transform(s.begin(), s.end(), s.begin(),
                   [](unsigned char c) { return static_cast<char>(std::tolower(c)); });
}

/**
 * Returns true if given term is in stop-word list.
 */
inline bool is_stop_word(const std::string& term)
{
    return kStopWords.find(term) != kStopWords.end();
}

/**
 * Escape special characters for SQL “LIKE” clauses.
 * Only underscores and percent signs have to be doubled;
 * the ORM will take care of higher-level escaping.
 */
inline std::string escape_like(const std::string& raw)
{
    std::string out;
    out.reserve(raw.size() * 2);  // worst case
    for (char ch : raw)
    {
        if (ch == '_' || ch == '%')
            out.push_back('\\');
        out.push_back(ch);
    }
    return out;
}

} // namespace

/* ────────────────────────────────────────────────────────────────────────── */
/*  Core Builder                                                             */
/* ────────────────────────────────────────────────────────────────────────── */

class SearchQueryBuilder
{
public:
    explicit SearchQueryBuilder(std::string_view searchInput,
                                const SearchFilters& filters = {})
        : rawInput_{searchInput}
        , filters_{filters}
    {
        parse();
        buildSql();
    }

    const SqlStatement&  statement()  const noexcept { return statement_;  }
    const SqlParameters& parameters() const noexcept { return parameters_; }

private:
    std::string              rawInput_;
    SearchFilters            filters_;
    std::vector<Token>       tokens_;
    SqlStatement             statement_;
    SqlParameters            parameters_;

    /* ────────────────────────────────────────────────────────────────── */
    /*  Parsing                                                          */
    /* ────────────────────────────────────────────────────────────────── */

    void parse()
    {
        if (rawInput_.empty())
            throw SearchQueryError{"Empty search string is not permitted."};

        // Simplistic parser: Short-circuit if quoted phrases exist.
        std::regex  phraseRegex{R"("([^"]+)")"};
        std::smatch match;
        std::string remaining = rawInput_;

        while (std::regex_search(remaining, match, phraseRegex))
        {
            if (match.prefix().length())
                parseWords(match.prefix().str());

            createToken(match[1].str(), /*phrase=*/true);
            remaining = match.suffix().str();
        }

        if (!remaining.empty())
            parseWords(remaining);

        if (tokens_.empty())
            throw SearchQueryError{"No searchable tokens after parsing."};
    }

    void parseWords(const std::string& segment)
    {
        std::istringstream iss{segment};
        std::string        word;

        while (iss >> word)
        {
            to_lower(word);
            if (word == "or")
            {
                if (!tokens_.empty())
                    tokens_.back().op = BooleanOperator::Or;
                continue;
            }
            if (word == "not" || word == "-")
            {
                // Negative prefix is applied to next token; we mark it here.
                Token t;
                t.isNegated   = true;
                t.op          = BooleanOperator::And; // defaults to AND
                tokens_.push_back(std::move(t));
                continue;
            }
            createToken(word, /*phrase=*/false);
        }
    }

    void createToken(const std::string& lexeme, bool phrase)
    {
        std::string term = lexeme;
        to_lower(term);
        trim(term);

        if (term.empty()
            || (term.size() == 1 && (term == "+" || term == "-"))
            || is_stop_word(term))
        {
            return;  // skip empty or stop-words
        }

        bool wildcard = false;
        if (!phrase && term.back() == '*')
        {
            term.pop_back();
            wildcard = true;
            if (term.empty())
                return;  // reject queries that are just '*'
        }

        Token t;
        t.lexeme      = term;
        t.isPhrase    = phrase;
        t.hasWildcard = wildcard;

        // Handle prefixed negation stub from previous call, if present.
        if (!tokens_.empty() && tokens_.back().lexeme.empty() && tokens_.back().isNegated)
        {
            t.isNegated       = true;
            t.op              = tokens_.back().op;   // carry operator
            tokens_.pop_back();                      // remove stub
        }

        tokens_.push_back(std::move(t));
    }

    /* ────────────────────────────────────────────────────────────────── */
    /*  SQL builder                                                      */
    /* ────────────────────────────────────────────────────────────────── */

    void buildSql()
    {
        std::ostringstream sql;
        sql << "SELECT b.* FROM blog_posts AS b WHERE ";

        bool first = true;
        for (const Token& tok : tokens_)
        {
            if (!first)
            {
                sql << (tok.op == BooleanOperator::Or ? " OR " : " AND ");
            }
            first = false;

            if (tok.isNegated)
                sql << "NOT (";

            if (tok.isPhrase)
            {
                sql << "to_tsvector('simple', b.content) @@ "
                       "phraseto_tsquery('simple', ?)";
                parameters_.push_back(tok.lexeme);
            }
            else
            {
                if (tok.hasWildcard)
                {
                    sql << "lower(b.content) LIKE ?";
                    parameters_.push_back(escape_like(tok.lexeme) + "%");
                }
                else
                {
                    sql << "to_tsvector('simple', b.content) @@ plainto_tsquery('simple', ?)";
                    parameters_.push_back(tok.lexeme);
                }
            }

            if (tok.isNegated)
                sql << ')';
        }

        appendFilterClauses(sql);
        appendOrderingClause(sql);

        statement_ = sql.str();
    }

    void appendFilterClauses(std::ostringstream& sql)
    {
        // Publish state
        if (!filters_.includeDrafts)
        {
            sql << " AND b.is_draft = FALSE";
        }

        // Language filter
        if (!filters_.languageCode.empty())
        {
            sql << " AND b.language_code = ?";
            parameters_.push_back(filters_.languageCode);
        }

        // Author filter
        if (!filters_.authorId.empty())
        {
            sql << " AND b.author_id = ?";
            parameters_.push_back(filters_.authorId);
        }

        // Tag filter (uses bridging table)
        if (!filters_.tags.empty())
        {
            sql << " AND EXISTS (SELECT 1 FROM post_tags pt "
                   "JOIN tags t ON t.id = pt.tag_id "
                   "WHERE pt.post_id = b.id AND t.slug IN (";
            for (std::size_t i = 0; i < filters_.tags.size(); ++i)
            {
                sql << (i == 0 ? "?" : ", ?");
                parameters_.push_back(filters_.tags[i]);
            }
            sql << "))";
        }

        // Published date range
        if (filters_.published.has_value())
        {
            const auto& range = filters_.published.value();
            if (!range.from.empty())
            {
                sql << " AND b.published_at >= ?";
                parameters_.push_back(range.from);
            }
            if (!range.to.empty())
            {
                sql << " AND b.published_at <= ?";
                parameters_.push_back(range.to);
            }
        }
    }

    void appendOrderingClause(std::ostringstream& sql) const
    {
        // Simple ordering: full-text rank followed by recency.
        sql << " ORDER BY ts_rank_cd(to_tsvector('simple', b.content), "
               "plainto_tsquery('simple', ?)) DESC, b.published_at DESC";
        parameters_.push_back(buildCombinedQuery());
    }

    /**
     * Combine tokens into a single tsquery string for ranking purposes.
     * Example: “foo & bar | baz”.
     */
    std::string buildCombinedQuery() const
    {
        std::ostringstream oss;
        bool first = true;

        for (const Token& tok : tokens_)
        {
            if (tok.isNegated)
                continue;  // skip negated terms for ranking

            if (!first)
            {
                oss << (tok.op == BooleanOperator::Or ? " | " : " & ");
            }
            first = false;

            oss << tok.lexeme;
            if (tok.hasWildcard)
                oss << ":*";
        }
        return oss.str();
    }
};

/* ────────────────────────────────────────────────────────────────────────── */
/*  Example usage (to be removed in production binaries)                     */
/* ────────────────────────────────────────────────────────────────────────── */

#ifdef BLOGSUITE_SEARCHQUERY_BUILDER_STANDALONE_TEST
int main()
{
    try
    {
        using namespace std::literals;

        SearchFilters f;
        f.tags          = {"cpp", "backend"};
        f.languageCode  = "en";
        f.includeDrafts = false;

        SearchQueryBuilder b{R"( "full text" OR metadata -draft*)", f};

        std::cout << "Generated SQL: \n" << b.statement() << "\n\nParameters:\n";
        for (const std::string& p : b.parameters())
            std::cout << "  " << p << '\n';
    }
    catch (const std::exception& ex)
    {
        std::cerr << "Error: " << ex.what() << '\n';
        return EXIT_FAILURE;
    }
}
#endif

} // namespace blog::search
```