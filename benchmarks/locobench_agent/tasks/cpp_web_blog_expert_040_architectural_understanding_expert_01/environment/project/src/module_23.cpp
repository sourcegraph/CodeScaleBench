#include <algorithm>
#include <chrono>
#include <cctype>
#include <exception>
#include <future>
#include <iomanip>
#include <iostream>
#include <list>
#include <memory>
#include <mutex>
#include <optional>
#include <regex>
#include <shared_mutex>
#include <sstream>
#include <string>
#include <unordered_map>
#include <utility>
#include <vector>

/**
 * src/module_23.cpp
 *
 * Portion of IntraLedger BlogSuite (web_blog)
 * ------------------------------------------------
 * Search subsystem: A minimal, self-contained Boolean query parser and executor
 * featuring an in-process LRU cache and asynchronous execution support.
 *
 * NOTE: In production the DocumentRepository would be implemented by the ORM
 * layer (MariaDB / PostgreSQL).  Here we provide an in-memory stub for demo
 * purposes while keeping all public interfaces intact.
 */

namespace blog::search {

// -----------------------------------------------------------------------------
// Utility helpers
// -----------------------------------------------------------------------------

namespace util {

inline std::string to_lower(std::string str) {
    std::transform(str.begin(), str.end(), str.begin(),
                   [](unsigned char c) { return static_cast<char>(std::tolower(c)); });
    return str;
}

inline std::vector<std::string> split_ws(const std::string& text) {
    std::vector<std::string> out;
    std::stringstream ss(text);
    std::string token;
    while (ss >> token) {
        out.emplace_back(token);
    }
    return out;
}

template <typename Clock = std::chrono::steady_clock>
inline std::string format_duration(typename Clock::duration d) {
    auto ms = std::chrono::duration_cast<std::chrono::milliseconds>(d).count();
    std::ostringstream oss;
    oss << ms << " ms";
    return oss.str();
}

}  // namespace util

// -----------------------------------------------------------------------------
// Data Models
// -----------------------------------------------------------------------------

struct Document {
    std::uint64_t id{};
    std::string   title;
    std::string   content;
    std::string   locale = "en";
    std::chrono::system_clock::time_point published_at{};
};

using DocumentList = std::vector<Document>;

// -----------------------------------------------------------------------------
// Search Request / Response DTOs
// -----------------------------------------------------------------------------

struct SearchRequest {
    std::string query;    // Raw user search string
    std::string locale;   // Optional locale filter (e.g., "en", "de"), empty = all
    std::size_t offset  = 0;
    std::size_t limit   = 10;
};

struct SearchResponse {
    DocumentList                       hits;
    std::size_t                        total_hits  = 0;
    std::chrono::milliseconds          took        = std::chrono::milliseconds{0};
};

// -----------------------------------------------------------------------------
// Exceptions
// -----------------------------------------------------------------------------

struct ParseError : public std::runtime_error {
    explicit ParseError(const std::string& msg) : std::runtime_error(msg) {}
};

// -----------------------------------------------------------------------------
// Boolean Query AST
// -----------------------------------------------------------------------------

enum class NodeType { TERM, PHRASE, AND, OR, NOT };

struct QueryNode {
    NodeType                            type;
    std::string                         term;        // used if TERM / PHRASE
    std::vector<std::unique_ptr<QueryNode>> children;

    explicit QueryNode(NodeType t, std::string term_ = {})
        : type(t), term(std::move(term_)) {}

