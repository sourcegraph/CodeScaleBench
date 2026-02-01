```cpp
/**
 *  FortiLedger360 Enterprise Security Suite
 *  -----------------------------------------
 *  File:        cmd/api_gateway/main.cpp
 *  Component:   Presentation & API Layer – Edge Gateway
 *
 *  Synopsis:
 *      Stateless HTTP/REST gateway that accepts customer-facing API calls, performs
 *      light-weight validation/authentication and finally publishes canonical
 *      Command objects onto the internal Event-Bus for further processing by the
 *      mesh services (Scanner, Metrics, BackupNode, …).
 *
 *      The server is implemented with Boost.Beast/Asio (header-only in C++17) to
 *      avoid any runtime-heavy dependencies. JSON payloads are parsed with
 *      nlohmann::json.  The gateway itself is intentionally thin: compliance
 *      checking, billing, and SLA enforcement live in deeper layers.
 *
 *  Build:
 *      Requires C++17, Boost (system, thread, chrono, beast), and nlohmann/json.
 *
 *          g++ -std=c++17 -O2 -Wall -Wextra \
 *              main.cpp -o api_gateway \
 *              -lboost_system -lpthread
 *
 *  NOTE:
 *      In a production deployment TLS termination is fronted by Envoy/NGINX.
 *      For brevity the transport here is plain HTTP.
 */

#include <boost/asio.hpp>
#include <boost/beast.hpp>
#include <boost/beast/version.hpp>
#include <boost/algorithm/string.hpp>
#include <nlohmann/json.hpp>

#include <chrono>
#include <cstdint>
#include <cstdlib>
#include <functional>
#include <iostream>
#include <memory>
#include <optional>
#include <string>
#include <unordered_map>
#include <utility>

namespace bl  = boost::asio;
namespace beast = boost::beast;
namespace http  = beast::http;
using     tcp   = bl::ip::tcp;
using     json  = nlohmann::json;

// -------------------------------------------------------------------------------------------------
// Domain primitives – the canonical commands that travel via the (internal) event-bus
// -------------------------------------------------------------------------------------------------
enum class CommandType
{
    InitiateSecurityScan,
    RollClusterBackup,
    Unknown
};

struct Command
{
    CommandType                 type{};
    json                        payload;
    std::string                 tenantId;
    std::chrono::system_clock::time_point issuedAt{ std::chrono::system_clock::now() };

    std::string to_string() const
    {
        json j{
            {"tenantId", tenantId},
            {"type",     static_cast<int>(type)},
            {"payload",  payload},
            {"issuedAt", std::chrono::duration_cast<std::chrono::milliseconds>(
                             issuedAt.time_since_epoch()).count()}
        };
        return j.dump();
    }
};

// -------------------------------------------------------------------------------------------------
// Simple in-process Event Bus stub. In production this would be backed by NATS, Kafka, or RabbitMQ.
// -------------------------------------------------------------------------------------------------
class CommandBus
{
public:
    void publish(const Command& cmd) noexcept
    {
        // In real world: serialize->push to message broker with publish-confirm.
        std::lock_guard<std::mutex> lock(mtx_);
        std::cout << "[CommandBus] Published: " << cmd.to_string() << std::endl;
    }

private:
    std::mutex mtx_;
};

// -------------------------------------------------------------------------------------------------
// Security middleware – verifies API tokens, basic rate-limiting etc.
// -------------------------------------------------------------------------------------------------
class SecurityContext
{
public:
    explicit SecurityContext(std::string tenantId)
        : tenantId_(std::move(tenantId)) {}

    const std::string& tenant_id() const { return tenantId_; }

private:
    std::string tenantId_;
};

class Authenticator
{
public:
    // Statically seeded token store for demo. Replace with call to IdP/OAuth2 server.
    bool verify(const std::string& bearerToken, SecurityContext& outCtx) const
    {
        static const std::unordered_map<std::string, std::string> token2tenant {
            {"token_tenant_alpha",  "tenant_alpha"},
            {"token_tenant_beta",   "tenant_beta"},
            {"token_tenant_charly", "tenant_charly"}
        };

        auto it = token2tenant.find(bearerToken);
        if (it == token2tenant.end()) { return false; }

        outCtx = SecurityContext{ it->second };
        return true;
    }
};

// -------------------------------------------------------------------------------------------------
// Chain-of-Responsibility: request validators.
// -------------------------------------------------------------------------------------------------
class RequestValidationError : public std::runtime_error
{
public:
    explicit RequestValidationError(const std::string& m) : std::runtime_error(m) {}
};

class RequestValidator
{
public:
    virtual ~RequestValidator() = default;
    virtual void validate(const http::request<http::string_body>& req,
                          const SecurityContext& ctx) const = 0;
};

using RequestValidatorPtr = std::shared_ptr<RequestValidator>;

class ContentTypeValidator : public RequestValidator
{
public:
    void validate(const http::request<http::string_body>& req,
                  const SecurityContext&) const override
    {
        auto ctHeader = req[http::field::content_type];
        if (ctHeader.empty() ||
            ctHeader.find("application/json") == std::string::npos)
        {
            throw RequestValidationError("Unsupported content-type, expecting application/json");
        }
    }
};

class VerbValidator : public RequestValidator
{
public:
    void validate(const http::request<http::string_body>& req,
                  const SecurityContext&) const override
    {
        if (req.method() != http::verb::post)
        {
            throw RequestValidationError("Only POST is allowed on this endpoint");
        }
    }
};

// -------------------------------------------------------------------------------------------------
// Command Mapper – converts outbound API contract into internal Command objects.
// -------------------------------------------------------------------------------------------------
class CommandMapper
{
public:
    std::optional<Command> map(const std::string& uri,
                               const json&          body,
                               const SecurityContext& ctx) const
    {
        if (boost::algorithm::equals(uri, "/v1/security/scan"))
        {
            Command c;
            c.type      = CommandType::InitiateSecurityScan;
            c.payload   = body;
            c.tenantId  = ctx.tenant_id();
            return c;
        }
        else if (boost::algorithm::equals(uri, "/v1/backup/roll"))
        {
            Command c;
            c.type      = CommandType::RollClusterBackup;
            c.payload   = body;
            c.tenantId  = ctx.tenant_id();
            return c;
        }
        return std::nullopt;
    }
};

// -------------------------------------------------------------------------------------------------
// HTTP Session – per connection object. Owns lifetime until socket is closed.
// -------------------------------------------------------------------------------------------------
class HTTPSession : public std::enable_shared_from_this<HTTPSession>
{
public:
    HTTPSession(tcp::socket socket,
                CommandBus& commandBus,
                const Authenticator& auth,
                std::vector<RequestValidatorPtr> validators)
        : socket_(std::move(socket)),
          strand_(socket_.get_executor()),
          commandBus_(commandBus),
          authenticator_(auth),
          validators_(std::move(validators))
    {}

    void run() { read_request(); }

private:
    tcp::socket                                      socket_;
    bl::strand<bl::io_context::executor_type>        strand_;
    beast::flat_buffer                               buffer_{8192};
    http::request<http::string_body>                 request_;
    CommandBus&                                      commandBus_;
    const Authenticator&                             authenticator_;
    const std::vector<RequestValidatorPtr>           validators_;

    void read_request()
    {
        auto self = shared_from_this();
        http::async_read(socket_, buffer_, request_,
            bl::bind_executor(strand_,
                [self](beast::error_code ec, std::size_t bytes) {
                    boost::ignore_unused(bytes);
                    if (!ec) self->process_request();
                }));
    }

    // NOTE: this function is synchronous to keep the example compact.
    void process_request()
    {
        // 1. Authentication
        SecurityContext secCtx{""};
        const std::string authHeader = request_[http::field::authorization].to_string();
        if (authHeader.rfind("Bearer ", 0) != 0 ||
            !authenticator_.verify(authHeader.substr(7), secCtx))
        {
            respond(http::status::unauthorized, R"({"error":"invalid_token"})");
            return;
        }

        // 2. Validation chain
        try {
            for (const auto& v : validators_) { v->validate(request_, secCtx); }
        }
        catch (const RequestValidationError& err)
        {
            respond(http::status::bad_request,
                    json({{"error", err.what()}}).dump());
            return;
        }

        // 3. Parse JSON body
        json body;
        try {
            body = json::parse(request_.body());
        }
        catch (const json::exception& e) {
            respond(http::status::bad_request,
                    json({{"error","invalid_json"}, {"detail", e.what()}}).dump());
            return;
        }

        // 4. Map to Command
        CommandMapper mapper;
        auto cmdOpt = mapper.map(request_.target().to_string(), body, secCtx);
        if (!cmdOpt)
        {
            respond(http::status::not_found,
                    R"({"error":"unknown_endpoint"})");
            return;
        }

        // 5. Publish
        commandBus_.publish(*cmdOpt);

        // 6. Respond success
        respond(http::status::accepted,
                json({{"status","accepted"}, {"commandId", cmdOpt->to_string()}}).dump());
    }

    void respond(http::status status, std::string body)
    {
        auto self = shared_from_this();
        auto res  = std::make_shared<http::response<http::string_body>>(
            status, request_.version());
        res->set(http::field::server,    "FortiLedger360/APIGateway");
        res->set(http::field::content_type, "application/json");
        res->keep_alive(request_.keep_alive());
        res->body() = std::move(body);
        res->prepare_payload();

        http::async_write(socket_, *res,
            bl::bind_executor(strand_,
                [self, res](beast::error_code ec, std::size_t) {
                    self->socket_.shutdown(tcp::socket::shutdown_send, ec);
                }));
    }
};

// -------------------------------------------------------------------------------------------------
// TCP Listener – accepts incoming connections.
// -------------------------------------------------------------------------------------------------
class Listener : public std::enable_shared_from_this<Listener>
{
public:
    Listener(bl::io_context& ioc,
             tcp::endpoint endpoint,
             CommandBus& bus,
             const Authenticator& auth,
             std::vector<RequestValidatorPtr> validators)
        : acceptor_(ioc),
          socket_(ioc),
          commandBus_(bus),
          authenticator_(auth),
          validators_(std::move(validators))
    {
        beast::error_code ec;

        acceptor_.open(endpoint.protocol(), ec);
        if (ec) { throw std::runtime_error("open: " + ec.message()); }

        acceptor_.set_option(bl::socket_base::reuse_address(true), ec);
        if (ec) { throw std::runtime_error("set_option: " + ec.message()); }

        acceptor_.bind(endpoint, ec);
        if (ec) { throw std::runtime_error("bind: " + ec.message()); }

        acceptor_.listen(bl::socket_base::max_listen_connections, ec);
        if (ec) { throw std::runtime_error("listen: " + ec.message()); }
    }

    void run() { do_accept(); }

private:
    tcp::acceptor                                   acceptor_;
    tcp::socket                                     socket_;
    CommandBus&                                     commandBus_;
    const Authenticator&                            authenticator_;
    const std::vector<RequestValidatorPtr>          validators_;

    void do_accept()
    {
        acceptor_.async_accept(socket_,
            [self = shared_from_this()](beast::error_code ec) {
                if (!ec) {
                    std::make_shared<HTTPSession>(
                        std::move(self->socket_),
                        self->commandBus_,
                        self->authenticator_,
                        self->validators_
                    )->run();
                }
                self->do_accept();
            });
    }
};

// -------------------------------------------------------------------------------------------------
// Bootstrapper / entry point
// -------------------------------------------------------------------------------------------------
int main(int argc, char* argv[])
{
    try
    {
        const uint16_t port =
            (argc > 1) ? static_cast<uint16_t>(std::atoi(argv[1])) : 8080;

        bl::io_context ioc{1}; // Single-threaded; scale horizontally in k8s.

        CommandBus     bus;
        Authenticator  authenticator;

        std::vector<RequestValidatorPtr> validators{
            std::make_shared<ContentTypeValidator>(),
            std::make_shared<VerbValidator>()
        };

        auto listener = std::make_shared<Listener>(
            ioc,
            tcp::endpoint{tcp::v4(), port},
            bus,
            authenticator,
            std::move(validators)
        );
        listener->run();

        std::cout << "FortiLedger360 API Gateway listening on :"
                  << port << std::endl;

        // Run until SIGINT/SIGTERM.
        ioc.run();
    }
    catch (const std::exception& e)
    {
        std::cerr << "[fatal] " << e.what() << std::endl;
        return EXIT_FAILURE;
    }
    return EXIT_SUCCESS;
}
```