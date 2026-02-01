#include "domain/commands/backup_command.h"

#include <chrono>
#include <exception>
#include <memory>
#include <sstream>
#include <stdexcept>
#include <string>
#include <utility>

#include "domain/events/event_bus.h"
#include "domain/events/tenant_backup_events.h"
#include "domain/services/backup_service.h"
#include "infrastructure/config/config_manager.h"
#include "infrastructure/logging/logger.h"
#include "infrastructure/metrics/metrics_collector.h"
#include "infrastructure/tracing/trace_span.h"

namespace fortiledger::domain::commands {

using fortiledger::infrastructure::logging::Logger;
using fortiledger::infrastructure::metrics::MetricsCollector;
using fortiledger::infrastructure::tracing::TraceSpan;

/* =========================================================================================
 *  Helpers
 * ========================================================================================= */

namespace {

// Convenience: Resolve human-readable name of BackupScope for logs/metrics.
constexpr std::string_view to_string(BackupScope scope) noexcept {
    switch (scope) {
        case BackupScope::kIncremental:
            return "incremental";
        case BackupScope::kFull:
            return "full";
        case BackupScope::kSnapshot:
            return "snapshot";
    }
    return "unknown";
}

}  // namespace

/* =========================================================================================
 *  Ctor / Dtor
 * ========================================================================================= */

BackupCommand::BackupCommand(std::string tenant_id,
                             BackupScope scope,
                             std::chrono::system_clock::time_point scheduled_for,
                             std::shared_ptr<services::BackupService> backup_service,
                             std::shared_ptr<events::EventBus> event_bus)
    : tenant_id_(std::move(tenant_id)),
      scope_(scope),
      scheduled_for_(scheduled_for),
      backup_service_(std::move(backup_service)),
      event_bus_(std::move(event_bus)) {
    if (tenant_id_.empty()) {
        throw std::invalid_argument("BackupCommand: tenant_id must not be empty");
    }
    if (!backup_service_) {
        throw std::invalid_argument("BackupCommand: backup_service must not be null");
    }
    if (!event_bus_) {
        throw std::invalid_argument("BackupCommand: event_bus must not be null");
    }
}

/* =========================================================================================
 *  Public API
 * ========================================================================================= */

CommandResult BackupCommand::Execute(CommandContext& ctx) noexcept {
    constexpr std::string_view kMetricNamespace = "domain.backup";

    auto span = TraceSpan::Start("BackupCommand::Execute")
                    .WithTag("tenant_id", tenant_id_)
                    .WithTag("scope", std::string{to_string(scope_)})
                    .WithTag("scheduled_for",
                             static_cast<std::uint64_t>(std::chrono::duration_cast<std::chrono::seconds>(
                                                            scheduled_for_.time_since_epoch())
                                                            .count()));

    Logger::Info("BackupCommand: Starting backup for tenant '{}' [scope: '{}']",
                 tenant_id_,
                 to_string(scope_));

    MetricsCollector::Instance().IncrementCounter(
        kMetricNamespace, "invoked_total", {{"scope", std::string{to_string(scope_)}}});

    // Ensure the command is executed within the configured backup window.
    if (!ValidateBackupWindow()) {
        Logger::Warn("BackupCommand: Backup window closed for tenant '{}'. Aborting.", tenant_id_);
        MetricsCollector::Instance().IncrementCounter(
            kMetricNamespace, "rejected_outside_window_total", {});
        return CommandResult::Rejected("Backup window closed");
    }

    // Publish "initiated" domain event.
    PublishInitiatedEvent();

    try {
        BackupDescriptor backup_desc = backup_service_->CreateBackup(tenant_id_, scope_);

        PublishCompletedEvent(backup_desc);
        MetricsCollector::Instance().IncrementCounter(
            kMetricNamespace, "success_total", {{"scope", std::string{to_string(scope_)}}});

        span.SetStatus(TraceSpan::Status::kOk);
        Logger::Info(
            "BackupCommand: Backup successfully completed for tenant '{}' [backup_id: '{}']",
            tenant_id_,
            backup_desc.backup_id);

        return CommandResult::Success();
    } catch (const services::BackupService::TransientError& ex) {
        // Transient error, can be retried
        PublishFailedEvent(ex, /*permanent*/ false);
        MetricsCollector::Instance().IncrementCounter(
            kMetricNamespace, "transient_failure_total", {{"scope", std::string{to_string(scope_)}}});

        span.SetStatus(TraceSpan::Status::kError, ex.what());
        Logger::Error("BackupCommand: Transient error while backing up tenant '{}': {}",
                      tenant_id_,
                      ex.what());
        return CommandResult::RetryableError(ex.what());
    } catch (const std::exception& ex) {
        // Permanent error
        PublishFailedEvent(ex, /*permanent*/ true);
        MetricsCollector::Instance().IncrementCounter(
            kMetricNamespace, "permanent_failure_total", {{"scope", std::string{to_string(scope_)}}});

        span.SetStatus(TraceSpan::Status::kError, ex.what());
        Logger::Error("BackupCommand: Permanent error while backing up tenant '{}': {}",
                      tenant_id_,
                      ex.what());
        return CommandResult::PermanentError(ex.what());
    }
}

/* =========================================================================================
 *  Internals
 * ========================================================================================= */

bool BackupCommand::ValidateBackupWindow() const {
    // Note: ConfigManager is thread-safe and memoized internally.
    auto cfg = infrastructure::config::ConfigManager::Instance();

    const auto window_start = cfg.GetTime("backup.window.start");  // e.g., "23:00"
    const auto window_end = cfg.GetTime("backup.window.end");      // e.g., "05:00"

    const auto now = std::chrono::system_clock::now();
    // simplistic sample check (actual implementation would handle cross-day ranges, etc.)
    return now >= window_start && now <= window_end;
}

void BackupCommand::PublishInitiatedEvent() const {
    events::TenantBackupInitiated evt{
        .tenant_id       = tenant_id_,
        .scope           = scope_,
        .timestamp_utc   = std::chrono::system_clock::now(),
    };
    event_bus_->Publish(evt);
}

void BackupCommand::PublishCompletedEvent(const BackupDescriptor& desc) const {
    events::TenantBackupSucceeded evt{
        .tenant_id       = tenant_id_,
        .scope           = scope_,
        .backup_id       = desc.backup_id,
        .location        = desc.location,
        .size_bytes      = desc.size_bytes,
        .timestamp_utc   = std::chrono::system_clock::now(),
    };
    event_bus_->Publish(evt);
}

void BackupCommand::PublishFailedEvent(const std::exception& ex, bool permanent) const {
    events::TenantBackupFailed evt{
        .tenant_id       = tenant_id_,
        .scope           = scope_,
        .permanent       = permanent,
        .error_message   = ex.what(),
        .timestamp_utc   = std::chrono::system_clock::now(),
    };
    event_bus_->Publish(evt);
}

}  // namespace fortiledger::domain::commands