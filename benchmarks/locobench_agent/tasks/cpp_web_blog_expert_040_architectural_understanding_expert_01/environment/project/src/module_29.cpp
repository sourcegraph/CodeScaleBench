#include <algorithm>
#include <cctype>
#include <exception>
#include <iomanip>
#include <iterator>
#include <optional>
#include <regex>
#include <sstream>
#include <stdexcept>
#include <string>
#include <string_view>
#include <unordered_set>
#include <utility>
#include <variant>
#include <vector>

//------------------------------------------------------------------------------
// IntraLedger BlogSuite – Search Query Compiler & Highlighter
//
// This module turns an end-user search string into:
//
//   1. A parameterised SQL fragment suitable for MariaDB or PostgreSQL
//      full-text indices
//   2. A list of “needles” that can be used to highlight matches in the UI
//
// The grammar is intentionally small but expressive:
//
//     query     := or_expr
//     or_expr   := and_expr ( '|' and_expr )*
//     and_expr  := not_expr ( '&' not_expr )*
//     not_expr  := [ '!' ] primary
//     primary   := WORD | PHRASE | '(' query ')'
//
// Where:
//   WORD   := [A-Za-z0-9_]+
//   PHRASE := '"' .*? '"'
//
// Operators:
//
//   |   Logical OR   (defaults to OR if no operator is given)
//   &   Logical AND  (defaults to AND inside an implicit group)
//   !   Logical NOT
//
// Example:
//
//   quick brown | "lazy dog" & !cat
//
//------------------------------------------------------------------------------

namespace ilbs     // IntraLedger BlogSuite (short-hand namespace)
{
namespace search
{

//------------------------------------------------------------------------------
// Exceptions
//------------------------------------------------------------------------------

struct QueryError : std::runtime_error
{
    explicit QueryError(const std::string& msg) : std::runtime_error(msg) {}
};

//------------------------------------------------------------------------------
// Tokenisation
//------------------------------------------------------------------------------

enum class TokenType
{
    Word,
    Phrase,
    And,
    Or,
    Not,
    LParen,
    RParen,
    EndOfInput
};

struct Token
{
    TokenType           type;
    std::string_view    lexeme;
    std::size_t         offset;     // byte offset in the original query
};

class Tokeniser
{
public:
    explicit Tokeniser(std::string_view input) : _input(input) {}

    Token next()
    {
        skip_ws();

        if (_pos >= _input.size())
            return make_tok(TokenType::EndOfInput, "");

        char ch = _input[_pos];

        switch (ch)
        {
            case '|': return advance(TokenType::Or, 1);
            case '&': return advance(TokenType::And, 1);
            case '!': return advance(TokenType::Not, 1);
            case '(': return advance(TokenType::LParen, 1);
            case ')': return advance(TokenType::RParen, 1);
            case '"': return parse_phrase();
            default:
                if (std::isalnum(static_cast<unsigned char>(ch)) || ch == '_')
                    return parse_word();
                break;
        }

        std::ostringstream oss;
        oss << "Unexpected character '" << ch << "' at offset " << _pos;
        throw QueryError(oss.str());
    }

private:
    std::string_view _input;
    std::size_t      _pos {0};

    void skip_ws()
    {
        while (_pos < _input.size() && std::isspace(static_cast<unsigned char>(_input[_pos])))
            ++_pos;
    }

    Token advance(TokenType t, std::size_t len)
    {
        Token tok {t, _input.substr(_pos, len), _pos};
        _pos += len;
        return tok;
    }

    Token make_tok(TokenType t, std::string_view sv)
    {
        return Token {t, sv, _pos};
    }

    Token parse_phrase()
    {
        std::size_t start = _pos;
        ++_pos; // consume opening "
        std::size_t phrase_start = _pos;

        while (_pos < _input.size() && _input[_pos] != '"')
            ++_pos;

        if (_pos >= _input.size())
        {
            std::ostringstream oss;
            oss << "Unterminated phrase starting at offset " << start;
            throw QueryError(oss.str());
        }

        std::string_view lex = _input.substr(phrase_start, _pos - phrase_start);
        ++_pos; // consume closing "
        return Token {TokenType::Phrase, lex, phrase_start - 1};
    }

