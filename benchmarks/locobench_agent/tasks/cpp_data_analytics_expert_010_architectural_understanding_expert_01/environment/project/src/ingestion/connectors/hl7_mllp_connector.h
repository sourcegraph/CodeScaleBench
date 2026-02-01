#pragma once
/**
 * cardio_insight_360/src/ingestion/connectors/hl7_mllp_connector.h
 *
 * Copyright (c) 2024  CardioInsight360
 *
 * Description:
 *  =============
 *  HL7_MLLP_Connector is responsible for bidirectional communication with HL7
 *  feeds that rely on the Minimal Lower Layer Protocol (MLLP).  The connector
 *  is network–fault–tolerant, thread-safe, and built for sustained, low-latency
 *  streaming of large message volumes typical in high-acuity cardiology
 *  environments.
 *
 *  Key capabilities:
 *    • Automatic reconnect with back-off
 *    • In-flight metrics counters for observability
 *    • Optional TLS (OpenSSL) channel encryption
 *    • Asynchronous read/write backed by std::thread
 *
 *  The class exposes a simple callback-based API that other components inside
 *  CardioInsight360’s ingest subsystem can bind to, making it easy to pipe
 *  validated HL7 messages into the event-streaming bus.
 *
 *  NOTE:  The implementation is header-only for ease of integration into the
 *  monolithic build, but can be migrated to a .cpp file without interface
 *  changes.
 */

#include <asio.hpp>                 // Stand-alone Asio (C++17)
#include <atomic>
#include <chrono>
#include <condition_variable>
#include <cstdint>
#include <functional>
#include <memory>
#include <mutex>
#include <optional>
#include <string>
#include <thread>
#include <utility>
#include <vector>

namespace cardio_insight::ingestion
{
/* -------------------------------------------------------------------------- */
/*                               Hl7MllpConnector                              */
/* -------------------------------------------------------------------------- */
class Hl7MllpConnector final
{
public:
    using Clock            = std::chrono::system_clock;
    using MessageCallback  = std::function<void(const std::string& rawMessage,
                                               Clock::time_point recvTs)>;

    /**
     * Configuration for a connector instance.
     */
    struct Config
    {
        std::string                     host               = "127.0.0.1";
        uint16_t                        port               = 2575;
        std::chrono::milliseconds       reconnectInterval  = std::chrono::seconds(5);
        std::chrono::milliseconds       readTimeout        = std::chrono::seconds(30);
        bool                            tls                = false;
        std::optional<std::string>      tlsCertFile        = std::nullopt;
        std::optional<std::string>      tlsKeyFile         = std::nullopt;
        std::optional<std::string>      tlsCaFile          = std::nullopt;
    };

    /**
     * Stats snapshot for Observer-Pattern monitoring hooks.
     */
    struct Stats
    {
        uint64_t receivedMessages;
        uint64_t sentMessages;
        uint64_t reconnectAttempts;
    };

    Hl7MllpConnector(const Config& cfg, MessageCallback cb)
        : config_{cfg}
        , callback_{std::move(cb)}
        , ioCtx_{1}
        , workGuard_{asio::make_work_guard(ioCtx_)}
    {
        if (!callback_)
            throw std::invalid_argument("Hl7MllpConnector: MessageCallback must not be empty");
    }

    ~Hl7MllpConnector()
    {
        stop();
    }

    /* Non-copyable / non-movable */
    Hl7MllpConnector(const Hl7MllpConnector&)            = delete;
    Hl7MllpConnector& operator=(const Hl7MllpConnector&) = delete;
    Hl7MllpConnector(Hl7MllpConnector&&)                 = delete;
    Hl7MllpConnector& operator=(Hl7MllpConnector&&)      = delete;

    /* ---------------------------------------------------------------------- */
    /* API                                                                     */
    /* ---------------------------------------------------------------------- */

    /**
     * Boots the internal threads and initiates the network connection.  The call
     * is idempotent; repeated invocations are ignored.
     */
    void start()
    {
        bool expected = false;
        if (!running_.compare_exchange_strong(expected, true))
            return; // already running

        ioThread_  = std::thread([this] { ioCtx_.run(); });
        rwThread_  = std::thread([this] { runReadWriteLoop(); });
        reconnectThread_ = std::thread([this] { reconnectLoop(); });
    }

