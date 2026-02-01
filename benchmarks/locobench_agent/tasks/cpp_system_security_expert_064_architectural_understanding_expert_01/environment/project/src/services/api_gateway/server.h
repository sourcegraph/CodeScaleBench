#ifndef FORTILEDGER360_SERVICES_API_GATEWAY_SERVER_H
#define FORTILEDGER360_SERVICES_API_GATEWAY_SERVER_H

/*
 *  FortiLedger360 – Enterprise Security Suite
 *
 *  File:    server.h
 *  Module:  API-Gateway (Presentation & API Layer)
 *
 *  Description:
 *      Lightweight, production-grade HTTP/JSON gateway that receives tenant
 *      requests, validates basic semantics and publishes them as typed Commands
 *      onto the internal event-bus.  The implementation is intentionally kept
 *      header-only to simplify embedding in unit/integration tests and to avoid
 *      “*.cc” linker friction for downstream users who only need the gateway
 *      in-process.
 *
 *      – Uses Boost.Asio / Boost.Beast for non-blocking I/O
 *      – JSON serialization via nlohmann::json (de-facto std in modern C++)
 *      – Thread-safe, RAII-driven start/stop semantics
 *
 *  © 2024 FortiLedger Inc. — All rights reserved.
 */

#include <atomic>
#include <chrono>
#include <cstdint>
#include <exception>
#include <functional>
#include <iomanip>
#include <iostream>
#include <memory>
#include <mutex>
#include <optional>
#include <sstream>
#include <stdexcept>
#include <string>
#include <thread>
#include <utility>
#include <vector>

#include <boost/asio.hpp>
#include <boost/beast.hpp>
#include <boost/beast/core/flat_buffer.hpp>
#include <boost/beast/http/string_body.hpp>
#include <boost/beast/version.hpp>
#include <nlohmann/json.hpp>

// -----------------------------------------------------------------------------
// Forward declarations / namespace aliases
// -----------------------------------------------------------------------------
namespace fortiledger360::services::api_gateway {

// Aliases for convenience
namespace net  = boost::asio;          // from <boost/asio.hpp>
namespace beast = boost::beast;        // from <boost/beast.hpp>
namespace http = beast::http;
using tcp       = net::ip::tcp;

// -----------------------------------------------------------------------------
// Domain abstractions
// -----------------------------------------------------------------------------

// Lightweight representation of an inbound Command that will be forwarded to
// the internal event-bus.
struct Command
{
    std::string name;          // e.g. "InitiateSecurityScan"
    nlohmann::json payload;    // arbitrary tenant-supplied attributes
};

// Publish-only interface so that the API-Gateway does not depend on the exact
// messaging technology (Kafka, NATS, RabbitMQ, etc.).
class EventBusPublisher
{
public:
    virtual ~EventBusPublisher() = default;

    // Implementations must be thread-safe.
    virtual void publish(const Command& cmd) = 0;
};

// -----------------------------------------------------------------------------
// Configuration
// -----------------------------------------------------------------------------
struct GatewayOptions
{
    std::string      host               = "0.0.0.0";
    std::uint16_t    port               = 8180;
    std::size_t      thread_pool_size   = std::thread::hardware_concurrency();
    std::chrono::seconds shutdown_grace = std::chrono::seconds{5};
};

// -----------------------------------------------------------------------------
// Exception helpers
// -----------------------------------------------------------------------------
class GatewayError : public std::runtime_error
{
public:
    using std::runtime_error::runtime_error;
};

// -----------------------------------------------------------------------------
// ApiGatewayServer
// -----------------------------------------------------------------------------
class ApiGatewayServer : public std::enable_shared_from_this<ApiGatewayServer>
{
public:
    explicit ApiGatewayServer(GatewayOptions opts,
                              std::shared_ptr<EventBusPublisher> publisher)
        : opts_(std::move(opts)),
          publisher_(std::move(publisher)),
          ioc_(static_cast<int>(opts_.thread_pool_size)),
          acceptor_(ioc_),
          running_(false)
    {
        if (!publisher_)
        {
            throw GatewayError("EventBusPublisher dependency is null");
        }
    }

