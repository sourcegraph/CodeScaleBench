#include "module_38.hpp"

#include <algorithm>
#include <cctype>
#include <chrono>
#include <iomanip>
#include <mutex>
#include <optional>
#include <regex>
#include <sstream>
#include <stdexcept>
#include <string_view>
#include <unordered_map>
#include <utility>

#if __has_include(<spdlog/spdlog.h>)
    #include <spdlog/spdlog.h>
    #define BLOGSUITE_LOG_INFO(...)  spdlog::info(__VA_ARGS__)
    #define BLOGSUITE_LOG_ERROR(...) spdlog::error(__VA_ARGS__)
#else
    #include <iostream>
    #define BLOGSUITE_LOG_INFO(...)  (std::cerr << "[INFO] "  << __VA_ARGS__ << '\n')
    #define BLOGSUITE_LOG_ERROR(...) (std::cerr << "[ERROR] " << __VA_ARGS__ << '\n')
#endif

// ---------------------------------------------------------------------------------------------------------------------
//  module_38.cpp
//  Purpose: Advanced user-facing search query parser & SQL compiler with an internal LRU memoization cache.
//           Intended for use by the BlogSuite Search Service.
// ---------------------------------------------------------------------------------------------------------------------

namespace intraledger::blogsuite::search
{
// ======= Exceptions ==================================================================================================

class ParseException : public std::runtime_error
{
public:
    explicit ParseException(std::string  message)
        : std::runtime_error { std::move(message) }
    {}
};

// ======= Helper Types ================================================================================================

enum class TokenMod
{
    Optional,   // no prefix, acts as SHOULD
    Required,   // '+' prefix, acts as MUST
    Excluded    // '-' prefix, acts as MUST_NOT
};

enum class SearchField
{
    Title,
    Body,
    Tags,
    Author,
    Unknown
};

static constexpr std::string_view DEFAULT_FIELD_NAME = "body";

// Maps canonical field names to enum
static const std::unordered_map<std::string_view, SearchField> kFieldMap{
    { "title",  SearchField::Title  },
    { "body",   SearchField::Body   },
    { "tag",    SearchField::Tags   },
    { "tags",   SearchField::Tags   },
    { "author", SearchField::Author }
};

// Convert enum to column name suited for SQL
static std::string_view toColumn(SearchField f)
{
    switch (f)
    {
    case SearchField::Title:  return "title";
    case SearchField::Body:   return "body";
    case SearchField::Tags:   return "tags";
    case SearchField::Author: return "author_name";
    default:                  return "body";
    }
}

// ======= Token =======================================================================================================

struct Token
{
    TokenMod        modifier   { TokenMod::Optional };
    SearchField     field      { SearchField::Unknown };
    std::string     lexeme;
    bool            isPhrase   { false };     // tokens wrapped in quotes
    bool            hasWildcard{ false };     // '*' found at beginning or end
};

// ======= Parsed Query ================================================================================================

struct ParsedQuery
{
    std::vector<Token> tokens;
};

// ======= LRU Cache (thread-safe) =====================================================================================

template <typename K, typename V, std::size_t MaxEntries = 128>
class ThreadSafeLRU
{
    struct Node
    {
        K                         key;
        V                         val;
        std::chrono::steady_clock::time_point lastHit;
    };

    std::list<Node> _items;
    mutable std::mutex _mx;

public:
    std::optional<V> find(const K& key) const
    {
        std::scoped_lock guard { _mx };
        auto it = std::find_if(_items.begin(), _items.end(),
                               [&] (const Node& node) { return node.key == key; });
        if (it == _items.end()) { return std::nullopt; }

        it->lastHit = std::chrono::steady_clock::now();
        _items.splice(_items.begin(), _items, it);                    // move node to front (most recently used)
        return it->val;
    }