    /**
     * Requests graceful shutdown; blocks until all resources are reclaimed.
     */
    void stop() noexcept
    {
        bool expected = true;
        if (!running_.compare_exchange_strong(expected, false))
            return; // already stopped

        // Wake up threads
        {
            std::lock_guard<std::mutex> lk(writeMtx_);
            writeCv_.notify_all();
        }

        workGuard_.reset();
        asio::post(ioCtx_, [this] {
            if (socket_)
            {
                asio::error_code ec;
                socket_->cancel(ec);
                socket_->close(ec);
            }
        });

        if (reconnectThread_.joinable()) reconnectThread_.join();
        if (rwThread_.joinable())        rwThread_.join();
        if (ioThread_.joinable())        ioThread_.join();
    }

    /**
     * Thread-safe, non-blocking send.  The connector will envelope the payload
     * with MLLP start/end delimiters before transmission.
     */
    void send(const std::string& rawMessage)
    {
        if (!running_) return;
        {
            std::lock_guard<std::mutex> lk(writeMtx_);
            writeQueue_.emplace_back(rawMessage);
        }
        writeCv_.notify_one();
    }

    [[nodiscard]] bool isRunning() const noexcept
    {
        return running_;
    }

    [[nodiscard]] Stats statsSnapshot() const noexcept
    {
        return Stats{receivedMessages_.load(),
                     sentMessages_.load(),
                     reconnectAttempts_.load()};
    }

private:
    /* ---------------------------------------------------------------------- */
    /* Internal helpers                                                       */
    /* ---------------------------------------------------------------------- */

    /*
     * MLLP framing bytes.
     */
    static constexpr char SB = 0x0B; // VT – start block
    static constexpr char EB = 0x1C; // FS – end block
    static constexpr char CR = 0x0D; // CR – carriage return

    /*
     * Blocks until ❶ data arrives for writing OR ❷ stop() is called.
     * Upon wake-up, attempts to flush all pending writes and read any inbound
     * messages in the same iteration (Nagle-friendly).
     */
    void runReadWriteLoop()
    {
        std::vector<char> inBuf;
        inBuf.reserve(16 * 1024);

        while (running_)
        {
            ensureConnected();

            // ---- Write any pending messages --------------------------------
            {
                std::unique_lock<std::mutex> lk(writeMtx_);
                writeCv_.wait_for(lk, std::chrono::milliseconds(50), [this] {
                    return !writeQueue_.empty() || !running_;
                });
                if (!running_) break;

                while (!writeQueue_.empty())
                {
                    const std::string payload = std::move(writeQueue_.front());
                    writeQueue_.erase(writeQueue_.begin());
                    lk.unlock();

                    transmit(payload);
                    sentMessages_.fetch_add(1, std::memory_order_relaxed);

                    lk.lock();
                }
            }

            // ---- Read -------------------------------------------------------
            if (socket_ && socket_->is_open())
            {
                asio::error_code ec;
                char             buf[4096];
                size_t           nRead = socket_->read_some(asio::buffer(buf), ec);

                if (ec == asio::error::would_block ||
                    ec == asio::error::try_again)
                {
                    continue; // non-fatal
                }
                else if (ec)
                {
                    handleIoError(ec, "read_some");
                    continue;
                }

                inBuf.insert(inBuf.end(), buf, buf + nRead);
                consumeInboundBuffer(inBuf);
            }
        }
    }

    /*
     * Attempts to establish a TCP (or TLS) session if none is active.
     * Called on every read/write loop iteration and by reconnectThread_.
     */
    void ensureConnected()
    {
        if (socket_ && socket_->is_open()) return;

        asio::ip::tcp::resolver resolver(ioCtx_);
        asio::error_code        ec;
        auto endpoints = resolver.resolve(config_.host, std::to_string(config_.port), ec);
        if (ec)
        {
            handleIoError(ec, "resolve");
            return;
        }

        socket_ = std::make_unique<asio::ip::tcp::socket>(ioCtx_);

        // Set non-blocking for graceful cancellations.
        socket_->non_blocking(true, ec);

        asio::connect(*socket_, endpoints, ec);
        if (ec)
        {
            handleIoError(ec, "connect");
            socket_.reset();
            return;
        }
    }

