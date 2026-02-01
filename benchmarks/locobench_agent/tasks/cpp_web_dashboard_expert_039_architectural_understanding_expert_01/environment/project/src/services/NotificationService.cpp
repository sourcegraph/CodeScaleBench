#include "services/NotificationService.hpp"

#include "core/EventBus.hpp"
#include "core/exceptions/ServiceException.hpp"
#include "core/http/HttpStatus.hpp"
#include "repositories/UserRepository.hpp"
#include "transports/EmailGateway.hpp"
#include "transports/WebsocketHub.hpp"

#include <nlohmann/json.hpp>
#include <spdlog/spdlog.h>

#include <algorithm>
#include <atomic>
#include <chrono>
#include <condition_variable>
#include <cstdlib>
#include <deque>
#include <mutex>
#include <thread>
#include <utility>

using json = nlohmann::json;
using namespace std::chrono_literals;

namespace mosaic::services
{

// -----------------------------------------------------------------------------
// ctor / dtor
// -----------------------------------------------------------------------------
NotificationService::NotificationService(core::EventBus&               eventBus,
                                         repository::UserRepository&   userRepo,
                                         transport::WebsocketHub&      wsHub,
                                         transport::EmailGateway&      emailGateway)
    : m_eventBus(eventBus)
    , m_userRepo(userRepo)
    , m_wsHub(wsHub)
    , m_emailGateway(emailGateway)
    , m_running(false)
{
    // Subscribe to internal event bus so we can enqueue app-wide events
    m_busToken = m_eventBus.subscribe(
        [this](const core::events::IEvent& evt)
        {
            if (const auto* notifEvt = dynamic_cast<const core::events::NotificationEvent*>(&evt))
            {
                enqueueNotification(notifEvt->notification());
            }
        });
}
// -----------------------------------------------------------------------------
NotificationService::~NotificationService()
{
    stop();
    m_eventBus.unsubscribe(m_busToken);
}
// -----------------------------------------------------------------------------
// public API
// -----------------------------------------------------------------------------
void NotificationService::start()
{
    std::lock_guard lock(m_stateMx);
    if (m_running) { return; }

    m_running = true;
    m_worker  = std::thread(&NotificationService::processQueueLoop, this);
    spdlog::info("[NotificationService] Worker thread started.");
}
// -----------------------------------------------------------------------------
void NotificationService::stop()
{
    {
        std::lock_guard lock(m_stateMx);
        if (!m_running) { return; }
        m_running = false;
    }

    m_cv.notify_all();
    if (m_worker.joinable())
    {
        m_worker.join();
        spdlog::info("[NotificationService] Worker thread stopped.");
    }
}
// -----------------------------------------------------------------------------
void NotificationService::subscribe(const std::string& userId,
                                    const std::string& channel)
{
    std::lock_guard lock(m_subscriptionMx);
    m_channelSubscribers[channel].insert(userId);
}
// -----------------------------------------------------------------------------
void NotificationService::unsubscribe(const std::string& userId,
                                      const std::string& channel)
{
    std::lock_guard lock(m_subscriptionMx);
    auto it = m_channelSubscribers.find(channel);
    if (it != m_channelSubscribers.end())
    {
        it->second.erase(userId);
        if (it->second.empty()) { m_channelSubscribers.erase(it); }
    }
}
// -----------------------------------------------------------------------------
void NotificationService::acknowledge(const std::string&   notificationId,
                                      const std::string&   userId,
                                      AcknowledgeCallback  callback)
{
    // In real implementation this state is persisted in DB.
    // For now we just propagate acknowledgement to interested parties.
    try
    {
        json payload = { { "notificationId", notificationId },
                         { "userId", userId },
                         { "status", "ACKNOWLEDGED" } };

        m_eventBus.publish(core::events::NotificationAckEvent{ std::move(payload) });

        if (callback) { callback(std::nullopt); }
    }
    catch (const std::exception& ex)
    {
        if (callback) { callback(ServiceException{ ex.what() }); }
    }
}
// -----------------------------------------------------------------------------
void NotificationService::enqueueNotification(Notification notification)
{
    {
        std::lock_guard lock(m_queueMx);
        m_queue.emplace_back(std::move(notification));
    }
    m_cv.notify_one();
}
// -----------------------------------------------------------------------------
// internals
// -----------------------------------------------------------------------------
void NotificationService::processQueueLoop()
{
    while (isRunning())
    {
        Notification next;
        {
            std::unique_lock lock(m_queueMx);
            m_cv.wait(lock, [this] { return !m_queue.empty() || !isRunning(); });

            if (!isRunning()) { break; }
            next = std::move(m_queue.front());
            m_queue.pop_front();
        }

        try
        {
            deliverNotification(next);
        }
        catch (const std::exception& ex)
        {
            spdlog::error("[NotificationService] Failed to deliver notification: {}", ex.what());
            // Optional: push to dead letter queue / db
        }
    }
}
// -----------------------------------------------------------------------------
bool NotificationService::isRunning() const
{
    std::lock_guard lock(m_stateMx);
    return m_running;
}
// -----------------------------------------------------------------------------
void NotificationService::deliverNotification(const Notification& notification)
{
    // 1) Determine all target users
    std::vector<std::string> recipients;

    {
        std::lock_guard lock(m_subscriptionMx);

        // Broadcast channel
        if (notification.channel == Notification::BroadcastChannel)
        {
            recipients = m_userRepo.fetchAllUserIds();
        }
        else
        {
            auto it = m_channelSubscribers.find(notification.channel);
            if (it != m_channelSubscribers.end())
            {
                recipients.assign(it->second.begin(), it->second.end());
            }
        }
    }

    if (recipients.empty())
    {
        spdlog::debug("[NotificationService] No recipients for channel '{}'",
                      notification.channel);
        return;
    }

    // 2) Create transport payload (JSON)
    json payload = { { "id", notification.id },
                     { "title", notification.title },
                     { "message", notification.message },
                     { "timestamp", notification.timestamp.count() },
                     { "channel", notification.channel } };

    // 3) Deliver over websocket
    for (const auto& uid : recipients)
    {
        try
        {
            m_wsHub.push(uid, payload.dump());
        }
        catch (const std::exception& ex)
        {
            spdlog::warn(
                "[NotificationService] Websocket delivery failed for user {}: {}", uid, ex.what());
            // continue; don't abort – attempt email fallback
        }

        // Email fallback (opt-in)
        if (notification.emailFallback)
        {
            try
            {
                auto user = m_userRepo.findById(uid);
                if (user.emailOptIn)
                {
                    transport::EmailMessage msg;
                    msg.to      = user.email;
                    msg.subject = notification.title;
                    msg.body    = notification.message;

                    m_emailGateway.send(std::move(msg));
                }
            }
            catch (const std::exception& ex)
            {
                spdlog::error(
                    "[NotificationService] Email fallback failed for user {}: {}", uid, ex.what());
            }
        }
    }
    spdlog::debug("[NotificationService] Notification '{}' delivered to {} recipients.",
                  notification.id,
                  recipients.size());
}

} // namespace mosaic::services