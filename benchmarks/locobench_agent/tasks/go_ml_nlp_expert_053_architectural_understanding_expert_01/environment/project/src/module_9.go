```go
// File: src/module_9.go
// Package monitoring implements on-line statistical drift detection for
// EchoPulse models.  It consumes model-level feature statistics from the
// event bus, calculates Population-Stability Index (PSI) against the
// training baseline, and publishes a retraining request when drift is
// detected.
//
// This module showcases Observer, Strategy, and Pipeline patterns: the
// DriftDetector observes a bus topic, applies the PSI strategy, and pushes
// a message into the retraining pipeline.
//
// NOTE: Production code would place interfaces shared across modules in a
//       dedicated internal/pkg directory; they are inlined here to keep the
//       example self-contained.
package monitoring

import (
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"os"
	"sync"
	"time"

	"github.com/segmentio/kafka-go"        // High-throughput event bus
	"go.uber.org/atomic"                   // Lightweight atomic counters
	"go.uber.org/zap"                      // Fast structured logging
	"gopkg.in/yaml.v3"                     // Baseline snapshot format
)

// ----------------------------------------------------------------------
// Public types & interfaces
// ----------------------------------------------------------------------

// EventBus is a minimal contract abstracting Kafka / NATS JetStream
type EventBus interface {
	Subscribe(ctx context.Context, topic string) (<-chan kafka.Message, error)
	Publish(ctx context.Context, topic string, msg []byte) error
	Close() error
}

// MonitoringEvent is produced by online inference services.  Each batch
// encapsulates histogram counts per feature computed over a sliding window.
type MonitoringEvent struct {
	Model     string         `json:"model"`
	Version   string         `json:"version"`
	Timestamp time.Time      `json:"ts"`
	Stats     []FeatureStats `json:"stats"`
}

// FeatureStats stores histogram bin counts for a single feature.
// The bins MUST align with the baseline bins.
type FeatureStats struct {
	Name  string    `json:"name"`
	Bins  []float64 `json:"bins"`
	Total float64   `json:"total"`
}

// DriftAlarm is published when PSI exceeds configured thresholds.
type DriftAlarm struct {
	Model       string            `json:"model"`
	Version     string            `json:"version"`
	FeaturePSIs map[string]float64`json:"feature_psi"`
	TriggeredAt time.Time         `json:"ts"`
}

// Config drives DriftDetector behavior and is usually injected via Viper,
// env vars, or config map.
type Config struct {
	InputTopic         string        `yaml:"input_topic"`
	OutputTopic        string        `yaml:"output_topic"`
	BaselineSnapshot   string        `yaml:"baseline_snapshot"`  // local path or S3 uri
	MaxPSI             float64       `yaml:"max_psi"`            // alarm threshold
	Cooldown           time.Duration `yaml:"cooldown"`           // min pause between alarms
	ConsumerBufferSize int           `yaml:"consumer_buffer"`    // chan size
}

// ----------------------------------------------------------------------
// DriftDetector
// ----------------------------------------------------------------------

// DriftDetector consumes monitoring events and emits drift alarms.
type DriftDetector struct {
	bus       EventBus
	log       *zap.Logger
	cfg       Config
	baseline  map[string][]float64 // bins per feature
	lastAlarm atomic.Time          // last time an alarm was emitted
	mu        sync.RWMutex         // protects baseline
}

// NewDriftDetector constructs a detector, loading the baseline snapshot.
func NewDriftDetector(bus EventBus, cfg Config, log *zap.Logger) (*DriftDetector, error) {
	if log == nil {
		log = zap.L().Named("drift-detector")
	}
	d := &DriftDetector{
		bus:       bus,
		cfg:       cfg,
		log:       log,
		baseline:  make(map[string][]float64),
		lastAlarm: atomic.Time{},
	}
	if err := d.loadBaseline(cfg.BaselineSnapshot); err != nil {
		return nil, err
	}
	return d, nil
}

// Start attaches to the input topic and blocks until ctx is cancelled.
func (d *DriftDetector) Start(ctx context.Context) error {
	msgCh, err := d.bus.Subscribe(ctx, d.cfg.InputTopic)
	if err != nil {
		return fmt.Errorf("subscribe: %w", err)
	}
	d.log.Info("drift detector started",
		zap.String("topic", d.cfg.InputTopic),
		zap.Duration("cooldown", d.cfg.Cooldown),
	)
	for {
		select {
		case <-ctx.Done():
			_ = d.bus.Close()
			return ctx.Err()
		case msg, ok := <-msgCh:
			if !ok {
				return errors.New("message channel closed")
			}
			if err := d.handleMessage(ctx, msg); err != nil {
				d.log.Error("failed to handle message", zap.Error(err))
			}
		}
	}
}

// ----------------------------------------------------------------------
// Internal helpers
// ----------------------------------------------------------------------

func (d *DriftDetector) handleMessage(ctx context.Context, msg kafka.Message) error {
	var ev MonitoringEvent
	if err := json.Unmarshal(msg.Value, &ev); err != nil {
		return fmt.Errorf("decode: %w", err)
	}
	drifted, psiMap := d.detectDrift(ev)
	if !drifted {
		return nil
	}

	// Rate-limit alarms
	last := d.lastAlarm.Load()
	if !last.IsZero() && time.Since(last) < d.cfg.Cooldown {
		d.log.Warn("drift detected but cooldown active",
			zap.Duration("since_last", time.Since(last)),
		)
		return nil
	}
	d.lastAlarm.Store(time.Now())

	alarm := DriftAlarm{
		Model:       ev.Model,
		Version:     ev.Version,
		FeaturePSIs: psiMap,
		TriggeredAt: time.Now().UTC(),
	}
	payload, err := json.Marshal(alarm)
	if err != nil {
		return fmt.Errorf("alarm marshal: %w", err)
	}
	if err := d.bus.Publish(ctx, d.cfg.OutputTopic, payload); err != nil {
		return fmt.Errorf("publish alarm: %w", err)
	}
	d.log.Warn("drift alarm emitted",
		zap.String("model", alarm.Model),
		zap.String("version", alarm.Version),
		zap.Any("psi", psiMap),
	)
	return nil
}

// detectDrift computes PSI per feature and returns true if any exceed thresh.
func (d *DriftDetector) detectDrift(ev MonitoringEvent) (bool, map[string]float64) {
	psiMap := make(map[string]float64, len(ev.Stats))
	var alarm bool

	d.mu.RLock()
	defer d.mu.RUnlock()

	for _, fs := range ev.Stats {
		base, ok := d.baseline[fs.Name]
		if !ok {
			// Unknown feature, skip or record warning
			d.log.Debug("missing baseline for feature", zap.String("feature", fs.Name))
			continue
		}
		psi := psi(base, fs.Bins)
		psiMap[fs.Name] = psi
		if psi > d.cfg.MaxPSI {
			alarm = true
		}
	}
	return alarm, psiMap
}

// loadBaseline pulls baseline snapshot from local disk (could be extended
// for S3 / GCS).  Snapshot format:
//
//   feature_name:
//     - 0.1
//     - 0.2
//     - 0.3
//     ...
func (d *DriftDetector) loadBaseline(path string) error {
	r, err := openMaybeRemote(path)
	if err != nil {
		return err
	}
	defer r.Close()

	var tmp map[string][]float64
	if err := yaml.NewDecoder(r).Decode(&tmp); err != nil {
		return fmt.Errorf("decode baseline: %w", err)
	}
	if len(tmp) == 0 {
		return errors.New("baseline snapshot empty")
	}

	d.mu.Lock()
	d.baseline = tmp
	d.mu.Unlock()

	d.log.Info("baseline snapshot loaded", zap.Int("features", len(tmp)))
	return nil
}

// ----------------------------------------------------------------------
// Utility functions
// ----------------------------------------------------------------------

// psi calculates population-stability index between expected (baseline) and
// actual (production) distributions.  PSI = Σ (actual-exp) * ln(actual/exp).
// Inputs are raw counts; they will be normalized to probabilities.
func psi(expected, actual []float64) float64 {
	if len(expected) == 0 || len(expected) != len(actual) {
		return 0
	}
	var sumExp, sumAct float64
	for i := range expected {
		sumExp += expected[i]
		sumAct += actual[i]
	}
	if sumExp == 0 || sumAct == 0 {
		return 0
	}

	var psi float64
	for i := range expected {
		e := expected[i] / sumExp
		a := actual[i] / sumAct
		// Guard tiny values to avoid log(0)
		if e < 1e-12 {
			e = 1e-12
		}
		if a < 1e-12 {
			a = 1e-12
		}
		psi += (a - e) * (math.Log(a / e))
	}
	return psi
}

// openMaybeRemote handles local files now; could be extended to download
// from S3 or HTTP.
func openMaybeRemote(path string) (io.ReadCloser, error) {
	return os.Open(path)
}

// ----------------------------------------------------------------------
// Kafka implementation of EventBus (simplified)
// ----------------------------------------------------------------------

// KafkaBus wraps segmentio/kafka-go for Pub/Sub.
type KafkaBus struct {
	reader *kafka.Reader
	writer *kafka.Writer
}

// NewKafkaBus returns EventBus backed by Kafka.
func NewKafkaBus(brokers []string, groupID string) (*KafkaBus, error) {
	if len(brokers) == 0 {
		return nil, errors.New("brokers list empty")
	}
	r := kafka.NewReader(kafka.ReaderConfig{
		Brokers: brokers,
		GroupID: groupID,
		// Topic is configured on Subscribe
		MinBytes: 1e3,
		MaxBytes: 10e6,
	})
	w := &kafka.Writer{
		Addr:         kafka.TCP(brokers...),
		RequiredAcks: kafka.RequireAll,
	}
	return &KafkaBus{reader: r, writer: w}, nil
}

func (k *KafkaBus) Subscribe(ctx context.Context, topic string) (<-chan kafka.Message, error) {
	// reconfigure topic
	k.reader.SetOffset(kafka.FirstOffset)
	k.reader.Config().Topic = topic

	out := make(chan kafka.Message, 1024)
	go func() {
		defer close(out)
		for {
			msg, err := k.reader.FetchMessage(ctx)
			if err != nil {
				return
			}
			out <- msg
			_ = k.reader.CommitMessages(ctx, msg)
		}
	}()
	return out, nil
}

func (k *KafkaBus) Publish(ctx context.Context, topic string, payload []byte) error {
	return k.writer.WriteMessages(ctx, kafka.Message{
		Topic: topic,
		Value: payload,
		Time:  time.Now(),
	})
}

func (k *KafkaBus) Close() error {
	if err := k.reader.Close(); err != nil {
		return err
	}
	return k.writer.Close()
}
```