```go
// Code generated for EchoPulse – Real-Time Social Signal Processing Platform.
// Path: src/module_67.go
//
// Module 67: Community-Health Score Aggregator
//
// Package ml_nlp implements a rolling, real-time health-score aggregator.
// It consumes canonical SocialEvent messages from the event-bus (Kafka / JetStream),
// applies pluggable HealthScorer strategies, maintains thread-safe rolling
// statistics per community, and publishes CommunityHealthScore events back onto
// the bus.  The module showcases Observer, Strategy, and Pipeline patterns.
package mlnlp

import (
	"context"
	"encoding/json"
	"errors"
	"math"
	"sync"
	"time"

	"github.com/segmentio/kafka-go"
	"go.uber.org/zap"
)

// -----------------------------------------------------------------------------
// Domain Types
// -----------------------------------------------------------------------------

// SocialEvent is the canonical event shape emitted by upstream ingestion
// pipelines.  Downstream services are expected to treat it as immutable.
type SocialEvent struct {
	EventID     string    `json:"event_id"`
	CommunityID string    `json:"community_id"`
	UserID      string    `json:"user_id"`
	Timestamp   time.Time `json:"ts"`

	// Features extracted by earlier pipeline stages.
	SentimentScore float64 `json:"sentiment"` // range [-1, 1]
	ToxicityScore  float64 `json:"toxicity"`  // range [0, 1]
}

// CommunityHealthScore is the aggregated signal produced by this module.
type CommunityHealthScore struct {
	CommunityID string    `json:"community_id"`
	Timestamp   time.Time `json:"ts"`

	// Rolling window metrics.
	AvgSentiment float64 `json:"avg_sentiment"`
	AvgToxicity  float64 `json:"avg_toxicity"`

	// Composite score in range [0, 100], higher is healthier.
	Score float64 `json:"score"`
}

// -----------------------------------------------------------------------------
// Health Scorer Strategy
// -----------------------------------------------------------------------------

// HealthScorer turns aggregated metrics into a normalized health score.
type HealthScorer interface {
	Score(avgSentiment, avgToxicity float64) float64
}

// DefaultHealthScorer is a reference implementation that uses a simple
// weighted formula.  Swap this out via functional options to experiment
// with different scoring algorithms without touching the aggregator core.
type DefaultHealthScorer struct {
	// weights must sum to 1.0 for normalized output.
	sentimentWeight float64
	toxicityWeight  float64
}

// NewDefaultHealthScorer returns a scorer using reasonable default weights.
func NewDefaultHealthScorer() *DefaultHealthScorer {
	return &DefaultHealthScorer{
		sentimentWeight: 0.6,
		toxicityWeight:  0.4,
	}
}

// Score implements HealthScorer.
func (d *DefaultHealthScorer) Score(avgSentiment, avgToxicity float64) float64 {
	// Rescale sentiment [-1,1] -> [0,1]
	normSentiment := (avgSentiment + 1) / 2
	// Toxicity already [0,1] but invert so 1 means healthy.
	normToxicity := 1 - avgToxicity

	raw := normSentiment*d.sentimentWeight + normToxicity*d.toxicityWeight
	return math.Round(raw * 100) // [0,100] convenient for dashboards
}

// -----------------------------------------------------------------------------
// Rolling Window (fixed-size ring buffer)
// -----------------------------------------------------------------------------

// rollingWindow maintains a fixed-size, thread-safe collection of floats.
type rollingWindow struct {
	sync.Mutex
	cursor int
	data   []float64
	sum    float64
}

func newRollingWindow(size int) *rollingWindow {
	return &rollingWindow{data: make([]float64, size)}
}

func (rw *rollingWindow) add(v float64) {
	rw.Lock()
	defer rw.Unlock()

	// subtract the value that is about to be overwritten
	rw.sum -= rw.data[rw.cursor]
	// add new value
	rw.data[rw.cursor] = v
	rw.sum += v

	rw.cursor++
	if rw.cursor == len(rw.data) {
		rw.cursor = 0
	}
}

func (rw *rollingWindow) avg() float64 {
	rw.Lock()
	defer rw.Unlock()

	return rw.sum / float64(len(rw.data))
}

// -----------------------------------------------------------------------------
// Aggregator Config / Options
// -----------------------------------------------------------------------------

type AggregatorOption func(*Aggregator)

// WithHealthScorer overrides the default scoring strategy.
func WithHealthScorer(scorer HealthScorer) AggregatorOption {
	return func(a *Aggregator) {
		a.scorer = scorer
	}
}

// WithLogger allows caller to inject a zap.Logger.
func WithLogger(l *zap.Logger) AggregatorOption {
	return func(a *Aggregator) {
		a.log = l
	}
}

// WithWindowSize changes the fixed rolling window size.
func WithWindowSize(n int) AggregatorOption {
	return func(a *Aggregator) {
		if n > 0 {
			a.windowSize = n
		}
	}
}

// -----------------------------------------------------------------------------
// Aggregator Implementation
// -----------------------------------------------------------------------------

// Aggregator consumes SocialEvents, maintains per-community rolling windows,
// computes CommunityHealthScore, and publishes results downstream.
type Aggregator struct {
	// Injected / Configured
	reader      *kafka.Reader
	writer      *kafka.Writer
	scorer      HealthScorer
	windowSize  int
	publishFreq time.Duration
	log         *zap.Logger

	// Internal state
	mu        sync.RWMutex
	sentiment map[string]*rollingWindow
	toxicity  map[string]*rollingWindow

	ctx    context.Context
	cancel context.CancelFunc
	wg     sync.WaitGroup
}

// NewAggregator wires dependencies and returns a ready-to-run Aggregator.
//
// `sourceTopic` and `sinkTopic` are Kafka topics for input and output.
func NewAggregator(brokers []string, sourceTopic, sinkTopic string, opts ...AggregatorOption) (*Aggregator, error) {
	if len(brokers) == 0 {
		return nil, errors.New("brokers list cannot be empty")
	}

	a := &Aggregator{
		reader: kafka.NewReader(kafka.ReaderConfig{
			Brokers:  brokers,
			Topic:    sourceTopic,
			GroupID:  "mlnlp-community-health-agg",
			MaxBytes: 10e6, // 10MB
		}),
		writer: &kafka.Writer{
			Addr:     kafka.TCP(brokers...),
			Topic:    sinkTopic,
			Balancer: &kafka.LeastBytes{},
		},
		scorer:      NewDefaultHealthScorer(),
		windowSize:  250,              // approx per-minute window @4 events/sec
		publishFreq: 5 * time.Second,  // throttle output
		log:         zap.NewNop(),
		sentiment:   make(map[string]*rollingWindow),
		toxicity:    make(map[string]*rollingWindow),
	}

	for _, opt := range opts {
		opt(a)
	}

	a.ctx, a.cancel = context.WithCancel(context.Background())
	return a, nil
}

// Run spins up goroutines for event intake and periodic publishing.
func (a *Aggregator) Run() {
	a.wg.Add(2)
	go a.eventLoop()
	go a.publishLoop()
}

// Stop initiates graceful shutdown and waits for all goroutines to finish.
func (a *Aggregator) Stop() {
	a.cancel()
	a.wg.Wait()

	_ = a.reader.Close()
	_ = a.writer.Close()
}

// eventLoop consumes SocialEvents from Kafka and updates rolling windows.
func (a *Aggregator) eventLoop() {
	defer a.wg.Done()

	for {
		m, err := a.reader.FetchMessage(a.ctx)
		if err != nil {
			if errors.Is(err, context.Canceled) {
				return
			}
			a.log.Warn("reader error", zap.Error(err))
			continue
		}

		var ev SocialEvent
		if err := json.Unmarshal(m.Value, &ev); err != nil {
			a.log.Warn("unmarshal error", zap.Error(err))
			_ = a.reader.CommitMessages(a.ctx, m) // skip bad message
			continue
		}

		// Update windows
		a.mu.Lock()
		sWin, ok := a.sentiment[ev.CommunityID]
		if !ok {
			sWin = newRollingWindow(a.windowSize)
			a.sentiment[ev.CommunityID] = sWin
		}
		tWin, ok := a.toxicity[ev.CommunityID]
		if !ok {
			tWin = newRollingWindow(a.windowSize)
			a.toxicity[ev.CommunityID] = tWin
		}
		a.mu.Unlock()

		sWin.add(ev.SentimentScore)
		tWin.add(ev.ToxicityScore)

		if err := a.reader.CommitMessages(a.ctx, m); err != nil {
			a.log.Warn("commit message failed", zap.Error(err))
		}
	}
}

// publishLoop periodically aggregates metrics and writes to Kafka.
func (a *Aggregator) publishLoop() {
	defer a.wg.Done()

	ticker := time.NewTicker(a.publishFreq)
	defer ticker.Stop()

	for {
		select {
		case <-a.ctx.Done():
			return
		case <-ticker.C:
			a.publishScores()
		}
	}
}

func (a *Aggregator) publishScores() {
	a.mu.RLock()
	defer a.mu.RUnlock()

	for cid, sWin := range a.sentiment {
		tWin := a.toxicity[cid]

		avgSent := sWin.avg()
		avgTox := tWin.avg()
		score := a.scorer.Score(avgSent, avgTox)

		out := CommunityHealthScore{
			CommunityID: cid,
			Timestamp:   time.Now().UTC(),
			AvgSentiment: math.Round(avgSent*1000) / 1000, // limit to 3dp for payload size
			AvgToxicity:  math.Round(avgTox*1000) / 1000,
			Score:        score,
		}

		payload, err := json.Marshal(out)
		if err != nil {
			a.log.Warn("marshal health score failed", zap.Error(err))
			continue
		}

		msg := kafka.Message{
			Key:   []byte(cid),
			Value: payload,
			Time:  out.Timestamp,
		}

		if err := a.writer.WriteMessages(a.ctx, msg); err != nil {
			a.log.Warn("write message failed", zap.Error(err))
			continue
		}
	}
}

// -----------------------------------------------------------------------------
// Example of module bootstrap (could live elsewhere in real project)
// -----------------------------------------------------------------------------

// The following is provided for illustrative purposes only.  In production,
// service start-up would be driven by a DI container and CLI flags.

// func main() {
// 	logger, _ := zap.NewProduction()
// 	defer logger.Sync()
//
// 	agg, err := NewAggregator(
// 		[]string{"kafka-broker-1:9092", "kafka-broker-2:9092"},
// 		"social_events",
// 		"community_health_scores",
// 		WithLogger(logger),
// 		WithWindowSize(300),
// 	)
// 	if err != nil {
// 		logger.Fatal("failed to create aggregator", zap.Error(err))
// 	}
//
// 	agg.Run()
// 	<-sigterm() // Wait for system signal
// 	agg.Stop()
// }
//
// func sigterm() <-chan struct{} {
// 	ch := make(chan struct{})
// 	go func() {
// 		c := make(chan os.Signal, 1)
// 		signal.Notify(c, syscall.SIGINT, syscall.SIGTERM)
// 		<-c
// 		close(ch)
// 	}()
// 	return ch
// }
```