    static std::unique_ptr<QueryNode> make(NodeType t,
                                           std::vector<std::unique_ptr<QueryNode>> ch = {}) {
        auto ptr = std::make_unique<QueryNode>(t);
        ptr->children = std::move(ch);
        return ptr;
    }
};

// -----------------------------------------------------------------------------
// Repository Interface
// -----------------------------------------------------------------------------

class DocumentRepository {
public:
    virtual ~DocumentRepository() = default;
    virtual DocumentList fetch_all() const = 0;
};

// Minimal in-memory stub repository
class StubDocumentRepository : public DocumentRepository {
public:
    explicit StubDocumentRepository(DocumentList docs) : docs_(std::move(docs)) {}
    DocumentList fetch_all() const override { return docs_; }

private:
    DocumentList docs_;
};

// -----------------------------------------------------------------------------
// LRU Cache (thread-safe)
// -----------------------------------------------------------------------------

template <typename Key, typename Value, std::size_t Capacity = 128>
class LruCache {
public:
    bool get(const Key& k, Value& out_value) {
        std::shared_lock lock(mu_);
        auto it = map_.find(k);
        if (it == map_.end()) return false;
        // Move touched item to front
        {
            std::unique_lock ulock(mu_, std::adopt_lock);
            list_.splice(list_.begin(), list_, it->second);
        }
        out_value = it->second->second;
        return true;
    }

    void put(const Key& k, Value v) {
        std::unique_lock lock(mu_);
        auto it = map_.find(k);
        if (it != map_.end()) {
            it->second->second = std::move(v);
            list_.splice(list_.begin(), list_, it->second);
            return;
        }
        if (list_.size() >= Capacity) {
            auto last = list_.end();
            --last;
            map_.erase(last->first);
            list_.pop_back();
        }
        list_.emplace_front(k, std::move(v));
        map_[k] = list_.begin();
    }

private:
    mutable std::shared_mutex
        mu_;  // allows concurrent reads while writes are unique
    std::list<std::pair<Key, Value>> list_;
    std::unordered_map<Key, typename std::list<std::pair<Key, Value>>::iterator> map_;
};

// -----------------------------------------------------------------------------
// Query Parser
// -----------------------------------------------------------------------------

class QueryParser {
public:
    explicit QueryParser(std::string q)
        : input_(std::move(q)), pos_(0) {
        tokenize();
    }

    std::unique_ptr<QueryNode> parse() {
        auto node = parse_or();
        if (pos_token_ != tokens_.size()) {
            throw ParseError("Unexpected token at end of query.");
        }
        return node;
    }

private:
    enum class TokType { WORD, PHRASE, AND, OR, NOT, LPAREN, RPAREN };

    struct Token {
        TokType     type;
        std::string text;  // For WORD/PHRASE
    };

    void tokenize() {
        static const std::regex re(R"((\"[^\"]+\")|\(|\)|\bAND\b|\bOR\b|\bNOT\b|\S+)",
                                   std::regex::icase);
        std::smatch m;
        std::string s = input_;
        while (std::regex_search(s, m, re)) {
            std::string tok = m.str(0);
            if (tok == "(") { tokens_.push_back({TokType::LPAREN, tok}); }
            else if (tok == ")") { tokens_.push_back({TokType::RPAREN, tok}); }
            else if (icase_eq(tok, "AND")) { tokens_.push_back({TokType::AND, tok}); }
            else if (icase_eq(tok, "OR")) { tokens_.push_back({TokType::OR, tok}); }
            else if (icase_eq(tok, "NOT")) { tokens_.push_back({TokType::NOT, tok}); }
            else if (tok.size() > 2 && tok.front() == '"' && tok.back() == '"') {
                tokens_.push_back({TokType::PHRASE,
                                   tok.substr(1, tok.size() - 2)});  // strip quotes
            } else {
                tokens_.push_back({TokType::WORD, tok});
            }
            s = m.suffix();
        }
    }

    static bool icase_eq(const std::string& a, const std::string& b) {
        return util::to_lower(a) == util::to_lower(b);
    }

    // Recursive-descent parser with operator precedence:
    //  OR (lowest) -> AND -> NOT -> term/paren (highest)
    std::unique_ptr<QueryNode> parse_or() {
        auto left = parse_and();
        while (match(TokType::OR)) {
            auto right = parse_and();
            std::vector<std::unique_ptr<QueryNode>> children;
            children.push_back(std::move(left));
            children.push_back(std::move(right));
            left = QueryNode::make(NodeType::OR, std::move(children));
        }
        return left;
    }

