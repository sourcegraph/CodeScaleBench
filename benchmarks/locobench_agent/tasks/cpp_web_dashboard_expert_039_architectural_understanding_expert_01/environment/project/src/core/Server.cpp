#include "Server.h"

#include <boost/asio.hpp>
#include <boost/asio/ssl.hpp>
#include <boost/beast.hpp>
#include <boost/beast/ssl.hpp>
#include <boost/beast/http.hpp>
#include <boost/beast/version.hpp>

#include <nlohmann/json.hpp>
#include <spdlog/spdlog.h>

#include <atomic>
#include <chrono>
#include <csignal>
#include <filesystem>
#include <functional>
#include <thread>
#include <unordered_map>
#include <variant>

#ifdef _WIN32
    #include <windows.h>
#else
    #include <dlfcn.h>
#endif

#include "EventBus.h"   // Internal event bus abstraction
#include "Version.h"    // Auto-generated at build time
#include "Metrics.h"    // Internal metrics collector

namespace fs   = std::filesystem;
namespace http = boost::beast::http;

namespace mb::core
{

/* -------------------------------------------------------------------------- */
/*                          Helper types / aliases                            */
/* -------------------------------------------------------------------------- */

using tcp        = boost::asio::ip::tcp;
using string_req = http::request<http::string_body>;
using string_res = http::response<http::string_body>;

using RouteCb = std::function<string_res(const string_req &)>;

/* -------------------------------------------------------------------------- */
/*                                 ServerImpl                                 */
/* -------------------------------------------------------------------------- */

class Server::Impl
{
public:
    explicit Impl(const Options &opts)
        : opts_{opts},
          ioc_{static_cast<int>(opts.threadCount)},
          acceptor_{ioc_},
          sslCtx_{boost::asio::ssl::context::tls_server},
          signals_{ioc_}
    {
        configureSignals();
        configureSSL();
        openAcceptor();
        registerDefaultRoutes();

        spdlog::info("Server initialized on {}:{}", opts_.address, opts_.port);
    }

    ~Impl()
    {
        stop();
        unloadPlugins();
    }

    void start()
    {
        if (running_.exchange(true)) { return; }    // Already running
        doAccept();

        // Spawn worker threads
        workerThreads_.reserve(opts_.threadCount);
        for (std::size_t i = 0; i < opts_.threadCount; ++i)
        {
            workerThreads_.emplace_back([this] {
                spdlog::debug("Worker thread {} started.", std::this_thread::get_id());
                ioc_.run();
            });
        }

        spdlog::info("Server started with {} worker threads.", opts_.threadCount);
    }

    void stop()
    {
        if (!running_.exchange(false)) { return; }    // Already stopped
        spdlog::info("Stopping server...");

        boost::system::error_code ec;
        acceptor_.cancel(ec);
        acceptor_.close(ec);

        ioc_.stop();
        for (auto &t : workerThreads_)
        {
            if (t.joinable()) { t.join(); }
        }
        workerThreads_.clear();

        spdlog::info("Server stopped.");
    }

    bool isRunning() const noexcept
    {
        return running_.load();
    }

    /* ------------------------------ Plugins -------------------------------- */

    void reloadPlugins()
    {
        std::scoped_lock lk{pluginMtx_};
        unloadPlugins();

        const fs::path pluginDir = opts_.pluginDirectory;
        if (!fs::exists(pluginDir) || !fs::is_directory(pluginDir))
        {
            spdlog::warn("Plugin directory '{}' does not exist.", pluginDir.string());
            return;
        }

        for (auto &entry : fs::directory_iterator{pluginDir})
        {
            if (entry.is_regular_file() && isLibrary(entry.path()))
            {
                void *handle = loadLibrary(entry.path());
                if (handle)
                {
                    auto initFunc = reinterpret_cast<InitPluginFn>(getSymbol(handle, "initializePlugin"));
                    if (initFunc)
                    {
                        try
                        {
                            initFunc(EventBus::instance());
                            loadedLibraries_.push_back(handle);
                            spdlog::info("Loaded plugin '{}'.", entry.path().string());
                        }
                        catch (const std::exception &ex)
                        {
                            spdlog::error("Initialization of plugin '{}' failed: {}", entry.path().string(), ex.what());
                            closeLibrary(handle);
                        }
                    }
                    else
                    {
                        spdlog::warn("Symbol 'initializePlugin' not found in '{}'.", entry.path().string());
                        closeLibrary(handle);
                    }
                }
            }
        }
    }

private:
    /* ----------------------------- Networking ----------------------------- */