    Token parse_word()
    {
        std::size_t start = _pos;
        while (_pos < _input.size() &&
               (std::isalnum(static_cast<unsigned char>(_input[_pos])) || _input[_pos] == '_'))
        {
            ++_pos;
        }
        std::string_view lex = _input.substr(start, _pos - start);
        return Token {TokenType::Word, lex, start};
    }
};

//------------------------------------------------------------------------------
// AST
//------------------------------------------------------------------------------

struct NodeBinary;
struct NodeUnary;
struct NodeTerm;

using NodePtr = std::shared_ptr<struct Node>;

struct Node
{
    using Variant = std::variant<NodeBinary, NodeUnary, NodeTerm>;
    Variant      data;
};

enum class BinaryOp { And, Or };
enum class UnaryOp  { Not };

struct NodeBinary
{
    BinaryOp op;
    NodePtr  lhs;
    NodePtr  rhs;
};

struct NodeUnary
{
    UnaryOp op;
    NodePtr rhs;
};

struct NodeTerm
{
    std::string_view term;    // word or phrase
    bool             is_phrase;
};

//------------------------------------------------------------------------------
// Parser
//------------------------------------------------------------------------------

class Parser
{
public:
    explicit Parser(std::string_view input)
        : _tokeniser(input)
    {
        _curr = _tokeniser.next();
    }

    NodePtr parse()
    {
        NodePtr ast = parse_or_expr();
        if (_curr.type != TokenType::EndOfInput)
            throw QueryError("Unexpected token after end of query");
        return ast;
    }

private:
    Tokeniser _tokeniser;
    Token     _curr;

    void advance() { _curr = _tokeniser.next(); }

    NodePtr parse_or_expr()
    {
        NodePtr node = parse_and_expr();
        while (_curr.type == TokenType::Or)
        {
            advance();
            NodePtr rhs  = parse_and_expr();
            node         = make_binary(BinaryOp::Or, std::move(node), std::move(rhs));
        }
        return node;
    }

    NodePtr parse_and_expr()
    {
        NodePtr node = parse_not_expr();
        while (_curr.type == TokenType::And ||
               _curr.type == TokenType::Word || _curr.type == TokenType::Phrase ||
               _curr.type == TokenType::LParen || _curr.type == TokenType::Not)
        {
            // Implicit AND when tokens follow directly
            if (_curr.type == TokenType::And)
                advance();
            NodePtr rhs = parse_not_expr();
            node        = make_binary(BinaryOp::And, std::move(node), std::move(rhs));
        }
        return node;
    }

    NodePtr parse_not_expr()
    {
        if (_curr.type == TokenType::Not)
        {
            advance();
            NodePtr rhs = parse_not_expr();
            return make_unary(UnaryOp::Not, std::move(rhs));
        }
        return parse_primary();
    }

    NodePtr parse_primary()
    {
        switch (_curr.type)
        {
            case TokenType::Word:
            {
                NodePtr node = make_term(_curr.lexeme, false);
                advance();
                return node;
            }
            case TokenType::Phrase:
            {
                NodePtr node = make_term(_curr.lexeme, true);
                advance();
                return node;
            }
            case TokenType::LParen:
            {
                advance();
                NodePtr node = parse_or_expr();
                if (_curr.type != TokenType::RParen)
                    throw QueryError("Expected ')'");
                advance();
                return node;
            }
            default:
                throw QueryError("Unexpected token in primary expression");
        }
    }

    static NodePtr make_binary(BinaryOp op, NodePtr lhs, NodePtr rhs)
    {
        auto n        = std::make_shared<Node>();
        n->data       = NodeBinary {op, std::move(lhs), std::move(rhs)};
        return n;
    }
    static NodePtr make_unary(UnaryOp op, NodePtr rhs)
    {
        auto n  = std::make_shared<Node>();
        n->data = NodeUnary {op, std::move(rhs)};
        return n;
    }

    static NodePtr make_term(std::string_view lexeme, bool phrase)
    {
        auto n  = std::make_shared<Node>();
        n->data = NodeTerm {lexeme, phrase};
        return n;
    }
};

//------------------------------------------------------------------------------
// Compiler – emits SQL + bind variables
//------------------------------------------------------------------------------

struct CompiledQuery
{
    std::string              sql_where;  // WHERE ... expression
    std::vector<std::string> bindings;   // Prepared-statement parameters
    std::vector<std::string> highlight_terms;
};

class Compiler
{
public:
    enum class Dialect { PostgreSQL, MariaDB };

    explicit Compiler(Dialect dialect) : _dialect(dialect)
    {
        // PostgreSQL uses plainto_tsquery / to_tsquery
        // MariaDB uses MATCH … AGAINST
    }

    CompiledQuery compile(const NodePtr& root)
    {
        _bindings.clear();
        _needles.clear();
        std::ostringstream oss;
        emit_node(root, oss);
        CompiledQuery cq;
        cq.sql_where       = oss.str();
        cq.bindings        = _bindings;
        cq.highlight_terms = _needles;
        return cq;
    }

private:
    Dialect                 _dialect;
    std::vector<std::string> _bindings;
    std::vector<std::string> _needles;

    static std::string placeholder(std::size_t idx, Dialect d)
    {
        return d == Dialect::PostgreSQL ? "$" + std::to_string(idx) : "?";
    }

