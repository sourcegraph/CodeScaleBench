```cpp
/**
 *  MosaicBoard Studio
 *  File: src/core/WebSocketManager.cpp
 *
 *  Description:
 *  ------------
 *  Centralised WebSocket façade that exposes a simple, thread–safe API
 *  for:
 *      • Broadcasting dashboard events to all connected clients
 *      • Unicasting replies to a specific client
 *      • Transparently handling TLS and non-TLS transports
 *      • Performing token-based authentication during the WebSocket
 *        handshake
 *      • Caching the N most-recent events so late-joiners receive the
 *        latest dashboard state
 *
 *  The implementation is based on `websocketpp` (header-only) with
 *  Boost.Asio as the transport layer.  
 *
 *  Build Dependencies:
 *      • websocketpp (https://github.com/zaphoyd/websocketpp)
 *      • Boost (>= 1.70) – system, thread, chrono
 *      • nlohmann/json (for payload parsing/serialisation)
 *      • spdlog          (structured logging)
 */

#include "WebSocketManager.hpp"            // Manager definition
#include "core/Configuration.hpp"          // Global config accessor
#include "core/EventBus.hpp"               // Internal event bus
#include "security/AuthService.hpp"        // JWT/Session validation
#include "util/LRUCache.hpp"               // Recent message cache

#include <websocketpp/config/asio_client.hpp>
#include <websocketpp/config/asio.hpp>
#include <websocketpp/server.hpp>

#include <boost/asio/ssl/context.hpp>
#include <boost/asio/signal_set.hpp>

#include <nlohmann/json.hpp>

#include <spdlog/spdlog.h>
#include <spdlog/fmt/bin_to_hex.h>

#include <chrono>
#include <thread>
#include <utility>
#include <exception>
#include <mutex>

using json = nlohmann::json;

namespace mosaic::core
{
    // ──────────────────────────────────────────────────────────────────────────
    //  Type aliases
    // ──────────────────────────────────────────────────────────────────────────
    namespace detail
    {
        // Non-TLS
        using websocket_server = websocketpp::server<websocketpp::config::asio>;
        // TLS
        using websocket_tls_server = websocketpp::server<websocketpp::config::asio_tls>;
    } // namespace detail

    // ──────────────────────────────────────────────────────────────────────────
    //  Helpers
    // ──────────────────────────────────────────────────────────────────────────
    static constexpr std::size_t kDefaultCacheSize = 128u;
    static constexpr std::chrono::seconds kHandshakeTimeout{ 10 };

    // Convert websocketpp error codes to readable strings
    inline std::string to_string(const websocketpp::lib::error_code& ec)
    {
        return ec ? (ec.message() + " (" + std::to_string(ec.value()) + ")") : "OK";
    }

    // ──────────────────────────────────────────────────────────────────────────
    //  WebSocketManager Implementation
    // ──────────────────────────────────────────────────────────────────────────
    WebSocketManager::WebSocketManager()
    : _cfg{ core::Configuration::instance() }
    , _ioCtx{ static_cast<unsigned int>(std::thread::hardware_concurrency()) }
    , _cache{ kDefaultCacheSize }
    , _authSvc{ std::make_unique<security::AuthService>() }
    , _signals{ _ioCtx, SIGINT, SIGTERM }
    {
        // Register to internal event bus
        EventBus::instance().subscribe(EventType::Broadcast,
            [this](const json& payload) { this->broadcast(payload.dump()); });

        // Handle POSIX signals for graceful shutdown
        _signals.async_wait([this](const boost::system::error_code& ec, int /*signo*/)
        {
            if (!ec)
            {
                spdlog::info("[WS] Received termination signal, stopping I/O context.");
                this->stop();
            }
        });
    }

    WebSocketManager::~WebSocketManager()
    {
        stop();
    }

    //---------------------------------------------------------------------------
    // Public API
    //---------------------------------------------------------------------------
    void WebSocketManager::start()
    {
        std::scoped_lock lk{ _stateMtx };
        if (_running)
        {
            spdlog::warn("[WS] Attempted to start WebSocketManager, but it is already running.");
            return;
        }

        _running = true;

        // Decide whether we need TLS
        if (_cfg.websocket().useTls)
            _serverVariant.emplace<ServerType::TLS>(std::in_place_type<detail::websocket_tls_server>, _ioCtx);
        else
            _serverVariant.emplace<ServerType::Plain>(std::in_place_type<detail::websocket_server>, _ioCtx);

        std::visit([this](auto& server) { configureServer(server); }, _serverVariant);

        // Start listener
        const auto endpoint = _cfg.websocket().endpoint;
        spdlog::info("[WS] Starting WebSocket server on {}", endpoint);

        websocketpp::lib::error_code ec;
        std::visit([&](auto& server) { server.listen(endpoint.port(), ec); }, _serverVariant);
        if (ec)
            throw std::runtime_error("[WS] listen() failed: " + to_string(ec));

        std::visit([](auto& server)
        {
            websocketpp::lib::error_code ec;
            server.start_accept(ec);
            if (ec)
                throw std::runtime_error("[WS] start_accept() failed: " + to_string(ec));
        }, _serverVariant);

        // Launch I/O threads
        const auto threads = std::max(1u, _cfg.websocket().ioThreads);
        for (unsigned i = 0; i < threads; ++i)
        {
            _workers.emplace_back([this]
            {
                spdlog::debug("[WS] Worker thread started.");
                try { _ioCtx.run(); }
                catch (const std::exception& ex)
                {
                    spdlog::error("[WS] Worker thread exception: {}", ex.what());
                }
                spdlog::debug("[WS] Worker thread terminated.");
            });
        }
    }

    void WebSocketManager::stop()
    {
        std::scoped_lock lk{ _stateMtx };
        if (!_running) return;

        spdlog::info("[WS] Stopping WebSocket server...");
        websocketpp::lib::error_code ignore;
        std::visit([&](auto& server) { server.stop_listening(); }, _serverVariant);
        for (auto& hdl : _connections)
        {
            std::visit([&](auto& server) { server.close(hdl, websocketpp::close::status::going_away, "Server Shutdown", ignore); }, _serverVariant);
        }

        _ioCtx.stop();

        for (auto& t : _workers)
            if (t.joinable()) t.join();
        _workers.clear();
        _connections.clear();
        _running = false;
    }

    void WebSocketManager::broadcast(const std::string& payload)
    {
        std::shared_lock lock{ _connMtx };

        if (_connections.empty())
            return;

        for (const auto& hdl : _connections)
        {
            websocketpp::lib::error_code ec;
            std::visit([&](auto& server) { server.send(hdl, payload, websocketpp::frame::opcode::text, ec); },
                       _serverVariant);
            if (ec)
                spdlog::warn("[WS] Broadcast failed to {} – {}", static_cast<void*>(hdl.lock().get()), to_string(ec));
        }

        // Cache last message
        _cache.put(std::chrono::steady_clock::now(), payload);
    }

    void WebSocketManager::sendTo(connection_hdl hdl, const json& msg)
    {
        websocketpp::lib::error_code ec;
        const auto payload = msg.dump();

        std::visit([&](auto& server) { server.send(hdl, payload, websocketpp::frame::opcode::text, ec); },
                   _serverVariant);
        if (ec)
            spdlog::warn("[WS] sendTo() failed – {}", to_string(ec));
    }

    //---------------------------------------------------------------------------
    // Private: Server Configuration
    //---------------------------------------------------------------------------
    template <typename ServerT>
    void WebSocketManager::configureServer(ServerT& server)
    {
        // Generic options
        server.set_reuse_addr(true);
        server.set_access_channels(websocketpp::log::alevel::none); // spdlog handles logging
        server.init_asio(&_ioCtx);
        server.clear_access_channels(websocketpp::log::alevel::all);
        server.set_open_handler([this](connection_hdl hdl) { this->handleOpen(hdl); });
        server.set_close_handler([this](connection_hdl hdl) { this->handleClose(hdl); });
        server.set_message_handler([this](connection_hdl hdl, auto msg) { this->handleMessage(hdl, msg); });
        server.set_validate_handler([this](connection_hdl hdl) { return this->handleValidate(hdl); });

        if constexpr (std::is_same_v<ServerT, detail::websocket_tls_server>)
        {
            server.set_tls_init_handler([this](connection_hdl /*hdl*/)
            {
                auto ctx = std::make_shared<boost::asio::ssl::context>(boost::asio::ssl::context::tls_server);
                const auto& certCfg = _cfg.tls();

                ctx->set_options(boost::asio::ssl::context::default_workarounds |
                                 boost::asio::ssl::context::no_sslv2 |
                                 boost::asio::ssl::context::single_dh_use);

                ctx->use_certificate_chain_file(certCfg.certChain);
                ctx->use_private_key_file(certCfg.privateKey, boost::asio::ssl::context::pem);
                if (!certCfg.tmpDh.empty())
                    ctx->use_tmp_dh_file(certCfg.tmpDh);

                return ctx;
            });
        }
    }

    //---------------------------------------------------------------------------
    // Private: Handlers
    //---------------------------------------------------------------------------
    void WebSocketManager::handleOpen(connection_hdl hdl)
    {
        {
            std::scoped_lock lk{ _connMtx };
            _connections.insert(hdl);
        }

        spdlog::info("[WS] Client [{}] connected. Active: {}", static_cast<void*>(hdl.lock().get()), _connections.size());

        // Flush recent cache
        for (const auto& [ts, payload] : _cache.snapshot())
        {
            websocketpp::lib::error_code ec;
            std::visit([&](auto& server) { server.send(hdl, payload, websocketpp::frame::opcode::text, ec); },
                       _serverVariant);
            if (ec)
                spdlog::warn("[WS] Failed cache replay to {} – {}", static_cast<void*>(hdl.lock().get()), to_string(ec));
        }
    }

    void WebSocketManager::handleClose(connection_hdl hdl)
    {
        {
            std::scoped_lock lk{ _connMtx };
            _connections.erase(hdl);
        }
        spdlog::info("[WS] Client [{}] disconnected. Active: {}", static_cast<void*>(hdl.lock().get()), _connections.size());
    }

    bool WebSocketManager::handleValidate(connection_hdl hdl)
    {
        using req_t = typename detail::websocket_server::request_type; // same for TLS variant

        auto req = std::visit([](auto& server) -> const req_t& { return server.get_con_from_hdl(server.get_con_from_hdl()).get_request(); }, _serverVariant); // intentionally verbose

        const auto tokenIter = req.get_header_map().find("Sec-WebSocket-Protocol");
        const std::string token = (tokenIter != req.get_header_map().end()) ? tokenIter->second : "";

        bool authorised = false;
        try
        {
            authorised = _authSvc->validateToken(token);
        }
        catch (const std::exception& ex)
        {
            spdlog::warn("[WS] Auth validation error: {}", ex.what());
            authorised = false;
        }

        if (!authorised)
            spdlog::warn("[WS] Rejecting connection – invalid token.");

        return authorised;
    }

    template <typename MessagePtr>
    void WebSocketManager::handleMessage(connection_hdl hdl, MessagePtr msg)
    {
        const auto opcode = msg->get_opcode();
        if (opcode != websocketpp::frame::opcode::text)
        {
            spdlog::debug("[WS] Ignoring non-text frame (opcode {}).", std::to_string(opcode));
            return;
        }

        try
        {
            auto payload = json::parse(msg->get_payload());

            // Dispatch to event bus
            EventBus::instance().publish(EventType::ClientMessage, payload);

            // Optionally echo
            if (payload.value("echo", false))
                sendTo(hdl, payload);
        }
        catch (const std::exception& ex)
        {
            spdlog::warn("[WS] Malformed JSON from client: {}", ex.what());
            json err = { { "type", "error" }, { "message", "Invalid JSON payload" } };
            sendTo(hdl, err);
        }
    }

} // namespace mosaic::core
```
