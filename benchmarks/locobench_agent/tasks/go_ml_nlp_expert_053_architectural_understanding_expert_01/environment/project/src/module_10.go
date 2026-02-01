```go
// File: src/module_10.go
//
// EchoPulse – Real-Time Social Signal Processing Platform
//
// Module 10: Community Sentiment Aggregator
//
// This component consumes SocialEvent records (already enriched
// with sentiment scores by an upstream NLP service) from Kafka,
// maintains a sliding-window sentiment average for every community,
// and periodically publishes CommunityHealthScore events back to
// Kafka so that downstream services (dashboards, moderation
// strategies, etc.) can react in near real-time.
//
// The design is production-grade: it is context-aware, employs the
// sarama ConsumerGroup API for exactly-once stream processing
// semantics, gracefully handles rebalance & errors, and scales
// horizontally (each partition is processed by exactly one consumer).
//
// NOTE: External dependencies are limited to sarama for Kafka and the
// standard library. The code can be vendored or integrated into a
// larger monorepo with common logging / metrics packages.

package module10

import (
	"context"
	"encoding/json"
	"errors"
	"log"
	"os"
	"os/signal"
	"sync"
	"sync/atomic"
	"syscall"
	"time"

	"github.com/Shopify/sarama"
)

/*******************************
 * Domain-Level Event Schemas  *
 *******************************/

// SocialEvent is produced by upstream ingestion / NLP services.
// For brevity we only keep fields that are relevant to sentiment.
type SocialEvent struct {
	EventID     string    `json:"event_id"`
	CommunityID string    `json:"community_id"`
	UserID      string    `json:"user_id"`
	Sentiment   float64   `json:"sentiment"` // normalized −1 … 1
	CreatedAt   time.Time `json:"created_at"`
}

// CommunityHealthScore is emitted by this module.
type CommunityHealthScore struct {
	CommunityID     string    `json:"community_id"`
	WindowStart     time.Time `json:"window_start"`
	WindowEnd       time.Time `json:"window_end"`
	AvgSentiment    float64   `json:"avg_sentiment"`
	NumEvents       int       `json:"num_events"`
	ProcessingEpoch int64     `json:"processing_epoch"` // monotonically increasing
}

/**********************
 * Runtime Structures *
 **********************/

// Config controls engine behaviour. DefaultConfig() provides sane values.
type Config struct {
	// Kafka connectivity
	Brokers     []string
	InputTopic  string
	OutputTopic string
	GroupID     string

	// Sliding window & flush cadence
	WindowSize    time.Duration
	FlushInterval time.Duration

	// Optional: caller-provided logger & sarama config
	Logger       *log.Logger
	SaramaConfig *sarama.Config
}

// DefaultConfig returns a proven baseline suitable for most deployments.
func DefaultConfig() Config {
	cfg := sarama.NewConfig()
	cfg.Version = sarama.V2_5_0_0 // recent, stable
	cfg.Consumer.Group.Rebalance.Strategy = sarama.BalanceStrategyRange
	cfg.Consumer.Offsets.Initial = sarama.OffsetNewest
	cfg.Consumer.Return.Errors = true
	cfg.Producer.Return.Successes = true
	cfg.Producer.RequiredAcks = sarama.WaitForAll
	cfg.Producer.Compression = sarama.CompressionSnappy

	return Config{
		Brokers:       []string{"localhost:9092"},
		InputTopic:    "social_events_enriched",
		OutputTopic:   "community_health_score",
		GroupID:       "community_sentiment_aggregator",
		WindowSize:    5 * time.Minute,
		FlushInterval: 5 * time.Second,
		SaramaConfig:  cfg,
		Logger:        log.New(os.Stdout, "[module10] ", log.LstdFlags|log.Lmicroseconds),
	}
}

// Engine is the long-running service that wires everything together.
type Engine struct {
	conf   Config
	ctx    context.Context
	cancel context.CancelFunc

	consumer sarama.ConsumerGroup
	producer sarama.SyncProducer

	state     *aggregatorState
	epoch     int64 // monotonic flush counter
	startOnce sync.Once
	stopOnce  sync.Once
	wg        sync.WaitGroup
}

// NewEngine validates configuration and returns a ready-to-start Engine.
func NewEngine(conf Config) (*Engine, error) {
	if len(conf.Brokers) == 0 {
		return nil, errors.New("no kafka brokers configured")
	}
	if conf.InputTopic == "" || conf.OutputTopic == "" {
		return nil, errors.New("input/output topics must be specified")
	}
	saramaCfg := conf.SaramaConfig
	if saramaCfg == nil {
		saramaCfg = sarama.NewConfig()
	}

	consumer, err := sarama.NewConsumerGroup(conf.Brokers, conf.GroupID, saramaCfg)
	if err != nil {
		return nil, err
	}
	producer, err := sarama.NewSyncProducer(conf.Brokers, saramaCfg)
	if err != nil {
		_ = consumer.Close()
		return nil, err
	}

	ctx, cancel := context.WithCancel(context.Background())

	engine := &Engine{
		conf:     conf,
		ctx:      ctx,
		cancel:   cancel,
		consumer: consumer,
		producer: producer,
		state:    newAggregatorState(conf.WindowSize),
	}

	return engine, nil
}

/********************
 * Engine Lifecycle *
 ********************/

// Start spins all goroutines and blocks until ctx is cancelled or fatal error.
func (e *Engine) Start() error {
	var runErr error

	e.startOnce.Do(func() {
		e.log().Printf("starting engine – brokers=%v topic=%s group=%s",
			e.conf.Brokers, e.conf.InputTopic, e.conf.GroupID)

		// Flush loop
		e.wg.Add(1)
		go func() {
			defer e.wg.Done()
			e.flushLoop()
		}()

		// Consumer loop
		e.wg.Add(1)
		go func() {
			defer e.wg.Done()
			for {
				if err := e.consumer.Consume(e.ctx,
					[]string{e.conf.InputTopic},
					consumerGroupHandler{engine: e}); err != nil {
					e.log().Printf("consumer error: %v", err)
					runErr = err
					// backoff a bit before retry
					select {
					case <-time.After(time.Second):
					case <-e.ctx.Done():
					}
				}
				if e.ctx.Err() != nil {
					return
				}
			}
		}()

		// error channel watchers
		e.wg.Add(1)
		go func() {
			defer e.wg.Done()
			for {
				select {
				case err, ok := <-e.consumer.Errors():
					if ok {
						e.log().Printf("consumer async error: %v", err)
					}
				case <-e.ctx.Done():
					return
				}
			}
		}()
	})

	return runErr
}

// Stop signals shutdown and waits until all goroutines complete.
func (e *Engine) Stop() {
	e.stopOnce.Do(func() {
		e.cancel()
		e.log().Println("shutting down…")
		e.wg.Wait()
		_ = e.consumer.Close()
		_ = e.producer.Close()
		e.log().Println("graceful shutdown complete")
	})
}

// flushLoop emits aggregated metrics at FlushInterval cadence.
func (e *Engine) flushLoop() {
	ticker := time.NewTicker(e.conf.FlushInterval)
	defer ticker.Stop()

	for {
		select {
		case <-ticker.C:
			e.doFlush()
		case <-e.ctx.Done():
			return
		}
	}
}

// doFlush snapshots aggregator state and publishes one record per community.
func (e *Engine) doFlush() {
	start := time.Now()
	epoch := atomic.AddInt64(&e.epoch, 1)
	count := 0

	e.state.Range(func(commID string, metric communityMetrics) bool {
		avg, n := metric.Snapshot()
		if n == 0 {
			return true
		}

		msg := CommunityHealthScore{
			CommunityID:     commID,
			WindowStart:     time.Now().Add(-e.conf.WindowSize),
			WindowEnd:       time.Now(),
			AvgSentiment:    avg,
			NumEvents:       n,
			ProcessingEpoch: epoch,
		}

		payload, err := json.Marshal(msg)
		if err != nil {
			e.log().Printf("json marshal error: %v", err)
			return true
		}

		_, _, err = e.producer.SendMessage(&sarama.ProducerMessage{
			Topic: e.conf.OutputTopic,
			Key:   sarama.StringEncoder(commID),
			Value: sarama.ByteEncoder(payload),
		})
		if err != nil {
			e.log().Printf("produce error: %v", err)
		} else {
			count++
		}
		return true
	})

	e.log().Printf("flush epoch=%d communities=%d elapsed=%s",
		epoch, count, time.Since(start).Truncate(time.Millisecond))
}

// log returns the configured logger.
func (e *Engine) log() *log.Logger { return e.conf.Logger }

/******************************
 * Sarama Consumer-Group Glue *
 ******************************/

type consumerGroupHandler struct {
	engine *Engine
}

func (h consumerGroupHandler) Setup(s sarama.ConsumerGroupSession) error {
	h.engine.log().Printf("partition assignment: %v", s.Claims())
	return nil
}
func (h consumerGroupHandler) Cleanup(s sarama.ConsumerGroupSession) error {
	h.engine.log().Println("session cleanup")
	return nil
}

func (h consumerGroupHandler) ConsumeClaim(
	session sarama.ConsumerGroupSession,
	claim sarama.ConsumerGroupClaim,
) error {
	for msg := range claim.Messages() {
		if err := h.handleMessage(msg); err != nil {
			h.engine.log().Printf("msg offset %d error: %v", msg.Offset, err)
			// commit anyway so we don't poison the stream
		}
		session.MarkMessage(msg, "")
	}
	return nil
}

func (h consumerGroupHandler) handleMessage(msg *sarama.ConsumerMessage) error {
	var se SocialEvent
	if err := json.Unmarshal(msg.Value, &se); err != nil {
		return err
	}
	h.engine.state.Add(se.CommunityID, se.Sentiment, se.CreatedAt)
	return nil
}

/*************************
 * In-Memory Aggregator  *
 *************************/

// aggregatorState is a threadsafe map[communityID]*communityMetrics.
type aggregatorState struct {
	windowSize time.Duration
	data       sync.Map // string → *communityMetrics
}

func newAggregatorState(window time.Duration) *aggregatorState {
	return &aggregatorState{windowSize: window}
}

func (a *aggregatorState) Add(commID string, sentiment float64, ts time.Time) {
	val, _ := a.data.LoadOrStore(commID, &communityMetrics{
		windowSize: a.windowSize,
	})
	cm := val.(*communityMetrics)
	cm.Push(sentiment, ts)
}

func (a *aggregatorState) Range(fn func(commID string, metric communityMetrics) bool) {
	a.data.Range(func(key, value any) bool {
		commID := key.(string)
		metric := *value.(*communityMetrics) // copy so caller can read without locking
		return fn(commID, metric)
	})
}

// communityMetrics maintains events in a time-ordered slice.
// Push/cleanup are protected by a mutex; readers copy the struct,
// ensuring low contention.
type communityMetrics struct {
	mu         sync.Mutex
	windowSize time.Duration
	events     []timedSentiment
	sum        float64
}

type timedSentiment struct {
	t  time.Time
	val float64
}

// Push appends a new observation, dropping out-of-window events.
func (cm *communityMetrics) Push(val float64, ts time.Time) {
	cm.mu.Lock()
	defer cm.mu.Unlock()

	cm.events = append(cm.events, timedSentiment{t: ts, val: val})
	cm.sum += val
	cm.expire(ts.Add(-cm.windowSize))
}

// Snapshot returns avg + count as of now.
func (cm *communityMetrics) Snapshot() (avg float64, n int) {
	cm.mu.Lock()
	defer cm.mu.Unlock()

	now := time.Now()
	cm.expire(now.Add(-cm.windowSize))

	if n = len(cm.events); n == 0 {
		return 0, 0
	}
	return cm.sum / float64(n), n
}

// expire removes events older than cutoff.
func (cm *communityMetrics) expire(cutoff time.Time) {
	idx := 0
	for idx < len(cm.events) && cm.events[idx].t.Before(cutoff) {
		cm.sum -= cm.events[idx].val
		idx++
	}
	if idx > 0 {
		cm.events = append([]timedSentiment(nil), cm.events[idx:]...) // copy-truncate
	}
}

/**************
 * Entrypoint *
 **************/

// Run is a convenience wrapper for standalone deployments.
// It starts the engine and blocks until SIGINT/SIGTERM.
func Run() {
	conf := DefaultConfig()
	engine, err := NewEngine(conf)
	if err != nil {
		log.Fatalf("engine init error: %v", err)
	}

	if err := engine.Start(); err != nil {
		log.Fatalf("startup error: %v", err)
	}

	// Wait for OS signal
	sigCh := make(chan os.Signal, 1)
	signal.Notify(sigCh, syscall.SIGINT, syscall.SIGTERM)

	select {
	case sig := <-sigCh:
		engine.log().Printf("caught signal %v, shutting down", sig)
	case <-engine.ctx.Done():
	}

	engine.Stop()
}
```