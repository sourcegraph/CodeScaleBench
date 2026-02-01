#ifndef CARDIO_INSIGHT_360_SRC_INGESTION_CONNECTORS_FHIR_HTTP_LISTENER_H_
#define CARDIO_INSIGHT_360_SRC_INGESTION_CONNECTORS_FHIR_HTTP_LISTENER_H_

/**
 *  CardioInsight360 – Unified Healthcare Analytics Engine
 *  ------------------------------------------------------
 *  File:    fhir_http_listener.h
 *  Author:  CardioInsight360 Ingestion Team
 *
 *  Description:
 *  =============
 *  FhirHttpListener is a lightweight, embeddable HTTP listener that receives
 *  FHIR-formatted JSON bundles (`application/fhir+json` or
 *  `application/json`) over HTTP/S, performs basic validation, and forwards
 *  the raw payload to the platform’s internal ingestion bus.  The class is
 *  intentionally header-only to simplify integration with the monolithic
 *  build and to avoid DLL/SO boundary complications in regulated healthcare
 *  environments.
 *
 *  Key characteristics:
 *    • Thread-safe lifecycle management (`start()`, `stop()`)
 *    • Streaming-capable, back-pressure-aware design (Boost.Beast)
 *    • Pluggable RawMessageHandler callback for downstream dispatch
 *    • Configurable maximum payload size
 *    • Detailed error handling and audit-ready logging hooks
 *
 *  NOTE:
 *  -----
 *  This component is **not** a full-blown FHIR server.  It focuses solely on
 *  *ingestion* of (possibly) gigantic NDJSON bundles coming from hospital
 *  gateways, MLLP proxies, or wearable device clouds.  Downstream components
 *  (e.g. the ETL Pipeline) are responsible for full semantic validation.
 *
 *  Copyright:
 *  ----------
 *  © 2024 CardioInsight360.  All rights reserved.  Unauthorized copying of
 *  this file, via any medium, is strictly prohibited.
 */

#include <atomic>
#include <chrono>
#include <cstdint>
#include <functional>
#include <memory>
#include <string>
#include <thread>
#include <utility>

// Boost
#include <boost/asio.hpp>
#include <boost/beast/core.hpp>
#include <boost/beast/http.hpp>
#include <boost/beast/version.hpp>

// 3rd-party
#include <nlohmann/json.hpp>  // MIT license

namespace cardio::ingestion {

/**
 *  FhirHttpListener
 *  ----------------
 *  Thin wrapper around Boost.Beast’s HTTP server primitives.  The listener
 *  blocks until `stop()` is called or a fatal transport error occurs.
 */
class FhirHttpListener {
public:
    using RawMessageHandler = std::function<void(const std::string& raw_json)>;

    /**
     * Constructor
     *
     * @param address           Interface to bind to (e.g. "0.0.0.0")
     * @param port              TCP port to listen on
     * @param handler           Callback invoked with the raw request body
     * @param max_body_size     Upper limit for inbound HTTP body (bytes)
     */
    FhirHttpListener(std::string address,
                     std::uint16_t port,
                     RawMessageHandler handler,
                     std::size_t max_body_size = 10 * 1024 * 1024 /* 10 MB */)
        : address_(std::move(address)),
          port_(port),
          is_running_(false),
          max_body_size_(max_body_size),
          handler_(std::move(handler)),
          ioc_(static_cast<int>(std::thread::hardware_concurrency())),
          acceptor_(ioc_) {
        if (!handler_) {
            throw std::invalid_argument("RawMessageHandler cannot be empty");
        }
    }

    // Non-copyable / non-movable
    FhirHttpListener(const FhirHttpListener&) = delete;
    FhirHttpListener& operator=(const FhirHttpListener&) = delete;

    ~FhirHttpListener() { stop(); }

    /**
     * Start the listener in its own thread.
     * Throws std::runtime_error on failure.
     */
    void start() {
        if (is_running_.exchange(true)) {
            // Already running
            return;
        }

        try {
            using boost::asio::ip::tcp;

            tcp::resolver resolver{ioc_};
            tcp::endpoint endpoint = *resolver.resolve(address_, std::to_string(port_)).begin();

            // Open acceptor
            acceptor_.open(endpoint.protocol());
            acceptor_.set_option(boost::asio::socket_base::reuse_address(true));
            acceptor_.bind(endpoint);
            acceptor_.listen(boost::asio::socket_base::max_listen_connections);

            // Launch I/O context in background thread
            listener_thread_ = std::thread([this]() {
                doAccept();
                ioc_.run();
            });
        } catch (const std::exception& ex) {
            is_running_ = false;
            throw std::runtime_error(
                std::string("Failed to start FhirHttpListener: ") + ex.what());
        }
    }

