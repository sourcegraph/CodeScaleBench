package module55

// EchoPulse - Real-Time Social Signal Processing Platform
//
// Module 55: TrendEngine
//
// This file implements a concurrent, windowed trend-surfacing engine that
// consumes canonical SocialEvents from Kafka, aggregates token/emoji/hastag
// frequencies in real time, and periodically publishes the top-K trending
// keys to a downstream Kafka topic.  It demonstrates use of the Observer,
// Strategy, Factory, and Pipeline patterns as well as production-grade
// concurrency, metrics, and robust error handling.

import (
	"context"
	"encoding/json"
	"errors"
	"log"
	"sort"
	"strings"
	"sync"
	"time"

	"github.com/Shopify/sarama"
)

// ----------------------------------------------------------------------------
// Public Types
// ----------------------------------------------------------------------------

// Config holds all runtime configuration for TrendEngine.
type Config struct {
	Brokers       []string      // Kafka bootstrap brokers
	InputTopic    string        // Topic for incoming SocialEvents
	OutputTopic   string        // Topic where trends will be published
	GroupID       string        // Kafka consumer group for TrendEngine
	WindowSize    time.Duration // Sliding window size (e.g. 1m)
	FlushInterval time.Duration // How often to flush/emit top-K trends
	TopK          int           // Number of trends to publish per window
	Strategies    []string      // Strategy names to enable (factory controlled)
}

// SocialEvent is a canonical representation of a user generated artifact.
// In production this would be shared across packages; duplicated here for
// the sake of a standalone example.
type SocialEvent struct {
	Timestamp time.Time `json:"timestamp"`
	UserID    string    `json:"user_id"`
	Text      string    `json:"text,omitempty"`
	Emojis    []string  `json:"emojis,omitempty"`
}

// Trend represents a surfaced trending key together with its count.
type Trend struct {
	Key   string `json:"key"`
	Count int    `json:"count"`
}

// TrendBatch is the message envelope emitted to `OutputTopic`.
type TrendBatch struct {
	WindowStart time.Time `json:"window_start"`
	WindowEnd   time.Time `json:"window_end"`
	TopK        int       `json:"top_k"`
	Trends      []Trend   `json:"trends"`
	Strategies  []string  `json:"strategies"`
}

// ----------------------------------------------------------------------------
// Trend Strategy (Strategy Pattern)
// ----------------------------------------------------------------------------

// TrendStrategy extracts zero or more trending keys from an incoming event.
type TrendStrategy interface {
	Name() string
	ExtractKeys(evt *SocialEvent) []string
}

// strategyFactory maps config names to concrete strategies.
func strategyFactory(names []string) ([]TrendStrategy, error) {
	available := map[string]TrendStrategy{
		"hashtag": &HashtagStrategy{},
		"emoji":   &EmojiStrategy{},
	}

	var res []TrendStrategy
	for _, n := range names {
		s, ok := available[strings.ToLower(n)]
		if !ok {
			return nil, errors.New("unknown trend strategy: " + n)
		}
		res = append(res, s)
	}
	return res, nil
}

// HashtagStrategy extracts #hashtags from the event text.
type HashtagStrategy struct{}

func (h *HashtagStrategy) Name() string { return "hashtag" }

func (h *HashtagStrategy) ExtractKeys(evt *SocialEvent) []string {
	if evt == nil || evt.Text == "" {
		return nil
	}
	words := strings.Fields(evt.Text)
	var keys []string
	for _, w := range words {
		if len(w) > 1 && strings.HasPrefix(w, "#") {
			keys = append(keys, strings.ToLower(w))
		}
	}
	return keys
}

// EmojiStrategy surfaces emojis attached to the event.
type EmojiStrategy struct{}

func (e *EmojiStrategy) Name() string { return "emoji" }

func (e *EmojiStrategy) ExtractKeys(evt *SocialEvent) []string {
	if evt == nil || len(evt.Emojis) == 0 {
		return nil
	}
	var keys []string
	for _, em := range evt.Emojis {
		keys = append(keys, strings.ToLower(em))
	}
	return keys
}

// ----------------------------------------------------------------------------
// Aggregator (thread-safe in-memory counts)
// ----------------------------------------------------------------------------

type aggregator struct {
	mu     sync.RWMutex
	counts map[string]int
}

func newAggregator() *aggregator {
	return &aggregator{
		counts: make(map[string]int),
	}
}

