```go
// Code generated for EchoPulse – Real-Time Social Signal Processing Platform
// Path: src/module_33.go
//
// Package monitoring provides live model-monitoring utilities such as
// statistical-drift detection with automatic retraining triggers.
//
// The implementation demonstrates several architectural patterns used across
// EchoPulse: ‑ Observer (for drift notifications), ‑ Factory (producer/consumer
// factories), and ‑ Pipeline (streaming feature-stat events → drift detector →
// retrain event publisher).
//
// The module intentionally avoids hard dependencies on any single messaging
// layer.  Concrete integrations (e.g. Kafka, NATS JetStream) may satisfy the
// thin interfaces defined below.
package monitoring

import (
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"math"
	"sync"
	"time"

	"github.com/Shopify/sarama"
)

// ----------------------------------------------------------------------------
// Domain Types
// ----------------------------------------------------------------------------

// FeatureStats is the canonical payload emitted by upstream feature pipelines
// summarizing the distribution of a single feature for a particular batch
// window (or streaming micro-batch).
type FeatureStats struct {
	Feature   string    `json:"feature"`
	Histogram []float64 `json:"histogram"` // Probabilities must sum≈1
	BucketID  int64     `json:"bucket_id"` // e.g. epoch minute for deduping
	Timestamp time.Time `json:"timestamp"`
}

// DriftWarning is an internal event fanned-out via the Observer pattern.  It
// may ultimately be surfaced to dashboards, tracing spans, or audit logs.
type DriftWarning struct {
	Feature      string    `json:"feature"`
	Divergence   float64   `json:"divergence"`
	Threshold    float64   `json:"threshold"`
	ObservedAt   time.Time `json:"observed_at"`
	BaselineHash string    `json:"baseline_hash"`
}

// RetrainRequest is the message published downstream to the MLOps workflow
// orchestrator once drift passes a critical threshold.
type RetrainRequest struct {
	ModelName   string    `json:"model_name"`
	Feature     string    `json:"feature"`
	Reason      string    `json:"reason"`
	TriggeredAt time.Time `json:"triggered_at"`
}

// ----------------------------------------------------------------------------
// Baseline Store (Strategy pattern ‑ could be Redis/DB/S3/etc.)
// ----------------------------------------------------------------------------

// BaselineStore returns the baseline distribution used when computing drift.
type BaselineStore interface {
	GetBaseline(ctx context.Context, feature string) ([]float64, string, error) // []float, hash, error
}

// memoryBaselineStore is a development-only, in-memory implementation.
type memoryBaselineStore struct {
	data map[string][]float64
	mu   sync.RWMutex
}

func NewMemoryBaselineStore() BaselineStore {
	return &memoryBaselineStore{data: make(map[string][]float64)}
}

func (m *memoryBaselineStore) GetBaseline(ctx context.Context, feature string) ([]float64, string, error) {
	m.mu.RLock()
	defer m.mu.RUnlock()
	dist, ok := m.data[feature]
	if !ok {
		return nil, "", errors.New("baseline distribution not found")
	}
	return dist, fmt.Sprintf("%p", dist), nil
}

// ----------------------------------------------------------------------------
// Observer Pattern
// ----------------------------------------------------------------------------

// DriftObserver receives asynchronous drift notifications.
type DriftObserver interface {
	OnDrift(ctx context.Context, w DriftWarning)
}

// ----------------------------------------------------------------------------
// Kafka Producer/Consumer Interfaces (Factory pattern)
// ----------------------------------------------------------------------------

// Producer abstracts a message producer (Kafka, NATS, etc.).
type Producer interface {
	Publish(ctx context.Context, topic string, key string, payload []byte) error
	Close() error
}

// Consumer abstracts a message consumer delivering FeatureStats items.
type Consumer interface {
	Start(ctx context.Context, handler func(*FeatureStats) error) error
	Close() error
}

// saramaProducer is a concrete Kafka producer using Shopify/sarama.
type saramaProducer struct {
	p sarama.SyncProducer
}

func NewSaramaProducer(brokers []string) (Producer, error) {
	cfg := sarama.NewConfig()
	cfg.Producer.Return.Successes = true
	p, err := sarama.NewSyncProducer(brokers, cfg)
	if err != nil {
		return nil, err
	}
	return &saramaProducer{p: p}, nil
}

func (s *saramaProducer) Publish(ctx context.Context, topic, key string, payload []byte) error {
	msg := &sarama.ProducerMessage{
		Topic: topic,
		Key:   sarama.StringEncoder(key),
		Value: sarama.ByteEncoder(payload),
	}
	_, _, err := s.p.SendMessage(msg)
	return err
}

func (s *saramaProducer) Close() error { return s.p.Close() }

// ----------------------------------------------------------------------------
// DriftWatcher Implementation
// ----------------------------------------------------------------------------

// DriftWatcher consumes FeatureStats, computes statistical divergence against
// a baseline, and triggers downstream actions (Observer callbacks, retrain
// requests).  It is safe for concurrent use.
type DriftWatcher struct {
	baseline     BaselineStore
	producer     Producer
	consumer     Consumer
	thresholds   map[string]float64 // per-feature custom thresholds
	modelName    string
	observers    []DriftObserver
	observersMu  sync.RWMutex
	publishTopic string
}

// NewDriftWatcher constructs a ready-to-use drift detector.
func NewDriftWatcher(
	baseline BaselineStore,
	consumer Consumer,
	producer Producer,
	modelName string,
	publishTopic string,
	globalThreshold float64,
) *DriftWatcher {
	return &DriftWatcher{
		baseline:     baseline,
		consumer:     consumer,
		producer:     producer,
		modelName:    modelName,
		publishTopic: publishTopic,
		thresholds:   map[string]float64{"*": globalThreshold},
	}
}

// SetThreshold overrides the global threshold for a specific feature.
func (dw *DriftWatcher) SetThreshold(feature string, v float64) {
	dw.thresholds[feature] = v
}

// Register attaches an observer which will receive drift warnings.
func (dw *DriftWatcher) Register(obs DriftObserver) {
	dw.observersMu.Lock()
	defer dw.observersMu.Unlock()
	dw.observers = append(dw.observers, obs)
}

// Start initiates the streaming pipeline (non-blocking).
func (dw *DriftWatcher) Start(ctx context.Context) error {
	if dw.consumer == nil {
		return errors.New("consumer not configured")
	}
	go func() {
		_ = dw.consumer.Start(ctx, dw.handleFeatureStats) // handle error via ctx cancellation
	}()
	return nil
}

// Stop gracefully shuts down internal resources.
func (dw *DriftWatcher) Stop() error {
	var errProd, errCons error
	if dw.producer != nil {
		errProd = dw.producer.Close()
	}
	if dw.consumer != nil {
		errCons = dw.consumer.Close()
	}
	if errProd != nil {
		return errProd
	}
	return errCons
}

// handleFeatureStats is invoked for each incoming FeatureStats message.
func (dw *DriftWatcher) handleFeatureStats(fs *FeatureStats) error {
	ctx := context.Background() // Could derive from stream ctx
	bline, hash, err := dw.baseline.GetBaseline(ctx, fs.Feature)
	if err != nil {
		// Baseline missing – typically first run; log & skip
		return nil
	}

	divergence := jensenShannonDivergence(bline, fs.Histogram)
	threshold := dw.thresholdFor(fs.Feature)

	if divergence >= threshold {
		warning := DriftWarning{
			Feature:      fs.Feature,
			Divergence:   divergence,
			Threshold:    threshold,
			ObservedAt:   fs.Timestamp,
			BaselineHash: hash,
		}
		dw.notifyObservers(ctx, warning)

		// Publish retrain request
		req := RetrainRequest{
			ModelName:   dw.modelName,
			Feature:     fs.Feature,
			Reason:      fmt.Sprintf("drift divergence=%.5f>%.5f", divergence, threshold),
			TriggeredAt: time.Now().UTC(),
		}
		return dw.publishRetrainRequest(ctx, req)
	}
	return nil
}

func (dw *DriftWatcher) notifyObservers(ctx context.Context, w DriftWarning) {
	dw.observersMu.RLock()
	defer dw.observersMu.RUnlock()
	for _, o := range dw.observers {
		go o.OnDrift(ctx, w) // best-effort fan-out
	}
}

func (dw *DriftWatcher) publishRetrainRequest(ctx context.Context, req RetrainRequest) error {
	if dw.producer == nil {
		return nil // Producer optional; unit-testing scenarios
	}
	payload, err := json.Marshal(req)
	if err != nil {
		return err
	}
	return dw.producer.Publish(ctx, dw.publishTopic, req.ModelName, payload)
}

func (dw *DriftWatcher) thresholdFor(feature string) float64 {
	if v, ok := dw.thresholds[feature]; ok {
		return v
	}
	return dw.thresholds["*"]
}

// ----------------------------------------------------------------------------
// Jensen-Shannon Divergence Utility
// ----------------------------------------------------------------------------

// jensenShannonDivergence returns the JSD between two probability
// distributions (symmetrized & bounded [0,1]).  Both slices must be equal
// length and sum approximately 1.0.
func jensenShannonDivergence(p, q []float64) float64 {
	if len(p) != len(q) {
		return 1.0 // Max divergence when shape mismatch
	}

	// m = 0.5(p+q)
	m := make([]float64, len(p))
	for i := range p {
		m[i] = 0.5 * (p[i] + q[i])
	}

	return 0.5*klDivergence(p, m) + 0.5*klDivergence(q, m)
}

// klDivergence returns Σ p_i * log2(p_i/m_i).  Zero terms contribute 0.
func klDivergence(p, m []float64) float64 {
	var sum float64
	for i := range p {
		if p[i] == 0 || m[i] == 0 {
			continue
		}
		sum += p[i] * math.Log2(p[i]/m[i])
	}
	if math.IsNaN(sum) || math.IsInf(sum, 0) {
		return 1.0
	}
	return sum
}
```