    /**
     * Stop the listener gracefully.
     */
    void stop() noexcept {
        if (!is_running_.exchange(false)) {
            return;
        }
        boost::system::error_code ec;
        acceptor_.cancel(ec);
        acceptor_.close(ec);
        ioc_.stop();
        if (listener_thread_.joinable()) {
            listener_thread_.join();
        }
    }

    /**
     * Check if the listener is currently accepting connections.
     */
    [[nodiscard]] bool isRunning() const noexcept { return is_running_; }

private:
    // Accept loop (asynchronous)
    void doAccept() {
        acceptor_.async_accept(
            boost::asio::make_strand(ioc_),
            [this](boost::system::error_code ec, boost::asio::ip::tcp::socket socket) {
                if (!ec) {
                    // Spawn a detached session
                    std::thread(&FhirHttpListener::doSession, this, std::move(socket)).detach();
                } else {
                    // TODO: route to central logging / metrics
                }

                // Continue accepting next connections if still running
                if (is_running_) {
                    doAccept();
                }
            });
    }

    // Per-connection session (synchronous, isolated thread)
    void doSession(boost::asio::ip::tcp::socket socket) {
        using namespace boost::beast;
        using http::field;
        using http::status;
        using http::verb;
        namespace asio = boost::asio;

        bool keep_alive = true;

        try {
            while (keep_alive && is_running_) {
                flat_buffer buffer;

                // 1. Read request
                http::request<http::string_body> req;
                http::read(socket, buffer, req);

                keep_alive = req.keep_alive();

                // 2. Validate verb and content type
                if (req.method() != verb::post) {
                    http::response<http::string_body> res{status::method_not_allowed,
                                                          req.version()};
                    res.set(field::server, "CardioInsight360/FhirHttpListener");
                    res.set(field::content_type, "text/plain");
                    res.keep_alive(keep_alive);
                    res.body() = "Only HTTP POST is supported.\n";
                    res.prepare_payload();
                    http::write(socket, res);
                    continue;
                }

                if (req.body().size() > max_body_size_) {
                    http::response<http::string_body> res{status::payload_too_large,
                                                          req.version()};
                    res.set(field::content_type, "text/plain");
                    res.body() = "Payload exceeds configured size limit.\n";
                    res.prepare_payload();
                    http::write(socket, res);
                    continue;
                }

                // 3. Basic JSON sanity check
                try {
                    auto json = nlohmann::json::parse(req.body(), /* allow_exceptions = */ true,
                                                      /* ignore_comments   = */ true);
                    (void)json;  // we only need to ensure parseability
                } catch (const nlohmann::json::parse_error&) {
                    http::response<http::string_body> res{status::bad_request, req.version()};
                    res.set(field::content_type, "text/plain");
                    res.body() = "Malformed JSON payload.\n";
                    res.prepare_payload();
                    http::write(socket, res);
                    continue;
                }

                // 4. Dispatch to handler
                try {
                    handler_(req.body());
                } catch (const std::exception& ex) {
                    // Downstream failure – log but do not expose internals
                    http::response<http::string_body> res{status::internal_server_error,
                                                          req.version()};
                    res.set(field::content_type, "text/plain");
                    res.body() = "Internal ingestion error.\n";
                    res.prepare_payload();
                    http::write(socket, res);
                    continue;
                }

                // 5. Respond OK
                http::response<http::string_body> res{status::accepted, req.version()};
                res.set(field::server, "CardioInsight360/FhirHttpListener");
                res.set(field::content_type, "text/plain");
                res.keep_alive(keep_alive);
                res.body() = "FHIR bundle accepted.\n";
                res.prepare_payload();
                http::write(socket, res);

                // Allow client to gracefully close connection
                if (!keep_alive) {
                    break;
                }
            }
        } catch (const std::exception&) {
            // Suppress low-level transport errors; connection will be closed
        }

        // Ensure socket is closed
        boost::system::error_code ec;
        socket.shutdown(boost::asio::ip::tcp::socket::shutdown_both, ec);
        socket.close(ec);
    }

private:
    const std::string address_;
    const std::uint16_t port_;
    std::atomic_bool is_running_{false};
    const std::size_t max_body_size_;
    const RawMessageHandler handler_;

    // Networking primitives
    boost::asio::io_context ioc_;
    boost::asio::ip::tcp::acceptor acceptor_;

    // Listener thread
    std::thread listener_thread_;
};

}  // namespace cardio::ingestion

#endif  // CARDIO_INSIGHT_360_SRC_INGESTION_CONNECTORS_FHIR_HTTP_LISTENER_H_