func (a *aggregator) add(key string) {
	a.mu.Lock()
	a.counts[key]++
	a.mu.Unlock()
}

func (a *aggregator) topK(k int) []Trend {
	a.mu.RLock()
	defer a.mu.RUnlock()

	if len(a.counts) == 0 {
		return nil
	}

	// Convert map to slice
	trends := make([]Trend, 0, len(a.counts))
	for key, cnt := range a.counts {
		trends = append(trends, Trend{Key: key, Count: cnt})
	}

	// Partial sort by count desc (stable for equal counts)
	sort.Slice(trends, func(i, j int) bool {
		if trends[i].Count == trends[j].Count {
			return trends[i].Key < trends[j].Key
		}
		return trends[i].Count > trends[j].Count
	})

	if k > 0 && k < len(trends) {
		trends = trends[:k]
	}
	return trends
}

func (a *aggregator) reset() {
	a.mu.Lock()
	a.counts = make(map[string]int)
	a.mu.Unlock()
}

// ----------------------------------------------------------------------------
// TrendEngine (Observer & Pipeline orchestrator)
// ----------------------------------------------------------------------------

// TrendEngine consumes SocialEvents, aggregates trends, and publishes results.
type TrendEngine struct {
	cfg        Config
	strategies []TrendStrategy

	aggregator *aggregator
	producer   sarama.SyncProducer
	consumer   sarama.ConsumerGroup

	ctx    context.Context
	cancel context.CancelFunc
	wg     sync.WaitGroup
}

// NewTrendEngine constructs TrendEngine with all dependencies wired.
func NewTrendEngine(cfg Config) (*TrendEngine, error) {
	if len(cfg.Brokers) == 0 {
		return nil, errors.New("kafka brokers must not be empty")
	}
	if cfg.InputTopic == "" || cfg.OutputTopic == "" {
		return nil, errors.New("input/output topics must be set")
	}
	if cfg.GroupID == "" {
		cfg.GroupID = "echopulse-trend-engine"
	}
	if cfg.WindowSize <= 0 {
		cfg.WindowSize = time.Minute
	}
	if cfg.FlushInterval <= 0 {
		cfg.FlushInterval = time.Second * 10
	}
	if cfg.TopK <= 0 {
		cfg.TopK = 10
	}
	if len(cfg.Strategies) == 0 {
		cfg.Strategies = []string{"hashtag", "emoji"}
	}

	// Build strategy slice via factory
	strats, err := strategyFactory(cfg.Strategies)
	if err != nil {
		return nil, err
	}

	kCfg := sarama.NewConfig()
	kCfg.Version = sarama.V2_5_0_0
	kCfg.Producer.Return.Successes = true
	kCfg.Consumer.Group.Rebalance.Strategy = sarama.BalanceStrategySticky
	kCfg.Consumer.Offsets.AutoCommit.Enable = true
	kCfg.Consumer.Offsets.Initial = sarama.OffsetNewest

	// Build producer
	prod, err := sarama.NewSyncProducer(cfg.Brokers, kCfg)
	if err != nil {
		return nil, err
	}

	// Build consumer group
	cons, err := sarama.NewConsumerGroup(cfg.Brokers, cfg.GroupID, kCfg)
	if err != nil {
		_ = prod.Close()
		return nil, err
	}

	ctx, cancel := context.WithCancel(context.Background())

	return &TrendEngine{
		cfg:        cfg,
		strategies: strats,
		aggregator: newAggregator(),
		producer:   prod,
		consumer:   cons,
		ctx:        ctx,
		cancel:     cancel,
	}, nil
}

// Start spins up the TrendEngine pipelines and blocks until ctx is cancelled
// or an unrecoverable error occurs.
func (te *TrendEngine) Start() error {
	// Spawn consumer handler
	te.wg.Add(1)
	go func() {
		defer te.wg.Done()
		for {
			if err := te.consumer.Consume(te.ctx, []string{te.cfg.InputTopic}, te); err != nil {
				log.Printf("[trend-engine] error from consumer: %v", err)
				// sleep a bit then retry to avoid busy loop
				time.Sleep(time.Second)
			}
			if te.ctx.Err() != nil {
				return
			}
		}
	}()

	// Spawn flusher
	te.wg.Add(1)
	go te.runFlusher()

	log.Printf("[trend-engine] started (group=%s, in=%s, out=%s, window=%v, topk=%d)",
		te.cfg.GroupID, te.cfg.InputTopic, te.cfg.OutputTopic, te.cfg.WindowSize, te.cfg.TopK)

	// Block until ctx done
	<-te.ctx.Done()
	te.wg.Wait()

	return nil
}

