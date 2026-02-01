```go
// File: src/module_15.go
//
// EchoPulse – Real-Time Community Health Scorer
//
// This module consumes fine-grained social metrics (per-event sentiment &
// toxicity signals) from Kafka, maintains rolling, in-memory aggregates per
// community, and continuously publishes high-level “CommunityHealthScore”
// events back onto Kafka.
//
// Patterns in play:
//   • Observer / Publish–Subscribe    – Kafka reader & writer
//   • Strategy                        – ScoringStrategy interface
//   • Pipeline                        – Metrics → Aggregates → Scores
//
// External dependency: github.com/segmentio/kafka-go
// Make sure to vendor / go-get the package before building.

package healthscore

import (
	"context"
	"encoding/json"
	"errors"
	"log"
	"math"
	"os"
	"os/signal"
	"sync"
	"syscall"
	"time"

	kafka "github.com/segmentio/kafka-go"
)

// ---------------------------------------------------------------------------
// Public API
// ---------------------------------------------------------------------------

// Config groups all tunables for the scorer instance.
type Config struct {
	Brokers       []string
	GroupID       string
	InTopic       string
	OutTopic      string
	Window        time.Duration // rolling window length, e.g. 5m
	BucketSize    time.Duration // granularity inside Window, e.g. 5s
	FlushInterval time.Duration // how often to emit scores
	Logger        *log.Logger   // optional
}

// HealthScorer consumes per-event metrics and emits aggregate scores.
type HealthScorer struct {
	cfg    Config
	reader *kafka.Reader
	writer *kafka.Writer

	aggrMu     sync.RWMutex
	aggregates map[string]*rollingAgg // keyed by communityID

	strategy ScoringStrategy
	log      *log.Logger
}

// NewHealthScorer spins up a new scorer with sane defaults.
func NewHealthScorer(cfg Config) (*HealthScorer, error) {
	if len(cfg.Brokers) == 0 || cfg.InTopic == "" || cfg.OutTopic == "" {
		return nil, errors.New("healthscore: missing required kafka configuration")
	}
	if cfg.Window <= 0 {
		cfg.Window = 5 * time.Minute
	}
	if cfg.BucketSize <= 0 {
		cfg.BucketSize = 5 * time.Second
	}
	if cfg.FlushInterval <= 0 {
		cfg.FlushInterval = 10 * time.Second
	}
	if cfg.Logger == nil {
		cfg.Logger = log.New(os.Stdout, "[healthscore] ", log.LstdFlags|log.Lmsgprefix)
	}

	hs := &HealthScorer{
		cfg:        cfg,
		aggregates: make(map[string]*rollingAgg),
		strategy:   DefaultScoringStrategy{},
		log:        cfg.Logger,
	}

	hs.reader = kafka.NewReader(kafka.ReaderConfig{
		Brokers:     cfg.Brokers,
		GroupID:     cfg.GroupID,
		Topic:       cfg.InTopic,
		StartOffset: kafka.LastOffset,
		MaxBytes:    1 << 20, // 1 MiB
		Logger:      kafka.LoggerFunc(cfg.Logger.Printf),
		ErrorLogger: kafka.LoggerFunc(cfg.Logger.Printf),
	})

	hs.writer = &kafka.Writer{
		Addr:         kafka.TCP(cfg.Brokers...),
		Topic:        cfg.OutTopic,
		Balancer:     &kafka.Hash{}, // stable per communityID
		RequiredAcks: kafka.RequireAll,
		Logger:       kafka.LoggerFunc(cfg.Logger.Printf),
		ErrorLogger:  kafka.LoggerFunc(cfg.Logger.Printf),
	}

	return hs, nil
}

// Run starts consuming / producing and blocks until ctx is canceled.
func (hs *HealthScorer) Run(ctx context.Context) error {
	ctx, cancel := context.WithCancel(ctx)
	defer cancel()

	// Graceful shutdown on SIGINT/SIGTERM.
	go func() {
		sigCh := make(chan os.Signal, 1)
		signal.Notify(sigCh, syscall.SIGINT, syscall.SIGTERM)
		<-sigCh
		hs.log.Println("shutdown signal caught")
		cancel()
	}()

	ticker := time.NewTicker(hs.cfg.FlushInterval)
	defer ticker.Stop()

	// Fairly simple fan-in select loop.
	for {
		select {
		case <-ctx.Done():
			hs.log.Println("context canceled, draining…")
			hs.drain()
			return ctx.Err()

		case <-ticker.C:
			if err := hs.flushScores(ctx); err != nil {
				hs.log.Printf("flush error: %v", err)
			}

		default:
			// Non-blocking pull with small timeout to avoid hot looping.
			hs.reader.SetReadDeadline(time.Now().Add(200 * time.Millisecond))
			msg, err := hs.reader.FetchMessage(ctx)
			if err != nil {
				if errors.Is(err, context.DeadlineExceeded) {
					continue // No message available.
				}
				if errors.Is(err, context.Canceled) {
					continue
				}
				hs.log.Printf("kafka fetch error: %v", err)
				continue
			}

			if err := hs.process(msg); err != nil {
				hs.log.Printf("processing error: %v", err)
				// optionally commit offset even on failure to avoid poison messages
			} else {
				_ = hs.reader.CommitMessages(ctx, msg)
			}
		}
	}
}

// ---------------------------------------------------------------------------
// Inbound Event Handling
// ---------------------------------------------------------------------------

// SocialMetricEvent is produced by up-stream NLP services.
type SocialMetricEvent struct {
	CommunityID string  `json:"community_id"`
	Sentiment   float64 `json:"sentiment"` // range [-1,1]
	Toxic       bool    `json:"toxic"`
	Timestamp   int64   `json:"ts"` // unix millis
}

// process parses and feeds the inbound metric into the rolling aggregator.
func (hs *HealthScorer) process(msg kafka.Message) error {
	var ev SocialMetricEvent
	if err := json.Unmarshal(msg.Value, &ev); err != nil {
		return err
	}

	// Enforce community key to keep hashing aligned.
	if ev.CommunityID == "" {
		return errors.New("missing communityID")
	}

	hs.aggrMu.RLock()
	agg, ok := hs.aggregates[ev.CommunityID]
	hs.aggrMu.RUnlock()

	if !ok {
		hs.aggrMu.Lock()
		agg, ok = hs.aggregates[ev.CommunityID]
		if !ok { // another check in case of race
			agg = newRollingAgg(hs.cfg.Window, hs.cfg.BucketSize)
			hs.aggregates[ev.CommunityID] = agg
		}
		hs.aggrMu.Unlock()
	}

	agg.Add(ev)
	return nil
}

// ---------------------------------------------------------------------------
// Rolling Aggregator
// ---------------------------------------------------------------------------

type bucket struct {
	count        int
	toxicCount   int
	sentimentSum float64
}

type rollingAgg struct {
	window     time.Duration
	bucketSize time.Duration
	buckets    []bucket
	cursor     int
	start      time.Time
	mu         sync.Mutex
}

func newRollingAgg(window, bucketSize time.Duration) *rollingAgg {
	nb := int(window / bucketSize)
	if nb <= 0 {
		nb = 1
	}
	return &rollingAgg{
		window:     window,
		bucketSize: bucketSize,
		buckets:    make([]bucket, nb),
		start:      time.Now(),
	}
}

// Add inserts a single metric event into the relevant time bucket.
func (ra *rollingAgg) Add(ev SocialMetricEvent) {
	ra.mu.Lock()
	defer ra.mu.Unlock()

	ts := time.UnixMilli(ev.Timestamp)
	now := time.Now()

	// Advance cursor if our view of time has moved on.
	steps := int(now.Sub(ra.start) / ra.bucketSize)
	if steps > 0 {
		for i := 0; i < steps && i < len(ra.buckets); i++ {
			ra.cursor = (ra.cursor + 1) % len(ra.buckets)
			ra.buckets[ra.cursor] = bucket{} // reset old bucket
		}
		ra.start = ra.start.Add(time.Duration(steps) * ra.bucketSize)
	}

	age := now.Sub(ts)
	if age < 0 || age > ra.window {
		// Ignore events that are in the future or too old.
		return
	}

	indexOffset := int((ra.window - age) / ra.bucketSize)
	idx := (ra.cursor - indexOffset + len(ra.buckets)) % len(ra.buckets)

	b := &ra.buckets[idx]
	b.count++
	b.sentimentSum += ev.Sentiment
	if ev.Toxic {
		b.toxicCount++
	}
}

// Snapshot returns aggregates across the whole window in a cheap copy.
func (ra *rollingAgg) Snapshot() (total int, toxic int, sentimentSum float64) {
	ra.mu.Lock()
	defer ra.mu.Unlock()

	for _, b := range ra.buckets {
		total += b.count
		toxic += b.toxicCount
		sentimentSum += b.sentimentSum
	}
	return
}

// ---------------------------------------------------------------------------
// Scoring Strategy
// ---------------------------------------------------------------------------

// CommunityHealthScore is published by this module.
type CommunityHealthScore struct {
	CommunityID string  `json:"community_id"`
	Score       float64 `json:"score"`       // 0-100
	WindowMs    int64   `json:"window_ms"`   // length of observation window
	GeneratedAt int64   `json:"generated_at"`// unix millis
}

// ScoringStrategy allows pluggable scoring algorithms.
type ScoringStrategy interface {
	Compute(totalEvents int, toxicEvents int, sentimentSum float64) float64
}

// DefaultScoringStrategy is a simple, interpretable variant:
//  – avgSentiment weight 0.7 (normalized 0..1)
//  – toxicity    weight 0.3 (inverse ratio)
type DefaultScoringStrategy struct{}

func (DefaultScoringStrategy) Compute(total int, toxic int, sentimentSum float64) float64 {
	if total == 0 {
		return 50.0 // neutral when no data
	}

	avgSent := (sentimentSum / float64(total) + 1) / 2 // [-1,1] → [0,1]
	toxicityRatio := float64(toxic) / float64(total)    // [0,1]

	score := (avgSent*0.7 + (1.0-toxicityRatio)*0.3) * 100
	return math.Round(score*10) / 10 // 1-decimal precision
}

// ---------------------------------------------------------------------------
// Flush & Publish
// ---------------------------------------------------------------------------

func (hs *HealthScorer) flushScores(ctx context.Context) error {
	hs.aggrMu.RLock()
	defer hs.aggrMu.RUnlock()

	nowMs := time.Now().UnixMilli()
	msgs := make([]kafka.Message, 0, len(hs.aggregates))

	for cid, agg := range hs.aggregates {
		total, toxic, sentSum := agg.Snapshot()
		score := hs.strategy.Compute(total, toxic, sentSum)

		out := CommunityHealthScore{
			CommunityID: cid,
			Score:       score,
			WindowMs:    int64(hs.cfg.Window / time.Millisecond),
			GeneratedAt: nowMs,
		}
		val, err := json.Marshal(out)
		if err != nil {
			hs.log.Printf("marshal error for community %s: %v", cid, err)
			continue
		}

		msgs = append(msgs, kafka.Message{
			Key:   []byte(cid),
			Value: val,
			Time:  time.Now(),
		})
	}

	if len(msgs) == 0 {
		return nil
	}

	return hs.writer.WriteMessages(ctx, msgs...)
}

// drain flushes remaining scores and closes kafka connections.
func (hs *HealthScorer) drain() {
	ctx, cancel := context.WithTimeout(context.Background(), 10*time.Second)
	defer cancel()

	_ = hs.flushScores(ctx)
	_ = hs.writer.Close()
	_ = hs.reader.Close()
}
```