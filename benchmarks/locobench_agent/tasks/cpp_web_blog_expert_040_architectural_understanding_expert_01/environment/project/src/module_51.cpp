```cpp
/**
 * src/module_51.cpp
 *
 * IntraLedger BlogSuite (web_blog)
 * --------------------------------
 * Multi-lingual E-mail Notification Service
 *
 * This module implements a robust service that prepares and dispatches
 * transactional e-mail notifications (new-comment, password-reset, purchase
 * receipts, etc.) to end-users in their preferred language.  Messages are
 * rendered from Mustache templates, localized through the internal
 * TranslationService, and delivered asynchronously through the central Job
 * Processor to avoid blocking the main request/response lifecycle.
 *
 * Architectural Concerns
 * ----------------------
 * • Service Layer — Provides a stable public API, abstracting away queueing
 *   mechanics, mail transport, and template look-ups.
 * • Repository Pattern — Fetches user preferences from the data store
 *   without leaking ORM specifics.
 * • Middleware Friendly — Emits strongly-typed exceptions that upstream
 *   middleware can translate into HTTP errors for REST controllers.
 *
 * © 2023-2024 IntraLedger Software GmbH
 * SPDX-License-Identifier: AGPL-3.0-or-later
 */

#include <chrono>
#include <exception>
#include <filesystem>
#include <future>
#include <iomanip>
#include <memory>
#include <mutex>
#include <optional>
#include <sstream>
#include <string>
#include <string_view>
#include <system_error>
#include <unordered_map>
#include <utility>
#include <vector>

#include "core/JobQueue.hpp"               // Thread-safe async job dispatcher
#include "core/Logger.hpp"                 // Structured logging facility
#include "core/TranslationService.hpp"     // i18n service interface
#include "persistence/UserRepository.hpp"  // Repository for user records
#include "services/MailTransport.hpp"      // SMTP/Send-grid wrapper
#include "utils/TemplateEngine.hpp"        // Mustache-like renderer

namespace intraledger::services {

/* ----------------------------------------------------------- Exceptions ---- */

/**
 * Base class for all errors originating from EmailNotificationService.
 */
class EmailServiceError : public std::runtime_error {
public:
    explicit EmailServiceError(const std::string& msg)
        : std::runtime_error{msg}
    {}
};

/**
 * Thrown when a template or translation key cannot be located.
 */
class TemplateNotFoundError : public EmailServiceError {
public:
    explicit TemplateNotFoundError(const std::string& tpl)
        : EmailServiceError{"E-mail template not found: " + tpl}
    {}
};

/**
 * Thrown when the MailTransport layer reports a fatal error.
 */
class MailDispatchError : public EmailServiceError {
public:
    explicit MailDispatchError(const std::string& reason)
        : EmailServiceError{"Mail dispatch failed: " + reason}
    {}
};

/* -------------------------------------------------------------- Models ---- */

/**
 * Compact aggregate describing everything required to send a single e-mail.
 */
struct EmailMessage final {
    std::string     recipientAddress;
    std::string     recipientName;
    std::string     subject;
    std::string     htmlBody;
    std::string     textBody;
};

/**
 * Domain object representing a pending notification.
 */
struct Notification final {
    enum class Type {
        CommentReply,
        PasswordReset,
        PurchaseReceipt,
        // add more use-cases as necessary
    };

    std::string id;           // UUID
    std::string userId;       // Receiver
    Type        type;
    nlohmann::json payload;   // Domain-specific fields
};

/* ----------------------------------------------------------- Interfaces ---- */

/**
 * Serves as the public façade for emitting e-mail notifications from outside
 * layers (controllers, domain services, etc.).
 */
class IEmailNotificationService {
public:
    virtual ~IEmailNotificationService() = default;

    /**
     * Queue a notification for background processing.
     *
     * The call is non-blocking; the actual SMTP-level delivery happens
     * asynchronously inside the Job Processor thread-pool.
     */
    virtual void enqueueNotification(Notification notification) = 0;
};

/* --------------------------------------------------- Implementation Details ---- */

class EmailNotificationService final : public IEmailNotificationService
{
public:
    using Clock = std::chrono::system_clock;

    EmailNotificationService(std::shared_ptr<core::JobQueue>            jobQueue,
                             std::shared_ptr<persistence::UserRepository> userRepo,
                             std::shared_ptr<core::TranslationService>  translator,
                             std::shared_ptr<services::MailTransport>   mailTransport,
                             std::shared_ptr<utils::TemplateEngine>     tplEngine)
        : m_jobQueue{std::move(jobQueue)}
        , m_userRepo{std::move(userRepo)}
        , m_translator{std::move(translator)}
        , m_mailTransport{std::move(mailTransport)}
        , m_tplEngine{std::move(tplEngine)}
    {
        if (!m_jobQueue || !m_userRepo || !m_translator ||
            !m_mailTransport || !m_tplEngine)
        {
            throw std::invalid_argument{"EmailNotificationService: nullptr dependency"};
        }
    }

    void enqueueNotification(Notification notification) override
    {
        using namespace std::literals::chrono_literals;

        // We capture `this` by value to retain a strong ptr to our dependencies
        // inside the async context.
        m_jobQueue->push([this, n = std::move(notification)]() {
            auto timerStart = Clock::now();
            try {
                core::Logger::debug("Processing notification {}", n.id);

                auto user = m_userRepo->findById(n.userId);
                if (!user) {
                    core::Logger::warn("User {} not found, dropping notification {}", n.userId, n.id);
                    return;
                }

                // 1. Assemble language context
                std::string lang = user->preferredLanguage.value_or("en");
                auto localeGuard = m_translator->scopedLocale(lang);

                // 2. Prepare e-mail message
                auto message = buildMessage(n, *user);

                // 3. Send e-mail
                m_mailTransport->send(message);

                // 4. Success logging
                auto elapsed = std::chrono::duration_cast<std::chrono::milliseconds>(
                                   Clock::now() - timerStart);
                core::Logger::info("Notification {} delivered to {} in {} ms",
                                   n.id, user->email, elapsed.count());
            }
            catch (const MailDispatchError& ex) {
                core::Logger::error("Notification {} failed: {}", n.id, ex.what());
                // Let the queue know that retry is possible
                throw; // JobQueue should implement retry strategy
            }
            catch (const std::exception& ex) {
                core::Logger::error("Notification {} processing error: {}", n.id, ex.what());
            }
        });
    }

private:
    /* Helpers -------------------------------------------------------------- */

    EmailMessage buildMessage(const Notification& n,
                              const persistence::User& user)
    {
        std::string_view tplBaseName = templateBaseName(n.type);

        auto subjectTplPath  = templatePath(tplBaseName, "subject.mustache");
        auto htmlTplPath     = templatePath(tplBaseName, "body.html.mustache");
        auto textTplPath     = templatePath(tplBaseName, "body.txt.mustache");

        if (!std::filesystem::exists(subjectTplPath) ||
            !std::filesystem::exists(htmlTplPath) ||
            !std::filesystem::exists(textTplPath))
        {
            throw TemplateNotFoundError{std::string{tplBaseName}};
        }

        // Convert payload to template context
        auto context = nlohmann::json{
            { "user", {
                { "name",  user.displayName },
                { "email", user.email }
            } }
        };
        context.merge_patch(n.payload); // domain-specific data

        EmailMessage msg;
        msg.recipientAddress = user.email;
        msg.recipientName    = user.displayName;
        msg.subject = m_tplEngine->renderFile(subjectTplPath, context);
        msg.htmlBody = m_tplEngine->renderFile(htmlTplPath, context);
        msg.textBody = m_tplEngine->renderFile(textTplPath, context);

        return msg;
    }

    static std::string templateBaseName(Notification::Type t)
    {
        switch (t) {
        case Notification::Type::CommentReply:    return "comment_reply";
        case Notification::Type::PasswordReset:   return "password_reset";
        case Notification::Type::PurchaseReceipt: return "purchase_receipt";
        default:                                  return "generic";
        }
    }

    static std::filesystem::path templatePath(std::string_view base,
                                              std::string_view filename)
    {
        constexpr std::string_view kTemplateRoot = "assets/email_templates";
        return std::filesystem::path{kTemplateRoot}
             / std::string{base}
             / std::string{filename};
    }

    /* Members -------------------------------------------------------------- */

    std::shared_ptr<core::JobQueue>              m_jobQueue;
    std::shared_ptr<persistence::UserRepository> m_userRepo;
    std::shared_ptr<core::TranslationService>    m_translator;
    std::shared_ptr<services::MailTransport>     m_mailTransport;
    std::shared_ptr<utils::TemplateEngine>       m_tplEngine;
};

/* ------------------------------------------------------ Factory Function ---- */

/**
 * Helper used by Service Locator / DI container to construct the service in
 * one convenient call.
 */
std::shared_ptr<IEmailNotificationService>
makeEmailNotificationService(std::shared_ptr<core::JobQueue>              jobQueue,
                             std::shared_ptr<persistence::UserRepository> userRepo,
                             std::shared_ptr<core::TranslationService>    translator,
                             std::shared_ptr<services::MailTransport>     mailTransport,
                             std::shared_ptr<utils::TemplateEngine>       tplEngine)
{
    return std::make_shared<EmailNotificationService>(std::move(jobQueue),
                                                      std::move(userRepo),
                                                      std::move(translator),
                                                      std::move(mailTransport),
                                                      std::move(tplEngine));
}

} // namespace intraledger::services
```