    // Non-copyable / non-movable
    ApiGatewayServer(const ApiGatewayServer&)            = delete;
    ApiGatewayServer& operator=(const ApiGatewayServer&) = delete;

    ~ApiGatewayServer()
    {
        try { stop(); }
        catch (...) { /* swallow in destructor */ }
    }

    // ---------------------------------------------------------------------
    // Lifecycle
    // ---------------------------------------------------------------------
    void start()
    {
        std::lock_guard<std::mutex> lock(lifecycle_mutex_);
        if (running_) { return; }

        // Resolve endpoint & bind socket
        tcp::endpoint endpoint{net::ip::make_address(opts_.host), opts_.port};

        beast::error_code ec;
        acceptor_.open(endpoint.protocol(), ec);
        if (ec) throw GatewayError("open: " + ec.message());

        acceptor_.set_option(net::socket_base::reuse_address(true), ec);
        if (ec) throw GatewayError("set_option: " + ec.message());

        acceptor_.bind(endpoint, ec);
        if (ec) throw GatewayError("bind: " + ec.message());

        acceptor_.listen(net::socket_base::max_listen_connections, ec);
        if (ec) throw GatewayError("listen: " + ec.message());

        // Kick-off async accept loop
        do_accept_();

        // Launch worker threads
        for (std::size_t i = 0; i < opts_.thread_pool_size; ++i)
        {
            workers_.emplace_back([self = shared_from_this()] {
                self->ioc_.run();
            });
        }

        running_.store(true, std::memory_order_release);

        std::ostringstream oss;
        oss << "[ApiGatewayServer] Listening on " << opts_.host
            << ":" << opts_.port << " with "
            << opts_.thread_pool_size << " worker threads\n";
        std::cerr << oss.str();
    }

    void stop()
    {
        std::lock_guard<std::mutex> lock(lifecycle_mutex_);
        if (!running_) { return; }

        // Stop accepting new clients
        beast::error_code ec;
        acceptor_.close(ec);

        // Stop I/O context after grace-period (allows inflight requests to finish)
        net::steady_timer timer{ioc_, opts_.shutdown_grace};
        timer.async_wait([&](auto) { ioc_.stop(); });

        // Join worker threads
        for (auto& t : workers_) if (t.joinable()) t.join();
        workers_.clear();

        running_.store(false, std::memory_order_release);
        std::cerr << "[ApiGatewayServer] Stopped\n";
    }

    [[nodiscard]] bool is_running() const noexcept
    {
        return running_.load(std::memory_order_acquire);
    }

private:
    // ---------------------------------------------------------------------
    // Networking plumbing
    // ---------------------------------------------------------------------
    void do_accept_()
    {
        acceptor_.async_accept(
            net::make_strand(ioc_),
            beast::bind_front_handler(&ApiGatewayServer::on_accept_,
                                      shared_from_this()));
    }

    void on_accept_(beast::error_code ec, tcp::socket socket)
    {
        if (ec)
        {
            if (ec != net::error::operation_aborted)
            {
                std::cerr << "[ApiGatewayServer] accept error: "
                          << ec.message() << '\n';
            }
        }
        else
        {
            // Create per-connection session
            std::make_shared<Session>(std::move(socket), publisher_)->run();
        }

        // Accept next connection
        if (acceptor_.is_open())
        {
            do_accept_();
        }
    }

    // ---------------------------------------------------------------------
    // Inner Session class (handles a single TCP connection)
    // ---------------------------------------------------------------------
    class Session : public std::enable_shared_from_this<Session>
    {
    public:
        Session(tcp::socket socket,
                std::shared_ptr<EventBusPublisher> publisher)
            : socket_(std::move(socket)),
              publisher_(std::move(publisher))
        {
        }

        // Start the asynchronous operation
        void run()
        {
            net::dispatch(socket_.get_executor(),
                          beast::bind_front_handler(&Session::do_read_,
                                                    shared_from_this()));
        }

    private:
        void do_read_()
        {
            req_ = {}; // Clear previous request
            socket_.expires_after(std::chrono::seconds(30));

            http::async_read(
                socket_, buffer_, req_,
                beast::bind_front_handler(&Session::on_read_,
                                          shared_from_this()));
        }

