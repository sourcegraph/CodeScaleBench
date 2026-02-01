#pragma once
/*
 *  MosaicBoard Studio
 *  WebSocketManager.h
 *
 *  A production-quality, header-only WebSocket service built on
 *  Boost.Asio / Boost.Beast.  The manager accepts secure or plain
 *  WebSocket connections, assigns each client a unique session id,
 *  exposes a thread-safe API for broadcasting / targeted messaging,
 *  and relays incoming frames to the rest of the application by way
 *  of a user-supplied callback.
 *
 *  This header is self-contained: just include it in exactly one
 *  translation unit before use (or add `BOOST_BEAST_SEPARATE_COMPILATION`
 *  to your build if you prefer the traditional split).
 *
 *  NOTE: link against Boost.System, Boost.Thread, and OpenSSL when
 *  building with TLS enabled (`-DMBS_WEBSOCKET_TLS=1`).
 */

#include <boost/asio.hpp>
#include <boost/beast/websocket.hpp>
#include <boost/beast/ssl.hpp>
#include <boost/beast/_experimental/role.hpp>
#include <boost/uuid/uuid.hpp>
#include <boost/uuid/uuid_generators.hpp>
#include <boost/uuid/uuid_io.hpp>

#include <atomic>
#include <functional>
#include <map>
#include <memory>
#include <mutex>
#include <shared_mutex>
#include <string>
#include <thread>
#include <unordered_map>
#include <vector>

#ifndef MBS_WEBSOCKET_TLS
#   define MBS_WEBSOCKET_TLS 0
#endif

#if MBS_WEBSOCKET_TLS
#   include <openssl/ssl.h>
#endif

namespace mbs::core {

namespace beast   = boost::beast;       // from <boost/beast.hpp>
namespace websocket = beast::websocket;
namespace net     = boost::asio;        // from <boost/asio.hpp>
using     tcp     = boost::asio::ip::tcp;

/*-----------------------------------------------------------
 * Minimal logging helpers
 *----------------------------------------------------------*/
#ifndef MBS_LOG_ERROR
#   include <iostream>
#   define MBS_LOG_ERROR(msg)   std::cerr << "[WebSocketManager:ERR] " << msg << '\n'
#   define MBS_LOG_INFO(msg)    std::cout << "[WebSocketManager:INF] " << msg << '\n'
#endif

/*-----------------------------------------------------------
 * WebSocketManager
 *----------------------------------------------------------*/
class WebSocketManager : public std::enable_shared_from_this<WebSocketManager>
{
public:
    using Ptr             = std::shared_ptr<WebSocketManager>;
    using MessageHandler  = std::function<void(const std::string& /*clientId*/,
                                               const std::string& /*payload*/)>;

    /*-------------------------------------------------------
     * Factory
     *------------------------------------------------------*/
    template <typename... Args>
    static Ptr create(Args&&... args)
    {
        return Ptr(new WebSocketManager(std::forward<Args>(args)...));
    }

    /*-------------------------------------------------------
     * Construction
     *------------------------------------------------------*/
    explicit WebSocketManager(std::size_t threadCount = std::thread::hardware_concurrency())
        : ioc_{static_cast<int>(threadCount)}
#if MBS_WEBSOCKET_TLS
        , ssl_ctx_{boost::asio::ssl::context::tlsv12_server}
#endif
        , threadCount_{threadCount}
    {
#if MBS_WEBSOCKET_TLS
        // NOTE: In production you will load proper certificates here.
        ssl_ctx_.set_default_verify_paths();
        ssl_ctx_.set_options(
            boost::asio::ssl::context::default_workarounds
            | boost::asio::ssl::context::no_sslv2
            | boost::asio::ssl::context::no_sslv3
            | boost::asio::ssl::context::single_dh_use);
#endif
    }

    ~WebSocketManager()
    {
        stop();
    }

    WebSocketManager(const WebSocketManager&)            = delete;
    WebSocketManager& operator=(const WebSocketManager&) = delete;

    /*-------------------------------------------------------
     * Set callback for incoming messages
     *------------------------------------------------------*/
    void setMessageHandler(MessageHandler h) noexcept
    {
        std::unique_lock lock(cbMutex_);
        handler_ = std::move(h);
    }