    std::unique_ptr<QueryNode> parse_and() {
        auto left = parse_not();
        while (match(TokType::AND)) {
            auto right = parse_not();
            std::vector<std::unique_ptr<QueryNode>> children;
            children.push_back(std::move(left));
            children.push_back(std::move(right));
            left = QueryNode::make(NodeType::AND, std::move(children));
        }
        return left;
    }

    std::unique_ptr<QueryNode> parse_not() {
        if (match(TokType::NOT)) {
            auto operand = parse_not();
            std::vector<std::unique_ptr<QueryNode>> ch;
            ch.push_back(std::move(operand));
            return QueryNode::make(NodeType::NOT, std::move(ch));
        }
        return parse_term();
    }

    std::unique_ptr<QueryNode> parse_term() {
        if (match(TokType::LPAREN)) {
            auto node = parse_or();
            if (!match(TokType::RPAREN)) {
                throw ParseError("Expected ')'");
            }
            return node;
        }
        if (match(TokType::WORD)) {
            return std::make_unique<QueryNode>(NodeType::TERM, prev_token_.text);
        }
        if (match(TokType::PHRASE)) {
            return std::make_unique<QueryNode>(NodeType::PHRASE, prev_token_.text);
        }
        throw ParseError("Unexpected token in query.");
    }

    bool match(TokType expected) {
        if (pos_token_ < tokens_.size() && tokens_[pos_token_].type == expected) {
            prev_token_ = tokens_[pos_token_++];
            return true;
        }
        return false;
    }

    std::string       input_;
    std::size_t       pos_;
    std::vector<Token> tokens_;
    std::size_t        pos_token_ = 0;
    Token              prev_token_{TokType::WORD, ""};
};

// -----------------------------------------------------------------------------
// Query Evaluator
// -----------------------------------------------------------------------------

class QueryEvaluator {
public:
    explicit QueryEvaluator(const QueryNode* root) : root_(root) {}

    DocumentList filter(const DocumentList& corpus) {
        DocumentList out;
        for (const auto& doc : corpus) {
            if (match_node(root_, doc)) { out.push_back(doc); }
        }
        return out;
    }

private:
    const QueryNode* root_;

    static bool match_term(const Document& doc, const std::string& term) {
        auto haystack = util::to_lower(doc.title + " " + doc.content);
        auto needle   = util::to_lower(term);
        return haystack.find(needle) != std::string::npos;
    }

    static bool match_phrase(const Document& doc, const std::string& phrase) {
        auto haystack = util::to_lower(doc.title + " " + doc.content);
        auto needle   = util::to_lower(phrase);
        return haystack.find(needle) != std::string::npos;
    }

    bool match_node(const QueryNode* node, const Document& doc) {
        switch (node->type) {
            case NodeType::TERM:
                return match_term(doc, node->term);
            case NodeType::PHRASE:
                return match_phrase(doc, node->term);
            case NodeType::AND:
                return std::all_of(
                    node->children.begin(), node->children.end(),
                    [&](const std::unique_ptr<QueryNode>& ch) { return match_node(ch.get(), doc); });
            case NodeType::OR:
                return std::any_of(
                    node->children.begin(), node->children.end(),
                    [&](const std::unique_ptr<QueryNode>& ch) { return match_node(ch.get(), doc); });
            case NodeType::NOT:
                return !match_node(node->children.front().get(), doc);
            default:
                return false;
        }
    }
};

// -----------------------------------------------------------------------------
// Search Service
// -----------------------------------------------------------------------------

class SearchService {
public:
    explicit SearchService(std::shared_ptr<DocumentRepository> repo,
                           std::size_t                         cache_entries = 512)
        : repo_(std::move(repo)), cache_(cache_entries) {}

