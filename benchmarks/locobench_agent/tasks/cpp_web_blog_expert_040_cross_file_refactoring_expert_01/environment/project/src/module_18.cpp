```cpp
/*
 *  IntraLedger BlogSuite – Search Query Parser
 *
 *  File:        src/module_18.cpp
 *  Author:      IntraLedger Core Team
 *  Description: Implements a boolean-aware, phrase-capable search query parser
 *               that folds to a parametrized SQL WHERE fragment consumable
 *               by the Repository/ORM layer.  The parser recognises:
 *
 *                 • Logical AND, OR, NOT   (case-insensitive, symbolic &&, ||, !)
 *                 • Parenthesis for precedence grouping
 *                 • Double-quoted phrases
 *                 • Plain words with automatic wildcard suffix
 *
 *               The output is safe for prepared statements; parameters are
 *               emitted separately to avoid SQL-injection.
 *
 *  Copyright © 2024 IntraLedger
 */

#include <algorithm>
#include <cctype>
#include <memory>
#include <optional>
#include <sstream>
#include <stdexcept>
#include <string>
#include <string_view>
#include <unordered_set>
#include <utility>
#include <vector>

namespace intraledger::search
{

// -------------------------------------------------
// Utilities
// -------------------------------------------------

namespace detail
{
inline std::string to_lower(std::string_view sv)
{
    std::string out;
    out.reserve(sv.size());
    std::transform(sv.begin(), sv.end(), std::back_inserter(out),
                   [](unsigned char ch) { return static_cast<char>(std::tolower(ch)); });
    return out;
}

inline bool iequals(std::string_view a, std::string_view b)
{
    return to_lower(a) == to_lower(b);
}

} // namespace detail

// -------------------------------------------------
// Tokenizer
// -------------------------------------------------

enum class TokenType
{
    Word,
    Phrase,
    And,
    Or,
    Not,
    LParen,
    RParen,
    End,
};

struct Token
{
    TokenType            type;
    std::string          lexeme;
};

class Tokenizer
{
public:
    explicit Tokenizer(std::string_view q) : _query(q), _pos(0) {}

    Token next_token()
    {
        consume_ws();

        if (_pos >= _query.size())
            return {TokenType::End, ""};

        char c = _query[_pos];

        // Parenthesis
        if (c == '(')
        {
            ++_pos;
            return {TokenType::LParen, "("};
        }
        if (c == ')')
        {
            ++_pos;
            return {TokenType::RParen, ")"};
        }

        // Symbolic operators
        if (c == '&' && peek(1) == '&')
        {
            _pos += 2;
            return {TokenType::And, "&&"};
        }
        if (c == '|' && peek(1) == '|')
        {
            _pos += 2;
            return {TokenType::Or, "||"};
        }
        if (c == '!')
        {
            ++_pos;
            return {TokenType::Not, "!"};
        }

        // Quoted phrase
        if (c == '"')
        {
            ++_pos;
            std::size_t start = _pos;
            while (_pos < _query.size() && _query[_pos] != '"')
            {
                if (_query[_pos] == '\\' && _pos + 1 < _query.size())
                    _pos += 2; // Skip escaped char
                else
                    ++_pos;
            }

            if (_pos >= _query.size())
                throw std::runtime_error("Unterminated quote in search query");

            std::string phrase;
            phrase.reserve(_pos - start);
            for (std::size_t i = start; i < _pos; ++i)
            {
                char ch = _query[i];
                if (ch == '\\' && i + 1 < _pos)
                {
                    phrase.push_back(_query[i + 1]);
                    ++i;
                }
                else
                {
                    phrase.push_back(ch);
                }
            }

            ++_pos; // Skip closing quote
            return {TokenType::Phrase, phrase};
        }

        // Word or textual operator
        std::size_t start = _pos;
        while (_pos < _query.size() && is_word_char(_query[_pos]))
            ++_pos;

        if (start == _pos)
            throw std::runtime_error("Unexpected character in search query");

        std::string word(_query.substr(start, _pos - start));

        // Check textual operators (AND/OR/NOT)
        if (detail::iequals(word, "AND"))
            return {TokenType::And, word};
        if (detail::iequals(word, "OR"))
            return {TokenType::Or, word};
        if (detail::iequals(word, "NOT"))
            return {TokenType::Not, word};

        return {TokenType::Word, std::move(word)};
    }

private:
    static bool is_word_char(char c)
    {
        return std::isalnum(static_cast<unsigned char>(c)) || c == '_' || c == '-';
    }

    char peek(std::size_t offset) const
    {
        if (_pos + offset >= _query.size())
            return '\0';
        return _query[_pos + offset];
    }

    void consume_ws()
    {
        while (_pos < _query.size() && std::isspace(static_cast<unsigned char>(_query[_pos])))
            ++_pos;
    }

    std::string_view _query;
    std::size_t      _pos;
};

// -------------------------------------------------
// AST
// -------------------------------------------------

struct Node
{
    virtual ~Node() = default;
};

using NodePtr = std::unique_ptr<Node>;

struct WordNode final : Node
{
    explicit WordNode(std::string w) : word(std::move(w)) {}
    std::string word;
};

struct PhraseNode final : Node
{
    explicit PhraseNode(std::string p) : phrase(std::move(p)) {}
    std::string phrase;
};

struct UnaryNode : Node
{
    explicit UnaryNode(NodePtr c) : child(std::move(c)) {}
    NodePtr child;
};

struct BinaryNode : Node
{
    BinaryNode(NodePtr l, NodePtr r) : left(std::move(l)), right(std::move(r)) {}
    NodePtr left;
    NodePtr right;
};

struct AndNode final : BinaryNode
{
    using BinaryNode::BinaryNode;
};

struct OrNode final : BinaryNode
{
    using BinaryNode::BinaryNode;
};

struct NotNode final : UnaryNode
{
    using UnaryNode::UnaryNode;
};

// -------------------------------------------------
// Parser (Recursive Descent LL(1))
// -------------------------------------------------

class Parser
{
public:
    explicit Parser(Tokenizer tz) : _tz(std::move(tz)), _curr(_tz.next_token()) {}

    NodePtr parse()
    {
        auto expr = parse_or();
        if (_curr.type != TokenType::End)
            throw std::runtime_error("Unexpected token after end of expression");
        return expr;
    }

private:
    // OR  → AND ( (OR) AND )*
    NodePtr parse_or()
    {
        NodePtr node = parse_and();
        while (_curr.type == TokenType::Or)
        {
            consume(TokenType::Or);
            NodePtr rhs = parse_and();
            node         = std::make_unique<OrNode>(std::move(node), std::move(rhs));
        }
        return node;
    }

    // AND → UNARY ( (AND) UNARY )*
    NodePtr parse_and()
    {
        NodePtr node = parse_unary();
        while (_curr.type == TokenType::And ||
               _curr.type == TokenType::Word ||
               _curr.type == TokenType::Phrase ||
               _curr.type == TokenType::LParen ||
               _curr.type == TokenType::Not)
        {
            // Implicit AND if next token starts another term
            if (_curr.type == TokenType::And)
                consume(TokenType::And);
            NodePtr rhs = parse_unary();
            node         = std::make_unique<AndNode>(std::move(node), std::move(rhs));
        }
        return node;
    }

    // UNARY → NOT UNARY | PRIMARY
    NodePtr parse_unary()
    {
        if (_curr.type == TokenType::Not)
        {
            consume(TokenType::Not);
            NodePtr operand = parse_unary();
            return std::make_unique<NotNode>(std::move(operand));
        }
        return parse_primary();
    }

    // PRIMARY → WORD | PHRASE | '(' OR ')'
    NodePtr parse_primary()
    {
        switch (_curr.type)
        {
        case TokenType::Word:
        {
            std::string w = _curr.lexeme;
            consume(TokenType::Word);
            return std::make_unique<WordNode>(std::move(w));
        }
        case TokenType::Phrase:
        {
            std::string p = _curr.lexeme;
            consume(TokenType::Phrase);
            return std::make_unique<PhraseNode>(std::move(p));
        }
        case TokenType::LParen:
        {
            consume(TokenType::LParen);
            NodePtr node = parse_or();
            consume(TokenType::RParen);
            return node;
        }
        default:
            throw std::runtime_error("Unexpected token in primary expression");
        }
    }

    void consume(TokenType expected)
    {
        if (_curr.type != expected)
            throw std::runtime_error("Unexpected token while parsing search query");
        _curr = _tz.next_token();
    }

    Tokenizer _tz;
    Token     _curr;
};

// -------------------------------------------------
// SQL Generator (simple visitor)
// -------------------------------------------------

class SqlEmitter
{
public:
    struct Result
    {
        std::string              where_fragment;
        std::vector<std::string> parameters;
    };

    static Result generate(const NodePtr& root, const std::string& column)
    {
        SqlEmitter emitter(column);
        emitter.visit(root.get());
        return {std::move(emitter._buffer), std::move(emitter._params)};
    }

private:
    explicit SqlEmitter(std::string col) : _column(std::move(col)) {}

    void visit(const Node* n)
    {
        if (dynamic_cast<const WordNode*>(n))
            visit_word(static_cast<const WordNode*>(n));
        else if (dynamic_cast<const PhraseNode*>(n))
            visit_phrase(static_cast<const PhraseNode*>(n));
        else if (dynamic_cast<const AndNode*>(n))
            visit_and(static_cast<const AndNode*>(n));
        else if (dynamic_cast<const OrNode*>(n))
            visit_or(static_cast<const OrNode*>(n));
        else if (dynamic_cast<const NotNode*>(n))
            visit_not(static_cast<const NotNode*>(n));
        else
            throw std::runtime_error("Unknown node type in SQL emitter");
    }

    void visit_word(const WordNode* node)
    {
        append_condition("ILIKE");
        _params.push_back('%' + node->word + '%');
    }

    void visit_phrase(const PhraseNode* node)
    {
        append_condition("ILIKE");
        _params.push_back('%' + node->phrase + '%');
    }

    void visit_not(const NotNode* node)
    {
        _buffer += "NOT (";
        visit(node->child.get());
        _buffer += ")";
    }

    void visit_and(const AndNode* node)
    {
        _buffer += "(";
        visit(node->left.get());
        _buffer += " AND ";
        visit(node->right.get());
        _buffer += ")";
    }

    void visit_or(const OrNode* node)
    {
        _buffer += "(";
        visit(node->left.get());
        _buffer += " OR ";
        visit(node->right.get());
        _buffer += ")";
    }

    void append_condition(const char* comparator)
    {
        _buffer += _column;
        _buffer += ' ';
        _buffer += comparator;
        _buffer += " ?";
    }

    std::string              _column;
    std::string              _buffer;
    std::vector<std::string> _params;
};

// -------------------------------------------------
// Public Facade
// -------------------------------------------------

class ParsedQuery
{
public:
    ParsedQuery(std::string  where,
                std::vector<std::string> params)
        : _where(std::move(where)),
          _params(std::move(params))
    {}

    const std::string& where_clause() const noexcept { return _where; }
    const std::vector<std::string>& params() const noexcept { return _params; }

private:
    std::string              _where;
    std::vector<std::string> _params;
};

class QueryParser
{
public:
    ParsedQuery compile(std::string_view raw_query,
                        const std::string& target_column = "content")
    {
        if (raw_query.empty())
            throw std::invalid_argument("Search query may not be empty");

        Tokenizer tokenizer(raw_query);
        Parser    parser(std::move(tokenizer));
        NodePtr   root = parser.parse();

        auto result = SqlEmitter::generate(root, target_column);

        if (result.where_fragment.empty())
            result.where_fragment = "TRUE"; // Match all (should not occur)

        return ParsedQuery{std::move(result.where_fragment),
                           std::move(result.parameters)};
    }
};

// -------------------------------------------------
// Convenience – Highlighting Helper
// -------------------------------------------------

std::string highlight_terms(std::string_view text,
                            const std::vector<std::string>& terms,
                            std::string_view open_tag = "<mark>",
                            std::string_view close_tag = "</mark>")
{
    if (terms.empty())
        return std::string(text);

    // Build lowercase copy of the text for case-insensitive search
    std::string lowered = detail::to_lower(text);
    std::string result;
    result.reserve(text.size() + 16 * terms.size());

    std::size_t pos = 0;
    while (pos < text.size())
    {
        std::size_t nearest = std::string::npos;
        std::size_t term_idx = 0;

        for (std::size_t i = 0; i < terms.size(); ++i)
        {
            std::string term_lower = detail::to_lower(terms[i]);
            std::size_t p          = lowered.find(term_lower, pos);
            if (p != std::string::npos && (nearest == std::string::npos || p < nearest))
            {
                nearest  = p;
                term_idx = i;
            }
        }

        if (nearest == std::string::npos)
        {
            result.append(text.substr(pos));
            break;
        }

        result.append(text.substr(pos, nearest - pos));
        result.append(open_tag);
        result.append(text.substr(nearest, terms[term_idx].size()));
        result.append(close_tag);

        pos = nearest + terms[term_idx].size();
    }

    return result;
}

// -------------------------------------------------
// Unit-Test-Like Self-Check (disabled for production build)
// -------------------------------------------------
#ifdef INTRALEDGER_QUERY_PARSER_SELFTEST
#include <iostream>

void selftest()
{
    QueryParser qp;
    const std::string q = R"(open-source AND ( "zero cost" OR NOT licensing ) )";

    try
    {
        auto parsed = qp.compile(q, "title");

        std::cout << "WHERE: " << parsed.where_clause() << "\n";
        std::cout << "PARAMS:\n";
        for (auto& p : parsed.params())
            std::cout << "  - " << p << "\n";
    }
    catch (const std::exception& ex)
    {
        std::cerr << "Error: " << ex.what() << '\n';
    }
}

int main()
{
    selftest();
    return 0;
}
#endif

} // namespace intraledger::search
```