    void insert(K key, V value)
    {
        std::scoped_lock guard { _mx };

        if (auto existing = std::find_if(_items.begin(), _items.end(),
                                         [&] (const Node& node) { return node.key == key; });
            existing != _items.end())
        {
            existing->val     = std::move(value);
            existing->lastHit = std::chrono::steady_clock::now();
            _items.splice(_items.begin(), _items, existing);
            return;
        }

        _items.emplace_front(Node{ std::move(key),
                                   std::move(value),
                                   std::chrono::steady_clock::now() });

        if (_items.size() > MaxEntries)
            _items.pop_back();
    }
};

// ======= Compiler Output =============================================================================================

struct SqlQuery
{
    std::string              statement;  // Prepared SQL statement with positional placeholders ($1, $2, ‥)
    std::vector<std::string> parameters; // Corresponding parameters in correct order
};

// ======= Query Parser Implementation =================================================================================

class SearchQueryParser
{
public:
    ParsedQuery parse(std::string_view input) const
    {
        ParsedQuery result;
        std::string_view remaining = trim(input);

        while (!remaining.empty())
        {
            Token token = extractNextToken(remaining);
            result.tokens.emplace_back(std::move(token));

            remaining = trim(remaining); // consume whitespace
        }
        return result;
    }

private:
    static std::string_view trim(std::string_view sv)
    {
        const auto first = sv.find_first_not_of(" \t\n\r");
        if (first == std::string_view::npos) return {};

        const auto last = sv.find_last_not_of(" \t\n\r");
        return sv.substr(first, (last - first) + 1);
    }

    static bool tryConsume(char expected, std::string_view& sv)
    {
        if (!sv.empty() && sv.front() == expected)
        {
            sv.remove_prefix(1);
            return true;
        }
        return false;
    }

    Token extractNextToken(std::string_view& sv) const
    {
        Token token;

        // 1) Detect modifier
        if (tryConsume('+', sv)) token.modifier = TokenMod::Required;
        else if (tryConsume('-', sv)) token.modifier = TokenMod::Excluded;

        // 2) Detect field prefix "title:", "body:" …
        auto colonPos = sv.find(':');
        if (colonPos != std::string_view::npos)
        {
            auto maybeField = trim(sv.substr(0, colonPos));
            if (auto it = kFieldMap.find(maybeField); it != kFieldMap.end())
            {
                token.field = it->second;
                sv.remove_prefix(colonPos + 1); // skip "field:"
            }
        }
        if (token.field == SearchField::Unknown)
            token.field = SearchField::Body; // fallback to default

        sv = trim(sv);

        // 3) Quoted phrase?
        if (!sv.empty() && sv.front() == '"')
        {
            token.isPhrase = true;
            sv.remove_prefix(1); // drop opening quote

            const auto endQuote = sv.find('"');
            if (endQuote == std::string_view::npos)
                throw ParseException { "Unterminated quote in search string." };

            token.lexeme = std::string(sv.substr(0, endQuote));
            sv.remove_prefix(endQuote + 1); // consume phrase and closing quote
        }
        else
        {
            // parse until whitespace
            const auto tokEnd = sv.find_first_of(" \t\r\n");
            token.lexeme = std::string(sv.substr(0, tokEnd));
            sv.remove_prefix(tokEnd == std::string_view::npos ? sv.size() : tokEnd);
        }

        // wildcard?
        token.hasWildcard = (!token.lexeme.empty() &&
                             (token.lexeme.front() == '*' || token.lexeme.back() == '*'));

        return token;
    }
};

// ======= SQL Compiler Implementation =================================================================================

class SearchQueryCompiler
{
public:
    explicit SearchQueryCompiler(bool useILike = false)
        : _useILikeSearch { useILike }
    {}