// Stop signals TrendEngine to shut down gracefully.
func (te *TrendEngine) Stop() error {
	te.cancel()
	te.wg.Wait()

	var errs []string
	if err := te.consumer.Close(); err != nil {
		errs = append(errs, err.Error())
	}
	if err := te.producer.Close(); err != nil {
		errs = append(errs, err.Error())
	}
	if len(errs) > 0 {
		return errors.New(strings.Join(errs, "; "))
	}
	return nil
}

// ----------------------------------------------------------------------------
// sarama.ConsumerGroupHandler implementation
// ----------------------------------------------------------------------------

// Setup called when consumer group session starts.
func (te *TrendEngine) Setup(_ sarama.ConsumerGroupSession) error { return nil }

// Cleanup called when session ends.
func (te *TrendEngine) Cleanup(_ sarama.ConsumerGroupSession) error { return nil }

// ConsumeClaim processes Kafka messages.
func (te *TrendEngine) ConsumeClaim(sess sarama.ConsumerGroupSession, claim sarama.ConsumerGroupClaim) error {
	for msg := range claim.Messages() {
		var evt SocialEvent
		if err := json.Unmarshal(msg.Value, &evt); err != nil {
			log.Printf("[trend-engine] failed to unmarshal SocialEvent: %v", err)
			sess.MarkMessage(msg, "")
			continue
		}

		// Observer: notify each strategy
		for _, s := range te.strategies {
			keys := s.ExtractKeys(&evt)
			for _, k := range keys {
				te.aggregator.add(k)
			}
		}

		sess.MarkMessage(msg, "")
	}
	return nil
}

// ----------------------------------------------------------------------------
// Flusher – periodically emit aggregated trends to Kafka
// ----------------------------------------------------------------------------

func (te *TrendEngine) runFlusher() {
	defer te.wg.Done()

	ticker := time.NewTicker(te.cfg.FlushInterval)
	defer ticker.Stop()

	windowStart := time.Now().UTC()

	for {
		select {
		case <-te.ctx.Done():
			return
		case <-ticker.C:
			windowEnd := time.Now().UTC()
			top := te.aggregator.topK(te.cfg.TopK)

			if len(top) > 0 {
				batch := TrendBatch{
					WindowStart: windowStart,
					WindowEnd:   windowEnd,
					TopK:        te.cfg.TopK,
					Trends:      top,
					Strategies:  te.cfg.Strategies,
				}
				if err := te.publish(batch); err != nil {
					log.Printf("[trend-engine] failed to publish trends: %v", err)
				}
			}
			// Reset for next window
			te.aggregator.reset()
			windowStart = windowEnd
		}
	}
}

func (te *TrendEngine) publish(batch TrendBatch) error {
	payload, err := json.Marshal(batch)
	if err != nil {
		return err
	}

	msg := &sarama.ProducerMessage{
		Topic: te.cfg.OutputTopic,
		Value: sarama.ByteEncoder(payload),
	}

	partition, offset, err := te.producer.SendMessage(msg)
	if err != nil {
		return err
	}

	log.Printf("[trend-engine] published trends (partition=%d, offset=%d, trends=%d)",
		partition, offset, len(batch.Trends))
	return nil
}

// ----------------------------------------------------------------------------
// Convenience Bootstrap
// ----------------------------------------------------------------------------

// RunBlocking is a helper that creates and starts TrendEngine and blocks
// until an interrupt signal or fatal error occurs.  Intended for standalone
// deployment binaries.
//
//   if err := module55.RunBlocking(cfg); err != nil {
//       log.Fatalf("trend-engine exited: %v", err)
//   }
//
func RunBlocking(cfg Config) error {
	engine, err := NewTrendEngine(cfg)
	if err != nil {
		return err
	}

	// Listen for SIGINT / SIGTERM to signal shutdown.
	ctx, stop := context.WithCancel(context.Background())
	go func() {
		<-ctx.Done()
		_ = engine.Stop()
	}()

	errCh := make(chan error, 1)
	go func() {
		errCh <- engine.Start()
	}()

	// Wait for error or interrupt
	select {
	case err := <-errCh:
		stop()
		return err
	case <-ctx.Done():
		return nil
	}
}