    /*-------------------------------------------------------
     * Start listening for clients
     *------------------------------------------------------*/
    void listen(uint16_t port)
    {
        if (acceptor_) {
            throw std::runtime_error("WebSocketManager already listening");
        }

        tcp::endpoint endpoint{tcp::v4(), port};
        acceptor_ = std::make_unique<tcp::acceptor>(ioc_);

        boost::system::error_code ec;
        acceptor_->open(endpoint.protocol(), ec);
        if (ec) {
            throw std::runtime_error("Failed to open acceptor: " + ec.message());
        }

        acceptor_->set_option(boost::asio::socket_base::reuse_address(true), ec);
        if (ec) {
            throw std::runtime_error("Failed to set acceptor option: " + ec.message());
        }

        acceptor_->bind(endpoint, ec);
        if (ec) {
            throw std::runtime_error("Failed to bind acceptor: " + ec.message());
        }

        acceptor_->listen(boost::asio::socket_base::max_listen_connections, ec);
        if (ec) {
            throw std::runtime_error("Failed to listen: " + ec.message());
        }

        doAccept();

        // Spin up thread pool
        for (std::size_t i = 0; i < threadCount_; ++i) {
            threads_.emplace_back([self = shared_from_this()] {
                self->ioc_.run();
            });
        }

        MBS_LOG_INFO("WebSocket server listening on port " << port);
    }

    /*-------------------------------------------------------
     * Graceful shutdown
     *------------------------------------------------------*/
    void stop()
    {
        if (stopped_.exchange(true)) return;

        MBS_LOG_INFO("Stopping WebSocketManager...");

        // Stop accepting new connections
        boost::system::error_code ec;
        if (acceptor_) {
            acceptor_->cancel(ec);
            acceptor_->close(ec);
        }

        // Close existing sessions
        {
            std::shared_lock lock(sessionsMutex_);
            for (auto& [_, weak] : sessions_) {
                if (auto s = weak.lock()) {
                    s->close();
                }
            }
        }

        ioc_.stop();
        for (auto& t : threads_) {
            if (t.joinable()) t.join();
        }

        MBS_LOG_INFO("WebSocketManager stopped");
    }

    /*-------------------------------------------------------
     * Broadcast helpers
     *------------------------------------------------------*/
    void broadcast(std::string message)
    {
        std::shared_lock lock(sessionsMutex_);
        for (auto& [_, weak] : sessions_) {
            if (auto s = weak.lock()) {
                s->send(message);
            }
        }
    }

    void sendTo(const std::string& clientId, std::string message)
    {
        std::shared_lock lock(sessionsMutex_);
        auto it = sessions_.find(clientId);
        if (it != sessions_.end()) {
            if (auto s = it->second.lock()) {
                s->send(std::move(message));
            }
        }
    }

    std::vector<std::string> connectedClients() const
    {
        std::vector<std::string> out;
        std::shared_lock lock(sessionsMutex_);
        out.reserve(sessions_.size());
        for (auto& [k, v] : sessions_) {
            if (!v.expired()) out.push_back(k);
        }
        return out;
    }

private:
    /*-------------------------------------------------------
     * Inner Session
     *------------------------------------------------------*/
    class Session : public std::enable_shared_from_this<Session>
    {
    public:
#if MBS_WEBSOCKET_TLS
        using Stream = websocket::stream<beast::ssl_stream<tcp::socket>>;
#else
        using Stream = websocket::stream<tcp::socket>;
#endif
        template <typename Socket>
        Session(WebSocketManager& owner, Socket&& socket)
            : owner_{owner}
#if MBS_WEBSOCKET_TLS
              , ws_{std::move(socket)}
#else
              , ws_(std::move(socket))
#endif
        {
            // Generate unique session id
            id_ = boost::uuids::to_string(boost::uuids::random_generator()());
        }

        ~Session() = default;
        Session(const Session&)            = delete;
        Session& operator=(const Session&) = delete;

        void run()
        {
            auto self = shared_from_this();

#if MBS_WEBSOCKET_TLS
            ws_.next_layer().async_handshake(
                boost::asio::ssl::stream_base::server,
                [self](beast::error_code ec) {
                    if (ec) {
                        MBS_LOG_ERROR("TLS handshake failed: " << ec.message());
                        return;
                    }
                    self->onHandshake();
                });
#else
            onHandshake();
#endif
        }

        void close()
        {
            beast::error_code ec;
            ws_.close(websocket::close_code::normal, ec);
        }

        void send(std::string message)
        {
            net::post(ws_.get_executor(),
                      [self = shared_from_this(), msg = std::move(message)]() mutable {
                          self->outbox_.push_back(std::move(msg));
                          if (self->outbox_.size() > 1) {
                              // write already in progress
                              return;
                          }
                          self->doWrite();
                      });
        }

        const std::string& id() const noexcept { return id_; }