    SqlQuery compile(const ParsedQuery& q) const
    {
        if (q.tokens.empty())
            throw ParseException { "Attempting to compile an empty search." };

        std::ostringstream sql;
        std::vector<std::string> params;
        std::size_t paramIndex = 1;

        sql << '(';

        bool firstClause = true;
        for (const Token& tok : q.tokens)
        {
            if (!firstClause)
            {
                sql << (tok.modifier == TokenMod::Excluded ? " AND " : " OR ");
            }
            firstClause = false;

            switch (tok.modifier)
            {
            case TokenMod::Required: sql << '('; break;
            case TokenMod::Optional: sql << '('; break;
            case TokenMod::Excluded: sql << "NOT ("; break;
            }

            // Build expression for field
            const std::string_view column = toColumn(tok.field);

            if (_useILikeSearch)
            {
                sql << column << ' ' << (_useILikeSearch ? "ILIKE" : "LIKE") << " $" << paramIndex++ << ')';

                // Build parameter with wildcards
                std::string param = tok.lexeme;
                if (tok.hasWildcard)
                {
                    // Replace '*' with SQL wildcard
                    std::replace(param.begin(), param.end(), '*', '%');
                }
                else if (tok.isPhrase)
                {
                    param = '%' + param + '%';
                }
                else
                {
                    param = '%' + param + '%';
                }
                params.emplace_back(std::move(param));
            }
            else
            {
                // Example full text search using PostgreSQL
                sql << "to_tsvector('simple'," << column << ") @@ to_tsquery('simple', $" << paramIndex++ << "))";
                params.emplace_back(transformLexemeToTsQuery(tok));
            }
        }

        sql << ')';

        SqlQuery result;
        result.statement  = sql.str();
        result.parameters = std::move(params);
        return result;
    }

private:
    bool _useILikeSearch;

    static std::string transformLexemeToTsQuery(const Token& tok)
    {
        // This is a naive transformation; production code would escape lexemes properly
        std::string queryPart;

        switch (tok.modifier)
        {
        case TokenMod::Required:
            queryPart += "";
            break;
        case TokenMod::Optional:
            queryPart += "";
            break;
        case TokenMod::Excluded:
            queryPart += "!";
            break;
        }

        if (tok.isPhrase)
        {
            std::string phrase = tok.lexeme;
            std::replace(phrase.begin(), phrase.end(), ' ', '&');
            queryPart += '(' + phrase + ")";
        }
        else
        {
            std::string lex = tok.lexeme;
            std::replace(lex.begin(), lex.end(), '*', ':'); // crude wildcard for illustration
            queryPart += lex;
        }
        return queryPart;
    }
};

// ======= Public Facade ===============================================================================================

class SearchEngine
{
public:
    explicit SearchEngine(bool useILike = false)
        : _compiler(useILike)
    {}

    SqlQuery translate(std::string_view userInput)
    {
        // 1) Try cache
        if (auto cached = _cache.find(userInput))
        {
            BLOGSUITE_LOG_INFO("Cache hit for query '{}'", userInput);
            return *cached;
        }

        try
        {
            ParsedQuery parsed = _parser.parse(userInput);
            SqlQuery    sql    = _compiler.compile(parsed);

            _cache.insert(std::string(userInput), sql);
            return sql;
        }
        catch (const std::exception& ex)
        {
            BLOGSUITE_LOG_ERROR("Unable to translate search query '{}'. Error: {}", userInput, ex.what());
            throw; // rethrow to caller
        }
    }

private:
    SearchQueryParser                     _parser;
    SearchQueryCompiler                   _compiler;
    ThreadSafeLRU<std::string, SqlQuery>  _cache;
};

// ======= Example Usage (unit-test / demonstration only) ==============================================================
#ifdef BLOGSUITE_SEARCH_STANDALONE_TEST

#include <iostream>

int main()
{
    SearchEngine engine(true); // use ILIKE mode for MariaDB
    const auto sql = engine.translate(R"(title:"modern C++" +security -deprecated)");
    std::cout << "SQL: " << sql.statement << "\nParams:\n";
    for (std::size_t i = 0; i < sql.parameters.size(); ++i)
        std::cout << '$' << (i + 1) << ": " << sql.parameters[i] << '\n';
    return 0;
}

#endif

} // namespace intraledger::blogsuite::search