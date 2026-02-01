```go
// Code generated for EchoPulse (ml_nlp)
// File: src/module_73.go
// Purpose: Real-Time Community Health Scorer.  This component consumes
//          low-level sentiment / toxicity events from Kafka, aggregates
//          them in sliding windows per community, scores the “health” of
//          each community using a pluggable strategy, and notifies
//          downstream observers when thresholds are crossed.

package module73

import (
	"context"
	"encoding/json"
	"errors"
	"log"
	"math"
	"os"
	"strconv"
	"sync"
	"time"

	"github.com/prometheus/client_golang/prometheus"
	"github.com/segmentio/kafka-go"
)

// ---------------------------------------------------------------------
// Domain Types
// ---------------------------------------------------------------------

// SocialEvent is the canonical, post-NLP artifact placed on the event bus.
type SocialEvent struct {
	CommunityID string    `json:"community_id"`
	Sentiment   float64   `json:"sentiment"` // −1 … +1 (negative … positive)
	Toxicity    float64   `json:"toxicity"`  // 0 … 1
	Timestamp   time.Time `json:"timestamp"`
}

// CommunityHealthEvent is emitted by this module when the health score
// moves outside configured thresholds.
type CommunityHealthEvent struct {
	CommunityID string    `json:"community_id"`
	Score       float64   `json:"score"`
	Timestamp   time.Time `json:"timestamp"`
	Reason      string    `json:"reason"`
}

// ---------------------------------------------------------------------
// Sliding Window Data Structure
// ---------------------------------------------------------------------

// ringBuffer is a fixed-size circular buffer for float64 values.
type ringBuffer struct {
	values []float64
	size   int
	index  int
	full   bool
}

func newRingBuffer(size int) *ringBuffer {
	return &ringBuffer{
		values: make([]float64, size),
		size:   size,
	}
}

func (r *ringBuffer) add(v float64) {
	r.values[r.index] = v
	r.index = (r.index + 1) % r.size
	if r.index == 0 {
		r.full = true
	}
}

func (r *ringBuffer) snapshot() []float64 {
	if !r.full {
		return r.values[:r.index]
	}
	out := make([]float64, r.size)
	copy(out, r.values[r.index:])
	copy(out[r.size-r.index:], r.values[:r.index])
	return out
}

// ---------------------------------------------------------------------
// Health Scoring Strategy Pattern
// ---------------------------------------------------------------------

// HealthScoringStrategy encapsulates how a score is produced from a
// slice of sentiment / toxicity signals.
type HealthScoringStrategy interface {
	Score(sentiments, toxicities []float64) float64
	Name() string
}

// SimpleAverageStrategy is the default.
type SimpleAverageStrategy struct{}

func (s SimpleAverageStrategy) Name() string { return "simple_average" }

func (s SimpleAverageStrategy) Score(sent, tox []float64) float64 {
	if len(sent) == 0 {
		return 0
	}
	var sumSent, sumTox float64
	for i := range sent {
		sumSent += sent[i]
		sumTox += tox[i]
	}
	avgSent := sumSent / float64(len(sent))
	avgTox := sumTox / float64(len(tox))
	// Combine sentiment (+) and toxicity (−) into a single score.
	return (avgSent - avgTox)
}

// ExpDecayStrategy weights recent events higher using exponential decay.
type ExpDecayStrategy struct {
	HalfLife time.Duration
}

func (s ExpDecayStrategy) Name() string { return "exp_decay" }

func (s ExpDecayStrategy) Score(sent, tox []float64) float64 {
	if len(sent) == 0 {
		return 0
	}
	now := time.Now()
	var sumWeight, score float64
	// Use half-life to compute decay for each event (assumes ordered ascending).
	for i := range sent {
		age := now.Sub(now.Add(-time.Duration(len(sent)-i) * time.Second)) // approximate
		weight := math.Pow(0.5, float64(age)/float64(s.HalfLife))
		sumWeight += weight
		score += weight * (sent[i] - tox[i])
	}
	return score / sumWeight
}

// strategyFactory chooses a strategy based on env vars.
func strategyFactory() HealthScoringStrategy {
	switch os.Getenv("EP_HEALTH_STRATEGY") {
	case "exp":
		hl, err := time.ParseDuration(os.Getenv("EP_HEALTH_HALF_LIFE"))
		if err != nil {
			hl = 5 * time.Minute
		}
		return ExpDecayStrategy{HalfLife: hl}
	default:
		return SimpleAverageStrategy{}
	}
}

// ---------------------------------------------------------------------
// Observer Pattern
// ---------------------------------------------------------------------

// Observer receives CommunityHealthEvents.
type Observer interface {
	Notify(event CommunityHealthEvent)
}

// ---------------------------------------------------------------------
// Metrics
// ---------------------------------------------------------------------

var (
	scoreGauge = prometheus.NewGaugeVec(
		prometheus.GaugeOpts{
			Name: "echopulse_community_health_score",
			Help: "Latest health score per community.",
		},
		[]string{"community"},
	)
	eventsTotal = prometheus.NewCounterVec(
		prometheus.CounterOpts{
			Name: "echopulse_events_total",
			Help: "Total SocialEvents processed.",
		},
		[]string{"community"},
	)
)

// init registers Prometheus collectors.
func init() {
	prometheus.MustRegister(scoreGauge, eventsTotal)
}

// ---------------------------------------------------------------------
// Core Component
// ---------------------------------------------------------------------

type HealthScorer struct {
	cfg        config
	reader     *kafka.Reader
	writer     *kafka.Writer
	strategy   HealthScoringStrategy
	observers  []Observer
	agg        map[string]*aggWindow
	mu         sync.RWMutex
	once       sync.Once
	cancelFunc context.CancelFunc
	wg         sync.WaitGroup
}

type aggWindow struct {
	sent *ringBuffer
	tox  *ringBuffer
}

// config holds runtime configuration.
type config struct {
	SourceTopic      string
	SinkTopic        string
	GroupID          string
	Brokers          []string
	WindowSize       int
	UpperThreshold   float64
	LowerThreshold   float64
	CommitInterval   time.Duration
	NotificationRate time.Duration
}

// NewHealthScorer constructs with sane defaults populated from env vars.
func NewHealthScorer() (*HealthScorer, error) {
	windowSize, _ := strconv.Atoi(getEnv("EP_HEALTH_WINDOW_SIZE", "300"))
	upper, _ := strconv.ParseFloat(getEnv("EP_HEALTH_UPPER", "0.5"), 64)
	lower, _ := strconv.ParseFloat(getEnv("EP_HEALTH_LOWER", "-0.5"), 64)
	commitDur, _ := time.ParseDuration(getEnv("EP_KAFKA_COMMIT_INTERVAL", "2s"))
	cfg := config{
		SourceTopic:      getEnv("EP_SENTIMENT_TOPIC", "analysis.sentiment"),
		SinkTopic:        getEnv("EP_HEALTH_TOPIC", "analysis.health"),
		GroupID:          getEnv("EP_HEALTH_GROUP", "health_scorer"),
		Brokers:          []string{getEnv("EP_KAFKA_BROKERS", "localhost:9092")},
		WindowSize:       windowSize,
		UpperThreshold:   upper,
		LowerThreshold:   lower,
		CommitInterval:   commitDur,
		NotificationRate: 30 * time.Second,
	}

	reader := kafka.NewReader(kafka.ReaderConfig{
		Brokers:        cfg.Brokers,
		GroupID:        cfg.GroupID,
		Topic:          cfg.SourceTopic,
		CommitInterval: cfg.CommitInterval,
		MinBytes:       10e3,
		MaxBytes:       10e6,
	})

	writer := &kafka.Writer{
		Addr:         kafka.TCP(cfg.Brokers...),
		Topic:        cfg.SinkTopic,
		RequiredAcks: kafka.RequireAll,
		Async:        true,
	}

	return &HealthScorer{
		cfg:      cfg,
		reader:   reader,
		writer:   writer,
		strategy: strategyFactory(),
		agg:      make(map[string]*aggWindow),
	}, nil
}

// Register attaches an observer.
func (hs *HealthScorer) Register(o Observer) {
	hs.mu.Lock()
	defer hs.mu.Unlock()
	hs.observers = append(hs.observers, o)
}

// Start spins up goroutines and begins processing.
func (hs *HealthScorer) Start(ctx context.Context) error {
	hs.once.Do(func() {
		ctx, cancel := context.WithCancel(ctx)
		hs.cancelFunc = cancel
		hs.wg.Add(1)
		go hs.run(ctx)
	})
	return nil
}

// Stop gracefully shuts down processing.
func (hs *HealthScorer) Stop() error {
	if hs.cancelFunc != nil {
		hs.cancelFunc()
	}
	hs.wg.Wait()
	if err := hs.reader.Close(); err != nil {
		return err
	}
	return hs.writer.Close()
}

// run contains the main event loop.
func (hs *HealthScorer) run(ctx context.Context) {
	defer hs.wg.Done()

	ticker := time.NewTicker(hs.cfg.NotificationRate)
	defer ticker.Stop()

	for {
		select {
		case <-ctx.Done():
			return
		default:
			m, err := hs.reader.FetchMessage(ctx)
			if err != nil {
				if errors.Is(err, context.Canceled) {
					return
				}
				log.Printf("healthscorer: kafka fetch error: %v", err)
				continue
			}

			var ev SocialEvent
			if err := json.Unmarshal(m.Value, &ev); err != nil {
				log.Printf("healthscorer: invalid json: %v", err)
				_ = hs.reader.CommitMessages(ctx, m) // skip bad message
				continue
			}
			hs.process(ev)
			if err := hs.reader.CommitMessages(ctx, m); err != nil {
				log.Printf("healthscorer: commit err: %v", err)
			}
		case <-ticker.C:
			hs.computeAndNotify()
		}
	}
}

// process updates sliding window statistics.
func (hs *HealthScorer) process(ev SocialEvent) {
	hs.mu.Lock()
	defer hs.mu.Unlock()

	window, ok := hs.agg[ev.CommunityID]
	if !ok {
		window = &aggWindow{
			sent: newRingBuffer(hs.cfg.WindowSize),
			tox:  newRingBuffer(hs.cfg.WindowSize),
		}
		hs.agg[ev.CommunityID] = window
	}
	window.sent.add(ev.Sentiment)
	window.tox.add(ev.Toxicity)

	eventsTotal.WithLabelValues(ev.CommunityID).Inc()
}

// computeAndNotify iterates over communities, computes score, updates
// Prometheus, and dispatches notifications & bus events if thresholds cross.
func (hs *HealthScorer) computeAndNotify() {
	hs.mu.RLock()
	defer hs.mu.RUnlock()

	for communityID, window := range hs.agg {
		sentSnapshot := window.sent.snapshot()
		toxSnapshot := window.tox.snapshot()
		score := hs.strategy.Score(sentSnapshot, toxSnapshot)

		scoreGauge.WithLabelValues(communityID).Set(score)

		if score > hs.cfg.UpperThreshold || score < hs.cfg.LowerThreshold {
			reason := "normal"
			if score > hs.cfg.UpperThreshold {
				reason = "very_positive"
			} else if score < hs.cfg.LowerThreshold {
				reason = "very_negative"
			}

			event := CommunityHealthEvent{
				CommunityID: communityID,
				Score:       score,
				Timestamp:   time.Now().UTC(),
				Reason:      reason,
			}

			// fire observer callbacks (non-blocking)
			for _, obs := range hs.observers {
				go obs.Notify(event)
			}

			// publish to Kafka
			bytes, _ := json.Marshal(event) // cannot fail
			msg := kafka.Message{
				Value: bytes,
				Key:   []byte(communityID),
				Time:  event.Timestamp,
			}
			if err := hs.writer.WriteMessages(context.Background(), msg); err != nil {
				log.Printf("healthscorer: kafka publish error: %v", err)
			}
		}
	}
}

// ---------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------

func getEnv(key, def string) string {
	if v := os.Getenv(key); v != "" {
		return v
	}
	return def
}
```