    // Asynchronous interface: returns future<SearchResponse>
    std::future<SearchResponse> search_async(SearchRequest req) {
        return std::async(std::launch::async, [this, req = std::move(req)]() {
            return this->search(req);
        });
    }

private:
    SearchResponse search(const SearchRequest& req) {
        const auto start_time = std::chrono::steady_clock::now();

        // Attempt cache lookup
        SearchResponse cached;
        if (cache_.get(req.query, cached)) {
            // apply offset/limit at response time to avoid storing slices
            SearchResponse resp = cached;
            resp.hits = slice(resp.hits, req.offset, req.limit);
            resp.took = std::chrono::duration_cast<std::chrono::milliseconds>(
                std::chrono::steady_clock::now() - start_time);
            return resp;
        }

        // Parse
        auto parser = QueryParser(req.query);
        auto ast    = parser.parse();

        // Evaluate
        auto corpus = repo_->fetch_all();
        if (!req.locale.empty()) {
            corpus.erase(std::remove_if(corpus.begin(), corpus.end(),
                                        [&](const Document& d) {
                                            return d.locale != req.locale;
                                        }),
                         corpus.end());
        }

        QueryEvaluator evaluator(ast.get());
        auto           matches = evaluator.filter(corpus);

        // Sort by publish date desc
        std::sort(matches.begin(), matches.end(), [](const auto& a, const auto& b) {
            return a.published_at > b.published_at;
        });

        SearchResponse resp;
        resp.total_hits = matches.size();
        resp.hits       = slice(matches, req.offset, req.limit);
        resp.took       = std::chrono::duration_cast<std::chrono::milliseconds>(
            std::chrono::steady_clock::now() - start_time);

        // Put in cache (store full hits, not sliced)
        cache_.put(req.query,
                   SearchResponse{matches, resp.total_hits,
                                  resp.took});  // storing took is fine; will be recomputed

        return resp;
    }

    static DocumentList slice(const DocumentList& v, std::size_t offset, std::size_t limit) {
        if (offset >= v.size()) return {};
        auto first = v.begin() + static_cast<std::ptrdiff_t>(offset);
        auto last  = (limit == 0 || offset + limit > v.size())
                         ? v.end()
                         : first + static_cast<std::ptrdiff_t>(limit);
        return {first, last};
    }

    std::shared_ptr<DocumentRepository> repo_;
    LruCache<std::string, SearchResponse> cache_;
};

// -----------------------------------------------------------------------------
// Demo / self-test (normally would be unit test framework)
// -----------------------------------------------------------------------------
#ifdef INTRALEDGER_BLOGSUITE_SEARCH_SELFTEST
static DocumentList sample_docs() {
    const auto now = std::chrono::system_clock::now();
    return {
        {1, "Hello World", "The very first post in our blog.", "en", now},
        {2, "Willkommen", "Dies ist ein deutscher Beitrag.", "de", now - std::chrono::hours(1)},
        {3, "C++ Tips", "Advanced tricks with modern C++ and templates.", "en", now -
                                                                               std::chrono::hours(2)},
        {4, "Holiday Announcement", "Office will be closed next week.", "en",
         now - std::chrono::hours(4)},
        {5, "Bienvenue", "Un article français.", "fr", now - std::chrono::hours(10)},
    };
}

int main() {
    auto repo = std::make_shared<StubDocumentRepository>(sample_docs());
    SearchService service(repo);

    SearchRequest req;
    req.query  = "C++ AND tricks";
    req.locale = "en";

    auto future = service.search_async(req);
    auto resp   = future.get();

    std::cout << "Found " << resp.total_hits << " results in "
              << resp.took.count() << " ms\n";
    for (const auto& doc : resp.hits) {
        std::cout << "  [" << doc.id << "] " << doc.title << "\n";
    }
}
#endif  // INTRALEDGER_BLOGSUITE_SEARCH_SELFTEST

}  // namespace blog::search