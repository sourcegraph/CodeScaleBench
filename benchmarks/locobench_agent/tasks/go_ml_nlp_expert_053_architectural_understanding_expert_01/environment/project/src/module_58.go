```go
// Code generated for EchoPulse – Real-Time Social Signal Processing Platform.
// File: src/module_58.go
//
// Package trend is responsible for surfacing trending keywords from the
// continuous stream of canonical SocialEvent messages.  It consumes the
// SocialEvent bus (Kafka topic), updates an exponentially-decayed counter per
// token, and periodically publishes a TrendEvent back onto Kafka so that other
// downstream services (dashboards, boost engines, recommendation pipelines)
// can react in near real-time.
//
// The implementation uses the Sarama Kafka client, a lock-free EWMA counter
// for per-token scoring, and adheres to Go best-practices such as context
// propagation, structured logging, and graceful shutdown.
//
// NOTE: External dependencies are assumed to be vendored or otherwise managed
// by the parent repository’s build system.

package trend

import (
	"context"
	"encoding/json"
	"errors"
	"os"
	"os/signal"
	"sort"
	"strings"
	"sync"
	"syscall"
	"time"

	"github.com/Shopify/sarama"
)

// -----------------------------------------------------------------------------
// Configuration
// -----------------------------------------------------------------------------

// SurferConfig contains everything required to spin-up a TrendSurfer.
type SurferConfig struct {
	// Kafka
	Brokers          []string      // ["broker-1:9092", "broker-2:9092"]
	ConsumerGroup    string        // "trend-surfacer"
	InputTopic       string        // "social-events"
	OutputTopic      string        // "trend-events"
	PublishInterval  time.Duration // e.g. 5 * time.Second

	// Trending algorithm
	HalfLife         time.Duration // EWMA half-life for decay
	TopK             int           // Number of trends to emit every interval

	// Misc
	TokenMinLength   int // Ignore tokens shorter than this
}

// Validate checks that the supplied config makes sense.
func (c SurferConfig) Validate() error {
	if len(c.Brokers) == 0 {
		return errors.New("brokers list cannot be empty")
	}
	if c.ConsumerGroup == "" {
		return errors.New("consumer group must be set")
	}
	if c.InputTopic == "" || c.OutputTopic == "" {
		return errors.New("input and output topic names are required")
	}
	if c.PublishInterval <= 0 {
		return errors.New("publish interval must be > 0")
	}
	if c.HalfLife <= 0 {
		return errors.New("half-life must be > 0")
	}
	if c.TopK <= 0 {
		return errors.New("TopK must be > 0")
	}
	if c.TokenMinLength < 1 {
		c.TokenMinLength = 1
	}
	return nil
}

// -----------------------------------------------------------------------------
// Public API
// -----------------------------------------------------------------------------

// TrendSurfer consumes SocialEvents, aggregates trending tokens, and publishes
// TrendEvents at a fixed cadence.
type TrendSurfer struct {
	cfg SurferConfig

	consumer sarama.ConsumerGroup
	producer sarama.SyncProducer

	agg      *tokenAggregator
	stopCh   chan struct{}
	stopOnce sync.Once
}

// NewTrendSurfer constructs a ready-to-run TrendSurfer.  The caller is
// responsible for ultimately calling Close.
func NewTrendSurfer(cfg SurferConfig, saramaCfg *sarama.Config) (*TrendSurfer, error) {
	if err := cfg.Validate(); err != nil {
		return nil, err
	}

	if saramaCfg == nil {
		saramaCfg = sarama.NewConfig()
	}
	saramaCfg.Version = sarama.V2_5_0_0
	saramaCfg.Consumer.Offsets.Initial = sarama.OffsetNewest
	saramaCfg.Producer.Return.Successes = true

	consumer, err := sarama.NewConsumerGroup(cfg.Brokers, cfg.ConsumerGroup, saramaCfg)
	if err != nil {
		return nil, err
	}

	producer, err := sarama.NewSyncProducer(cfg.Brokers, saramaCfg)
	if err != nil {
		_ = consumer.Close()
		return nil, err
	}

	return &TrendSurfer{
		cfg:      cfg,
		consumer: consumer,
		producer: producer,
		agg:      newTokenAggregator(cfg.HalfLife),
		stopCh:   make(chan struct{}),
	}, nil
}

// Run starts consuming, processing, and publishing until the context is
// cancelled or Close is called.
func (ts *TrendSurfer) Run(ctx context.Context) error {
	ctx, cancel := context.WithCancel(ctx)
	defer cancel()

	// Handle external OS signals for graceful shutdown.
	go ts.listenForSignals(cancel)

	// Schedule periodic publishing of TrendEvents.
	go ts.publishLoop(ctx)

	// Sarama requires a ConsumerGroupHandler implementation.
	handler := &consumerHandler{
		cfg:      ts.cfg,
		agg:      ts.agg,
		minLen:   ts.cfg.TokenMinLength,
		stopCh:   ts.stopCh,
	}

	for {
		// Consume in a blocking manner; sarama handles partition balancing.
		if err := ts.consumer.Consume(ctx, []string{ts.cfg.InputTopic}, handler); err != nil {
			return err
		}
		// Exit when context is done or Stop() has been invoked.
		if ctx.Err() != nil {
			return ctx.Err()
		}
		select {
		case <-ts.stopCh:
			return nil
		default:
		}
	}
}

// Close shuts down the TrendSurfer immediately.
func (ts *TrendSurfer) Close() error {
	ts.stopOnce.Do(func() { close(ts.stopCh) })
	_ = ts.consumer.Close()
	return ts.producer.Close()
}

// -----------------------------------------------------------------------------
// OS Signal Handling
// -----------------------------------------------------------------------------

func (ts *TrendSurfer) listenForSignals(cancel context.CancelFunc) {
	ch := make(chan os.Signal, 1)
	signal.Notify(ch, syscall.SIGINT, syscall.SIGTERM)
	<-ch
	cancel()
}

// -----------------------------------------------------------------------------
// Consumer Group Handler
// -----------------------------------------------------------------------------

type consumerHandler struct {
	cfg    SurferConfig
	agg    *tokenAggregator
	minLen int
	stopCh <-chan struct{}
}

func (h *consumerHandler) Setup(_ sarama.ConsumerGroupSession) error   { return nil }
func (h *consumerHandler) Cleanup(_ sarama.ConsumerGroupSession) error { return nil }

func (h *consumerHandler) ConsumeClaim(sess sarama.ConsumerGroupSession, claim sarama.ConsumerGroupClaim) error {
	for {
		select {
		case msg, ok := <-claim.Messages():
			if !ok {
				return nil
			}
			h.processMessage(msg.Value)
			sess.MarkMessage(msg, "")
		case <-h.stopCh:
			return nil
		}
	}
}

func (h *consumerHandler) processMessage(raw []byte) {
	var ev SocialEvent
	if err := json.Unmarshal(raw, &ev); err != nil {
		// In production a structured logger would be used with a sampling rate.
		return
	}
	tokens := tokenize(ev.Text, h.minLen)
	h.agg.update(tokens)
}

// -----------------------------------------------------------------------------
// Event Schemas
// -----------------------------------------------------------------------------

// SocialEvent is the canonical envelope for inbound messages.
type SocialEvent struct {
	ID        string    `json:"id"`
	UserID    string    `json:"user_id"`
	Text      string    `json:"text"`
	Timestamp time.Time `json:"timestamp"`
}

// TrendEvent is what we publish downstream.
type TrendEvent struct {
	AsOf   time.Time        `json:"as_of"`
	TopK   int              `json:"top_k"`
	Tokens []TrendingToken  `json:"tokens"`
}

// TrendingToken bundles a token with its EWMA score.
type TrendingToken struct {
	Token string  `json:"token"`
	Score float64 `json:"score"`
}

// -----------------------------------------------------------------------------
// Publish Loop
// -----------------------------------------------------------------------------

func (ts *TrendSurfer) publishLoop(ctx context.Context) {
	ticker := time.NewTicker(ts.cfg.PublishInterval)
	defer ticker.Stop()

	for {
		select {
		case <-ticker.C:
			ts.publishSnapshot()
		case <-ctx.Done():
			return
		case <-ts.stopCh:
			return
		}
	}
}

func (ts *TrendSurfer) publishSnapshot() {
	top := ts.agg.topK(ts.cfg.TopK)
	event := TrendEvent{
		AsOf:   time.Now().UTC(),
		TopK:   len(top),
		Tokens: top,
	}

	payload, err := json.Marshal(event)
	if err != nil {
		return
	}

	msg := &sarama.ProducerMessage{
		Topic: ts.cfg.OutputTopic,
		Key:   sarama.StringEncoder("trend_snapshot"),
		Value: sarama.ByteEncoder(payload),
	}

	_, _, _ = ts.producer.SendMessage(msg)
}

// -----------------------------------------------------------------------------
// Token Aggregator (EWMA)
// -----------------------------------------------------------------------------

// tokenAggregator maintains an exponentially decayed score per token.
//
//		score(t) = score(t-1) * 0.5^(Δ / halfLife) + 1
//
// where Δ is time elapsed since the last update.
type tokenAggregator struct {
	mu       sync.RWMutex
	halfLife time.Duration
	entries  map[string]*tokenEntry
}

type tokenEntry struct {
	score float64
	last  time.Time
}

func newTokenAggregator(halfLife time.Duration) *tokenAggregator {
	return &tokenAggregator{
		halfLife: halfLife,
		entries:  make(map[string]*tokenEntry, 1024),
	}
}

func (ta *tokenAggregator) update(tokens []string) {
	now := time.Now()

	ta.mu.Lock()
	defer ta.mu.Unlock()

	for _, tok := range tokens {
		ent, ok := ta.entries[tok]
		if !ok {
			ent = &tokenEntry{score: 1, last: now}
			ta.entries[tok] = ent
			continue
		}

		decay := mathPowHalf(float64(now.Sub(ent.last)) / float64(ta.halfLife))
		ent.score = ent.score*decay + 1
		ent.last = now
	}
}

func (ta *tokenAggregator) topK(k int) []TrendingToken {
	ta.mu.RLock()
	defer ta.mu.RUnlock()

	// Guard against empty map.
	if len(ta.entries) == 0 {
		return nil
	}

	// Build slice and sort.
	out := make([]TrendingToken, 0, len(ta.entries))
	for tok, ent := range ta.entries {
		// Apply decay so old tokens don’t artificially persist.
		decay := mathPowHalf(float64(time.Since(ent.last)) / float64(ta.halfLife))
		score := ent.score * decay
		if score <= 0.01 { // prune near-zero
			continue
		}
		out = append(out, TrendingToken{Token: tok, Score: score})
	}

	sort.Slice(out, func(i, j int) bool { return out[i].Score > out[j].Score })

	if k > len(out) {
		k = len(out)
	}
	return out[:k]
}

// mathPowHalf computes 0.5^(x)
// It’s faster than math.Pow for tiny bases, avoids import of math pkg.
func mathPowHalf(x float64) float64 {
	// log2(e) ≈ 1.4426950408889634, 0.5^x = e^(x * ln(0.5))
	const lnHalf = -0.6931471805599453
	return exp(x * lnHalf)
}

// exp is a naive approximation of e^x using the first 10 terms of the
// Taylor expansion.  Replace with math.Exp in production builds to avoid
// precision loss.  Here we re-implement to remove heavy math dependency.
func exp(x float64) float64 {
	sum, term := 1.0, 1.0
	for i := 1; i < 10; i++ {
		term *= x / float64(i)
		sum += term
	}
	return sum
}

// -----------------------------------------------------------------------------
// Tokenization Helpers
// -----------------------------------------------------------------------------

// tokenize splits text into lower-cased tokens, removes punctuation and stop
// words, and filters short tokens.
func tokenize(s string, minLen int) []string {
	s = strings.ToLower(s)
	// Replace punctuation with spaces.
	s = strings.Map(func(r rune) rune {
		if r >= 'a' && r <= 'z' || r >= '0' && r <= '9' || r == ' ' {
			return r
		}
		return ' '
	}, s)

	fields := strings.Fields(s)
	out := make([]string, 0, len(fields))
	for _, f := range fields {
		if len(f) < minLen {
			continue
		}
		if _, stop := stopWords[f]; stop {
			continue
		}
		out = append(out, f)
	}
	return out
}

// A (very small) built-in English stop-word list.  In practice this should be
// configurable and language-aware.
var stopWords = map[string]struct{}{
	"the": {}, "and": {}, "for": {}, "that": {},
	"are": {}, "with": {}, "this": {}, "from": {},
	"have": {}, "but": {}, "not": {}, "you": {},
	"your": {}, "just": {}, "all": {}, "was": {},
}
```