    void configureSignals()
    {
        signals_.add(SIGINT);
        signals_.add(SIGTERM);
#if defined(SIGQUIT)
        signals_.add(SIGQUIT);
#endif
        signals_.async_wait([this](const boost::system::error_code & /*ec*/, int /*signo*/) {
            spdlog::warn("Shutdown signal received.");
            stop();
        });
    }

    void configureSSL()
    {
        if (!opts_.useSSL) { return; }

        sslCtx_.set_options(
            boost::asio::ssl::context::default_workarounds
            | boost::asio::ssl::context::no_sslv2
            | boost::asio::ssl::context::single_dh_use);

        sslCtx_.use_certificate_chain_file(opts_.certFile);
        sslCtx_.use_private_key_file(opts_.keyFile, boost::asio::ssl::context::file_format::pem);
    }

    void openAcceptor()
    {
        boost::system::error_code ec;

        tcp::endpoint endpoint{boost::asio::ip::make_address(opts_.address, ec), opts_.port};
        if (ec)
        {
            throw std::runtime_error{"Invalid address: " + ec.message()};
        }

        acceptor_.open(endpoint.protocol(), ec);
        if (ec) { throw std::runtime_error{"Open error: " + ec.message()}; }

        acceptor_.set_option(boost::asio::socket_base::reuse_address(true));
        acceptor_.bind(endpoint, ec);
        if (ec) { throw std::runtime_error{"Bind error: " + ec.message()}; }

        acceptor_.listen(boost::asio::socket_base::max_listen_connections, ec);
        if (ec) { throw std::runtime_error{"Listen error: " + ec.message()}; }
    }

    void doAccept()
    {
        acceptor_.async_accept([this](boost::system::error_code ec, tcp::socket socket) {
            if (!ec)
            {
                spdlog::trace("Incoming connection from {}", socket.remote_endpoint());
                std::make_shared<HTTPSession>(std::move(socket), opts_.useSSL ? &sslCtx_ : nullptr,
                                              [this](string_req &&req) { return dispatch(std::move(req)); })
                    ->run();
            }
            else
            {
                spdlog::error("Accept error: {}", ec.message());
            }

            if (isRunning()) { doAccept(); }
        });
    }

    /* ----------------------------- Routing -------------------------------- */

    void registerDefaultRoutes()
    {
        routes_["/health"]  = [this](const string_req &) { return handleHealth(); };
        routes_["/version"] = [this](const string_req &) { return handleVersion(); };
        routes_["/metrics"] = [this](const string_req &) { return handleMetrics(); };
    }

    string_res dispatch(string_req &&req)
    {
        try
        {
            auto target = std::string_view{req.target().data(), req.target().size()};
            auto it     = routes_.find(target);
            if (it != routes_.end())
            {
                return it->second(req);
            }
            return notFound(req);
        }
        catch (const std::exception &ex)
        {
            return serverError(req, ex.what());
        }
    }

    /* -------------------------- Route Handlers ---------------------------- */

    static string_res notFound(const string_req &req)
    {
        string_res res{http::status::not_found, req.version()};
        res.set(http::field::content_type, "text/html");
        res.body() = "The resource '" + std::string{req.target()} + "' was not found.";
        res.prepare_payload();
        return res;
    }

