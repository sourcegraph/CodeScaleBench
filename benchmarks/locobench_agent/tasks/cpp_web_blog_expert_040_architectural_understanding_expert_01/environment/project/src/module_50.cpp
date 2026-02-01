```cpp
/**
 *  IntraLedger BlogSuite
 *  File:        src/module_50.cpp
 *
 *  Component:   Full-Text Search – Query Parser & Cache
 *  Purpose:     Converts user-provided search strings into safe, DB-vendor
 *               specific SQL expressions.  Includes a thread-safe LRU cache
 *               for already-parsed queries, minimizing CPU cycles for
 *               repetitive searches (common in autocomplete scenarios).
 *
 *  Copyright
 *  ---------
 *  (c) 2024 IntraLedger Inc.  All rights reserved.
 *
 *  License
 *  -------
 *  This file is part of the proprietary IntraLedger BlogSuite code-base and
 *  may not be copied, modified, or distributed without prior written consent
 *  from IntraLedger Inc.
 */

#include <algorithm>
#include <cctype>
#include <chrono>
#include <exception>
#include <iomanip>
#include <iostream>
#include <list>
#include <mutex>
#include <regex>
#include <shared_mutex>
#include <sstream>
#include <stdexcept>
#include <string>
#include <string_view>
#include <unordered_map>
#include <utility>
#include <vector>

namespace intraledger::search {

/* --------------------------------------------------------------------------
 *  Constants & Type Aliases
 * --------------------------------------------------------------------------*/

using Clock          = std::chrono::steady_clock;
using TimePoint      = Clock::time_point;
using TokenContainer = std::vector<std::string>;

/* --------------------------------------------------------------------------
 *  Vendor enum (MariaDB / PostgreSQL)
 * --------------------------------------------------------------------------*/

enum class DbVendor
{
    MariaDB,
    PostgreSQL
};

/* --------------------------------------------------------------------------
 *  ParsedQuery – DTO returned by parser
 * --------------------------------------------------------------------------*/

struct ParsedQuery
{
    std::string  originalText;
    std::string  sqlExpression;      // e.g.: to_tsquery($1 || ':*')    OR   MATCH(title, body) AGAINST(? IN BOOLEAN MODE)
    TokenContainer bindValues;       // Values to be bound to prepared-statement placeholders
    bool         isValid = false;    // Quick validation flag
};

/* --------------------------------------------------------------------------
 *  LRUCache – thread-safe templated least-recently-used cache
 * --------------------------------------------------------------------------*/

template <typename Key, typename Value>
class LRUCache
{
public:
    explicit LRUCache(std::size_t capacity) : m_capacity(capacity)
    {
        if (capacity == 0)
        {
            throw std::invalid_argument("LRUCache capacity must be greater than zero.");
        }
    }

    bool get(const Key& key, Value& out)
    {
        std::shared_lock lock(m_mutex);

        auto itr = m_index.find(key);
        if (itr == m_index.end()) { return false; }

        // Move the accessed element to the front of the list (most recent)
        {
            std::unique_lock uniqueLock(m_mutexUpgrade);
            m_items.splice(m_items.begin(), m_items, itr->second);
            out = itr->second->second;
        }
        return true;
    }

    void put(const Key& key, const Value& value)
    {
        std::unique_lock lock(m_mutexUpgrade); // exclusive

        auto itr = m_index.find(key);
        if (itr != m_index.end())
        {
            // Replace existing
            itr->second->second = value;
            m_items.splice(m_items.begin(), m_items, itr->second);
            return;
        }

        // Insert new
        m_items.emplace_front(key, value);
        m_index[key] = m_items.begin();

        if (m_index.size() > m_capacity)
        {
            // Evict least-recently-used
            auto last = m_items.end();
            --last;
            m_index.erase(last->first);
            m_items.pop_back();
        }
    }

private:
    std::size_t m_capacity;
    std::list<std::pair<Key, Value>> m_items;     // Most recent at front
    std::unordered_map<Key, typename std::list<std::pair<Key, Value>>::iterator> m_index;
    mutable std::shared_mutex m_mutex;
    std::mutex m_mutexUpgrade; // for list modification
};

/* --------------------------------------------------------------------------
 *  Stop-word list (minimal; realistically this would be loaded from external)
 * --------------------------------------------------------------------------*/

static const std::unordered_map<std::string_view, bool> kStopWords {
    {"a", true},   {"an", true},  {"the", true},  {"and", true},
    {"or", true},  {"but", true}, {"of", true},   {"to", true},
    {"in", true},  {"for", true}, {"on", true},   {"with", true}
};

/* --------------------------------------------------------------------------
 *  SearchQueryParser
 * --------------------------------------------------------------------------*/

class SearchQueryParser
{
public:
    SearchQueryParser(DbVendor vendor, std::size_t cacheSize = 512)
    : m_vendor(vendor)
    , m_cache(cacheSize)
    {}

    ParsedQuery parse(const std::string& userInput)
    {
        // Attempt cache hit
        ParsedQuery pq;
        if (m_cache.get(userInput, pq))
        {
            return pq;
        }

        // Perform parsing
        pq = buildParsedQuery(userInput);

        // Cache result (even invalid queries – keeps consistent behaviour)
        m_cache.put(userInput, pq);
        return pq;
    }

private:
    DbVendor m_vendor;
    LRUCache<std::string, ParsedQuery> m_cache;

    /*  Tokenization -------------------------------------------------------*/
    static TokenContainer tokenize(std::string_view sv)
    {
        TokenContainer tokens;
        std::string token;
        token.reserve(64);

        for (char ch : sv)
        {
            if (std::isalnum(static_cast<unsigned char>(ch)))
            {
                token += static_cast<char>(std::tolower(ch));
            }
            else
            {
                if (!token.empty())
                {
                    tokens.emplace_back(token);
                    token.clear();
                }
            }
        }
        if (!token.empty()) { tokens.emplace_back(std::move(token)); }
        return tokens;
    }

    /*  Build SQL expression ----------------------------------------------*/
    ParsedQuery buildParsedQuery(const std::string& input)
    {
        ParsedQuery result;
        result.originalText = input;

        // Quick sanity check
        std::string lexed = trim(input);
        if (lexed.empty())
        {
            result.isValid = false;
            return result;
        }

        auto tokens = tokenize(lexed);
        TokenContainer filtered;
        filtered.reserve(tokens.size());

        for (auto& t : tokens)
        {
            if (kStopWords.find(t) == kStopWords.end())
            {
                filtered.push_back(std::move(t));
            }
        }

        if (filtered.empty())
        {
            result.isValid = false;
            return result;
        }

        /* Bind placeholders as concatenated lexemes, vendor specific */
        switch (m_vendor)
        {
            case DbVendor::PostgreSQL:
            {
                // For Postgres we build a tsquery string `'token1 & token2:*'`
                std::ostringstream builder;
                for (std::size_t i = 0; i < filtered.size(); ++i)
                {
                    builder << filtered[i] << ":*";
                    if (i + 1 < filtered.size()) { builder << " & "; }
                }
                result.sqlExpression = "to_tsquery($1)";
                result.bindValues    = { builder.str() };
                break;
            }
            case DbVendor::MariaDB:
            {
                // MariaDB full-text search in boolean mode
                std::ostringstream builder;
                for (std::size_t i = 0; i < filtered.size(); ++i)
                {
                    builder << '+' << filtered[i] << '*';
                    if (i + 1 < filtered.size()) { builder << ' '; }
                }
                result.sqlExpression =
                    "MATCH(title, body, tags) AGAINST (? IN BOOLEAN MODE)";
                result.bindValues = { builder.str() };
                break;
            }
            default:
                throw std::logic_error("Unsupported database vendor.");
        }

        result.isValid = true;
        return result;
    }

    /*  Helpers ------------------------------------------------------------*/
    static std::string trim(const std::string& str)
    {
        const auto begin = str.find_first_not_of(" \t\n\r\f\v");
        if (begin == std::string::npos) { return {}; }
        const auto end = str.find_last_not_of(" \t\n\r\f\v");
        return str.substr(begin, end - begin + 1);
    }
};

/* --------------------------------------------------------------------------
 *  Example usage (would normally be in the service layer)
 * --------------------------------------------------------------------------*/

#ifdef BLOGSUITE_SEARCH_TEST_MAIN
int main()
{
    try
    {
        SearchQueryParser mariaParser(DbVendor::MariaDB);
        SearchQueryParser pgParser(DbVendor::PostgreSQL);

        auto pq1 = mariaParser.parse("The quick brown fox");
        auto pq2 = pgParser.parse("The quick brown fox");

        std::cout << "MariaDB SQL: " << pq1.sqlExpression << "\n"
                  << "Bind value : " << pq1.bindValues.front() << "\n\n"
                  << "PostgreSQL SQL: " << pq2.sqlExpression << "\n"
                  << "Bind value    : " << pq2.bindValues.front() << std::endl;
    }
    catch (const std::exception& ex)
    {
        std::cerr << "Error: " << ex.what() << '\n';
        return EXIT_FAILURE;
    }
}
#endif // BLOGSUITE_SEARCH_TEST_MAIN

} // namespace intraledger::search
```