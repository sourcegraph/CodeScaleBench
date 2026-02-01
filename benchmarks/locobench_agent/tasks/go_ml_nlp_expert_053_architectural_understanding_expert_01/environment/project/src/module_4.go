```go
// File: src/module_4.go
// Package pipeline provides high–throughput, concurrent processing stages that can be
// chained together to build complex ML/NLP pipelines.  This module implements a
// real-time sentiment aggregation stage that converts raw SocialEvents into
// CommunityHealthScore events which are then published back to the event bus.
//
// The stage showcases several architectural patterns used across EchoPulse:
//   • Factory Pattern      – Constructor helpers hide kafka-driver details
//   • Strategy Pattern     – Pluggable SentimentScorer algorithms
//   • Pipeline Pattern     – A streaming operator that can be composed with others
//   • Observer Pattern     – Down-stream stages simply subscribe to the sink topic
//
// NOTE: Types like SocialEvent are duplicated here for self-containment.  In the
// real repository they are shared from a common `events` module.

package pipeline

import (
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"sync"
	"time"

	"github.com/segmentio/kafka-go"
	"go.uber.org/zap"
	"golang.org/x/sync/errgroup"
)

// ----------------------------------------------------------------------------
// Domain Models (trimmed copies from the events package)
// ----------------------------------------------------------------------------

// SocialEvent is the canonical, schemaless envelope representing any user
// interaction across the platform.  Ingest stages enrich the event with raw
// model predictions (e.g. sentiment) used by later stages.
type SocialEvent struct {
	ID          string    `json:"id"`
	CommunityID string    `json:"community_id"`
	UserID      string    `json:"user_id"`
	Timestamp   time.Time `json:"ts"`
	Payload     string    `json:"payload"`

	// Enriched signals
	Sentiment    float64 `json:"sentiment,omitempty"` // [-1, 1]
	ToxicityProb float64 `json:"toxicity_prob,omitempty"`
}

// CommunityHealthScore is a periodic, aggregated signal produced by this stage.
type CommunityHealthScore struct {
	CommunityID string    `json:"community_id"`
	WindowStart time.Time `json:"window_start"`
	WindowEnd   time.Time `json:"window_end"`
	// Aggregate statistics
	EventCount        int     `json:"event_count"`
	AvgSentiment      float64 `json:"avg_sentiment"`
	AvgToxicityProb   float64 `json:"avg_toxicity_prob"`
	PositiveSentRatio float64 `json:"positive_sent_ratio"`
}

// ----------------------------------------------------------------------------
// Sentiment Scoring Strategy (Strategy Pattern)
// ----------------------------------------------------------------------------

// SentimentScorer scores an incoming SocialEvent.  Several concrete strategies
// may exist (lexicon, transformer, remote-gRPC, etc.).
type SentimentScorer interface {
	Score(ctx context.Context, evt *SocialEvent) (float64, error)
	Name() string
}

// WeightedLexiconScorer is a simple, deterministic scorer useful for
// quick-feedback or as a canary/baseline model.
type WeightedLexiconScorer struct {
	weights map[string]float64
}

// NewWeightedLexiconScorer constructs a scorer from the supplied lexicon map.
// A real implementation might load from an on-disk artifact in the model store.
func NewWeightedLexiconScorer(lexicon map[string]float64) *WeightedLexiconScorer {
	return &WeightedLexiconScorer{weights: lexicon}
}

// Score implements SentimentScorer.
func (w *WeightedLexiconScorer) Score(_ context.Context, evt *SocialEvent) (float64, error) {
	if evt == nil {
		return 0, errors.New("nil event")
	}
	var score float64
	for token, weight := range w.weights {
		if containsInsensitive(evt.Payload, token) {
			score += weight
		}
	}
	// Clamp between -1 and 1
	if score > 1 {
		score = 1
	}
	if score < -1 {
		score = -1
	}
	return score, nil
}

// Name returns the human-friendly algorithm name.
func (w *WeightedLexiconScorer) Name() string { return "weighted_lexicon" }

// containsInsensitive is a naive string utility; real code should use proper
// tokenization and matching for Unicode.
func containsInsensitive(s, substr string) bool {
	return len(s) >= len(substr) && // quick length check
		(len(substr) == 0 || // empty substr considered as contained
			// case-insensitive contains
			containsFold(s, substr))
}

func containsFold(s, substr string) bool { // go 1.19 lacks strings.ContainsFold
	for i := 0; i+len(substr) <= len(s); i++ {
		if equalFold(s[i:i+len(substr)], substr) {
			return true
		}
	}
	return false
}

func equalFold(a, b string) bool {
	if len(a) != len(b) {
		return false
	}
	for i := range a {
		ra, rb := a[i], b[i]
		// minimal ASCII-only case fold
		if ra|32 != rb|32 {
			return false
		}
	}
	return true
}

// ----------------------------------------------------------------------------
// Aggregator Stage (Pipeline Pattern)
// ----------------------------------------------------------------------------

// AggregatorConfig defines all tunables for a sentiment aggregator.
type AggregatorConfig struct {
	SourceTopic      string        // raw event topic
	SinkTopic        string        // aggregated score topic
	Brokers          []string      // kafka brokers
	GroupID          string        // consumer group
	Window           time.Duration // sliding window length
	FlushInterval    time.Duration // how often to emit aggregate
	Logger           *zap.Logger   // structured logger
	Scorer           SentimentScorer
	Clock            func() time.Time // testable time source
	CommitInterval   time.Duration    // kafka commit interval
	ReaderBufferSize int              // kafka reader buffer
	WriterBatchSize  int              // kafka writer batch
}

// Aggregator ingests SocialEvents, computes per-community aggregates and emits
// CommunityHealthScore messages.
type Aggregator struct {
	cfg     AggregatorConfig
	reader  *kafka.Reader
	writer  *kafka.Writer
	buckets *bucketStore
}

// NewAggregator is the factory entrypoint (Factory Pattern).
func NewAggregator(cfg AggregatorConfig) (*Aggregator, error) {
	if cfg.Logger == nil {
		cfg.Logger = zap.NewNop()
	}
	if cfg.Scorer == nil {
		return nil, errors.New("scorer must not be nil")
	}
	if len(cfg.Brokers) == 0 {
		return nil, errors.New("brokers slice empty")
	}
	if cfg.Clock == nil {
		cfg.Clock = time.Now
	}
	if cfg.Window <= 0 || cfg.FlushInterval <= 0 {
		return nil, errors.New("invalid window/flush values")
	}

	r := kafka.NewReader(kafka.ReaderConfig{
		Brokers:        cfg.Brokers,
		Topic:          cfg.SourceTopic,
		GroupID:        cfg.GroupID,
		MinBytes:       1e3, // 1KB
		MaxBytes:       10e6,
		CommitInterval: cfg.CommitInterval,
		MaxWait:        500 * time.Millisecond,
		LogFunc:        cfg.Logger.Sugar().Debugf,
		ErrorLogger:    kafka.LoggerFunc(cfg.Logger.Sugar().Errorf),
	})
	if cfg.ReaderBufferSize > 0 {
		r.SetReadLagInterval(0) // disable lag metrics for manual buffering
	}

	w := &kafka.Writer{
		Addr:         kafka.TCP(cfg.Brokers...),
		Topic:        cfg.SinkTopic,
		Balancer:     &kafka.LeastBytes{},
		BatchTimeout: 10 * time.Millisecond,
		BatchSize:    cfg.WriterBatchSize,
		RequiredAcks: kafka.RequireOne,
		Async:        true,
		ErrorLogger:  kafka.LoggerFunc(cfg.Logger.Sugar().Errorf),
	}

	return &Aggregator{
		cfg:     cfg,
		reader:  r,
		writer:  w,
		buckets: newBucketStore(cfg.Window, cfg.Clock),
	}, nil
}

// Start launches the aggregator loop and blocks until ctx is cancelled or an
// unrecoverable error occurs.
func (a *Aggregator) Start(ctx context.Context) error {
	g, ctx := errgroup.WithContext(ctx)

	// Goroutine #1: consume and update buckets
	g.Go(func() error {
		for {
			m, err := a.reader.FetchMessage(ctx)
			if err != nil {
				return fmt.Errorf("fetch message: %w", err)
			}

			var evt SocialEvent
			if err := json.Unmarshal(m.Value, &evt); err != nil {
				a.cfg.Logger.Warn("invalid event payload", zap.Error(err))
				// still commit offset to avoid poison pill loops
				_ = a.reader.CommitMessages(ctx, m)
				continue
			}

			// Score event if not already scored upstream
			if evt.Sentiment == 0 {
				score, err := a.cfg.Scorer.Score(ctx, &evt)
				if err != nil {
					a.cfg.Logger.Warn("scoring failed", zap.Error(err))
					_ = a.reader.CommitMessages(ctx, m)
					continue
				}
				evt.Sentiment = score
			}

			a.buckets.add(&evt)

			// Async commit.  Errors are handled by group error return.
			if err := a.reader.CommitMessages(ctx, m); err != nil {
				return fmt.Errorf("commit: %w", err)
			}
		}
	})

	// Goroutine #2: periodic flush
	g.Go(func() error {
		ticker := time.NewTicker(a.cfg.FlushInterval)
		defer ticker.Stop()

		for {
			select {
			case <-ctx.Done():
				return ctx.Err()
			case <-ticker.C:
				scores := a.buckets.flush()
				if len(scores) == 0 {
					continue
				}
				msgs := make([]kafka.Message, 0, len(scores))
				now := a.cfg.Clock()
				for _, s := range scores {
					s.WindowEnd = now
					value, err := json.Marshal(s)
					if err != nil {
						a.cfg.Logger.Warn("marshal score", zap.Error(err))
						continue
					}
					msgs = append(msgs, kafka.Message{
						Key:   []byte(s.CommunityID),
						Value: value,
						Time:  now,
					})
				}
				if err := a.writer.WriteMessages(ctx, msgs...); err != nil {
					a.cfg.Logger.Error("publish scores", zap.Error(err))
					return err
				}
				a.cfg.Logger.Debug("flushed community scores",
					zap.Int("count", len(msgs)))
			}
		}
	})

	return g.Wait()
}

// Close stops the kafka writer/reader.  Callers should Cancel the ctx passed to
// Start() before invoking Close().
func (a *Aggregator) Close() error {
	err1 := a.reader.Close()
	err2 := a.writer.Close()
	if err1 != nil {
		return err1
	}
	return err2
}

// ----------------------------------------------------------------------------
// Internal State – Sliding Window Bucket Store
// ----------------------------------------------------------------------------

// bucket aggregates events falling into a given time slot.
type bucket struct {
	sumSent float64
	sumTox  float64
	posSent int
	count   int
}

// bucketStore maintains per-community ring buffers.
type bucketStore struct {
	window      time.Duration
	clock       func() time.Time
	mu          sync.RWMutex
	communities map[string]*ring
}

func newBucketStore(window time.Duration, clock func() time.Time) *bucketStore {
	return &bucketStore{
		window:      window,
		clock:       clock,
		communities: make(map[string]*ring),
	}
}

// add inserts event into the correct bucket for its community.
func (bs *bucketStore) add(evt *SocialEvent) {
	now := bs.clock()
	bs.mu.Lock()
	r, ok := bs.communities[evt.CommunityID]
	if !ok {
		r = newRing(bs.window, now)
		bs.communities[evt.CommunityID] = r
	}
	bs.mu.Unlock()

	r.add(evt)
}

// flush returns CommunityHealthScore snapshots and discards expired buckets.
func (bs *bucketStore) flush() []CommunityHealthScore {
	now := bs.clock()
	bs.mu.RLock()
	defer bs.mu.RUnlock()

	var out []CommunityHealthScore
	for cid, r := range bs.communities {
		stats := r.snapshot(now)
		if stats.EventCount == 0 {
			continue
		}
		stats.CommunityID = cid
		stats.WindowStart = now.Add(-bs.window)
		out = append(out, stats)
	}
	return out
}

// ----------------------------------------------------------------------------
// Ring Buffer per Community
// ----------------------------------------------------------------------------

type ring struct {
	size     int           // number of buckets
	step     time.Duration // duration per bucket
	buckets  []bucket
	headTime time.Time // inclusive start time of head bucket
	mu       sync.Mutex
}

func newRing(window time.Duration, now time.Time) *ring {
	const steps = 12 // tune granularity; 12 buckets == 5s for 1m window
	step := window / steps
	if step < time.Second {
		step = time.Second
	}
	return &ring{
		size:     int(window / step),
		step:     step,
		buckets:  make([]bucket, int(window/step)),
		headTime: now.Truncate(step),
	}
}

func (r *ring) advance(now time.Time) {
	// calculate how many buckets we need to advance
	diff := int(now.Sub(r.headTime) / r.step)
	if diff <= 0 {
		return
	}
	for i := 0; i < diff && i < r.size; i++ {
		// zero out the bucket that moves out of the window
		index := (i + r.index(0)) % r.size
		r.buckets[index] = bucket{}
	}
	r.headTime = r.headTime.Add(time.Duration(diff) * r.step)
}

func (r *ring) index(offset int) int {
	return (int(r.headTime.UnixNano()/r.step.Nanoseconds()) + offset) % r.size
}

func (r *ring) bucketFor(ts time.Time) int {
	diff := int(ts.Sub(r.headTime) / r.step)
	return r.index(diff)
}

func (r *ring) add(evt *SocialEvent) {
	if evt == nil {
		return
	}
	r.mu.Lock()
	defer r.mu.Unlock()

	now := evt.Timestamp
	r.advance(now)
	idx := r.bucketFor(now)
	b := &r.buckets[idx]
	b.sumSent += evt.Sentiment
	b.sumTox += evt.ToxicityProb
	if evt.Sentiment > 0 {
		b.posSent++
	}
	b.count++
}

func (r *ring) snapshot(now time.Time) CommunityHealthScore {
	r.mu.Lock()
	defer r.mu.Unlock()

	r.advance(now)

	var score CommunityHealthScore
	for i := 0; i < r.size; i++ {
		b := r.buckets[i]
		score.EventCount += b.count
		score.AvgSentiment += b.sumSent
		score.AvgToxicityProb += b.sumTox
		score.PositiveSentRatio += float64(b.posSent)
	}
	if score.EventCount > 0 {
		score.AvgSentiment /= float64(score.EventCount)
		score.AvgToxicityProb /= float64(score.EventCount)
		score.PositiveSentRatio /= float64(score.EventCount)
	}
	return score
}
```