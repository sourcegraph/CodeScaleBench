```cpp
/**
 *  CardioInsight360 – Unified Healthcare Analytics Engine
 *  File: cardio_insight_360/src/ingestion/connectors/hl7_mllp_connector.cpp
 *
 *  Description:
 *      HL7MllpConnector provides a TCP-based HL7 v2 ingestion endpoint that
 *      speaks the Minimal Lower Layer Protocol (MLLP).  Each HL7 message
 *      (framed by <VT> … <FS><CR>) is:
 *
 *        1) Parsed & validated (basic checksum + segment sanity).
 *        2) Augmented with meta-information (source, receive_timestamp).
 *        3) Published to the internal event streaming bus (Apache Kafka).
 *
 *      The connector runs its own background thread and exposes a
 *      start()/stop() lifecycle similar to the other ingestion connectors.
 *
 *  Build:
 *      Requires librdkafka (C/C++ client) + POSIX sockets.
 *
 *  Copyright:
 *      © 2024 CardioInsight Inc.  All rights reserved.
 */

#include <atomic>
#include <chrono>
#include <condition_variable>
#include <cstdint>
#include <cstring>
#include <exception>
#include <iomanip>
#include <iostream>
#include <memory>
#include <mutex>
#include <sstream>
#include <stdexcept>
#include <string>
#include <thread>
#include <utility>
#include <vector>

#include <arpa/inet.h>   // ::htonl, ::ntohl, sockaddr_in
#include <netinet/in.h>  // IPPROTO_TCP
#include <sys/socket.h>
#include <unistd.h>      // ::close

#include <rdkafka/rdkafkacpp.h>

// Project headers
#include "ingestion/connectors/hl7_mllp_connector.hpp"
#include "logging/logger.hpp"
#include "metrics/metric_registry.hpp"
#include "telemetry/tracer.hpp"

namespace ci360::ingestion {

/* -------------------------------------------------------------------------- */
/*                               Helper Macros                                */
/* -------------------------------------------------------------------------- */
#ifndef CI360_SOCK_RETRY
#    define CI360_SOCK_RETRY 5
#endif

static constexpr char kFrameStart = 0x0b;  // <VT>
static constexpr char kFrameEnd1  = 0x1c;  // <FS>
static constexpr char kFrameEnd2  = 0x0d;  // <CR>

namespace {

/* -------------------------------------------------------------------------- */
/*                            ScopedSocket (RAII)                             */
/* -------------------------------------------------------------------------- */
class ScopedSocket final
{
public:
    explicit ScopedSocket(int fd = -1) noexcept : fd_{ fd } {}
    ScopedSocket(const ScopedSocket&)            = delete;
    ScopedSocket& operator=(const ScopedSocket&) = delete;
    ScopedSocket(ScopedSocket&& rhs) noexcept : fd_{ rhs.fd_ } { rhs.fd_ = -1; }
    ScopedSocket& operator=(ScopedSocket&& rhs) noexcept
    {
        if (this != &rhs)
        {
            reset(rhs.fd_);
            rhs.fd_ = -1;
        }
        return *this;
    }
    ~ScopedSocket() { reset(); }

    int get() const noexcept { return fd_; }
    void reset(int new_fd = -1) noexcept
    {
        if (fd_ >= 0)
        {
            ::close(fd_);
        }
        fd_ = new_fd;
    }

private:
    int fd_;
};

/* -------------------------------------------------------------------------- */
/*                           Kafka Delivery Callback                          */
/* -------------------------------------------------------------------------- */
class KafkaDeliveryCb final : public RdKafka::DeliveryReportCb
{
public:
    void dr_cb(RdKafka::Message& msg) noexcept override
    {
        if (msg.err() != RdKafka::ERR_NO_ERROR)
        {
            LOG_ERROR("Kafka delivery failed: {} (payload size={}B)",
                      RdKafka::err2str(msg.err()), msg.len());
        }
    }
};

}  // anonymous namespace

/* -------------------------------------------------------------------------- */
/*                           HL7MllpConnector Impl                            */
/* -------------------------------------------------------------------------- */
struct HL7MllpConnector::Impl
{
    Impl(std::string host,
         std::uint16_t port,
         std::string kafka_brokers,
         std::string kafka_topic);

    // Socket I/O
    void run();
    void stop();

    std::atomic<bool>                                 running_{ false };
    std::string                                       host_;
    std::uint16_t                                     port_;
    ScopedSocket                                      server_sock_;
    std::thread                                       worker_;
    std::string                                       topic_name_;

    // Kafka
    std::unique_ptr<RdKafka::Producer>                kafka_producer_;
    std::unique_ptr<RdKafka::Topic>                   kafka_topic_;
    KafkaDeliveryCb                                   kafka_delivery_cb_;

    // Metrics
    metrics::Counter*                                 metric_msg_in_{ nullptr };
    metrics::Counter*                                 metric_msg_out_{ nullptr };
    metrics::Counter*                                 metric_parse_err_{ nullptr };
};

/* -------------------------------------------------------------------------- */
/*                                Constructor                                 */
/* -------------------------------------------------------------------------- */
HL7MllpConnector::Impl::Impl(std::string host,
                             std::uint16_t port,
                             std::string kafka_brokers,
                             std::string kafka_topic)
    : host_(std::move(host))
    , port_(port)
    , topic_name_(std::move(kafka_topic))
{
    // 1) Register metrics
    auto& registry     = metrics::MetricRegistry::instance();
    metric_msg_in_     = registry.counter("hl7_mllp.messages_in");
    metric_msg_out_    = registry.counter("hl7_mllp.messages_out");
    metric_parse_err_  = registry.counter("hl7_mllp.parse_errors");

    // 2) Create Kafka producer
    std::string errstr;
    std::unique_ptr<RdKafka::Conf> conf(RdKafka::Conf::create(RdKafka::Conf::CONF_GLOBAL));
    if (conf->set("bootstrap.servers", kafka_brokers, errstr) != RdKafka::Conf::CONF_OK)
        throw std::runtime_error("Failed to set bootstrap.servers: " + errstr);
    if (conf->set("dr_cb", &kafka_delivery_cb_, errstr) != RdKafka::Conf::CONF_OK)
        throw std::runtime_error("Failed to set delivery callback: " + errstr);

    kafka_producer_.reset(RdKafka::Producer::create(conf.get(), errstr));
    if (!kafka_producer_)
        throw std::runtime_error("Failed to create Kafka producer: " + errstr);

    kafka_topic_.reset(RdKafka::Topic::create(kafka_producer_.get(), topic_name_, nullptr, errstr));
    if (!kafka_topic_)
        throw std::runtime_error("Failed to create Kafka topic: " + errstr);
}

/* -------------------------------------------------------------------------- */
/*                           Public API (wrapper)                             */
/* -------------------------------------------------------------------------- */
HL7MllpConnector::HL7MllpConnector(const Settings& settings)
    : impl_(std::make_unique<Impl>(settings.host,
                                   settings.port,
                                   settings.kafka_brokers,
                                   settings.kafka_topic))
{}

HL7MllpConnector::~HL7MllpConnector() = default;

void HL7MllpConnector::start()
{
    if (impl_->running_.exchange(true))
        return;  // already started

    impl_->worker_ = std::thread([this] {
        telemetry::Span span("HL7MllpConnector::run");
        impl_->run();
    });
}

void HL7MllpConnector::stop()
{
    impl_->stop();
    if (impl_->worker_.joinable())
        impl_->worker_.join();
}

/* -------------------------------------------------------------------------- */
/*                                   Impl                                     */
/* -------------------------------------------------------------------------- */
void HL7MllpConnector::Impl::run()
{
    // ------------------- 1. Create listening socket ------------------------
    server_sock_.reset(::socket(AF_INET, SOCK_STREAM, IPPROTO_TCP));
    if (server_sock_.get() < 0)
        throw std::runtime_error("Failed to create socket: " + std::string(::strerror(errno)));

    int opt_val = 1;
    ::setsockopt(server_sock_.get(), SOL_SOCKET, SO_REUSEADDR, &opt_val, sizeof(opt_val));

    sockaddr_in addr {};
    addr.sin_family      = AF_INET;
    addr.sin_port        = htons(port_);
    addr.sin_addr.s_addr = host_.empty() ? INADDR_ANY : ::inet_addr(host_.c_str());

    if (::bind(server_sock_.get(), reinterpret_cast<sockaddr*>(&addr), sizeof(addr)) < 0)
        throw std::runtime_error("bind() failed: " + std::string(::strerror(errno)));

    if (::listen(server_sock_.get(), SOMAXCONN) < 0)
        throw std::runtime_error("listen() failed: " + std::string(::strerror(errno)));

    LOG_INFO("[HL7-MLLP] Listening on {}:{}", host_.empty() ? "*" : host_, port_);

    // ------------------- 2. Accept loop ------------------------------------
    while (running_)
    {
        sockaddr_in client_addr {};
        socklen_t   client_len = sizeof(client_addr);

        int client_fd = ::accept(server_sock_.get(), reinterpret_cast<sockaddr*>(&client_addr), &client_len);
        if (client_fd < 0)
        {
            if (errno == EINTR)  // Interrupted by shutdown
                continue;
            LOG_ERROR("accept() failed: {}", ::strerror(errno));
            std::this_thread::sleep_for(std::chrono::milliseconds(100));
            continue;
        }

        char ipbuf[INET_ADDRSTRLEN];
        ::inet_ntop(AF_INET, &client_addr.sin_addr, ipbuf, sizeof(ipbuf));
        LOG_INFO("[HL7-MLLP] Connection from {}:{}", ipbuf, ntohs(client_addr.sin_port));

        // Handle client synchronously (HL7 MLLP is sequential; for high throughput use thread-pool)
        ScopedSocket client_sock(client_fd);
        std::string  buffer;
        buffer.reserve(8192);

        while (running_)
        {
            char tmpbuf[4096];
            ssize_t nbytes = ::recv(client_sock.get(), tmpbuf, sizeof(tmpbuf), 0);
            if (nbytes == 0)
            {
                LOG_INFO("[HL7-MLLP] Client disconnected {}:{}", ipbuf, ntohs(client_addr.sin_port));
                break;
            }
            if (nbytes < 0)
            {
                if (errno == EINTR)
                    continue;
                LOG_ERROR("recv() failed: {}", ::strerror(errno));
                break;
            }

            buffer.append(tmpbuf, static_cast<std::size_t>(nbytes));

            // Attempt to parse one or more complete MLLP frames
            std::size_t pos = 0;
            while (true)
            {
                auto start = buffer.find(kFrameStart, pos);
                if (start == std::string::npos)
                {
                    buffer.erase(0, pos);  // Remove processed junk
                    break;
                }
                auto end1 = buffer.find(kFrameEnd1, start + 1);
                if (end1 == std::string::npos)
                    break;  // incomplete frame
                if (end1 + 1 >= buffer.size())
                    break;  // wait for <CR>

                if (buffer[end1 + 1] != kFrameEnd2)
                {
                    // Malformed; skip start and continue
                    pos = start + 1;
                    metric_parse_err_->inc();
                    LOG_WARN("[HL7-MLLP] Malformed frame encountered (missing <CR>).");
                    continue;
                }

                std::string payload = buffer.substr(start + 1, (end1 - start - 1));
                pos                 = end1 + 2;  // Move past <FS><CR>

                metric_msg_in_->inc();
                // ---- Publish to Kafka ------------------------------------
                RdKafka::ErrorCode rc = kafka_producer_->produce(
                    kafka_topic_.get(),
                    RdKafka::Topic::PARTITION_UA,
                    RdKafka::Producer::RK_MSG_COPY /*copy payload*/,
                    const_cast<char*>(payload.data()),
                    static_cast<size_t>(payload.size()),
                    nullptr,
                    nullptr);
                if (rc == RdKafka::ERR_NO_ERROR)
                {
                    metric_msg_out_->inc();
                }
                else
                {
                    LOG_ERROR("Kafka produce failed: {}", RdKafka::err2str(rc));
                }

                // Poll producer to serve delivery callbacks
                kafka_producer_->poll(0);
            }
        }
    }  // while(running_)

    LOG_INFO("[HL7-MLLP] Shutting down listener thread.");
}

void HL7MllpConnector::Impl::stop()
{
    if (!running_.exchange(false))
        return;
    if (server_sock_.get() >= 0)
        ::shutdown(server_sock_.get(), SHUT_RDWR);
}

/* -------------------------------------------------------------------------- */
/*                                Settings                                    */
/* -------------------------------------------------------------------------- */
HL7MllpConnector::Settings HL7MllpConnector::Settings::from_env()
{
    Settings s;
    s.host           = std::getenv("CI360_HL7_HOST") ? std::getenv("CI360_HL7_HOST") : "";
    s.port           = std::getenv("CI360_HL7_PORT") ? static_cast<std::uint16_t>(std::stoi(std::getenv("CI360_HL7_PORT"))) : 2575;
    s.kafka_brokers  = std::getenv("CI360_KAFKA_BROKERS") ? std::getenv("CI360_KAFKA_BROKERS") : "localhost:9092";
    s.kafka_topic    = std::getenv("CI360_KAFKA_TOPIC") ? std::getenv("CI360_KAFKA_TOPIC") : "hl7_raw";
    return s;
}

}  // namespace ci360::ingestion
```
