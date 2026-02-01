#include <algorithm>
#include <cctype>
#include <exception>
#include <memory>
#include <sstream>
#include <stdexcept>
#include <string>
#include <string_view>
#include <utility>
#include <vector>

//
//  IntraLedger BlogSuite
//  src/module_57.cpp
//
//  Search Query Parser & Translator
//
//  This module parses a mini-DSL used in the global search bar
//  and converts it into a parameterised SQL fragment that can
//  be fed into the platform’s internal ORM.
//
//  Grammar (EBNF):
//      expr        := or_expr
//      or_expr     := and_expr ( "OR" and_expr )*
//      and_expr    := not_expr ( "AND" not_expr )*
//      not_expr    := "NOT"* primary
//      primary     := TERM
//                   | PHRASE
//                   | field_spec
//                   | "(" expr ")"
//      field_spec  := IDENT ":" ( TERM | PHRASE )
//
//  Examples:
//      marketing AND (newsletter OR "press release")
//      author:alice NOT draft
//
//  NOTE: This translation layer intentionally limits the DSL
//        to prevent SQL injection (all values become bind
//        parameters) and to guarantee index utilisation.
//

namespace intraledger::search {

//
// Helpers & forward declarations
// -------------------------------------------------------------

struct SqlQuery; // forward

// Custom exception used for both lexical and syntactic errors.
class QueryError : public std::runtime_error {
public:
    using std::runtime_error::runtime_error;
};

//----------------------------------------------------------------
// Lexer
//----------------------------------------------------------------
enum class TokenKind {
    Word,       // bare word
    Phrase,     // "quoted phrase"
    And,
    Or,
    Not,
    LParen,
    RParen,
    Colon,
    End
};

struct Token {
    TokenKind kind{};
    std::string text; // raw text (unescaped)

    Token() = default;
    Token(TokenKind k, std::string t = {}) : kind(k), text(std::move(t)) {}
};

class Lexer {
public:
    explicit Lexer(std::string_view src) : _src(src) { consume(); }

    // Return current token
    const Token& current() const { return _current; }

    // Advance to next token
    void next() { consume(); }

private:
    std::string_view _src;
    size_t           _pos{0};
    Token            _current;

    static bool is_word_char(char c) {
        return std::isalnum(static_cast<unsigned char>(c)) || c == '_' || c == '-';
    }

    void skip_ws() {
        while (_pos < _src.size() && std::isspace(static_cast<unsigned char>(_src[_pos]))) { ++_pos; }
    }

    void consume() {
        skip_ws();
        if (_pos >= _src.size()) {
            _current = { TokenKind::End };
            return;
        }

        char ch = _src[_pos];
        switch (ch) {
            case '(':
                ++_pos;
                _current = { TokenKind::LParen };
                break;
            case ')':
                ++_pos;
                _current = { TokenKind::RParen };
                break;
            case ':':
                ++_pos;
                _current = { TokenKind::Colon };
                break;
            case '"':
                lex_phrase();
                break;
            default:
                if (is_word_char(ch)) {
                    lex_word();
                } else {
                    throw QueryError{ "Unexpected character in search query: " + std::string{1, ch} };
                }
        }
    }

    void lex_word() {
        size_t start = _pos;
        while (_pos < _src.size() && is_word_char(_src[_pos])) { ++_pos; }

        std::string word{ _src.substr(start, _pos - start) };

        // Convert to upper to detect logical keywords
        std::string upper(word);
        std::transform(upper.begin(), upper.end(), upper.begin(), [](unsigned char c) { return std::toupper(c); });

        if (upper == "AND")
            _current = { TokenKind::And };
        else if (upper == "OR")
            _current = { TokenKind::Or };
        else if (upper == "NOT")
            _current = { TokenKind::Not };
        else
            _current = { TokenKind::Word, std::move(word) };
    }