    private:
        void onHandshake()
        {
            // Accept WebSocket handshake
            ws_.set_option(websocket::stream_base::timeout::suggested(beast::role_type::server));

            ws_.set_option(websocket::stream_base::decorator(
                [](websocket::response_type& res) {
                    res.set(boost::beast::http::field::server, "MosaicBoard Studio");
                }));

            ws_.async_accept(beast::bind_front_handler(&Session::onAccept, shared_from_this()));
        }

        void onAccept(beast::error_code ec)
        {
            if (ec) {
                MBS_LOG_ERROR("WebSocket accept failed: " << ec.message());
                return;
            }

            owner_.registerSession(shared_from_this());

            doRead();
        }

        void doRead()
        {
            ws_.async_read(buffer_, beast::bind_front_handler(&Session::onRead, shared_from_this()));
        }

        void onRead(beast::error_code ec, std::size_t bytes)
        {
            boost::ignore_unused(bytes);
            if (ec == websocket::error::closed) {
                // Normal closure
                owner_.unregisterSession(id_);
                return;
            }
            if (ec) {
                MBS_LOG_ERROR("Read error: " << ec.message());
                owner_.unregisterSession(id_);
                return;
            }

            std::string payload{
                beast::buffers_to_string(buffer_.data())
            };
            buffer_.consume(buffer_.size());

            // Pass payload to upper layer
            owner_.dispatchIncoming(id_, std::move(payload));

            doRead();
        }

        void doWrite()
        {
            ws_.async_write(net::buffer(outbox_.front()),
                            [self = shared_from_this()](beast::error_code ec, std::size_t) {
                                if (ec) {
                                    MBS_LOG_ERROR("Write error: " << ec.message());
                                    self->owner_.unregisterSession(self->id_);
                                    return;
                                }
                                self->outbox_.erase(self->outbox_.begin());
                                if (!self->outbox_.empty()) {
                                    self->doWrite();
                                }
                            });
        }

        WebSocketManager& owner_;
        Stream            ws_;
        beast::flat_buffer buffer_;
        std::vector<std::string> outbox_;
        std::string       id_;
    };

    /*-------------------------------------------------------
     * Accept loop
     *------------------------------------------------------*/
    void doAccept()
    {
        acceptor_->async_accept(
            net::make_strand(ioc_),
            beast::bind_front_handler(&WebSocketManager::onAccept, shared_from_this()));
    }

    void onAccept(beast::error_code ec, tcp::socket socket)
    {
        if (ec) {
            if (!stopped_) {
                MBS_LOG_ERROR("Accept error: " << ec.message());
                doAccept();
            }
            return;
        }

        // Launch session
#if MBS_WEBSOCKET_TLS
        auto sslStream = beast::ssl_stream<tcp::socket>(std::move(socket), ssl_ctx_);
        auto session   = std::make_shared<Session>(*this, std::move(sslStream));
#else
        auto session   = std::make_shared<Session>(*this, std::move(socket));
#endif
        session->run();

        doAccept();
    }

    /*-------------------------------------------------------
     * Session registration
     *------------------------------------------------------*/
    void registerSession(std::shared_ptr<Session> s)
    {
        {
            std::unique_lock lock(sessionsMutex_);
            sessions_[s->id()] = s;
        }

        MBS_LOG_INFO("Client connected: " << s->id());
    }

    void unregisterSession(const std::string& id)
    {
        std::unique_lock lock(sessionsMutex_);
        sessions_.erase(id);
        MBS_LOG_INFO("Client disconnected: " << id);
    }

    /*-------------------------------------------------------
     * Dispatch incoming frames to the application
     *------------------------------------------------------*/
    void dispatchIncoming(const std::string& clientId, std::string payload)
    {
        MessageHandler cbCopy;
        {
            std::shared_lock lock(cbMutex_);
            cbCopy = handler_;
        }

        if (cbCopy) {
            try {
                cbCopy(clientId, std::move(payload));
            } catch (const std::exception& ex) {
                MBS_LOG_ERROR("Message handler threw: " << ex.what());
            }
        }
    }

    /*-------------------------------------------------------
     * Data members
     *------------------------------------------------------*/
    net::io_context                ioc_;
#if MBS_WEBSOCKET_TLS
    boost::asio::ssl::context      ssl_ctx_;
#endif
    std::size_t                    threadCount_;
    std::unique_ptr<tcp::acceptor> acceptor_;
    std::vector<std::thread>       threads_;
    std::atomic_bool               stopped_{false};

    std::unordered_map<std::string, std::weak_ptr<Session>> sessions_;
    mutable std::shared_mutex      sessionsMutex_;

    MessageHandler                 handler_;
    mutable std::shared_mutex      cbMutex_;
};

} // namespace mbs::core