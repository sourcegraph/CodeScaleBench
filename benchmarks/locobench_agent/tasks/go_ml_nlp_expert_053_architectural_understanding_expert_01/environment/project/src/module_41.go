```go
// Code generated for EchoPulse – DO NOT EDIT.
// File: src/module_41.go
//
// Package processing contains stream-processing components that subscribe to the
// event bus, compute intermediate analytics, and publish higher-level signals.
// Module 41 implements a real-time sentiment anomaly detector that watches the
// aggregated sentiment of each community and emits a CommunityDriftEvent when
// the current sentiment departs too far from the rolling baseline.
//
// Design notes
//   • Observer pattern: detector implements the Observer interface and receives
//     SocialEvents from the dispatcher.
//   • Pipeline pattern: data flows ⟶ ingest ⟶ feature extraction (sentiment) ⟶
//     rolling stats ⟶ anomaly detection ⟶ emit drift event.
//   • Strategy pattern: the statistic (e.g., z-score) can be swapped without
//     impacting the rest of the component.
//   • MLOps hooks: every emitted CommunityDriftEvent is archived to the feature
//     store for offline analysis and can trigger an auto-retraining routine.

package processing

import (
	"context"
	"encoding/json"
	"errors"
	"math"
	"sync"
	"time"

	"github.com/Shopify/sarama"
)

// ----------------------------------------------------------------------------
// Public data contracts (shared with other services).
// ----------------------------------------------------------------------------

// SocialEvent is the canonical envelope for every artifact ingested by
// EchoPulse.  The struct is intentionally slim; most heavy fields are stored in
// the columnar feature store and replaced by IDs here.
type SocialEvent struct {
	EventID     string    `json:"event_id"`
	CommunityID string    `json:"community_id"`
	CreatedAt   time.Time `json:"created_at"`
	// Enriched fields.
	SentimentScore float64 `json:"sentiment_score"` // range [-1, +1]
}

// CommunityDriftEvent is published when a community’s average sentiment shows
// anomalous deviation from its rolling baseline.
type CommunityDriftEvent struct {
	CommunityID string    `json:"community_id"`
	WindowSize  int       `json:"window_size"`
	ZScore      float64   `json:"z_score"`
	Timestamp   time.Time `json:"timestamp"`
}

// ----------------------------------------------------------------------------
// Config.
// ----------------------------------------------------------------------------

// DetectorConfig groups dependency injection and runtime parameters.
type DetectorConfig struct {
	ConsumerGroup      string        // Kafka consumer group.
	InputTopic         string        // Topic to read SocialEvents from.
	OutputTopic        string        // Topic to publish CommunityDriftEvents to.
	Brokers            []string      // Kafka bootstrap brokers.
	RollingWindowSize  int           // Number of samples in rolling window.
	AnomalyZThreshold  float64       // Z-score to declare anomaly.
	FlushInterval      time.Duration // Flush interval for async producer.
	RebalanceTimeout   time.Duration // Consumer group rebalance timeout.
	ShutdownGracefully time.Duration // Max time to finish in-flight work.
}

// Validate performs basic sanity checks.
func (c DetectorConfig) Validate() error {
	if len(c.Brokers) == 0 {
		return errors.New("brokers list cannot be empty")
	}
	if c.InputTopic == "" || c.OutputTopic == "" {
		return errors.New("input and output topics must be specified")
	}
	if c.RollingWindowSize < 5 {
		return errors.New("rolling window size must be ≥ 5")
	}
	if c.AnomalyZThreshold <= 0 {
		return errors.New("anomaly threshold must be positive")
	}
	return nil
}

// ----------------------------------------------------------------------------
// Rolling statistics implementation.
// ----------------------------------------------------------------------------

// rollingStats keeps a fixed-size window of float64 values and computes mean
// and standard deviation in O(1) via Welford’s algorithm.
type rollingStats struct {
	mu      sync.Mutex
	window  []float64
	size    int
	mean    float64
	m2      float64 // Sum of squares of differences from the current mean.
	entries int
	pos     int
}

func newRollingStats(size int) *rollingStats {
	return &rollingStats{
		window: make([]float64, size),
		size:   size,
	}
}

// add inserts a new value and updates mean/variance incrementally.
func (r *rollingStats) add(v float64) {
	r.mu.Lock()
	defer r.mu.Unlock()

	// If we already have 'size' samples, remove the oldest from aggregates.
	if r.entries == r.size {
		old := r.window[r.pos]
		r.removeImpact(old)
	} else {
		r.entries++
	}

	// Add new value.
	r.window[r.pos] = v
	r.addImpact(v)

	// Move ring buffer position.
	r.pos = (r.pos + 1) % r.size
}

// addImpact updates mean/m2 when adding a new sample.
func (r *rollingStats) addImpact(v float64) {
	delta := v - r.mean
	r.mean += delta / float64(r.entries)
	r.m2 += delta * (v - r.mean)
}

// removeImpact updates aggregates when discarding a sample.
func (r *rollingStats) removeImpact(v float64) {
	if r.entries == 0 {
		return
	}
	prevMean := r.mean
	r.entries--
	if r.entries == 0 {
		r.mean, r.m2 = 0, 0
		return
	}
	r.mean = (float64(r.entries+1)*prevMean - v) / float64(r.entries)
	r.m2 -= (v - prevMean) * (v - r.mean)
}

// snapshot returns mean and population standard deviation.
func (r *rollingStats) snapshot() (mean, std float64) {
	r.mu.Lock()
	defer r.mu.Unlock()

	if r.entries < 2 {
		return r.mean, 0
	}
	return r.mean, math.Sqrt(r.m2 / float64(r.entries))
}

// ----------------------------------------------------------------------------
// SentimentAnomalyDetector.
// ----------------------------------------------------------------------------

// SentimentAnomalyDetector consumes SocialEvents, updates per-community rolling
// stats, and publishes CommunityDriftEvents when anomalies are detected.
type SentimentAnomalyDetector struct {
	cfg      DetectorConfig
	consumer sarama.ConsumerGroup
	producer sarama.AsyncProducer

	// Per-community rolling stats.
	mu        sync.RWMutex
	community map[string]*rollingStats
}

// NewSentimentAnomalyDetector wires kafka consumer/producer and returns a ready
// instance.  Call Start(ctx) to begin processing and Wait() to block.
func NewSentimentAnomalyDetector(cfg DetectorConfig) (*SentimentAnomalyDetector, error) {
	if err := cfg.Validate(); err != nil {
		return nil, err
	}

	//------------------------------------------
	// Kafka consumer group.
	//------------------------------------------
	cgCfg := sarama.NewConfig()
	cgCfg.Version = sarama.V2_5_0_0
	cgCfg.Consumer.Group.Rebalance.Timeout = cfg.RebalanceTimeout
	cgCfg.Consumer.Offsets.Initial = sarama.OffsetNewest

	consumer, err := sarama.NewConsumerGroup(cfg.Brokers, cfg.ConsumerGroup, cgCfg)
	if err != nil {
		return nil, err
	}

	//------------------------------------------
	// Kafka async producer.
	//------------------------------------------
	pCfg := sarama.NewConfig()
	pCfg.Producer.Return.Errors = true
	pCfg.Producer.Flush.Frequency = cfg.FlushInterval
	pCfg.Version = sarama.V2_5_0_0

	producer, err := sarama.NewAsyncProducer(cfg.Brokers, pCfg)
	if err != nil {
		consumer.Close()
		return nil, err
	}

	d := &SentimentAnomalyDetector{
		cfg:       cfg,
		consumer:  consumer,
		producer:  producer,
		community: make(map[string]*rollingStats),
	}
	go d.forwardProducerErrors()
	return d, nil
}

// forwardProducerErrors logs producer errors to avoid blocking on channel.
func (d *SentimentAnomalyDetector) forwardProducerErrors() {
	for err := range d.producer.Errors() {
		// In production, send to Sentry or a central error pipeline.
		_ = err // Replace with structured logging.
	}
}

// Start begins consuming messages and processing events.
func (d *SentimentAnomalyDetector) Start(ctx context.Context) error {
	handler := detectorGroupHandler{detector: d}
	go func() {
		for {
			if err := d.consumer.Consume(ctx, []string{d.cfg.InputTopic}, handler); err != nil {
				// In prod, add backoff & metrics.
				time.Sleep(2 * time.Second)
				continue
			}
			if ctx.Err() != nil {
				return
			}
		}
	}()
	return nil
}

// Close flushes producer, closes Kafka clients, and releases resources.
func (d *SentimentAnomalyDetector) Close() error {
	d.producer.AsyncClose()
	if err := d.consumer.Close(); err != nil {
		return err
	}
	return nil
}

// detectorGroupHandler satisfies sarama.ConsumerGroupHandler.
type detectorGroupHandler struct {
	detector *SentimentAnomalyDetector
}

func (h detectorGroupHandler) Setup(_ sarama.ConsumerGroupSession) error   { return nil }
func (h detectorGroupHandler) Cleanup(_ sarama.ConsumerGroupSession) error { return nil }

// ConsumeClaim is where the hot path lives.
func (h detectorGroupHandler) ConsumeClaim(sess sarama.ConsumerGroupSession, claim sarama.ConsumerGroupClaim) error {
	for msg := range claim.Messages() {
		if err := h.detector.processRaw(msg.Value); err != nil {
			// Production: record metric + DLQ.
		}
		sess.MarkMessage(msg, "")
	}
	return nil
}

// processRaw decodes SocialEvent JSON and feeds it into the anomaly pipeline.
func (d *SentimentAnomalyDetector) processRaw(b []byte) error {
	var evt SocialEvent
	if err := json.Unmarshal(b, &evt); err != nil {
		return err
	}
	if evt.CommunityID == "" {
		return errors.New("social event missing community_id")
	}
	rs := d.getOrCreateStats(evt.CommunityID)
	rs.add(evt.SentimentScore)

	mean, std := rs.snapshot()
	if std == 0 { // Not enough variance yet.
		return nil
	}
	z := math.Abs(evt.SentimentScore-mean) / std
	if z >= d.cfg.AnomalyZThreshold {
		return d.emitDriftEvent(evt.CommunityID, z)
	}
	return nil
}

// getOrCreateStats fetches rollingStats for a community, creating it if needed.
func (d *SentimentAnomalyDetector) getOrCreateStats(cid string) *rollingStats {
	d.mu.RLock()
	rs, ok := d.community[cid]
	d.mu.RUnlock()
	if ok {
		return rs
	}

	d.mu.Lock()
	defer d.mu.Unlock()
	// Double-check in case it was created while waiting.
	if rs, ok = d.community[cid]; ok {
		return rs
	}
	rs = newRollingStats(d.cfg.RollingWindowSize)
	d.community[cid] = rs
	return rs
}

// emitDriftEvent serializes CommunityDriftEvent and publishes to Kafka.
func (d *SentimentAnomalyDetector) emitDriftEvent(cid string, z float64) error {
	payload := CommunityDriftEvent{
		CommunityID: cid,
		WindowSize:  d.cfg.RollingWindowSize,
		ZScore:      z,
		Timestamp:   time.Now().UTC(),
	}
	b, err := json.Marshal(payload)
	if err != nil {
		return err
	}
	d.producer.Input() <- &sarama.ProducerMessage{
		Topic: d.cfg.OutputTopic,
		Key:   sarama.StringEncoder(cid),
		Value: sarama.ByteEncoder(b),
	}
	return nil
}
```