    void lex_phrase() {
        ++_pos; // eat initial quote
        size_t start = _pos;

        while (_pos < _src.size() && _src[_pos] != '"') {
            // simple; does not support escapes
            ++_pos;
        }

        if (_pos >= _src.size())
            throw QueryError{ "Unterminated quoted phrase in search query" };

        std::string phrase{ _src.substr(start, _pos - start) };
        ++_pos; // eat closing quote

        _current = { TokenKind::Phrase, std::move(phrase) };
    }
};

//----------------------------------------------------------------
// AST
//----------------------------------------------------------------
struct Node {
    virtual ~Node() = default;
    virtual void   to_sql(SqlQuery& out) const = 0;
};

using NodePtr = std::unique_ptr<Node>;

// Terminal nodes ------------------------------------------------
struct TermNode final : Node {
    std::string value;
    explicit TermNode(std::string v) : value(std::move(v)) {}
    void to_sql(SqlQuery& out) const override;
};

struct PhraseNode final : Node {
    std::string value; // raw text without quotes
    explicit PhraseNode(std::string v) : value(std::move(v)) {}
    void to_sql(SqlQuery& out) const override;
};

struct FieldNode final : Node {
    std::string field; // column/field name
    NodePtr     rhs;   // either TermNode or PhraseNode
    FieldNode(std::string f, NodePtr n) : field(std::move(f)), rhs(std::move(n)) {}

    void to_sql(SqlQuery& out) const override;
};

// Composite nodes ----------------------------------------------
//  NOT unary
struct NotNode final : Node {
    NodePtr child;
    explicit NotNode(NodePtr n) : child(std::move(n)) {}
    void to_sql(SqlQuery& out) const override;
};

//  AND / OR binary (variadic for convenience)
enum class LogicalKind { And, Or };

struct LogicalNode final : Node {
    LogicalKind             kind;
    std::vector<NodePtr>    children;

    LogicalNode(LogicalKind k, std::vector<NodePtr> c) : kind(k), children(std::move(c)) {}

    void to_sql(SqlQuery& out) const override;
};

//----------------------------------------------------------------
// SqlQuery – simple helper to build parameterised WHERE clauses
//----------------------------------------------------------------
struct SqlQuery {
    std::ostringstream text;
    std::vector<std::string> params;

    // Returns PostgreSQL-style placeholder: $n
    std::string add_param(std::string v) {
        params.emplace_back(std::move(v));
        text << '$' << params.size();
        return params.back();
    }
};

//----------------------------------------------------------------
// Parser
//----------------------------------------------------------------
class Parser {
public:
    explicit Parser(Lexer lex) : _lex(std::move(lex)) {}

    NodePtr parse() {
        auto root = parse_or();
        if (_lex.current().kind != TokenKind::End)
            throw QueryError{ "Unexpected token after end of expression" };
        return root;
    }

private:
    Lexer _lex;

    // expr -> or_expr
    NodePtr parse_or() {
        std::vector<NodePtr> terms;
        terms.push_back(parse_and());

        while (_lex.current().kind == TokenKind::Or) {
            _lex.next(); // consume 'OR'
            terms.push_back(parse_and());
        }

        if (terms.size() == 1)
            return std::move(terms.front());
        return std::make_unique<LogicalNode>(LogicalKind::Or, std::move(terms));
    }

    // and_expr
    NodePtr parse_and() {
        std::vector<NodePtr> factors;
        factors.push_back(parse_not());

        while (_lex.current().kind == TokenKind::And) {
            _lex.next(); // consume 'AND'
            factors.push_back(parse_not());
        }

        // Implicit AND (whitespace) support
        while (is_primary_start(_lex.current().kind)) {
            factors.push_back(parse_not());
        }

        if (factors.size() == 1)
            return std::move(factors.front());
        return std::make_unique<LogicalNode>(LogicalKind::And, std::move(factors));
    }

    // not_expr
    NodePtr parse_not() {
        bool is_not = false;
        while (_lex.current().kind == TokenKind::Not) {
            is_not = !is_not; // double NOT cancels
            _lex.next();
        }
        auto node = parse_primary();
        if (is_not)
            return std::make_unique<NotNode>(std::move(node));
        return node;
    }

