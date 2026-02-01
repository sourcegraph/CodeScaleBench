```cpp
/**
 *  IntraLedger BlogSuite : Search Query Parsing & SQL Translation Module
 *  ---------------------------------------------------------------------
 *
 *  File:        src/module_61.cpp
 *  Author:      IntraLedger Core Team
 *  Description: Implements a light-weight domain-specific language (DSL) that
 *               allows end-users to perform advanced full-text search queries
 *               similar to what you would expect from modern SaaS products.
 *
 *               Example query language features:
 *                 • Logical operators:  AND, OR, NOT
 *                 • Grouping:           ( ... )
 *                 • Phrase search:      "open source"
 *                 • Field scoping:      title:security  body:"zero trust"
 *
 *               The module is responsible for
 *                 1. Tokenising raw, user-supplied query strings
 *                 2. Building an Abstract Syntax Tree (AST)
 *                 3. Translating the AST into a SQL fragment that can be
 *                    embedded safely (with positional parameters) in queries
 *                    issued by our ORM layer.
 *
 *               All public APIs are contained under namespace:
 *                   IntraLedger::Search
 *
 *               The code follows modern C++20 best-practices, makes heavy use
 *               of RAII, std::variant, and strong type safety, while paying
 *               particular attention to predictable performance and security
 *               (e.g. SQL-injection prevention through bound parameters).
 *
 *  ---------------------------------------------------------------------
 *  Copyright © 2024 IntraLedger
 *  SPDX-License-Identifier: BUSL-1.1
 */

#include <algorithm>
#include <cctype>
#include <charconv>
#include <iomanip>
#include <iostream>
#include <memory>
#include <optional>
#include <sstream>
#include <stdexcept>
#include <string>
#include <string_view>
#include <utility>
#include <variant>
#include <vector>

namespace IntraLedger::Search
{

// ─────────────────────────────────────────────────────────────────────────────
//  Exceptions
// ─────────────────────────────────────────────────────────────────────────────

class ParseError : public std::runtime_error
{
public:
    ParseError(std::string_view message, std::size_t position)
        : std::runtime_error(fmt(message, position)), m_position(position)
    {}

    [[nodiscard]] std::size_t position() const noexcept { return m_position; }

private:
    static std::string fmt(std::string_view msg, std::size_t pos)
    {
        std::ostringstream oss;
        oss << "ParseError @ " << pos << ": " << msg;
        return oss.str();
    }

    std::size_t m_position;
};

// ─────────────────────────────────────────────────────────────────────────────
//  Lexer
// ─────────────────────────────────────────────────────────────────────────────

enum class TokenType
{
    Word,
    Phrase,
    And,
    Or,
    Not,
    Colon,
    LParen,
    RParen,
    EndOfInput
};

struct Token
{
    TokenType       type;
    std::string     lexeme;
    std::size_t     position;   // byte offset in original query string
};

class Lexer
{
public:
    explicit Lexer(std::string_view input) : m_input(input), m_cursor(0) {}

    [[nodiscard]] const Token& peek() const { return m_current; }

    [[nodiscard]] Token next()
    {
        Token t = m_current;
        m_current = lex();
        return t;
    }

    void consume() { m_current = lex(); }

    void reset()
    {
        m_cursor  = 0;
        m_current = lex();
    }

private:
    std::string_view m_input;
    std::size_t      m_cursor;
    Token            m_current { TokenType::EndOfInput, "", 0 };

    // Skip whitespace but keep track of cursor
    void skip_ws()
    {
        while (m_cursor < m_input.size() && std::isspace(static_cast<unsigned char>(m_input[m_cursor])))
            ++m_cursor;
    }

    // Read characters while predicate holds
    template <typename Pred>
    std::string read_while(Pred p)
    {
        const auto start = m_cursor;
        while (m_cursor < m_input.size() && p(static_cast<unsigned char>(m_input[m_cursor])))
            ++m_cursor;
        return std::string { m_input.substr(start, m_cursor - start) };
    }

    Token lex()
    {
        skip_ws();
        if (m_cursor >= m_input.size())
            return { TokenType::EndOfInput, "", m_cursor };

        const char ch = m_input[m_cursor];

        // Punctuation tokens
        switch (ch)
        {
            case ':':
                ++m_cursor;
                return { TokenType::Colon, ":", m_cursor - 1 };
            case '(':
                ++m_cursor;
                return { TokenType::LParen, "(", m_cursor - 1 };
            case ')':
                ++m_cursor;
                return { TokenType::RParen, ")", m_cursor - 1 };
            case '"':
                return lex_phrase();
            default:
                break;
        }

        // Word or reserved keyword
        if (std::isalnum(static_cast<unsigned char>(ch)) || ch == '_' || ch == '-')
        {
            auto word = read_while([](unsigned char c) {
                return std::isalnum(c) || c == '_' || c == '-' || c == '.';
            });

            const auto lower = to_lower(word);
            if (lower == "and")
                return { TokenType::And, word, m_cursor - word.size() };
            if (lower == "or")
                return { TokenType::Or, word, m_cursor - word.size() };
            if (lower == "not")
                return { TokenType::Not, word, m_cursor - word.size() };

            return { TokenType::Word, word, m_cursor - word.size() };
        }

        throw ParseError { std::string { "Invalid character '" } + ch + "'", m_cursor };
    }

    Token lex_phrase()
    {
        const std::size_t start_pos = m_cursor;
        ++m_cursor; // skip opening quote

        std::ostringstream oss;
        bool escaped = false;

        while (m_cursor < m_input.size())
        {
            char ch = m_input[m_cursor++];
            if (escaped)
            {
                // Accept common escape sequences or keep char as is
                switch (ch)
                {
                    case '"':  oss << '"'; break;
                    case '\\': oss << '\\'; break;
                    case 'n':  oss << '\n'; break;
                    case 't':  oss << '\t'; break;
                    default:   oss << ch;  break;
                }
                escaped = false;
            }
            else if (ch == '\\')
            {
                escaped = true;
            }
            else if (ch == '"')
            {
                // End of phrase
                return { TokenType::Phrase, oss.str(), start_pos };
            }
            else
            {
                oss << ch;
            }
        }

        // Reached end-of-input without closing quote
        throw ParseError { "Unterminated string literal", start_pos };
    }

    static std::string to_lower(std::string_view sv)
    {
        std::string out;
        out.reserve(sv.size());
        std::transform(sv.begin(), sv.end(), std::back_inserter(out),
                       [](unsigned char c) { return static_cast<char>(std::tolower(c)); });
        return out;
    }
};

// ─────────────────────────────────────────────────────────────────────────────
//  AST definitions
// ─────────────────────────────────────────────────────────────────────────────

struct QueryNode;

using NodePtr = std::unique_ptr<QueryNode>;

struct Term
{
    std::string value;
};

struct Phrase
{
    std::string value;
};

struct FieldFilter
{
    std::string field;  // e.g. "title"
    NodePtr     arg;    // Term or Phrase
};

struct Not
{
    NodePtr arg;
};

struct And
{
    NodePtr lhs;
    NodePtr rhs;
};

struct Or
{
    NodePtr lhs;
    NodePtr rhs;
};

struct QueryNode : std::variant<Term, Phrase, FieldFilter, Not, And, Or>
{
    using variant::variant;

    // Helper predicates
    bool is_logical() const
    {
        return std::holds_alternative<And>(*this) || std::holds_alternative<Or>(*this)
               || std::holds_alternative<Not>(*this);
    }
};

// ─────────────────────────────────────────────────────────────────────────────
//  Parser (recursive-descent)
// ─────────────────────────────────────────────────────────────────────────────

class Parser
{
public:
    explicit Parser(std::string_view input) : m_lexer(input)
    {
        m_lexer.reset(); // initialise first token
    }

    NodePtr parse()
    {
        auto expr = parse_or();
        expect(TokenType::EndOfInput);
        return expr;
    }

private:
    Lexer m_lexer;

    // Highest level: OR
    NodePtr parse_or()
    {
        auto node = parse_and();
        while (match(TokenType::Or))
        {
            auto rhs = parse_and();
            node     = std::make_unique<QueryNode>(Or { std::move(node), std::move(rhs) });
        }
        return node;
    }

    // Intermediate level: AND (implicit or explicit)
    NodePtr parse_and()
    {
        auto node = parse_unary();

        while (true)
        {
            if (match(TokenType::And))
            {
                auto rhs = parse_unary();
                node     = std::make_unique<QueryNode>(And { std::move(node), std::move(rhs) });
            }
            // Implicit AND: two consecutive terms / groups
            else if (peek_any({ TokenType::Word, TokenType::Phrase, TokenType::LParen, TokenType::Not }))
            {
                auto rhs = parse_unary();
                node     = std::make_unique<QueryNode>(And { std::move(node), std::move(rhs) });
            }
            else
            {
                break;
            }
        }

        return node;
    }

    // Unary: NOT
    NodePtr parse_unary()
    {
        if (match(TokenType::Not))
        {
            auto arg = parse_unary();
            return std::make_unique<QueryNode>(Not { std::move(arg) });
        }
        return parse_primary();
    }

    // Primary: term, phrase, parenthesis, field filter
    NodePtr parse_primary()
    {
        if (match(TokenType::LParen))
        {
            auto inner = parse_or();
            expect(TokenType::RParen);
            return inner;
        }

        if (peek(TokenType::Word))
        {
            auto wordTok = m_lexer.next();

            // Field filter?
            if (match(TokenType::Colon))
            {
                const std::string fieldName = to_lower(wordTok.lexeme);

                // Support only whitelisted fields
                if (!is_whitelisted_field(fieldName))
                    throw ParseError { "Unknown filter field '" + fieldName + "'", wordTok.position };

                // Value can be phrase or term
                NodePtr valueNode;
                if (peek(TokenType::Phrase))
                {
                    auto phraseTok = m_lexer.next();
                    valueNode      = std::make_unique<QueryNode>(Phrase { phraseTok.lexeme });
                }
                else if (peek(TokenType::Word))
                {
                    auto termTok = m_lexer.next();
                    valueNode    = std::make_unique<QueryNode>(Term { termTok.lexeme });
                }
                else
                {
                    throw ParseError { "Missing value after field filter ':'", m_lexer.peek().position };
                }

                return std::make_unique<QueryNode>(FieldFilter { fieldName, std::move(valueNode) });
            }

            /* Plain term */
            return std::make_unique<QueryNode>(Term { wordTok.lexeme });
        }

        if (peek(TokenType::Phrase))
        {
            auto phraseTok = m_lexer.next();
            return std::make_unique<QueryNode>(Phrase { phraseTok.lexeme });
        }

        throw ParseError { "Unexpected token '" + m_lexer.peek().lexeme + "'", m_lexer.peek().position };
    }

    // Helper ────────────────────────────────────────────────────────────────

    bool match(TokenType t)
    {
        if (peek(t))
        {
            m_lexer.consume();
            return true;
        }
        return false;
    }

    void expect(TokenType t)
    {
        if (!match(t))
            throw ParseError { "Expected different token", m_lexer.peek().position };
    }

    bool peek(TokenType t) const { return m_lexer.peek().type == t; }

    bool peek_any(std::initializer_list<TokenType> list) const
    {
        const TokenType cur = m_lexer.peek().type;
        return std::find(list.begin(), list.end(), cur) != list.end();
    }

    static std::string to_lower(std::string_view sv)
    {
        std::string out;
        out.reserve(sv.size());
        std::transform(sv.begin(), sv.end(), std::back_inserter(out),
                       [](unsigned char c) { return static_cast<char>(std::tolower(c)); });
        return out;
    }

    static bool is_whitelisted_field(const std::string& field)
    {
        static constexpr std::array allowed = { "title", "body", "tag", "author" };
        return std::find(allowed.begin(), allowed.end(), field) != allowed.end();
    }
};

// ─────────────────────────────────────────────────────────────────────────────
//  SQL Translation
// ─────────────────────────────────────────────────────────────────────────────

struct SqlFragment
{
    std::string              sql;     // WHERE clause without the "WHERE" keyword
    std::vector<std::string> params;  // positional parameters to bind in order
};

class SqlTranslator
{
public:
    // Compile AST into SQL WHERE fragment
    SqlFragment compile(const QueryNode& root)
    {
        m_buffer.clear();
        m_params.clear();
        walk(root);
        return { m_buffer.str(), m_params };
    }

private:
    std::ostringstream        m_buffer;
    std::vector<std::string>  m_params;

    // Depth-first traversal
    void walk(const QueryNode& node)
    {
        std::visit([this](auto&& n) { generate(n); }, node);
    }

    // Generates SQL with PostgreSQL/MariaDB full-text search in mind.
    // The ORM will later splice this fragment into a larger statement.
    void generate(const Term& n)
    {
        emit_param(to_tsquery(n.value));
    }

    void generate(const Phrase& n)
    {
        emit_param(to_tsquery_phrase(n.value));
    }

    void generate(const FieldFilter& n)
    {
        m_buffer << '(';
        const std::string columnName = map_field_to_column(n.field);
        m_buffer << columnName << " @@ ";
        walk(*n.arg);
        m_buffer << ')';
    }

    void generate(const Not& n)
    {
        m_buffer << "NOT (";
        walk(*n.arg);
        m_buffer << ')';
    }

    void generate(const And& n)
    {
        m_buffer << '(';
        walk(*n.lhs);
        m_buffer << " AND ";
        walk(*n.rhs);
        m_buffer << ')';
    }

    void generate(const Or& n)
    {
        m_buffer << '(';
        walk(*n.lhs);
        m_buffer << " OR ";
        walk(*n.rhs);
        m_buffer << ')';
    }

    // Helpers ────────────────────────────────────────────────────────────────

    static std::string to_tsquery(const std::string& term)
    {
        // Simplistic sanitisation; production code would do stemming, etc.
        std::string sanitized;
        sanitized.reserve(term.size());
        for (char c : term)
        {
            if (std::isalnum(static_cast<unsigned char>(c)) || c == '_')
                sanitized.push_back(static_cast<char>(std::tolower(c)));
        }
        return sanitized + ":*"; // prefix search
    }

    static std::string to_tsquery_phrase(const std::string& phrase)
    {
        // Replace spaces with & to enforce term adjacency in tsquery
        std::string ts = phrase;
        std::replace(ts.begin(), ts.end(), ' ', '&');
        return ts;
    }

    static std::string map_field_to_column(const std::string& field)
    {
        if (field == "title")  return "search_title";
        if (field == "body")   return "search_body";
        if (field == "tag")    return "search_tags";
        if (field == "author") return "search_author";
        // Fallback should never happen thanks to whitelist in parser
        throw std::logic_error("Unexpected field mapping request: " + field);
    }

    void emit_param(const std::string& value)
    {
        m_buffer << "to_tsquery(?)";
        m_params.emplace_back(value);
    }
};

// ─────────────────────────────────────────────────────────────────────────────
//  Public facade
// ─────────────────────────────────────────────────────────────────────────────

class SearchCompiler
{
public:
    SqlFragment operator()(std::string_view query)
    {
        Parser        parser { query };
        SqlTranslator translator;

        auto ast = parser.parse();
        return translator.compile(*ast);
    }
};

// ─────────────────────────────────────────────────────────────────────────────
//  Self-test (only compiled in debug / unit builds)
// ─────────────────────────────────────────────────────────────────────────────

#ifndef NDEBUG
static void self_test()
{
    SearchCompiler compiler;
    std::vector<std::string> cases = {
        R"(security AND (title:"zero trust" OR body:firewall))",
        R"(tag:cpp AND NOT author:"Bad Actor")",
        R"(backup or disaster AND recovery)",
        R"("open source" AND (license:mit or license:gpl))" // this will throw (invalid field)
    };

    for (const auto& q : cases)
    {
        try
        {
            auto result = compiler(q);
            std::cout << "\nQuery: " << q << "\nSQL:   " << result.sql << "\nParams:";
            for (const auto& p : result.params) std::cout << " [" << p << "]";
            std::cout << "\n";
        }
        catch (const std::exception& ex)
        {
            std::cerr << "Error compiling query '" << q << "': " << ex.what() << '\n';
        }
    }
}

struct SelfTestRegistrator
{
    SelfTestRegistrator() { self_test(); }
} _registrator;

#endif // NDEBUG

} // namespace IntraLedger::Search
```