    void emit_node(const NodePtr& node, std::ostringstream& oss)
    {
        std::visit(
            [&](auto&& n) { emit(n, oss); },
            node->data);
    }

    void emit(const NodeBinary& n, std::ostringstream& oss)
    {
        oss << '(';
        emit_node(n.lhs, oss);
        oss << (n.op == BinaryOp::And ? " AND " : " OR ");
        emit_node(n.rhs, oss);
        oss << ')';
    }

    void emit(const NodeUnary& n, std::ostringstream& oss)
    {
        oss << "(NOT ";
        emit_node(n.rhs, oss);
        oss << ')';
    }

    void emit(const NodeTerm& term, std::ostringstream& oss)
    {
        std::string needle {term.term};
        _needles.push_back(needle);

        // Build parameter placeholder
        _bindings.push_back(needle);

        std::size_t index = _bindings.size();
        oss << build_match_expression(term, index);
    }

    std::string build_match_expression(const NodeTerm& term, std::size_t bindIndex) const
    {
        const auto param = placeholder(bindIndex, _dialect);
        if (_dialect == Dialect::PostgreSQL)
        {
            // Using to_tsquery for phrases, plainto_tsquery for single words
            if (term.is_phrase)
                return "search_vector @@ phraseto_tsquery('simple', " + param + ")";
            else
                return "search_vector @@ plainto_tsquery('simple', " + param + ")";
        }
        else
        {
            // MariaDB assumes FULLTEXT index on (title, body)
            if (term.is_phrase)
                return "MATCH(title, body) AGAINST (" + param + " IN BOOLEAN MODE)";
            else
                return "MATCH(title, body) AGAINST (" + param + " IN NATURAL LANGUAGE MODE)";
        }
    }
};

//------------------------------------------------------------------------------
// Highlighter
//------------------------------------------------------------------------------

namespace util
{
inline std::string to_lower(std::string_view s)
{
    std::string out;
    out.reserve(s.size());
    std::transform(s.begin(), s.end(), std::back_inserter(out),
                   [](unsigned char c){ return std::tolower(c); });
    return out;
}
} // namespace util

class Highlighter
{
public:
    Highlighter() = default;

    // Surrounds occurrences of needles with <mark> … </mark>
    std::string highlight(std::string_view text,
                          const std::vector<std::string>& needles) const
    {
        if (needles.empty())
            return std::string(text);

        // Build case-insensitive regex
        std::ostringstream oss;
        oss << "(";
        for (std::size_t i = 0; i < needles.size(); ++i)
        {
            if (i) oss << '|';
            oss << std::regex_replace(needles[i], std::regex(R"([.^$|()\\+\[\]{}])"), R"(\$&)");
        }
        oss << ")";
        std::regex re(oss.str(), std::regex::icase | std::regex::optimize);

        std::string result;
        std::regex_replace(std::back_inserter(result),
                           text.begin(),
                           text.end(),
                           re,
                           "<mark>$&</mark>");
        return result;
    }
};

//------------------------------------------------------------------------------
// Public API
//------------------------------------------------------------------------------

class SearchQueryCompiler
{
public:
    explicit SearchQueryCompiler(Compiler::Dialect dialect = Compiler::Dialect::PostgreSQL)
        : _compiler(dialect)
    {}

    CompiledQuery compile(std::string_view query)
    {
        Parser   p(query);
        NodePtr  ast = p.parse();
        return _compiler.compile(ast);
    }

    std::string highlight(std::string_view text, const CompiledQuery& cq) const
    {
        return _highlighter.highlight(text, cq.highlight_terms);
    }

private:
    Compiler     _compiler;
    Highlighter  _highlighter;
};

//------------------------------------------------------------------------------
// Unit test (compile with -DILBS_SEARCH_TEST)
//------------------------------------------------------------------------------

#ifdef ILBS_SEARCH_TEST
#include <iostream>

int main()
{
    try
    {
        SearchQueryCompiler qc(SearchQueryCompiler::Compiler::Dialect::PostgreSQL);
        const auto result = qc.compile(R"(quick brown | "lazy dog" & !cat)");

        std::cout << "SQL WHERE: " << result.sql_where << '\n';
        std::cout << "Bindings:\n";
        for (std::size_t i = 0; i < result.bindings.size(); ++i)
            std::cout << "  $" << (i + 1) << " = " << result.bindings[i] << '\n';

        const std::string snippet =
            "The quick brown fox jumps over the lazy dog while the cat sleeps.";

        std::cout << "\nHighlighted:\n"
                  << qc.highlight(snippet, result) << '\n';
    }
    catch (const QueryError& e)
    {
        std::cerr << "Query Error: " << e.what() << '\n';
    }
    catch (const std::exception& e)
    {
        std::cerr << "Unhandled exception: " << e.what() << '\n';
    }
}
#endif

} // namespace search
} // namespace ilbs