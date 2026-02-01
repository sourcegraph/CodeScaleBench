```cpp
/**
 *  IntraLedger BlogSuite
 *  File:    src/module_75.cpp
 *
 *  Module 75 – SearchQueryParser & Compiler
 *
 *  A production-ready, modern-C++ implementation that converts an end-user
 *  search string into an abstract syntax tree (AST) and finally into a
 *  parameterised SQL WHERE-clause understood by the in-house ORM layer.
 *
 *  The component is completely self-contained, yet pluggable: it exposes a
 *  minimal façade (SearchQuery::parse + SearchQuery::compile) and hides the
 *  actual parsing/compilation machinery in an implementation namespace.
 *
 *  Supported grammar (BNF):
 *      <expr>  ::= <term> { ( "OR" ) <term> }*
 *      <term>  ::= <factor> { ( "AND" ) <factor> }*
 *      <factor>::= [ "NOT" ] <primary>
 *      <primary>::= <WORD>|<PHRASE>|"(" <expr> ")"
 *
 *  Words and phrases are matched case-insensitively against the article
 *  title and body. The compiler generates dialect-aware SQL for PostgreSQL
 *  and MariaDB, correctly parameterising LIKE/ILIKE patterns so that the ORM
 *  can bind them later in a type-safe manner.
 *
 *  Copyright (c) 2024
 *  SPDX-License-Identifier: MIT
 */

#include <algorithm>
#include <cctype>
#include <memory>
#include <optional>
#include <stdexcept>
#include <string>
#include <string_view>
#include <utility>
#include <vector>

namespace blog::search
{

//-------- Public API ---------------------------------------------------------

enum class SqlDialect
{
    PostgreSQL,
    MariaDB
};

/**
 *  SearchQuery – Méthode-chaîne façade.
 *
 *      SearchQuery query = SearchQuery::parse(userInput);
 *      auto [sql, params] = query.compile(SqlDialect::PostgreSQL);
 */
class SearchQuery
{
public:
    // Factory
    static SearchQuery parse(std::string_view input);

    // Compile to <SQL where-clause, bound-parameter list>
    [[nodiscard]] std::pair<std::string, std::vector<std::string>>
    compile(SqlDialect dialect) const;

private:
    // Implementation details tucked away via PIMPL to minimise recompiles
    struct Impl;
    std::shared_ptr<const Impl> _impl;

    explicit SearchQuery(std::shared_ptr<const Impl> p) : _impl(std::move(p)) {}
};

//----------------------------------------------------------------------------
//  Implementation
//----------------------------------------------------------------------------

namespace impl
{

//--------------------------------------------------- Tokenisation ----------//
enum class TokenType
{
    Word,      // e.g. hello
    Phrase,    // e.g. "hello world"
    And,       // AND (case-insensitive)
    Or,        // OR
    Not,       // NOT
    LParen,    // (
    RParen,    // )
    End        // EOF sentinel
};

struct Token
{
    TokenType          type {};
    std::string        lexeme;
    std::string_view   span;   // Reference into input for diagnostics
};

class Lexer
{
public:
    explicit Lexer(std::string_view source) : _src{source}, _p{_src.begin()} {}

    Token next()
    {
        skipSpace();

        if (_p == _src.end()) return {TokenType::End, {}, {}};

        char c = *_p;
        if (c == '(')
        {
            ++_p;
            return {TokenType::LParen, "(", {_p - 1, 1}};
        }
        if (c == ')')
        {
            ++_p;
            return {TokenType::RParen, ")", {_p - 1, 1}};
        }
        if (c == '"')
        {
            return lexPhrase();
        }
        if (std::isalnum(static_cast<unsigned char>(c)) || c == '_' || c == '-')
        {
            return lexWordOrKeyword();
        }

        throw std::runtime_error("Unexpected character in search string");
    }

private:
    std::string_view _src;
    std::string_view::const_iterator _p;

    void skipSpace()
    {
        while (_p != _src.end() && std::isspace(static_cast<unsigned char>(*_p)))
            ++_p;
    }

    Token lexPhrase()
    {
        auto start = _p; // points at the opening quote
        ++_p;            // consume "
        std::string value;
        while (_p != _src.end())
        {
            char c = *_p++;
            if (c == '"')
            {
                return {TokenType::Phrase, std::move(value),
                        {start, static_cast<std::size_t>(_p - start)}};
            }
            value += c;
        }
        throw std::runtime_error("Unterminated quoted phrase in search string");
    }

    Token lexWordOrKeyword()
    {
        auto start = _p;
        std::string value;
        while (_p != _src.end() &&
               (std::isalnum(static_cast<unsigned char>(*_p)) || *_p == '_' ||
                *_p == '-'))
        {
            value += *_p++;
        }

        std::string valueUpper;
        valueUpper.resize(value.size());
        std::transform(value.begin(), value.end(), valueUpper.begin(),
                       [](char ch) { return std::toupper(static_cast<unsigned char>(ch)); });

        if (valueUpper == "AND")
            return {TokenType::And, value, {start, static_cast<std::size_t>(_p - start)}};
        if (valueUpper == "OR")
            return {TokenType::Or, value, {start, static_cast<std::size_t>(_p - start)}};
        if (valueUpper == "NOT")
            return {TokenType::Not, value, {start, static_cast<std::size_t>(_p - start)}};

        return {TokenType::Word, value, {start, static_cast<std::size_t>(_p - start)}};
    }
};

//------------------------------------------------------- AST --------------//
enum class NodeKind
{
    Term,   // leaf node
    And,
    Or,
    Not
};

struct ASTNode
{
    NodeKind                            kind {};
    std::string                         term;      // Only for Term
    std::vector<std::shared_ptr<ASTNode>> children;
};

//-------------------------------------------------- Recursive-descent -----//
class Parser
{
public:
    explicit Parser(std::string_view input) : _lex{input}, _curr{_lex.next()} {}

    std::shared_ptr<ASTNode> parse()
    {
        auto expr = parseExpr();
        expect(TokenType::End);
        return expr;
    }

private:
    Lexer _lex;
    Token _curr;

    void advance() { _curr = _lex.next(); }

    bool match(TokenType t)
    {
        if (_curr.type == t)
        {
            advance();
            return true;
        }
        return false;
    }

    void expect(TokenType t)
    {
        if (_curr.type != t)
            throw std::runtime_error("Syntax error in search string");
    }

    std::shared_ptr<ASTNode> parseExpr()        // OR precedence (lowest)
    {
        auto node = parseTerm();
        while (match(TokenType::Or))
        {
            auto rhs = parseTerm();
            node = makeNode(NodeKind::Or, {}, {node, rhs});
        }
        return node;
    }

    std::shared_ptr<ASTNode> parseTerm()        // AND precedence
    {
        auto node = parseFactor();
        while (match(TokenType::And))
        {
            auto rhs = parseFactor();
            node = makeNode(NodeKind::And, {}, {node, rhs});
        }
        return node;
    }

    std::shared_ptr<ASTNode> parseFactor()      // NOT precedence
    {
        if (match(TokenType::Not))
        {
            auto operand = parseFactor();
            return makeNode(NodeKind::Not, {}, {operand});
        }
        return parsePrimary();
    }

    std::shared_ptr<ASTNode> parsePrimary()
    {
        if (match(TokenType::LParen))
        {
            auto node = parseExpr();
            expect(TokenType::RParen);
            advance();
            return node;
        }

        if (_curr.type == TokenType::Word || _curr.type == TokenType::Phrase)
        {
            std::string term = _curr.lexeme;
            advance();
            return makeNode(NodeKind::Term, std::move(term), {});
        }

        throw std::runtime_error("Unexpected token in search string");
    }

    static std::shared_ptr<ASTNode>
    makeNode(NodeKind k, std::string value, std::vector<std::shared_ptr<ASTNode>> children)
    {
        auto node      = std::make_shared<ASTNode>();
        node->kind     = k;
        node->term     = std::move(value);
        node->children = std::move(children);
        return node;
    }
};

//-------------------------------------------------- SQL Compilation ------//

class SqlCompiler
{
public:
    std::pair<std::string, std::vector<std::string>>
    compile(const std::shared_ptr<ASTNode>& root, SqlDialect dialect)
    {
        _dialect = dialect;
        std::string where = visit(root);
        return {where.empty() ? "TRUE" : where, _params};
    }

private:
    SqlDialect               _dialect {SqlDialect::PostgreSQL};
    std::vector<std::string> _params;

    static std::string ilikeOperator(SqlDialect d)
    {
        // PostgreSQL has true ILIKE; MariaDB uses LIKE with COLLATE
        return (d == SqlDialect::PostgreSQL) ? "ILIKE" : "LIKE";
    }

    std::string visit(const std::shared_ptr<ASTNode>& node)
    {
        switch (node->kind)
        {
            case NodeKind::Term: return visitTerm(node->term);
            case NodeKind::And:
                return "(" + visit(node->children.at(0)) + " AND " +
                       visit(node->children.at(1)) + ")";
            case NodeKind::Or:
                return "(" + visit(node->children.at(0)) + " OR " +
                       visit(node->children.at(1)) + ")";
            case NodeKind::Not:
                return "(NOT " + visit(node->children.at(0)) + ")";
        }
        return {};
    }

    std::string visitTerm(const std::string& term)
    {
        const std::string wild = '%' + term + '%';
        _params.emplace_back(wild);
        _params.emplace_back(wild);

        std::string sql;
        if (_dialect == SqlDialect::PostgreSQL)
        {
            sql = "(title " + ilikeOperator(_dialect) + " ? "  // param n
                  " OR body " + ilikeOperator(_dialect) + " ?)"; // param n+1
        }
        else
        {
            // MariaDB: Use UTF8MB4, case-insensitive collation via COLLATE
            sql = "(title " + ilikeOperator(_dialect) + " ? COLLATE utf8mb4_general_ci"
                  " OR body " + ilikeOperator(_dialect) +
                  " ? COLLATE utf8mb4_general_ci)";
        }
        return sql;
    }
};

} // namespace impl

//----------------------------------------------------------------------------
//  SearchQuery::Impl – PIMPL storage of the AST
//----------------------------------------------------------------------------
struct SearchQuery::Impl
{
    explicit Impl(std::shared_ptr<impl::ASTNode> ast) : _ast(std::move(ast)) {}
    std::shared_ptr<impl::ASTNode> _ast;
};

//----------------------------------------------------------------------------
//  Public API implementation
//----------------------------------------------------------------------------
SearchQuery SearchQuery::parse(std::string_view input)
{
    impl::Parser parser{input};
    auto         ast = parser.parse();
    return SearchQuery{std::make_shared<Impl>(std::move(ast))};
}

std::pair<std::string, std::vector<std::string>>
SearchQuery::compile(SqlDialect dialect) const
{
    impl::SqlCompiler compiler;
    return compiler.compile(_impl->_ast, dialect);
}

} // namespace blog::search
```