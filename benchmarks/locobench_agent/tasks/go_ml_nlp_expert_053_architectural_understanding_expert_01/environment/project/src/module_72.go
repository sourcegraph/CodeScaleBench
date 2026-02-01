```go
// Code generated for EchoPulse: Real-Time Social Signal Processing Platform.
// Source: src/module_72.go
//
// Module 72 – Streaming Feature-Drift Detector
//
// This component monitors a stream of feature vectors, continuously computing
// Population-Stability-Index (PSI) scores against a reference distribution
// kept in the feature-store.  When statistically significant drift is found
// the detector publishes a DriftAlert event onto the event-bus so that the
// automated retraining loop can kick in.
//
// Pattern palette:
//   • Observer      – Kafka consumer group watching the feature topic
//   • Strategy      – PSI (default) but pluggable detector interface
//   • Pipeline      – Streaming window → aggregation → scoring → alerting
//
// The implementation is completely self-contained; external dependencies are
// limited to Sarama (Kafka) and the standard library.

package echopulse

import (
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"log/slog"
	"math"
	"os"
	"os/signal"
	"sync"
	"syscall"
	"time"

	"github.com/Shopify/sarama"
	"golang.org/x/sync/errgroup"
)

// DriftDetectorConfig contains all runtime knobs for the detector.
type DriftDetectorConfig struct {
	BrokerURLs   []string                     // Kafka bootstrap servers
	FeatureTopic string                       // Topic that carries feature vectors
	AlertTopic   string                       // Topic to publish DriftAlert events
	GroupID      string                       // Kafka consumer group
	WindowSize   int                          // #observations per sliding window
	PSIThreshold float64                      // Alert threshold
	Reference    map[string]FeatureReference  // Pre-computed reference distributions
	Logger       *slog.Logger                 // Optional structured logger
}

// FeatureReference holds a reference distribution for one feature.
type FeatureReference struct {
	Bins      []float64 `json:"bins"`       // Edges, monotonically increasing
	Expected  []float64 `json:"expected"`   // Expected proportions (len = len(Bins)-1)
}

// DriftAlert is the event emitted when drift is detected.
type DriftAlert struct {
	Feature    string    `json:"feature"`
	PSI        float64   `json:"psi"`
	Threshold  float64   `json:"threshold"`
	WindowSize int       `json:"window_size"`
	Timestamp  time.Time `json:"timestamp"`
}

// detectorWindow keeps a sliding window of observations for one feature.
type detectorWindow struct {
	ref FeatureReference
	mu  sync.Mutex
	// counts len = len(ref.Expected)
	counts []int
	n      int // total count in window
}

func newDetectorWindow(ref FeatureReference) *detectorWindow {
	return &detectorWindow{
		ref:    ref,
		counts: make([]int, len(ref.Expected)),
	}
}

func (w *detectorWindow) add(v float64) {
	w.mu.Lock()
	defer w.mu.Unlock()

	idx := binIndex(v, w.ref.Bins)
	if idx < 0 || idx >= len(w.counts) {
		// out of bounds → ignore but keep metrics consistent
		return
	}
	w.counts[idx]++
	w.n++
}

func (w *detectorWindow) ready(windowSize int) bool {
	w.mu.Lock()
	defer w.mu.Unlock()
	return w.n >= windowSize
}

// pop returns counts and resets window.
func (w *detectorWindow) pop() []int {
	w.mu.Lock()
	defer w.mu.Unlock()

	out := make([]int, len(w.counts))
	copy(out, w.counts)

	// reset
	for i := range w.counts {
		w.counts[i] = 0
	}
	w.n = 0
	return out
}

// DriftDetector listens on FeatureTopic and publishes DriftAlert to AlertTopic.
type DriftDetector struct {
	conf     DriftDetectorConfig
	producer sarama.AsyncProducer
	windows  map[string]*detectorWindow
	log      *slog.Logger
}

// NewDriftDetector prepares a ready-to-run detector.
func NewDriftDetector(cfg DriftDetectorConfig) (*DriftDetector, error) {
	if cfg.WindowSize <= 0 {
		return nil, errors.New("window size must be > 0")
	}
	if cfg.PSIThreshold <= 0 {
		return nil, errors.New("PSI threshold must be > 0")
	}
	if len(cfg.Reference) == 0 {
		return nil, errors.New("reference distributions cannot be empty")
	}
	if len(cfg.BrokerURLs) == 0 {
		return nil, errors.New("at least one broker URL must be provided")
	}

	// Logger fallback
	if cfg.Logger == nil {
		cfg.Logger = slog.New(slog.NewJSONHandler(os.Stderr, nil))
	}

	prodCfg := sarama.NewConfig()
	prodCfg.Producer.Return.Successes = false
	prodCfg.Producer.RequiredAcks = sarama.WaitForLocal
	prodCfg.Version = sarama.MaxVersion

	prod, err := sarama.NewAsyncProducer(cfg.BrokerURLs, prodCfg)
	if err != nil {
		return nil, fmt.Errorf("create producer: %w", err)
	}

	w := make(map[string]*detectorWindow)
	for fname, ref := range cfg.Reference {
		if len(ref.Bins) < 2 || len(ref.Expected) != len(ref.Bins)-1 {
			return nil, fmt.Errorf("invalid reference for feature %q", fname)
		}
		w[fname] = newDetectorWindow(ref)
	}

	return &DriftDetector{
		conf:     cfg,
		producer: prod,
		windows:  w,
		log:      cfg.Logger.With("component", "drift-detector"),
	}, nil
}

// Run blocks until ctx is canceled or a fatal error occurs.
func (d *DriftDetector) Run(ctx context.Context) error {
	grp, ctx := errgroup.WithContext(ctx)

	// Graceful shutdown: surface producer errors
	grp.Go(func() error {
		for {
			select {
			case <-ctx.Done():
				return ctx.Err()
			case err := <-d.producer.Errors():
				if err != nil {
					d.log.Error("producer error", "err", err)
				}
			}
		}
	})

	// Consumer group
	grp.Go(func() error {
		return d.consume(ctx)
	})

	// Wait for termination
	err := grp.Wait()
	_ = d.producer.Close()
	return err
}

// consume spins up a Sarama consumer group and processes messages.
func (d *DriftDetector) consume(ctx context.Context) error {
	cfg := sarama.NewConfig()
	cfg.Version = sarama.MaxVersion
	cfg.ClientID = "echopulse-drift-detector"
	cfg.Consumer.Offsets.Initial = sarama.OffsetNewest
	cfg.Consumer.Group.Rebalance.GroupStrategies = []sarama.BalanceStrategy{sarama.NewBalanceStrategyRange()}
	cfg.Consumer.Group.Session.Timeout = 10 * time.Second

	cg, err := sarama.NewConsumerGroup(d.conf.BrokerURLs, d.conf.GroupID, cfg)
	if err != nil {
		return fmt.Errorf("create consumer group: %w", err)
	}
	defer cg.Close()

	handler := &featureConsumerGroupHandler{
		ctx:      ctx,
		detector: d,
	}

	for {
		if err := cg.Consume(ctx, []string{d.conf.FeatureTopic}, handler); err != nil {
			return fmt.Errorf("consume loop: %w", err)
		}
		if ctx.Err() != nil {
			return ctx.Err()
		}
	}
}

// featureConsumerGroupHandler processes messages for one session.
type featureConsumerGroupHandler struct {
	ctx      context.Context
	detector *DriftDetector
}

func (h *featureConsumerGroupHandler) Setup(_ sarama.ConsumerGroupSession) error   { return nil }
func (h *featureConsumerGroupHandler) Cleanup(_ sarama.ConsumerGroupSession) error { return nil }
func (h *featureConsumerGroupHandler) ConsumeClaim(sess sarama.ConsumerGroupSession, claim sarama.ConsumerGroupClaim) error {
	for msg := range claim.Messages() {
		select {
		case <-h.ctx.Done():
			return h.ctx.Err()
		default:
		}

		if err := h.detector.processMessage(msg.Value); err != nil {
			h.detector.log.Error("process message", "err", err)
		}
		sess.MarkMessage(msg, "")
	}
	return nil
}

// processMessage decodes a feature vector and updates windows.
func (d *DriftDetector) processMessage(raw []byte) error {
	var obs map[string]float64
	if err := json.Unmarshal(raw, &obs); err != nil {
		return fmt.Errorf("decode feature vector: %w", err)
	}

	for fname, v := range obs {
		win, ok := d.windows[fname]
		if !ok {
			continue // unknown feature
		}
		win.add(v)
		if win.ready(d.conf.WindowSize) {
			counts := win.pop()
			psi, err := computePSI(counts, win.ref.Expected)
			if err != nil {
				d.log.Warn("psi computation failed", "feature", fname, "err", err)
				continue
			}
			if psi >= d.conf.PSIThreshold {
				alert := DriftAlert{
					Feature:    fname,
					PSI:        psi,
					Threshold:  d.conf.PSIThreshold,
					WindowSize: d.conf.WindowSize,
					Timestamp:  time.Now().UTC(),
				}
				if err := d.publishAlert(alert); err != nil {
					d.log.Error("publish alert failed", "feature", fname, "err", err)
				} else {
					d.log.Info("drift detected", "feature", fname, "psi", psi)
				}
			}
		}
	}

	return nil
}

func (d *DriftDetector) publishAlert(alert DriftAlert) error {
	payload, err := json.Marshal(alert)
	if err != nil {
		return fmt.Errorf("encode alert: %w", err)
	}

	msg := &sarama.ProducerMessage{
		Topic:     d.conf.AlertTopic,
		Key:       sarama.StringEncoder(alert.Feature),
		Value:     sarama.ByteEncoder(payload),
		Timestamp: alert.Timestamp,
	}

	d.producer.Input() <- msg
	return nil
}

/****************************
 *      Helper Functions    *
 ****************************/

// computePSI returns the population stability index.
// counts and expected must have identical length.
func computePSI(counts []int, expected []float64) (float64, error) {
	if len(counts) != len(expected) {
		return 0, errors.New("mismatched lengths")
	}
	total := 0
	for _, c := range counts {
		total += c
	}
	if total == 0 {
		return 0, errors.New("empty window")
	}

	var psi float64
	for i, count := range counts {
		act := float64(count) / float64(total)
		exp := expected[i]
		if exp == 0 {
			continue // skip bins with no expectation
		}
		delta := act - exp
		if act == 0 {
			continue // avoid log(0)
		}
		psi += delta * math.Log(act/exp)
	}
	return psi, nil
}

// binIndex finds the index of the bin into which v falls.
// Bins are defined by edges such that bin[i] = [edges[i], edges[i+1])
func binIndex(v float64, edges []float64) int {
	n := len(edges) - 1
	// Linear scan (n is typically < 50).  A binary search would
	// be faster for wide bins but adds complexity.
	for i := 0; i < n; i++ {
		if v >= edges[i] && v < edges[i+1] {
			return i
		}
	}
	// Include right-most edge
	if v == edges[len(edges)-1] {
		return n - 1
	}
	return -1
}

/****************************
 *   Stand-alone Entrypoint *
 ****************************/

// The main func is provided for convenience so the detector can be launched as
// an independent micro-service. Integrators may embed DriftDetector in their
// own process instead.
func main() {
	// Basic signal handling – cancel ctx on SIGINT/SIGTERM
	ctx, stop := signal.NotifyContext(context.Background(), syscall.SIGINT, syscall.SIGTERM)
	defer stop()

	// Load reference distributions (could be fetched from feature-store)
	ref, err := loadReferenceFromDisk("reference.json")
	if err != nil {
		slog.Error("failed to load reference", "err", err)
		os.Exit(1)
	}

	cfg := DriftDetectorConfig{
		BrokerURLs:   []string{"kafka:9092"},
		FeatureTopic: "feature_vectors",
		AlertTopic:   "drift_alerts",
		GroupID:      "drift-detector-v1",
		WindowSize:   10_000,
		PSIThreshold: 0.25,
		Reference:    ref,
	}

	detector, err := NewDriftDetector(cfg)
	if err != nil {
		slog.Error("failed to create detector", "err", err)
		os.Exit(1)
	}

	if err := detector.Run(ctx); err != nil && !errors.Is(err, context.Canceled) {
		slog.Error("runtime error", "err", err)
		os.Exit(1)
	}
}

// loadReferenceFromDisk is a helper to read a JSON file of reference stats.
func loadReferenceFromDisk(path string) (map[string]FeatureReference, error) {
	data, err := os.ReadFile(path)
	if err != nil {
		return nil, err
	}
	var out map[string]FeatureReference
	if err := json.Unmarshal(data, &out); err != nil {
		return nil, err
	}
	return out, nil
}
```