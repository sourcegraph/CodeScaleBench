```cpp
/**
 *  src/module_59.cpp
 *  IntraLedger BlogSuite (web_blog)
 *
 *  Module 59: Email Template Rendering & Dispatch Service
 *
 *  This compilation unit provides a small but fully–functional slice of the
 *  “notification pipeline” for IntraLedger BlogSuite.  It demonstrates how the
 *  platform glues Repository access, Service–Layer business rules, and external
 *  integrations together in a production-quality manner.
 *
 *  Responsibilities
 *  ─────────────────
 *   • Fetch localized e-mail templates from the database (via repository)
 *   • Perform safe runtime variable substitution
 *   • Dispatch the rendered message through the configured mail transport
 *   • Provide comprehensive error handling & structured logging
 *
 *  NOTE: Interfaces for ITemplateRepository and IMailTransport are intentionally
 *        kept minimal here; in the real codebase they live in separate
 *        translation units and are much richer.
 */

#include <chrono>
#include <exception>
#include <future>
#include <map>
#include <memory>
#include <mutex>
#include <optional>
#include <regex>
#include <shared_mutex>
#include <stdexcept>
#include <string>
#include <string_view>
#include <system_error>
#include <thread>
#include <utility>
#include <vector>

#include <fmt/core.h>
#include <fmt/chrono.h>

namespace blog::email {

// ─────────────────────────────────────────────────────────────────────────────
// Exception hierarchy
// ─────────────────────────────────────────────────────────────────────────────
class EmailError : public std::runtime_error {
public:
    explicit EmailError(std::string message) : std::runtime_error(std::move(message)) {}
};

class TemplateNotFoundError : public EmailError {
public:
    explicit TemplateNotFoundError(std::string_view key)
        : EmailError(fmt::format("E-mail template '{}' not found", key)) {}
};

class MissingSubstitutionError : public EmailError {
public:
    explicit MissingSubstitutionError(std::string_view placeholder)
        : EmailError(fmt::format("Missing required placeholder: {}", placeholder)) {}
};

class MailTransportError : public EmailError {
public:
    explicit MailTransportError(std::string message)
        : EmailError(std::move(message)) {}
};

// ─────────────────────────────────────────────────────────────────────────────
// Repository & transport interfaces
// ─────────────────────────────────────────────────────────────────────────────
struct Template {
    std::string subject;
    std::string bodyHtml;
    std::string bodyText;
    std::string locale; // e.g. "en_US", "fr_FR"
};

class ITemplateRepository {
public:
    virtual ~ITemplateRepository() = default;

    // Returns the most specific locale match for {key, locale}.  Implementations
    // should fall back to language-only (“en” when “en_GB” is requested), then
    // to default (“en_US”), returning std::nullopt when no template exists.
    virtual std::optional<Template>
    fetchTemplate(std::string_view key, std::string_view locale) const = 0;
};

struct EmailMessage {
    std::string from;
    std::vector<std::string> to;
    std::string subject;
    std::string bodyHtml;
    std::string bodyText;
};

// Transport is intentionally async-friendly; send() must be non-blocking.
class IMailTransport {
public:
    virtual ~IMailTransport() = default;
    virtual std::future<void> send(EmailMessage msg) = 0;
};

// ─────────────────────────────────────────────────────────────────────────────
// Template renderer (thread-safe, cached)
// ─────────────────────────────────────────────────────────────────────────────
class TemplateRenderer {
public:
    explicit TemplateRenderer(std::shared_ptr<ITemplateRepository> repository,
                              std::chrono::seconds ttl = std::chrono::minutes(5))
        : repo_{std::move(repository)}, cacheTtl_{ttl}
    {
        if (!repo_) { throw std::invalid_argument("TemplateRepository must not be nullptr"); }
    }

    Template render(std::string_view key,
                    std::string_view locale,
                    const std::map<std::string, std::string>& variables) const
    {
        auto tpl = getTemplate(key, locale);
        return performSubstitution(tpl, variables);
    }

private:
    struct CachedEntry {
        Template tpl;
        std::chrono::steady_clock::time_point insertedAt;
    };

    Template performSubstitution(const Template& tpl,
                                 const std::map<std::string, std::string>& vars) const
    {
        static const std::regex placeholder(R"(\{\{\s*([a-zA-Z_][a-zA-Z0-9_]*)\s*\}\})");

        auto sub = [&](const std::string& source) -> std::string {
            std::string result;
            std::sregex_iterator begin(source.begin(), source.end(), placeholder), end;
            std::size_t lastPos = 0;

            for (auto it = begin; it != end; ++it) {
                const std::smatch& m = *it;
                result.append(source, lastPos, m.position() - lastPos);
                const std::string key = m[1].str();

                auto found = vars.find(key);
                if (found == vars.end()) { throw MissingSubstitutionError(key); }
                result.append(found->second);
                lastPos = m.position() + m.length();
            }
            result.append(source, lastPos, std::string::npos);
            return result;
        };

        Template out = tpl;
        out.subject   = sub(tpl.subject);
        out.bodyHtml  = sub(tpl.bodyHtml);
        out.bodyText  = sub(tpl.bodyText);
        return out;
    }

    Template getTemplate(std::string_view key, std::string_view locale) const
    {
        const CacheKey ck{std::string{key}, std::string{locale}};

        {
            std::shared_lock rlock(cacheMtx_);
            auto it = cache_.find(ck);
            if (it != cache_.end() && !isExpired(it->second)) { return it->second.tpl; }
        }

        // Upgrade to unique lock for write
        std::unique_lock wlock(cacheMtx_);

        // Re-check after acquiring exclusive lock
        auto it = cache_.find(ck);
        if (it != cache_.end() && !isExpired(it->second)) { return it->second.tpl; }

        auto tplOpt = repo_->fetchTemplate(key, locale);
        if (!tplOpt) { throw TemplateNotFoundError(key); }

        CachedEntry entry{*tplOpt, std::chrono::steady_clock::now()};
        cache_[ck] = entry;
        return entry.tpl;
    }

    bool isExpired(const CachedEntry& entry) const
    {
        return (std::chrono::steady_clock::now() - entry.insertedAt) > cacheTtl_;
    }

    struct CacheKey {
        std::string key;
        std::string locale;

        bool operator==(const CacheKey& other) const noexcept {
            return key == other.key && locale == other.locale;
        }
    };

    struct CacheKeyHasher {
        std::size_t operator()(const CacheKey& ck) const noexcept {
            return std::hash<std::string>{}(ck.key) ^ (std::hash<std::string>{}(ck.locale) << 1);
        }
    };

    std::shared_ptr<ITemplateRepository> repo_;
    mutable std::unordered_map<CacheKey, CachedEntry, CacheKeyHasher> cache_;
    mutable std::shared_mutex cacheMtx_;
    const std::chrono::seconds cacheTtl_;
};

// ─────────────────────────────────────────────────────────────────────────────
// Dispatch service
// ─────────────────────────────────────────────────────────────────────────────
class EmailService {
public:
    EmailService(std::shared_ptr<TemplateRenderer> renderer,
                 std::shared_ptr<IMailTransport> transport,
                 std::string defaultFrom)
        : renderer_{std::move(renderer)},
          transport_{std::move(transport)},
          defaultFrom_{std::move(defaultFrom)}
    {
        if (!renderer_ || !transport_) {
            throw std::invalid_argument("renderer and transport must not be nullptr");
        }
    }

    // Launches a send operation; returns future that resolves when the e-mail
    // has been accepted by the transport.
    std::future<void> sendTemplated(std::string_view templateKey,
                                    std::string_view locale,
                                    std::vector<std::string> recipients,
                                    std::map<std::string, std::string> vars,
                                    std::optional<std::string> fromOverride = std::nullopt)
    {
        if (recipients.empty()) {
            throw EmailError("EmailService::sendTemplated called with empty recipients");
        }

        try {
            Template rendered = renderer_->render(templateKey, locale, vars);

            EmailMessage msg{
                .from       = fromOverride.value_or(defaultFrom_),
                .to         = std::move(recipients),
                .subject    = std::move(rendered.subject),
                .bodyHtml   = std::move(rendered.bodyHtml),
                .bodyText   = std::move(rendered.bodyText)
            };

            return transport_->send(std::move(msg));
        }
        catch (...) {
            // Package exception_ptr to propagate via future
            std::promise<void> p;
            p.set_exception(std::current_exception());
            return p.get_future();
        }
    }

private:
    std::shared_ptr<TemplateRenderer> renderer_;
    std::shared_ptr<IMailTransport>   transport_;
    std::string                       defaultFrom_;
};

// ─────────────────────────────────────────────────────────────────────────────
// Mock implementations (for unit/integration tests)
// ─────────────────────────────────────────────────────────────────────────────
#ifdef BLOGSUITE_ENABLE_EMAIL_TEST_MOCKS

class InMemoryTemplateRepository final : public ITemplateRepository {
public:
    void addTemplate(std::string key, std::string locale, Template tpl)
    {
        std::unique_lock lk(m_);
        storage_[std::move(key)][std::move(locale)] = std::move(tpl);
    }

    std::optional<Template>
    fetchTemplate(std::string_view key, std::string_view locale) const override
    {
        std::shared_lock lk(m_);
        auto kit = storage_.find(std::string{key});
        if (kit == storage_.end()) { return std::nullopt; }

        const auto& perLocale = kit->second;

        // Most specific → language only → default
        auto exact = perLocale.find(std::string{locale});
        if (exact != perLocale.end()) { return exact->second; }

        // language match
        auto dashPos = locale.find('_');
        if (dashPos != std::string_view::npos) {
            std::string lang{locale.substr(0, dashPos)};
            auto langIt = perLocale.find(lang);
            if (langIt != perLocale.end()) { return langIt->second; }
        }

        // default fallback
        auto defIt = perLocale.find("en_US");
        if (defIt != perLocale.end()) { return defIt->second; }

        return std::nullopt;
    }

private:
    mutable std::shared_mutex m_;
    std::map<std::string, std::map<std::string, Template>> storage_;
};

class LoggingMailTransport final : public IMailTransport {
public:
    std::future<void> send(EmailMessage msg) override
    {
        return std::async(std::launch::async, [msg = std::move(msg)] {
            // Simulate I/O latency
            std::this_thread::sleep_for(std::chrono::milliseconds(25));
            fmt::print(
                "[mail] From: {}\n       To: {}\n   Subject: {}\n-------------\n{}\n\n",
                msg.from, fmt::join(msg.to, ", "), msg.subject, msg.bodyText);
        });
    }
};

#endif // BLOGSUITE_ENABLE_EMAIL_TEST_MOCKS

} // namespace blog::email
```