    static string_res serverError(const string_req &req, std::string_view what)
    {
        string_res res{http::status::internal_server_error, req.version()};
        res.set(http::field::content_type, "text/html");
        res.body() = "An error occurred: '" + std::string{what} + "'";
        res.prepare_payload();
        return res;
    }

    string_res handleHealth()
    {
        nlohmann::json j{
            {"status", "ok"},
            {"timestamp", std::chrono::system_clock::to_time_t(std::chrono::system_clock::now())}};
        return makeJsonResponse(j);
    }

    string_res handleVersion()
    {
        nlohmann::json j{
            {"version", Version::string()},
            {"commit", Version::commitHash()},
            {"build_time", Version::buildTime()}};
        return makeJsonResponse(j);
    }

    string_res handleMetrics()
    {
        return makeJsonResponse(Metrics::instance().snapshot());
    }

    /* --------------------------- HTTP helpers ----------------------------- */

    static string_res makeJsonResponse(const nlohmann::json &j, unsigned status = 200)
    {
        string_res res{static_cast<http::status>(status), 11};
        res.set(http::field::content_type, "application/json");
        res.body() = j.dump();
        res.prepare_payload();
        return res;
    }

    /* ----------------------- Dynamic Library Helpers ---------------------- */

    static bool isLibrary(const fs::path &p)
    {
#if defined(_WIN32)
        return p.extension() == ".dll";
#elif defined(__APPLE__)
        return p.extension() == ".dylib";
#else
        return p.extension() == ".so";
#endif
    }

    using InitPluginFn = void (*)(EventBus &);

    static void *loadLibrary(const fs::path &path)
    {
#ifdef _WIN32
        return LoadLibraryW(path.wstring().c_str());
#else
        return dlopen(path.c_str(), RTLD_NOW | RTLD_LOCAL);
#endif
    }

    static void *getSymbol(void *lib, const char *symbol)
    {
#ifdef _WIN32
        return reinterpret_cast<void *>(GetProcAddress(static_cast<HMODULE>(lib), symbol));
#else
        return dlsym(lib, symbol);
#endif
    }

    static void closeLibrary(void *lib)
    {
        if (!lib) { return; }
#ifdef _WIN32
        FreeLibrary(static_cast<HMODULE>(lib));
#else
        dlclose(lib);
#endif
    }

    void unloadPlugins()
    {
        for (void *lib : loadedLibraries_)
        {
            closeLibrary(lib);
        }
        loadedLibraries_.clear();
    }

    /* ---------------------------- Data members ---------------------------- */

    Options                                opts_;
    boost::asio::io_context                ioc_;
    tcp::acceptor                          acceptor_;
    boost::asio::ssl::context              sslCtx_;
    boost::asio::signal_set                signals_;
    std::atomic_bool                       running_{false};
    std::vector<std::thread>               workerThreads_;

    std::unordered_map<std::string_view, RouteCb> routes_;

    std::mutex       pluginMtx_;
    std::vector<void *> loadedLibraries_;

    /* ---------------------------------------------------------------------- */
    /*                          Nested HTTPSession class                      */
    /* ---------------------------------------------------------------------- */

    class HTTPSession : public std::enable_shared_from_this<HTTPSession>
    {
    public:
        using ReqHandler = std::function<string_res(string_req &&)>;

        HTTPSession(tcp::socket socket,
                    boost::asio::ssl::context *sslCtx,
                    ReqHandler                 handler)
            : stream_(std::move(socket), sslCtx),
              reqHandler_{std::move(handler)},
              skipper_{[]() {}} {}

        void run()
        {
            if (stream_.isSSL())
            {
                auto self = shared_from_this();
                stream_.asyncHandshakeServer([self](boost::system::error_code ec) {
                    if (!ec) { self->doRead(); }
                });
            }
            else
            {
                doRead();
            }
        }

    private:
        void doRead()
        {
            req_ = {};
            auto self = shared_from_this();
            stream_.asyncRead(req_, [self](boost::system::error_code ec, std::size_t) {
                if (ec)
                {
                    if (ec != http::error::end_of_stream)
                        spdlog::warn("Read error: {}", ec.message());
                    self->doClose();
                    return;
                }
                self->handleRequest();
            });
        }

