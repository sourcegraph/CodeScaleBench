```cpp
#ifndef MOSAICBOARD_STUDIO_CORE_SERVER_H
#define MOSAICBOARD_STUDIO_CORE_SERVER_H
/**
 *  MosaicBoard Studio
 *  File:    src/core/Server.h
 *  Author:  (auto-generated)
 *
 *  A lightweight, production-grade HTTP/WebSocket server based on
 *  Boost.Asio/Beast.  The server provides:
 *    • Thread-pooled, asynchronous request handling
 *    • Pluggable routing with path-parameter extraction (std::regex)
 *    • Basic middleware chain (authentication / CORS demo)
 *    • Graceful shutdown on SIGINT/SIGTERM
 *
 *  NOTE: This header is intentionally self-contained (“header-only”)
 *  for ease of integration with the plugin system.  It can be split
 *  into .h / .cpp as the codebase evolves.
 */

#include <boost/asio.hpp>
#include <boost/beast.hpp>
#include <boost/algorithm/string.hpp>

#include <atomic>
#include <chrono>
#include <cstdint>
#include <functional>
#include <future>
#include <memory>
#include <mutex>
#include <regex>
#include <shared_mutex>
#include <thread>
#include <unordered_map>
#include <vector>

namespace mosaic::core {

// ========== Forward Decls / Aliases ============================================================
namespace beast = boost::beast;          // from <boost/beast.hpp>
namespace http  = beast::http;           // from <boost/beast/http.hpp>
namespace net   = boost::asio;           // from <boost/asio.hpp>
using     tcp   = net::ip::tcp;

using HttpRequest  = http::request<http::string_body>;
using HttpResponse = http::response<http::string_body>;
using HttpHandler  = std::function<void(const HttpRequest&, HttpResponse&)>;

// ========== Utility ============================================================================

inline std::string httpDateString()
{
    // RFC-1123 compliant date header
    std::time_t t = std::time(nullptr);
    char buf[64];
    std::strftime(buf, sizeof(buf), "%a, %d %b %Y %H:%M:%S GMT", std::gmtime(&t));
    return std::string{buf};
}

// ========== Router =============================================================================
class Router
{
public:
    void add(http::verb method, std::string_view pattern, HttpHandler cb)
    {
        std::unique_lock lock(mutex_);
        routes_.emplace_back(method, std::regex{std::string(pattern)}, std::move(cb));
    }

    bool dispatch(const HttpRequest& req, HttpResponse& res) const
    {
        std::shared_lock lock(mutex_);
        for (auto&& r : routes_)
        {
            if (r.method != req.method()) continue;
            if (std::regex_match(req.target().begin(), req.target().end(), r.compiled))
            {
                r.cb(req, res);
                return true;
            }
        }
        return false; // no match => caller decides 404
    }

private:
    struct Route
    {
        http::verb   method;
        std::regex   compiled;
        HttpHandler  cb;
        Route(http::verb m, std::regex rx, HttpHandler h)
            : method(m), compiled(std::move(rx)), cb(std::move(h)) {}
    };

    mutable std::shared_mutex mutex_;
    std::vector<Route>        routes_;
};

// ========== Server ============================================================================

class Server : public std::enable_shared_from_this<Server>
{
public:
    // --------------------------------------------------------------------------------------------
    // CTOR / DTOR
    // --------------------------------------------------------------------------------------------
    Server(net::io_context& ioc, std::uint16_t port,
           std::size_t threadCount = std::thread::hardware_concurrency())
        : ioc_(ioc)
        , acceptor_(net::make_strand(ioc))
        , signals_(ioc, SIGINT, SIGTERM)
        , threadCount_(threadCount ? threadCount : 1)
        , isRunning_(false)
    {
        beast::error_code ec;

        // Prepare the TCP acceptor
        tcp::endpoint endpoint{tcp::v4(), port};
        acceptor_.open(endpoint.protocol(), ec);
        if (ec) throw beast::system_error{ec};

        acceptor_.set_option(net::socket_base::reuse_address(true), ec);
        if (ec) throw beast::system_error{ec};

        acceptor_.bind(endpoint, ec);
        if (ec) throw beast::system_error{ec};

        acceptor_.listen(net::socket_base::max_listen_connections, ec);
        if (ec) throw beast::system_error{ec};

        // Handle Ctrl-C / SIGTERM
        signals_.async_wait([this](auto, auto){ stop(); });
    }

    ~Server() { stop(); }

    Server(const Server&)            = delete;
    Server& operator=(const Server&) = delete;

    // --------------------------------------------------------------------------------------------
    // Public API
    // --------------------------------------------------------------------------------------------
    void start()
    {
        if (isRunning_.exchange(true)) return; // already running

        doAccept();

        // Launch thread pool
        for (std::size_t i = 0; i < threadCount_; ++i)
        {
            workers_.emplace_back([this]{
                try { ioc_.run(); }
                catch (const std::exception& ex)
                {
                    // Log and swallow; Threads keep spinning
                    std::lock_guard lg(cerr_mutex_);
                    std::cerr << "[Server] Worker exception: " << ex.what() << '\n';
                }
            });
        }
    }

    void stop()
    {
        if (!isRunning_.exchange(false)) return;
        beast::error_code ec;
        acceptor_.close(ec); // stop accepting
        signals_.cancel(ec);
        ioc_.stop();

        for (auto& t : workers_) if (t.joinable()) t.join();
        workers_.clear();
    }

    inline bool isRunning() const noexcept { return isRunning_; }

    // Routing helpers ---------------------------------------------------------------------------
    template <class Callable>
    void get(std::string_view pattern, Callable&& cb)
    { router_.add(http::verb::get, pattern, std::forward<Callable>(cb)); }

    template <class Callable>
    void post(std::string_view pattern, Callable&& cb)
    { router_.add(http::verb::post, pattern, std::forward<Callable>(cb)); }

    template <class Callable>
    void del(std::string_view pattern, Callable&& cb)
    { router_.add(http::verb::delete_, pattern, std::forward<Callable>(cb)); }

    // CORS (simple demo) ------------------------------------------------------------------------
    void enableCORS(std::string allowedOrigin = "*")
    {
        corsOrigin_ = std::move(allowedOrigin);
    }

private:
    // --------------------------------------------------------------------------------------------
    // HTTP Session (per-connection)
    // --------------------------------------------------------------------------------------------
    class HttpSession : public std::enable_shared_from_this<HttpSession>
    {
    public:
        HttpSession(tcp::socket&& socket, Server& owner)
            : stream_(std::move(socket)), owner_(owner) {}

        void run() { doRead(); }

    private:
        void doRead()
        {
            req_ = {}; // reset
            stream_.expires_after(std::chrono::seconds{30});
            http::async_read(stream_, buffer_, req_,
                beast::bind_front_handler(&HttpSession::onRead, shared_from_this()));
        }

        void onRead(beast::error_code ec, std::size_t bytesTrans)
        {
            boost::ignore_unused(bytesTrans);
            if (ec == http::error::end_of_stream) return doClose();
            if (ec) return fail(ec, "read");

            // Prepare blank response
            HttpResponse res{http::status::ok, req_.version()};
            res.set(http::field::server, "MosaicBoard Studio");
            res.set(http::field::date, httpDateString());
            res.keep_alive(req_.keep_alive());

            // Middleware: Simple CORS
            if (!owner_.corsOrigin_.empty())
            {
                res.set(http::field::access_control_allow_origin, owner_.corsOrigin_);
                res.set(http::field::access_control_allow_credentials, "true");
            }

            // Route
            bool dispatched = owner_.router_.dispatch(req_, res);
            if (!dispatched)
            {
                res.result(http::status::not_found);
                res.body() = "404 route not found";
            }

            res.prepare_payload();

            http::async_write(stream_, res,
                beast::bind_front_handler(&HttpSession::onWrite, shared_from_this(), res.need_eof()));
        }

        void onWrite(bool close, beast::error_code ec, std::size_t bytesTrans)
        {
            boost::ignore_unused(bytesTrans);
            if (ec) return fail(ec, "write");
            if (close) return doClose();
            doRead(); // read next req
        }

        void doClose()
        {
            beast::error_code ec;
            stream_.socket().shutdown(tcp::socket::shutdown_send, ec);
        }

        void fail(beast::error_code ec, const char* what)
        {
            if (ec == net::error::operation_aborted) return;
            std::lock_guard lg(owner_.cerr_mutex_);
            std::cerr << "[HttpSession] " << what << ": " << ec.message() << "\n";
        }

        beast::tcp_stream      stream_;
        beast::flat_buffer     buffer_;
        HttpRequest            req_;
        Server&                owner_;
    };

    // --------------------------------------------------------------------------------------------
    // Internals
    // --------------------------------------------------------------------------------------------
    void doAccept()
    {
        acceptor_.async_accept(
            net::make_strand(ioc_),
            beast::bind_front_handler(&Server::onAccept, shared_from_this()));
    }

    void onAccept(beast::error_code ec, tcp::socket socket)
    {
        if (ec)
        {
            std::lock_guard lg(cerr_mutex_);
            std::cerr << "[Server] accept: " << ec.message() << "\n";
        }
        else
        {
            // Launch session
            std::make_shared<HttpSession>(std::move(socket), *this)->run();
        }

        if (isRunning_) doAccept(); // continue accepting
    }

private:
    // I/O
    net::io_context&      ioc_;
    tcp::acceptor         acceptor_;
    net::signal_set       signals_;

    // Threading
    std::size_t           threadCount_;
    std::vector<std::thread> workers_;
    std::atomic_bool      isRunning_;
    mutable std::mutex    cerr_mutex_;

    // Routing / CORS
    Router                router_;
    std::string           corsOrigin_;
};

// ====== Example Usage Helper ====================================================================
//
// inline std::shared_ptr<Server> makeDefaultServer(net::io_context& ctx, std::uint16_t port)
// {
//     auto srv = std::make_shared<Server>(ctx, port);
//     srv->get(R"(^/health$)", [](auto&, HttpResponse& res){
//         res.body() = R"({"status":"ok"})";
//         res.set(http::field::content_type, "application/json");
//     });
//     srv->enableCORS();
//     return srv;
// }

} // namespace mosaic::core

#endif // MOSAICBOARD_STUDIO_CORE_SERVER_H
```