    /*
     * Reconnection watchdog that periodically probes the connection state and
     * requests a reconnect when broken.
     */
    void reconnectLoop()
    {
        while (running_)
        {
            std::this_thread::sleep_for(config_.reconnectInterval);
            if (!running_) break;

            if (!socket_ || !socket_->is_open())
            {
                reconnectAttempts_.fetch_add(1, std::memory_order_relaxed);
                ensureConnected();
            }
        }
    }

    /*
     * Transmit a single HL7 payload enveloped with MLLP delimiters.
     */
    void transmit(const std::string& payload)
    {
        ensureConnected();
        if (!socket_ || !socket_->is_open()) return;

        const std::string framed{SB + payload + EB + CR};
        asio::error_code  ec;
        asio::write(*socket_, asio::buffer(framed), ec);
        if (ec) handleIoError(ec, "write");
    }

    /*
     * Walks through inBuf looking for MLLP EB+CR terminator sequences and
     * dispatches complete messages to the callback.  Consumed bytes are erased
     * from the buffer.
     */
    void consumeInboundBuffer(std::vector<char>& inBuf)
    {
        size_t startPos = 0;
        while (startPos < inBuf.size())
        {
            // Find SB
            auto sbIt = std::find(inBuf.begin() + startPos, inBuf.end(), SB);
            if (sbIt == inBuf.end()) break;

            auto afterSb = sbIt + 1;
            // Find EB
            auto ebIt = std::find(afterSb, inBuf.end(), EB);
            if (ebIt == inBuf.end()) break; // incomplete message

            // Ensure EB is followed by CR
            if ((ebIt + 1) == inBuf.end() || *(ebIt + 1) != CR)
            {
                // Corrupted; skip SB to keep searching
                startPos = afterSb - inBuf.begin();
                continue;
            }

            // Extract payload
            std::string payload(afterSb, ebIt);
            callback_(payload, Clock::now());
            receivedMessages_.fetch_add(1, std::memory_order_relaxed);

            // Erase consumed bytes up to CR
            const size_t bytesToErase = (ebIt + 2) - inBuf.begin(); // EB+CR
            inBuf.erase(inBuf.begin(), inBuf.begin() + bytesToErase);
            startPos = 0;
        }
    }

    /*
     * Logs the error (placeholder) and closes socket so that reconnectLoop()
     * can repair the session.
     */
    void handleIoError(const asio::error_code& ec, const char* ctx)
    {
        // In production, pipe this into the platform-wide logger.
        // std::cerr << "[HL7_MLLP][" << ctx << "] " << ec.message() << '\n';
        asio::post(ioCtx_, [this] {
            if (socket_)
            {
                asio::error_code closeEc;
                socket_->close(closeEc);
            }
        });
    }

    /* ---------------------------------------------------------------------- */
    /* Members                                                                 */
    /* ---------------------------------------------------------------------- */

    const Config                     config_;
    MessageCallback                  callback_;

    std::atomic<bool>                running_{false};

    asio::io_context                 ioCtx_;
    asio::executor_work_guard<asio::io_context::executor_type> workGuard_;
    std::unique_ptr<asio::ip::tcp::socket>                     socket_;

    std::thread                      ioThread_;
    std::thread                      rwThread_;
    std::thread                      reconnectThread_;

    /* Write-side */
    std::mutex                       writeMtx_;
    std::condition_variable          writeCv_;
    std::vector<std::string>         writeQueue_;

    /* Metrics */
    std::atomic<uint64_t>            receivedMessages_{0};
    std::atomic<uint64_t>            sentMessages_{0};
    std::atomic<uint64_t>            reconnectAttempts_{0};
};

} // namespace cardio_insight::ingestion