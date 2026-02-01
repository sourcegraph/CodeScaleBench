```go
// File: src/module_35.go
//
// Package pipeline holds real-time data-processing stages that attach to the
// EchoPulse event bus.  Module 35 implements a rolling sentiment aggregation
// stage that consumes fine-grained sentiment scores, applies a pluggable
// aggregation strategy (SMA, EWMA, etc.) per community, and publishes high-
// level “heartbeat” signals for dashboards and monitoring/alarm rules.
package pipeline

import (
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"log"
	"sync"
	"time"

	"github.com/segmentio/kafka-go"
)

// ----------------------------------------------------------------------------
// Public types
// ----------------------------------------------------------------------------

// SocialEvent is the canonical envelope used on the EchoPulse bus.
// Only the fields required for this stage are modeled here.
type SocialEvent struct {
	EventID     string  `json:"event_id"`
	CommunityID string  `json:"community_id"`
	Sentiment   float64 `json:"sentiment"` // normalised [-1,1]
	Timestamp   int64   `json:"timestamp"` // unix ms
}

// AggregatedSentiment is the message produced by this stage.
type AggregatedSentiment struct {
	CommunityID string  `json:"community_id"`
	Mean        float64 `json:"mean"`
	WindowSize  int      `json:"window_size"`
	UpdatedAt   int64   `json:"updated_at"`
	Algorithm   string  `json:"algorithm"`
}

// ----------------------------------------------------------------------------
// Strategy pattern – different rolling-average algorithms
// ----------------------------------------------------------------------------

// AggregationStrategy calculates a rolling mean from an unbounded stream.
type AggregationStrategy interface {
	// Update ingests a new value and returns (<current-mean>, <is-window-warm>)
	Update(float64) (float64, bool)
	// Name returns a short identifier for telemetry / envelopes.
	Name() string
}

// SimpleMovingAverageStrategy keeps a fixed-size FIFO window.
type SimpleMovingAverageStrategy struct {
	window []float64
	size   int
	sum    float64
}

func NewSimpleMovingAverage(size int) *SimpleMovingAverageStrategy {
	return &SimpleMovingAverageStrategy{
		window: make([]float64, 0, size),
		size:   size,
	}
}

func (s *SimpleMovingAverageStrategy) Update(v float64) (float64, bool) {
	if len(s.window) == s.size {
		s.sum -= s.window[0]
		s.window = s.window[1:]
	}
	s.window = append(s.window, v)
	s.sum += v

	return s.sum / float64(len(s.window)), len(s.window) == s.size
}

func (s *SimpleMovingAverageStrategy) Name() string { return fmt.Sprintf("SMA_%d", s.size) }

// ExponentialWeightingStrategy gives exponentially more weight to newer items.
type ExponentialWeightingStrategy struct {
	decay float64
	mean  float64
	first bool
}

func NewExponentialWeighting(decay float64) (*ExponentialWeightingStrategy, error) {
	if decay <= 0 || decay >= 1 {
		return nil, errors.New("decay must be in (0,1)")
	}
	return &ExponentialWeightingStrategy{decay: decay, first: true}, nil
}

func (e *ExponentialWeightingStrategy) Update(v float64) (float64, bool) {
	if e.first {
		e.mean = v
		e.first = false
	} else {
		e.mean = e.decay*v + (1-e.decay)*e.mean
	}
	return e.mean, true // Always "warm"
}

func (e *ExponentialWeightingStrategy) Name() string { return fmt.Sprintf("EWMA_%.2f", e.decay) }

// ----------------------------------------------------------------------------
// RollingSentimentAggregator – the pipeline stage
// ----------------------------------------------------------------------------

// RollingSentimentAggregatorConfig holds external settings.
type RollingSentimentAggregatorConfig struct {
	InputTopic        string
	OutputTopic       string
	GroupID           string
	Brokers           []string
	WindowSize        int           // for SMA
	EWDecay           float64       // for EWMA
	CommitInterval    time.Duration // kafka consumer
	Algorithm         string        // "sma" | "ewma"
	HealthCheckEvery  time.Duration
	Logger            *log.Logger
}

// RollingSentimentAggregator is a long-lived component running in its own goroutine.
type RollingSentimentAggregator struct {
	cfg          RollingSentimentAggregatorConfig
	reader       *kafka.Reader
	writer       *kafka.Writer
	strategiesMu sync.RWMutex
	strategies   map[string]AggregationStrategy // keyed by CommunityID
	ctx          context.Context
	cancel       context.CancelFunc
}

// NewRollingSentimentAggregator wires Kafka IO and internal state.
func NewRollingSentimentAggregator(cfg RollingSentimentAggregatorConfig) (*RollingSentimentAggregator, error) {
	if cfg.Logger == nil {
		cfg.Logger = log.Default()
	}
	reader := kafka.NewReader(kafka.ReaderConfig{
		Brokers:        cfg.Brokers,
		Topic:          cfg.InputTopic,
		GroupID:        cfg.GroupID,
		CommitInterval: cfg.CommitInterval,
		MinBytes:       10e3, // 10KB
		MaxBytes:       10e6, // 10MB
	})
	writer := &kafka.Writer{
		Addr:         kafka.TCP(cfg.Brokers...),
		Topic:        cfg.OutputTopic,
		Async:        true,
		BatchTimeout: 100 * time.Millisecond,
	}
	ctx, cancel := context.WithCancel(context.Background())
	return &RollingSentimentAggregator{
		cfg:        cfg,
		reader:     reader,
		writer:     writer,
		strategies: make(map[string]AggregationStrategy),
		ctx:        ctx,
		cancel:     cancel,
	}, nil
}

// Start begins the ingest-process-publish loop.  It is non-blocking.
func (r *RollingSentimentAggregator) Start() {
	go r.run()
}

// Stop signals a graceful shutdown and waits for resources to close.
func (r *RollingSentimentAggregator) Stop() error {
	r.cancel()
	err1 := r.reader.Close()
	err2 := r.writer.Close()
	if err1 != nil {
		return err1
	}
	return err2
}

// run is the internal main loop.
func (r *RollingSentimentAggregator) run() {
	r.cfg.Logger.Printf("[sentiment-aggregator] started; algorithm=%s", r.cfg.Algorithm)
	healthTicker := time.NewTicker(r.cfg.HealthCheckEvery)
	defer healthTicker.Stop()

	for {
		select {
		case <-r.ctx.Done():
			r.cfg.Logger.Println("[sentiment-aggregator] shutdown requested")
			return

		case <-healthTicker.C:
			r.emitHealthMetric()

		default:
			msg, err := r.reader.FetchMessage(r.ctx)
			if err != nil {
				if errors.Is(err, context.Canceled) {
					return
				}
				r.cfg.Logger.Printf("fetch error: %v", err)
				continue
			}

			if err := r.processMessage(msg); err != nil {
				r.cfg.Logger.Printf("processing error: %v", err)
			}

			if err := r.reader.CommitMessages(r.ctx, msg); err != nil {
				r.cfg.Logger.Printf("commit error: %v", err)
			}
		}
	}
}

// processMessage deserializes and updates aggregation for a single event.
func (r *RollingSentimentAggregator) processMessage(msg kafka.Message) error {
	var se SocialEvent
	if err := json.Unmarshal(msg.Value, &se); err != nil {
		return fmt.Errorf("unmarshal social event: %w", err)
	}

	strat := r.getOrCreateStrategy(se.CommunityID)

	mean, warm := strat.Update(se.Sentiment)
	if !warm {
		return nil // skip early window
	}

	payload := AggregatedSentiment{
		CommunityID: se.CommunityID,
		Mean:        mean,
		WindowSize:  r.cfg.WindowSize,
		UpdatedAt:   time.Now().UnixMilli(),
		Algorithm:   strat.Name(),
	}
	buf, err := json.Marshal(payload)
	if err != nil {
		return fmt.Errorf("marshal output: %w", err)
	}

	return r.writer.WriteMessages(r.ctx, kafka.Message{
		Key:   []byte(se.CommunityID),
		Value: buf,
	})
}

// getOrCreateStrategy lazily initialises the algo per community.
func (r *RollingSentimentAggregator) getOrCreateStrategy(communityID string) AggregationStrategy {
	r.strategiesMu.RLock()
	strat, ok := r.strategies[communityID]
	r.strategiesMu.RUnlock()
	if ok {
		return strat
	}

	r.strategiesMu.Lock()
	defer r.strategiesMu.Unlock()
	// Check again (double-checked locking)
	if strat, ok = r.strategies[communityID]; ok {
		return strat
	}

	switch r.cfg.Algorithm {
	case "sma":
		strat = NewSimpleMovingAverage(r.cfg.WindowSize)
	case "ewma":
		ew, err := NewExponentialWeighting(r.cfg.EWDecay)
		if err != nil {
			// Fallback to SMA on mis-configuration
			r.cfg.Logger.Printf("invalid EWMA decay; falling back to SMA: %v", err)
			strat = NewSimpleMovingAverage(r.cfg.WindowSize)
		} else {
			strat = ew
		}
	default:
		r.cfg.Logger.Printf("unknown algorithm '%s'; defaulting to SMA", r.cfg.Algorithm)
		strat = NewSimpleMovingAverage(r.cfg.WindowSize)
	}
	r.strategies[communityID] = strat
	return strat
}

// emitHealthMetric logs the number of tracked communities for observability.
// Production systems would push this to Prometheus or StatsD.
func (r *RollingSentimentAggregator) emitHealthMetric() {
	r.strategiesMu.RLock()
	total := len(r.strategies)
	r.strategiesMu.RUnlock()
	r.cfg.Logger.Printf("[sentiment-aggregator] tracking %d communities", total)
}
```