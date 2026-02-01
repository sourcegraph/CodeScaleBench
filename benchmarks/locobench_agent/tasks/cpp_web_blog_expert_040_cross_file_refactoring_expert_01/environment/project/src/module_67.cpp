/*
 *  IntraLedger BlogSuite
 *  File: src/module_67.cpp
 *
 *  Description:
 *      SearchQueryBuilder – a dialect-aware full-text search query builder
 *      used by the search service layer.  The builder translates an end-user
 *      search string into a secure, parameterised SQL statement compatible
 *      with either MariaDB (InnoDB FTS) or PostgreSQL (GIN/GIST + tsvector).
 *
 *      The produced query returns an ordered list of article identifiers
 *      alongside a ranking score so that the caller can hydrate the final
 *      DTOs using the Repository layer.  The class is entirely header-only,
 *      but lives in a .cpp compilation unit to avoid template bloat and to
 *      retain the ability to hide implementation details.
 *
 *  NOTE:
 *      The surrounding infrastructure—database connection pool, repository,
 *      and DI container—are assumed to exist elsewhere in the codebase.  This
 *      module purposefully depends only on the C++17 standard library.
 *
 *  Copyright (c) 2024
 *  SPDX-License-Identifier: MIT
 */

#include <algorithm>
#include <cctype>
#include <optional>
#include <regex>
#include <sstream>
#include <stdexcept>
#include <string>
#include <string_view>
#include <unordered_set>
#include <utility>
#include <vector>

namespace intraledger::blog::search {

// ---------------------------------------------------------------------------------------------------------------------
//  Utility helpers
// ---------------------------------------------------------------------------------------------------------------------

namespace detail {

/* English stop word list (partial).  In production this is usually loaded from
 * a language pack or compiled into the database’s FTS dictionary. */
static const std::unordered_set<std::string_view> STOP_WORDS{
    "a",  "an",  "and", "are", "as",  "at",  "be", "but", "by",  "for",
    "if", "in",  "into", "is", "it",  "no",  "not","of",  "on",  "or",
    "such","that","the","their","then","there","these","they","this",
    "to","was","will","with"};

/* Trim whitespace from both ends of the string. */
inline std::string_view trim(std::string_view str) {
    auto left  = std::find_if_not(str.begin(), str.end(), ::isspace);
    auto right = std::find_if_not(str.rbegin(), str.rend(), ::isspace).base();
    return (left < right) ? std::string_view{left, static_cast<std::size_t>(right - left)} : std::string_view{};
}

/* Converts input to lower case. */
inline std::string to_lower(std::string_view s) {
    std::string out(s.size(), '\0');
    std::transform(s.begin(), s.end(), out.begin(),
                   [](unsigned char c) { return static_cast<char>(std::tolower(c)); });
    return out;
}

/* Escapes '%' and '_' for LIKE queries (MariaDB fallback when FTS index is missing). */
inline std::string escape_like(std::string_view s) {
    std::string out;
    out.reserve(s.size());
    for (char c : s) {
        if (c == '%' || c == '_' || c == '\\') {
            out.push_back('\\');
        }
        out.push_back(c);
    }
    return out;
}

} // namespace detail

// ---------------------------------------------------------------------------------------------------------------------
//  Public data structures
// ---------------------------------------------------------------------------------------------------------------------

struct SqlParameter {
    std::string name;   // Named parameter (":term1")
    std::string value;  // Raw value, Database layer handles binding/escaping
};

struct SqlQuery {
    std::string               text;
    std::vector<SqlParameter> params;
};

enum class DatabaseDialect { MariaDB, PostgreSQL };

struct SearchOptions {
    DatabaseDialect dialect                = DatabaseDialect::PostgreSQL;
    std::vector<std::string> searchColumns = {"title", "body"};
    std::string resultIdColumn             = "id";
    std::string fromTable                  = "articles";
    std::optional<std::string> publishedConstraint =
        "status = 'PUBLISHED'"; // SQL fragment, injected verbatim
    int maxTokens                          = 32;   // Safety guard
};

// ---------------------------------------------------------------------------------------------------------------------
//  SearchQueryBuilder
// ---------------------------------------------------------------------------------------------------------------------

class SearchQueryBuilder {
public:
    explicit SearchQueryBuilder(SearchOptions opts) : opts_(std::move(opts)) {}

    SqlQuery build(std::string_view rawSearch) const {
        auto tokens = tokenize(rawSearch);

        if (tokens.empty()) {
            throw std::invalid_argument("SearchQueryBuilder: keyword list empty after tokenisation");
        }

        switch (opts_.dialect) {
            case DatabaseDialect::MariaDB:
                return build_mariadb(std::move(tokens));
            case DatabaseDialect::PostgreSQL:
                return build_postgres(std::move(tokens));
        }
        throw std::logic_error("SearchQueryBuilder: unsupported dialect");
    }

private:
    // -----------------------------------------------------------------------------------------------------------------
    //  Tokenisation / pre-processing
    // -----------------------------------------------------------------------------------------------------------------

