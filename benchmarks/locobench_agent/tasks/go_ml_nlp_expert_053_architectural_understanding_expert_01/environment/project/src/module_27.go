```go
// File: src/module_27.go
//
// PulseAggregator is a real–time component of EchoPulse that continuously
// consumes SocialEvents from Kafka, performs an exponentially-weighted moving
// average (EWMA) update of sentiment for every community, detects statistically
// significant sentiment drift, and publishes CommunityHealth events back onto
// Kafka.  It also exposes Prometheus metrics so that operators can monitor
// lag, processing throughput, and the current EWMA per community.
//
// The component implements sarama.ConsumerGroupHandler so it can safely be run
// in a distributed consumer group while retaining at-least-once semantics.
//
// Dependencies:
//   github.com/Shopify/sarama          – Apache Kafka client
//   github.com/prometheus/client_golang – Metrics exposition
//
// NOTE: Errors are surfaced through a dedicated error channel so that callers
// can decide whether to restart, escalate, or ignore.
//
// Author: EchoPulse Core Team

package module

import (
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"sync"
	"time"

	"github.com/Shopify/sarama"
	"github.com/prometheus/client_golang/prometheus"
)

// Config provides runtime configuration for PulseAggregator.
type Config struct {
	Brokers                []string      // Kafka bootstrap brokers
	InputTopic             string        // "social-events"
	OutputTopic            string        // "community-health"
	ConsumerGroup          string        // consumer group name
	DriftThreshold         float64       // sentiment delta required to emit alert
	EWMALambda             float64       // decay factor for EWMA (0<λ<=1)
	RebalanceTimeout       time.Duration // ConsumerGroup rebalance timeout
	ShutdownGracePeriod    time.Duration // Time to wait for graceful shutdown
	ProducerFlushFrequency time.Duration // How often to flush producer
}

// SocialEvent is the canonical representation of every piece of
// user-generated content after ingestion and NLP processing.
type SocialEvent struct {
	EventID       string  `json:"event_id"`
	CommunityID   string  `json:"community_id"`
	Sentiment     float64 `json:"sentiment"` // Normalized −1 .. 1
	OriginalEpoch int64   `json:"original_epoch"`
}

// CommunityHealth is the outbound event raised when significant sentiment drift
// is detected.
type CommunityHealth struct {
	CommunityID      string  `json:"community_id"`
	EWMASentiment    float64 `json:"ewma_sentiment"`
	Baseline         float64 `json:"baseline"`
	Delta            float64 `json:"delta"`
	TriggeredEpochMs int64   `json:"triggered_epoch_ms"`
}

// EWMA computes an exponentially-weighted moving average.
// It is not goroutine-safe: callers must provide their own locking.
type EWMA struct {
	Value   float64
	Lambda  float64
	Seeded  bool
	Updated int64
}

// Update returns the new EWMA after incorporating x.
func (e *EWMA) Update(x float64) float64 {
	if !e.Seeded {
		e.Value = x
		e.Seeded = true
	} else {
		e.Value = e.Lambda*x + (1-e.Lambda)*e.Value
	}
	e.Updated = time.Now().UnixMilli()
	return e.Value
}

// PulseAggregator consumes events, updates sentiment EWMAs, and publishes drift
// alerts back into Kafka.
type PulseAggregator struct {
	cfg       Config
	ctx       context.Context
	cancel    context.CancelFunc
	consumer  sarama.ConsumerGroup
	producer  sarama.AsyncProducer
	metrics   *aggregatorMetrics
	sentiment map[string]*EWMA // communityID -> EWMA
	baseline  map[string]float64
	mu        sync.RWMutex
	errCh     chan error
	wg        sync.WaitGroup
}

// aggregatorMetrics holds all Prometheus gauges/counters.
type aggregatorMetrics struct {
	EventsConsumed prometheus.Counter
	EventsEmitted  prometheus.Counter
	CurrentEWMA    *prometheus.GaugeVec
}

// newAggregatorMetrics registers Prometheus metrics and returns a struct of
// metric handles. It panics if called twice with the same metric names.
func newAggregatorMetrics() *aggregatorMetrics {
	m := &aggregatorMetrics{
		EventsConsumed: prometheus.NewCounter(
			prometheus.CounterOpts{
				Name: "echopulse_aggregator_events_consumed_total",
				Help: "Total number of SocialEvents consumed by the PulseAggregator.",
			}),
		EventsEmitted: prometheus.NewCounter(
			prometheus.CounterOpts{
				Name: "echopulse_aggregator_events_emitted_total",
				Help: "Total number of CommunityHealth events emitted by the PulseAggregator.",
			}),
		CurrentEWMA: prometheus.NewGaugeVec(
			prometheus.GaugeOpts{
				Name: "echopulse_aggregator_ewma_sentiment",
				Help: "The latest EWMA sentiment per community.",
			},
			[]string{"community_id"},
		),
	}

	prometheus.MustRegister(m.EventsConsumed, m.EventsEmitted, m.CurrentEWMA)
	return m
}

// NewPulseAggregator constructs a ready-to-start PulseAggregator.
func NewPulseAggregator(cfg Config) (*PulseAggregator, error) {
	if len(cfg.Brokers) == 0 {
		return nil, errors.New("brokers cannot be empty")
	}
	if cfg.EWMALambda <= 0 || cfg.EWMALambda > 1 {
		return nil, fmt.Errorf("ewma_lambda must be in (0,1]; got %f", cfg.EWMALambda)
	}

	saramaCfg := sarama.NewConfig()
	saramaCfg.Version = sarama.V3_3_0_0
	saramaCfg.Consumer.Group.Rebalance.Timeout = cfg.RebalanceTimeout
	saramaCfg.Producer.Return.Errors = true
	saramaCfg.Producer.Return.Successes = false
	saramaCfg.Producer.Flush.Frequency = cfg.ProducerFlushFrequency

	consumer, err := sarama.NewConsumerGroup(cfg.Brokers, cfg.ConsumerGroup, saramaCfg)
	if err != nil {
		return nil, fmt.Errorf("create consumer group: %w", err)
	}

	producer, err := sarama.NewAsyncProducer(cfg.Brokers, saramaCfg)
	if err != nil {
		_ = consumer.Close()
		return nil, fmt.Errorf("create async producer: %w", err)
	}

	ctx, cancel := context.WithCancel(context.Background())

	return &PulseAggregator{
		cfg:       cfg,
		ctx:       ctx,
		cancel:    cancel,
		consumer:  consumer,
		producer:  producer,
		metrics:   newAggregatorMetrics(),
		sentiment: make(map[string]*EWMA),
		baseline:  make(map[string]float64),
		errCh:     make(chan error, 1),
	}, nil
}

// Errors returns a channel where unrecoverable errors are sent.
func (p *PulseAggregator) Errors() <-chan error { return p.errCh }

// Start launches the aggregator’s main loops. It is non-blocking.
func (p *PulseAggregator) Start() {
	p.wg.Add(2)
	go p.consumeLoop()
	go p.producerErrorLoop()
}

// Stop gracefully shuts down the aggregator and blocks until completion.
func (p *PulseAggregator) Stop() error {
	p.cancel()
	done := make(chan struct{})
	go func() {
		p.wg.Wait()
		close(done)
	}()

	select {
	case <-done:
	case <-time.After(p.cfg.ShutdownGracePeriod):
		return errors.New("graceful shutdown timed out")
	}

	if err := p.consumer.Close(); err != nil {
		return fmt.Errorf("close consumer: %w", err)
	}
	if err := p.producer.Close(); err != nil {
		return fmt.Errorf("close producer: %w", err)
	}
	return nil
}

// consumeLoop subscribes to Kafka and handles rebalance events.
func (p *PulseAggregator) consumeLoop() {
	defer p.wg.Done()
	for {
		if err := p.consumer.Consume(p.ctx, []string{p.cfg.InputTopic}, p); err != nil {
			select {
			case p.errCh <- fmt.Errorf("consume: %w", err):
			default:
			}
			return
		}
		// sarama requires us to check ctx each loop.
		if p.ctx.Err() != nil {
			return
		}
	}
}

// producerErrorLoop reports producer errors but otherwise does not stop the loop.
func (p *PulseAggregator) producerErrorLoop() {
	defer p.wg.Done()
	for {
		select {
		case err, ok := <-p.producer.Errors():
			if !ok {
				return
			}
			select {
			case p.errCh <- fmt.Errorf("producer error: %w", err):
			default:
			}
		case <-p.ctx.Done():
			return
		}
	}
}

/* ---------------- sarama.ConsumerGroupHandler implementation ---------------- */

// Setup is run at the beginning of a new session, before ConsumeClaim.
func (p *PulseAggregator) Setup(_ sarama.ConsumerGroupSession) error { return nil }

// Cleanup is run at the end of a session, once all ConsumeClaim goroutines have exited.
func (p *PulseAggregator) Cleanup(_ sarama.ConsumerGroupSession) error { return nil }

// ConsumeClaim runs once per assigned partition.
func (p *PulseAggregator) ConsumeClaim(sess sarama.ConsumerGroupSession, claim sarama.ConsumerGroupClaim) error {
	for msg := range claim.Messages() {
		if err := p.handleMessage(msg); err != nil {
			select {
			case p.errCh <- err:
			default:
			}
		} else {
			sess.MarkMessage(msg, "")
		}
	}
	return nil
}

/* --------------------------------- helpers --------------------------------- */

// handleMessage decodes, updates EWMA, and emits CommunityHealth events.
func (p *PulseAggregator) handleMessage(msg *sarama.ConsumerMessage) error {
	var event SocialEvent
	if err := json.Unmarshal(msg.Value, &event); err != nil {
		return fmt.Errorf("unmarshal SocialEvent: %w", err)
	}

	p.metrics.EventsConsumed.Inc()

	p.mu.Lock()
	e, ok := p.sentiment[event.CommunityID]
	if !ok {
		e = &EWMA{Lambda: p.cfg.EWMALambda}
		p.sentiment[event.CommunityID] = e
		// Set baseline to first sentiment seen.
		p.baseline[event.CommunityID] = event.Sentiment
	}
	newEWMA := e.Update(event.Sentiment)
	baseline := p.baseline[event.CommunityID]
	p.mu.Unlock()

	p.metrics.CurrentEWMA.WithLabelValues(event.CommunityID).Set(newEWMA)

	delta := newEWMA - baseline
	if abs(delta) >= p.cfg.DriftThreshold {
		return p.emitHealthEvent(event.CommunityID, newEWMA, baseline, delta)
	}
	return nil
}

// emitHealthEvent serializes and publishes a CommunityHealth event.
func (p *PulseAggregator) emitHealthEvent(commID string, ewma, baseline, delta float64) error {
	health := CommunityHealth{
		CommunityID:      commID,
		EWMASentiment:    ewma,
		Baseline:         baseline,
		Delta:            delta,
		TriggeredEpochMs: time.Now().UnixMilli(),
	}
	bytes, err := json.Marshal(health)
	if err != nil {
		return fmt.Errorf("marshal CommunityHealth: %w", err)
	}

	p.producer.Input() <- &sarama.ProducerMessage{
		Topic: p.cfg.OutputTopic,
		Key:   sarama.StringEncoder(commID),
		Value: sarama.ByteEncoder(bytes),
	}

	p.metrics.EventsEmitted.Inc()
	return nil
}

func abs(x float64) float64 {
	if x < 0 {
		return -x
	}
	return x
}
```