    // primary
    NodePtr parse_primary() {
        auto tok = _lex.current();

        switch (tok.kind) {
            case TokenKind::Word: {
                // Might be a field spec if next token is colon
                _lex.next();
                if (_lex.current().kind == TokenKind::Colon) {
                    std::string field = tok.text;
                    _lex.next(); // consume ':'
                    auto rhs_tok = _lex.current();
                    if (rhs_tok.kind != TokenKind::Word && rhs_tok.kind != TokenKind::Phrase)
                        throw QueryError{ "Expected term or phrase after field ':'" };

                    NodePtr rhs;
                    if (rhs_tok.kind == TokenKind::Word) {
                        rhs = std::make_unique<TermNode>(rhs_tok.text);
                    } else {
                        rhs = std::make_unique<PhraseNode>(rhs_tok.text);
                    }
                    _lex.next();
                    return std::make_unique<FieldNode>(std::move(field), std::move(rhs));
                } else {
                    return std::make_unique<TermNode>(tok.text);
                }
            }
            case TokenKind::Phrase:
                _lex.next();
                return std::make_unique<PhraseNode>(tok.text);

            case TokenKind::LParen: {
                _lex.next(); // consume '('
                auto node = parse_or();
                if (_lex.current().kind != TokenKind::RParen)
                    throw QueryError{ "Expected ')' in search query" };
                _lex.next(); // consume ')'
                return node;
            }

            default:
                throw QueryError{ "Unexpected token in search query primary" };
        }
    }

    static bool is_primary_start(TokenKind k) {
        return k == TokenKind::Word || k == TokenKind::Phrase || k == TokenKind::LParen || k == TokenKind::Not;
    }
};

//----------------------------------------------------------------
// SQL Generation
//----------------------------------------------------------------
namespace {

std::string escape_like(std::string_view in) {
    std::string out;
    out.reserve(in.size());
    for (char c : in) {
        if (c == '%' || c == '_' || c == '\\')
            out.push_back('\\');
        out.push_back(c);
    }
    return out;
}

// Build a LIKE expression for a given column.
void build_like(SqlQuery& q, std::string_view column, std::string_view value) {
    q.text << '(' << column << " ILIKE ";
    q.add_param('%' + escape_like(value) + '%');
    q.text << ')';
}

} // anonymous namespace

// TermNode ------------------------------------------------------
void TermNode::to_sql(SqlQuery& out) const {
    build_like(out, "body", value); // default column
}

// PhraseNode ----------------------------------------------------
void PhraseNode::to_sql(SqlQuery& out) const {
    build_like(out, "body", value);
}

// FieldNode -----------------------------------------------------
void FieldNode::to_sql(SqlQuery& out) const {
    static const std::vector<std::string> allowed_fields = { "title", "body", "author", "tags" };

    // Basic whitelist
    auto it = std::find(allowed_fields.begin(), allowed_fields.end(), field);
    if (it == allowed_fields.end())
        throw QueryError{ "Unknown searchable field: " + field };

    if (!rhs)
        throw QueryError{ "Missing RHS for field node" };

    // Replace column in RHS translation
    struct LocalTranslator : public Node {
        const std::string& col;
        const Node&        node;

        explicit LocalTranslator(const std::string& c, const Node& n) : col(c), node(n) {}
        void to_sql(SqlQuery& out) const override {
            // Use Node's behavior but override default column via ad-hoc cast
            // Not polymorphic; call build_like directly for simplicity.
            if (auto term = dynamic_cast<const TermNode*>(&node)) {
                build_like(out, col, term->value);
            } else if (auto phrase = dynamic_cast<const PhraseNode*>(&node)) {
                build_like(out, col, phrase->value);
            } else {
                throw QueryError{ "Invalid node type for field-specific search" };
            }
        }
    };

    LocalTranslator t{ field, *rhs };
    t.to_sql(out);
}

// NotNode -------------------------------------------------------
void NotNode::to_sql(SqlQuery& out) const {
    out.text << "NOT (";
    child->to_sql(out);
    out.text << ')';
}

// LogicalNode ---------------------------------------------------
void LogicalNode::to_sql(SqlQuery& out) const {
    const char* op = (kind == LogicalKind::And) ? " AND " : " OR ";

    out.text << '(';
    for (size_t i = 0; i < children.size(); ++i) {
        if (i != 0)
            out.text << op;
        children[i]->to_sql(out);
    }
    out.text << ')';
}

//----------------------------------------------------------------
// Public API
//----------------------------------------------------------------

SqlQuery compile_search_query(std::string_view input) {
    Lexer  lexer(input);
    Parser parser(std::move(lexer));

    auto ast = parser.parse();

    SqlQuery query;
    ast->to_sql(query);
    return query;
}

} // namespace intraledger::search

//
//  --- Example usage (inside service layer) ----------------------
//
//  try {
//      auto sql = intraledger::search::compile_search_query(request.query());
//      orm->where(sql.text.str(), sql.params);
//  } catch (const intraledger::search::QueryError& ex) {
//      // Gracefully degrade to basic search or return 400
//  }
//

// End of module_57.cpp