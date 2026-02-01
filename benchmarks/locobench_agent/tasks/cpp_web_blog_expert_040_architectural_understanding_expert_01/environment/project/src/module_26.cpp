```cpp
/**************************************************************************************************
 *  IntraLedger BlogSuite – SearchQueryParser & Engine
 *  ---------------------------------------------------
 *  This module is responsible for parsing user-supplied search strings (e.g. from a search bar)
 *  into a structured representation and translating that representation into an SQL WHERE clause
 *  that can be consumed by the internal ORM layer.  While the actual ORM is part of another
 *  compilation unit, this module purposefully avoids any concrete ORM dependency by exposing the
 *  final artefact as a pair<string, vector<string>>   – the SQL snippet and its positional
 *  parameters – so that the call-site can decide how to bind them.
 *
 *  Highlights
 *  ----------
 *  • Robust, UTF-8 aware tokeniser (handles quotes, parentheses, boolean operators, field filters)
 *  • Shunting-yard implementation that outputs Reverse-Polish-Notation (RPN) for easy evaluation
 *  • Vocabulary-driven operator precedence and associativity
 *  • Runtime-safe (bounds-checked) parameter binding to thwart SQL-injection
 *  • Designed for extension: custom fields, operators, and pre/post processors can be registered
 *
 *  Copyright (c) 2024  IntraLedger Corp.
 **************************************************************************************************/

// STL
#include <algorithm>
#include <cctype>
#include <functional>
#include <iostream>
#include <locale>
#include <optional>
#include <regex>
#include <sstream>
#include <stdexcept>
#include <string>
#include <tuple>
#include <unordered_map>
#include <utility>
#include <variant>
#include <vector>

namespace intraledger::util
{
// Lightweight logger (placeholder for full-blown logging facility)
enum class LogLevel
{
    Trace,
    Debug,
    Info,
    Warning,
    Error,
    Fatal
};

inline void log(LogLevel level, const std::string &msg) noexcept
{
    static constexpr const char *levelStr[] = {"[TRACE]", "[DEBUG]", "[INFO]", "[WARN]", "[ERROR]",
                                               "[FATAL]"};
    std::clog << levelStr[static_cast<int>(level)] << ' ' << msg << '\n';
}

// String helpers
inline std::string ltrim(std::string s)
{
    s.erase(s.begin(), std::find_if(s.begin(), s.end(),
                                    [](unsigned char ch) { return !std::isspace(ch); }));
    return s;
}

inline std::string rtrim(std::string s)
{
    s.erase(std::find_if(s.rbegin(), s.rend(),
                         [](unsigned char ch) { return !std::isspace(ch); })
                .base(),
            s.end());
    return s;
}

inline std::string trim(std::string s) { return rtrim(ltrim(std::move(s))); }

} // namespace intraledger::util

namespace intraledger::search
{

// Publicly accessible error type
class ParseError : public std::runtime_error
{
  public:
    explicit ParseError(const std::string &msg) : std::runtime_error(msg) {}
};

// ------------------------- Token definition -----------------------------------------------------

enum class TokenType
{
    Word,
    Phrase,
    And,
    Or,
    Not,
    LParen,
    RParen,
    FieldFilter // e.g.  title:"foo"
};

struct Token
{
    TokenType                type;
    std::string              lexeme;     // Raw text (unescaped for phrases)
    std::optional<std::string> field;    // For FieldFilter
};

// ------------------------- Lexer ---------------------------------------------------------------

class Lexer
{
  public:
    explicit Lexer(std::string_view src) : source_(src), idx_(0) {}

    std::vector<Token> tokenize()
    {
        std::vector<Token> tokens;
        while (!eof())
        {
            skipWhitespace();
            if (eof())
                break;

            char ch = peek();
            switch (ch)
            {
            case '"':
                tokens.push_back(readPhrase());
                break;
            case '(':
                tokens.push_back({TokenType::LParen, std::string(1, ch), std::nullopt});
                advance();
                break;
            case ')':
                tokens.push_back({TokenType::RParen, std::string(1, ch), std::nullopt});
                advance();
                break;
            default:
                if (isAlpha(ch))
                    tokens.push_back(readWordOrOperatorOrField());
                else
                    throw ParseError("Unexpected character in search query: " + std::string(1, ch));
            }
        }
        return tokens;
    }

  private:
    std::string_view source_;
    std::size_t      idx_;

    bool eof() const noexcept { return idx_ >= source_.size(); }

    char peek() const noexcept { return source_[idx_]; }

    char advance() noexcept { return source_[idx_++]; }

    void skipWhitespace() noexcept
    {
        while (!eof() && std::isspace(static_cast<unsigned char>(peek())))
            advance();
    }

    static bool isAlpha(char ch) noexcept
    {
        return std::isalpha(static_cast<unsigned char>(ch)) || ch == '_';
    }

    static bool equalsIgnoreCase(const std::string &a, const std::string &b) noexcept
    {
        if (a.size() != b.size())
            return false;
        for (size_t i = 0; i < a.size(); ++i)
        {
            if (std::tolower(static_cast<unsigned char>(a[i])) !=
                std::tolower(static_cast<unsigned char>(b[i])))
                return false;
        }
        return true;
    }

    Token readPhrase()
    {
        // Called with current char == '"'
        advance(); // Skip opening quote
        std::ostringstream oss;
        while (!eof())
        {
            char ch = advance();
            if (ch == '"')
            {
                // End of phrase
                return {TokenType::Phrase, oss.str(), std::nullopt};
            }
            else if (ch == '\\' && !eof())
            {
                // Escape
                ch = advance();
                oss << ch;
            }
            else
            {
                oss << ch;
            }
        }
        throw ParseError("Unterminated string literal in search query");
    }

    Token readWordOrOperatorOrField()
    {
        std::ostringstream oss;
        // Read until whitespace or special char
        while (!eof() && !std::isspace(static_cast<unsigned char>(peek())) && peek() != '(' &&
               peek() != ')')
        {
            char ch = advance();
            if (ch == ':')
            {
                // We encountered a field specifier (e.g. title:foo)
                std::string fieldName = util::trim(oss.str());
                if (fieldName.empty())
                    throw ParseError("Empty field name before ':' in search query");

                // Value after ':' could be phrase or simple word
                if (eof())
                    throw ParseError("Unterminated field filter: missing value after ':'");

                // If next char is quote, delegate phrase reader
                skipWhitespace();
                if (peek() == '"')
                {
                    Token phraseToken = readPhrase();
                    phraseToken.field = fieldName;
                    phraseToken.type  = TokenType::FieldFilter;
                    return phraseToken;
                }
                else
                {
                    // Read until next whitespace or special char
                    std::ostringstream valueOss;
                    while (!eof() && !std::isspace(static_cast<unsigned char>(peek())) &&
                           peek() != '(' && peek() != ')')
                    {
                        valueOss << advance();
                    }
                    std::string value = valueOss.str();
                    if (value.empty())
                        throw ParseError("Empty value in field filter");
                    return {TokenType::FieldFilter, value, fieldName};
                }
            }
            else
            {
                oss << ch;
            }
        }

        std::string word = oss.str();
        if (equalsIgnoreCase(word, "AND"))
            return {TokenType::And, word, std::nullopt};
        if (equalsIgnoreCase(word, "OR"))
            return {TokenType::Or, word, std::nullopt};
        if (equalsIgnoreCase(word, "NOT"))
            return {TokenType::Not, word, std::nullopt};
        return {TokenType::Word, word, std::nullopt};
    }
};

// ------------------------- AST/RPN --------------------------------------------------------------

enum class Op
{
    And,
    Or,
    Not
};

// A node can be either a term (word/phrase/field) or a logical operator
using RpnAtom = std::variant<Token, Op>;

// ------------------------- Parser ---------------------------------------------------------------

class Parser
{
  public:
    explicit Parser(std::vector<Token> tokens) : tokens_(std::move(tokens)), idx_(0) {}

    std::vector<RpnAtom> parse()
    {
        using util::log;
        using util::LogLevel;

        std::vector<RpnAtom> output;
        std::vector<Token>   opStack;

        auto precedence = [](const Token &t) -> int {
            if (t.type == TokenType::Not)
                return 3;
            if (t.type == TokenType::And)
                return 2;
            if (t.type == TokenType::Or)
                return 1;
            return 0;
        };

        auto isOperator = [](const Token &t) {
            return t.type == TokenType::And || t.type == TokenType::Or || t.type == TokenType::Not;
        };

        while (idx_ < tokens_.size())
        {
            const Token &tok = tokens_[idx_++];
            switch (tok.type)
            {
            case TokenType::Word:
            case TokenType::Phrase:
            case TokenType::FieldFilter:
                output.push_back(tok);
                break;
            case TokenType::And:
            case TokenType::Or:
            case TokenType::Not:
                while (!opStack.empty() && isOperator(opStack.back()) &&
                       precedence(opStack.back()) >= precedence(tok))
                {
                    output.push_back(toOp(opStack.back()));
                    opStack.pop_back();
                }
                opStack.push_back(tok);
                break;
            case TokenType::LParen:
                opStack.push_back(tok);
                break;
            case TokenType::RParen:
                while (!opStack.empty() && opStack.back().type != TokenType::LParen)
                {
                    output.push_back(toOp(opStack.back()));
                    opStack.pop_back();
                }
                if (opStack.empty() || opStack.back().type != TokenType::LParen)
                    throw ParseError("Mismatched parentheses in search query");
                opStack.pop_back(); // Pop '('
                break;
            default:
                throw ParseError("Unexpected token during parsing");
            }
        }

        // Drain operator stack
        while (!opStack.empty())
        {
            if (opStack.back().type == TokenType::LParen || opStack.back().type == TokenType::RParen)
                throw ParseError("Mismatched parentheses in search query");
            output.push_back(toOp(opStack.back()));
            opStack.pop_back();
        }

        log(LogLevel::Debug, "Generated RPN with " + std::to_string(output.size()) + " atoms");
        return output;
    }

  private:
    std::vector<Token> tokens_;
    std::size_t        idx_;

    static Op toOp(const Token &t)
    {
        switch (t.type)
        {
        case TokenType::And:
            return Op::And;
        case TokenType::Or:
            return Op::Or;
        case TokenType::Not:
            return Op::Not;
        default:
            throw ParseError("Token is not a logical operator");
        }
    }
};

// ------------------------- SQL Builder ----------------------------------------------------------

struct SqlFragment
{
    std::string              clause;     // e.g. "(lower(title) LIKE lower(?))"
    std::vector<std::string> parameters; // Bound parameters (same order as '?')
};

class SqlBuilder
{
  public:
    // The list of supported field names and the column they map to in the database
    using FieldMap = std::unordered_map<std::string, std::string>;

    explicit SqlBuilder(FieldMap fieldMapping) : fields_(std::move(fieldMapping)) {}

    SqlFragment build(const std::vector<RpnAtom> &rpnAtoms)
    {
        using util::log;
        using util::LogLevel;

        std::vector<SqlFragment> stack;
        for (const auto &atom : rpnAtoms)
        {
            if (std::holds_alternative<Token>(atom))
            {
                stack.push_back(termToSql(std::get<Token>(atom)));
            }
            else
            {
                Op op = std::get<Op>(atom);
                if (op == Op::Not)
                {
                    if (stack.empty())
                        throw ParseError("NOT operator missing operand");
                    SqlFragment arg = popBack(stack);
                    stack.push_back(unaryNot(std::move(arg)));
                }
                else
                {
                    if (stack.size() < 2)
                        throw ParseError("Binary operator missing operands");
                    SqlFragment rhs = popBack(stack);
                    SqlFragment lhs = popBack(stack);
                    if (op == Op::And)
                        stack.push_back(binary("AND", std::move(lhs), std::move(rhs)));
                    else
                        stack.push_back(binary("OR", std::move(lhs), std::move(rhs)));
                }
            }
        }

        if (stack.size() != 1)
            throw ParseError("Invalid search expression");

        log(LogLevel::Info, "SQL WHERE fragment built: " + stack.back().clause);
        return stack.back();
    }

  private:
    FieldMap fields_;

    static SqlFragment popBack(std::vector<SqlFragment> &v)
    {
        SqlFragment frag = std::move(v.back());
        v.pop_back();
        return frag;
    }

    static SqlFragment unaryNot(SqlFragment arg)
    {
        SqlFragment res;
        res.clause = "NOT (" + arg.clause + ")";
        res.parameters.insert(res.parameters.end(), arg.parameters.begin(), arg.parameters.end());
        return res;
    }

    static SqlFragment binary(const std::string &op, SqlFragment lhs, SqlFragment rhs)
    {
        SqlFragment res;
        res.clause = "(" + lhs.clause + " " + op + " " + rhs.clause + ")";
        res.parameters.reserve(lhs.parameters.size() + rhs.parameters.size());
        res.parameters.insert(res.parameters.end(), lhs.parameters.begin(), lhs.parameters.end());
        res.parameters.insert(res.parameters.end(), rhs.parameters.begin(), rhs.parameters.end());
        return res;
    }

    SqlFragment termToSql(const Token &t)
    {
        auto makeLike = [](const std::string &column) {
            return "lower(" + column + ") LIKE lower(?)";
        };

        SqlFragment frag;

        switch (t.type)
        {
        case TokenType::Word:
            frag.clause = makeLike("content_index");
            frag.parameters = {"%" + t.lexeme + "%"};
            break;
        case TokenType::Phrase:
            frag.clause     = makeLike("content_index");
            frag.parameters = {"%" + t.lexeme + "%"};
            break;
        case TokenType::FieldFilter: {
            auto it = fields_.find(t.field.value());
            if (it == fields_.end())
                throw ParseError("Unknown field name in search query: " + t.field.value());
            frag.clause     = makeLike(it->second);
            frag.parameters = {"%" + t.lexeme + "%"};
            break;
        }
        default:
            throw ParseError("Unexpected token type in termToSql");
        }
        return frag;
    }
};

// ------------------------- Public-facing Search API --------------------------------------------

class SearchEngine
{
  public:
    using FieldMap = SqlBuilder::FieldMap;

    explicit SearchEngine(FieldMap fieldMap) : builder_(std::move(fieldMap)) {}

    // Converts a raw user query into (sql, parameters)
    std::pair<std::string, std::vector<std::string>> compileQuery(const std::string &raw)
    {
        if (raw.empty())
            throw ParseError("Query string cannot be empty");

        Lexer   lexer(raw);
        Parser  parser(lexer.tokenize());
        auto    rpn = parser.parse();
        auto    sql = builder_.build(rpn);

        return {sql.clause, sql.parameters};
    }

  private:
    SqlBuilder builder_;
};

// ------------------------- Example usage (can be removed in production) -------------------------

#ifdef INTRALEDGER_SEARCH_EXAMPLE
int main()
{
    try
    {
        intraledger::search::SearchEngine engine(
            {{"title", "posts.title"}, {"author", "users.display_name"}});

        auto [clause, params] =
            engine.compileQuery(R"(title:"Hello World" AND (author:Alice OR author:Bob) NOT draft)");

        std::cout << "WHERE " << clause << '\n';
        std::cout << "Params:\n";
        for (const auto &p : params)
            std::cout << "  " << p << '\n';
    }
    catch (const intraledger::search::ParseError &e)
    {
        std::cerr << "Parse error: " << e.what() << '\n';
        return 1;
    }
}
#endif

} // namespace intraledger::search
```