        void handleRequest()
        {
            auto res          = reqHandler_(std::move(req_));
            auto self         = shared_from_this();
            auto sp           = std::make_shared<string_res>(std::move(res));
            stream_.asyncWrite(*sp, [self, sp](boost::system::error_code ec, std::size_t) {
                if (ec)
                {
                    spdlog::warn("Write error: {}", ec.message());
                    self->doClose();
                    return;
                }
                if (sp->need_eof()) { self->doClose(); }
                else { self->doRead(); }
            });
        }

        void doClose()
        {
            boost::system::error_code ec;
            stream_.shutdown(ec);   // For SSL
            stream_.socket().shutdown(tcp::socket::shutdown_send, ec);
        }

        /* --------------------- Helper wrapper for SSL --------------------- */

        struct BeastStream
        {
            using PlainStream   = boost::beast::tcp_stream;
            using SSLStream     = boost::beast::ssl_stream<PlainStream>;

            BeastStream(tcp::socket &&sock, boost::asio::ssl::context *sslCtx)
                : plain_{std::move(sock)}, ssl_{std::move(plain_), *sslCtx}, useSSL_{sslCtx != nullptr}
            {
            }

            bool isSSL() const { return useSSL_; }

            template <typename MutableBufferSequence, typename ReadHandler>
            void asyncRead(MutableBufferSequence const &buffers, ReadHandler &&handler)
            {
                if (useSSL_) { http::async_read(ssl_, buffer_, req_, std::forward<ReadHandler>(handler)); }
                else { http::async_read(plain_, buffer_, req_, std::forward<ReadHandler>(handler)); }
            }

            template <typename Body, typename Fields, typename WriteHandler>
            void asyncWrite(http::message<true, Body, Fields> &msg, WriteHandler &&handler)
            {
                if (useSSL_) { http::async_write(ssl_, msg, std::forward<WriteHandler>(handler)); }
                else { http::async_write(plain_, msg, std::forward<WriteHandler>(handler)); }
            }

            template <typename HandshakeHandler>
            void asyncHandshakeServer(HandshakeHandler &&handler)
            {
                ssl_.async_handshake(boost::asio::ssl::stream_base::server, std::forward<HandshakeHandler>(handler));
            }

            void shutdown(boost::system::error_code &ec)
            {
                if (useSSL_) ssl_.shutdown(ec);
            }

            tcp::socket &socket() { return useSSL_ ? ssl_.next_layer().socket() : plain_.socket(); }

            boost::beast::flat_buffer buffer_;
            string_req                req_;

        private:
            PlainStream plain_;
            SSLStream   ssl_;
            bool        useSSL_;
        };

        BeastStream stream_;
        string_req  req_;
        ReqHandler  reqHandler_;
    };
};

/* -------------------------------------------------------------------------- */
/*                                Server facade                               */
/* -------------------------------------------------------------------------- */

Server::Server(const Options &opt) : pImpl_{std::make_unique<Impl>(opt)} {}

Server::~Server() = default;

void Server::start()               { pImpl_->start(); }
void Server::stop()                { pImpl_->stop(); }
bool Server::isRunning() const     { return pImpl_->isRunning(); }
void Server::reloadPlugins()       { pImpl_->reloadPlugins(); }

/* -------------------------------------------------------------------------- */
/*                                 Factory API                                */
/* -------------------------------------------------------------------------- */

Server::Options Server::Options::withDefaults()
{
    Options o;
    o.address         = "0.0.0.0";
    o.port            = 8443;
    o.useSSL          = true;
    o.certFile        = "certs/server.crt";
    o.keyFile         = "certs/server.key";
    o.threadCount     = std::max<std::size_t>(2, std::thread::hardware_concurrency());
    o.pluginDirectory = "plugins";
    return o;
}

}  // namespace mb::core