    std::vector<std::string> tokenize(std::string_view raw) const {
        std::vector<std::string> result;
        std::string cleaned = detail::to_lower(detail::trim(raw));
        if (cleaned.empty()) return result;

        std::regex wordRe(R"(\b[\w\-]+\b)", std::regex::ECMAScript);
        auto       wordsBegin = std::sregex_iterator(cleaned.begin(), cleaned.end(), wordRe);
        auto       wordsEnd   = std::sregex_iterator();

        for (auto it = wordsBegin; it != wordsEnd; ++it) {
            std::string token = it->str();
            if (detail::STOP_WORDS.contains(token)) continue; // skip stop words
            result.emplace_back(std::move(token));
            if (static_cast<int>(result.size()) >= opts_.maxTokens) break;
        }
        return result;
    }

    // -----------------------------------------------------------------------------------------------------------------
    //  Dialect specific builders
    // -----------------------------------------------------------------------------------------------------------------

    SqlQuery build_mariadb(std::vector<std::string> tokens) const {
        SqlQuery query;
        std::ostringstream oss;

        // Build SELECT clause
        oss << "SELECT " << opts_.resultIdColumn << ", "
            << "MATCH(" << join_columns(",") << ") "
            << "AGAINST (";

        // Compose AGAINST string with wildcard (*) for prefix search
        std::ostringstream against;
        against << '\'';
        for (std::size_t i = 0; i < tokens.size(); ++i) {
            if (i) against << ' ';
            against << tokens[i] << '*';
        }
        against << '\'';

        oss << against.str() << " IN BOOLEAN MODE) AS rank "
            << "FROM " << opts_.fromTable << ' ';

        // WHERE clause
        oss << "WHERE MATCH(" << join_columns(",") << ") "
            << "AGAINST (:" << param_name("against") << " IN BOOLEAN MODE) ";

        query.params.push_back({param_name("against"), against.str().substr(1, against.str().size() - 2)}); // strip quotes

        if (opts_.publishedConstraint) {
            oss << "AND " << *opts_.publishedConstraint << ' ';
        }

        // ORDER BY
        oss << "ORDER BY rank DESC "
            << "LIMIT 100;";

        query.text = std::move(oss).str();
        return query;
    }

    SqlQuery build_postgres(std::vector<std::string> tokens) const {
        SqlQuery query;
        std::ostringstream oss;

        // Prepare ts_query string
        std::ostringstream ts;
        for (std::size_t i = 0; i < tokens.size(); ++i) {
            if (i) ts << " & "; // AND-ed
            ts << tokens[i] << ":*"; // prefix search
        }

        const auto tsParam = param_name("tsquery");
        query.params.push_back({tsParam, ts.str()});

        // Build SELECT
        oss << "SELECT " << opts_.resultIdColumn << ", "
            << "ts_rank(search_vector, :" << tsParam << ") AS rank "
            << "FROM (SELECT "
            << opts_.resultIdColumn << ", "
            << "to_tsvector('simple', " << join_columns(" || ' ' || ") << ") AS search_vector "
            << "FROM " << opts_.fromTable;

        // Inner WHERE for published status
        if (opts_.publishedConstraint) {
            oss << " WHERE " << *opts_.publishedConstraint;
        }
        oss << ") sub "
            << "WHERE search_vector @@ :" << tsParam << " "
            << "ORDER BY rank DESC "
            << "LIMIT 100;";

        query.text = std::move(oss).str();
        return query;
    }

    // -----------------------------------------------------------------------------------------------------------------
    //  Helper
    // -----------------------------------------------------------------------------------------------------------------

    std::string join_columns(std::string_view separator) const {
        std::ostringstream oss;
        for (std::size_t i = 0; i < opts_.searchColumns.size(); ++i) {
            if (i) oss << separator;
            oss << opts_.searchColumns[i];
        }
        return oss.str();
    }

    mutable int paramCounter_{0};

    std::string param_name(std::string_view base) const {
        std::ostringstream oss;
        oss << base << ++paramCounter_;
        return oss.str();
    }

    SearchOptions opts_;
};

} // namespace intraledger::blog::search

// ---------------------------------------------------------------------------------------------------------------------
//  Usage example (would normally live in a service/handler, kept here for unit
//  test convenience; compile with -DQUERY_BUILDER_DEMO to include main()).
// ---------------------------------------------------------------------------------------------------------------------
#ifdef QUERY_BUILDER_DEMO
#include <iostream>

int main() {
    using namespace intraledger::blog::search;

    SearchOptions optsPg;
    optsPg.dialect = DatabaseDialect::PostgreSQL;
    SearchQueryBuilder builderPg(optsPg);

    auto q1 = builderPg.build("C++ Dependency Injection Architecture");
    std::cout << "Postgres query:\n" << q1.text << "\n";
    for (auto &p : q1.params) {
        std::cout << p.name << " = " << p.value << "\n";
    }

    std::cout << "\n------------------------------------\n";

    SearchOptions optsMy;
    optsMy.dialect = DatabaseDialect::MariaDB;
    SearchQueryBuilder builderMy(optsMy);

    auto q2 = builderMy.build("High availability replication");
    std::cout << "MariaDB query:\n" << q2.text << "\n";
    for (auto &p : q2.params) {
        std::cout << p.name << " = " << p.value << "\n";
    }
}
#endif /* QUERY_BUILDER_DEMO */