        void on_read_(beast::error_code ec,
                      std::size_t /*bytes_transferred*/)
        {
            if (ec == http::error::end_of_stream)
                return do_close_();

            if (ec)
            {
                std::cerr << "[Session] read error: " << ec.message() << '\n';
                return;
            }

            handle_request_();

            // If not keep-alive, close socket after write
            if(!res_.keep_alive())
            {
                res_.prepare_payload();
                http::async_write(
                    socket_, res_,
                    beast::bind_front_handler(&Session::on_write_,
                                              shared_from_this(),
                                              res_.need_eof()));
            }
            else
            {
                res_.prepare_payload();
                http::async_write(
                    socket_, res_,
                    beast::bind_front_handler(&Session::on_write_,
                                              shared_from_this(), false));
            }
        }

        void on_write_(bool close,
                       beast::error_code ec,
                       std::size_t /*bytes_transferred*/)
        {
            if (ec)
            {
                std::cerr << "[Session] write error: "
                          << ec.message() << '\n';
                return;
            }

            if (close)
                return do_close_();

            // Continue reading next request on same connection
            do_read_();
        }

        void do_close_()
        {
            beast::error_code ec;
            socket_.shutdown(tcp::socket::shutdown_send, ec);
            // ignore not_connected
        }

        // -------------------------------------------------------------
        // Business logic
        // -------------------------------------------------------------
        void handle_request_()
        {
            res_.version(req_.version());
            res_.set(http::field::server, "FortiLedger360/1.0");

            // Basic validation (method + content-type)
            if (req_.method() != http::verb::post ||
                req_.target() != "/v1/commands")
            {
                res_.result(http::status::not_found);
                res_.set(http::field::content_type, "text/plain");
                res_.body() = "Unsupported endpoint";
                return;
            }

            auto contentTypeIt = req_.find(http::field::content_type);
            if (contentTypeIt == req_.end() ||
                contentTypeIt->value() != "application/json")
            {
                res_.result(http::status::unsupported_media_type);
                res_.set(http::field::content_type, "text/plain");
                res_.body() = "Content-Type must be application/json";
                return;
            }

            // Parse JSON body
            nlohmann::json jsonBody;
            try
            {
                jsonBody = nlohmann::json::parse(req_.body());
            }
            catch (const std::exception& ex)
            {
                res_.result(http::status::bad_request);
                res_.set(http::field::content_type, "text/plain");
                res_.body() = std::string("Malformed JSON: ") + ex.what();
                return;
            }

            // Extract command & payload
            if (!jsonBody.contains("command") || !jsonBody["command"].is_string())
            {
                res_.result(http::status::bad_request);
                res_.set(http::field::content_type, "text/plain");
                res_.body() = "Missing \"command\" string property";
                return;
            }

            Command cmd;
            cmd.name    = jsonBody["command"].get<std::string>();
            cmd.payload = jsonBody.value("payload", nlohmann::json::object());

            try
            {
                publisher_->publish(cmd);
            }
            catch (const std::exception& ex)
            {
                res_.result(http::status::internal_server_error);
                res_.set(http::field::content_type, "text/plain");
                res_.body() = std::string("Failed to publish: ") + ex.what();
                return;
            }

            // OK – Accepted
            res_.result(http::status::accepted);
            res_.set(http::field::content_type, "application/json");
            res_.body() = R"({"status":"accepted"})";
        }

        // -------------------------------------------------------------
        // Data members
        // -------------------------------------------------------------
        tcp::socket socket_;
        std::shared_ptr<EventBusPublisher> publisher_;
        beast::flat_buffer buffer_;
        http::request<http::string_body>  req_;
        http::response<http::string_body> res_;
    };

    // ---------------------------------------------------------------------
    // Data members
    // ---------------------------------------------------------------------
    GatewayOptions                     opts_;
    std::shared_ptr<EventBusPublisher> publisher_;

    net::io_context                    ioc_;
    tcp::acceptor                      acceptor_;
    std::vector<std::thread>           workers_;
    std::atomic<bool>                  running_;
    std::mutex                         lifecycle_mutex_;
};

} // namespace fortiledger360::services::api_gateway

#endif // FORTILEDGER360_SERVICES_API_GATEWAY_SERVER_H