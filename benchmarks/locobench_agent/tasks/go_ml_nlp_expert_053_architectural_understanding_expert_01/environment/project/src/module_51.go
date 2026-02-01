```go
// Package echopulse implements core, event–driven ML/NLP stream-processing
// primitives used by EchoPulse.  This file wires together a production-grade,
// sentiment-analysis processor that illustrates Observer, Factory, Strategy
// and Pipeline patterns in a single cohesive component.
package echopulse

import (
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"sync"
	"time"

	"github.com/prometheus/client_golang/prometheus"
	"go.uber.org/zap"
)

//──────────────────────────────────────────────────────────────────────────────
// Canonical social event definition
//──────────────────────────────────────────────────────────────────────────────

// SocialEvent is the canonical payload that flows through EchoPulse.  All
// upstream producers (transcribers, chat gateways, reaction handlers) map their
// native data into this schema before pushing onto the event bus.
type SocialEvent struct {
	ID        string            `json:"id"`
	UserID    string            `json:"user_id"`
	Timestamp time.Time         `json:"timestamp"`
	Channel   string            `json:"channel"` // e.g. "#general", "topic/sports"
	Text      string            `json:"text"`    // Raw, un-normalized textual content
	Meta      map[string]string `json:"meta"`    // Arbitrary feature bag
}

// MarshalBinary lets SocialEvent satisfy kafka's Encoder / NATS msg payloads.
func (e SocialEvent) MarshalBinary() ([]byte, error) { return json.Marshal(e) }

// UnmarshalSocialEvent utility.
func UnmarshalSocialEvent(b []byte) (SocialEvent, error) {
	var ev SocialEvent
	err := json.Unmarshal(b, &ev)
	return ev, err
}

//──────────────────────────────────────────────────────────────────────────────
// Strategy interface – sentiment inference
//──────────────────────────────────────────────────────────────────────────────

// SentimentScore is the output of a model inference: range [-1.0, 1.0].
type SentimentScore float64

// SentimentModel exposes minimal contract for a model loaded from the
// ModelRegistry.  It purposefully decouples the processor from the actual ML
// framework (TensorFlow, PyTorch, ONNX Runtime, etc).
type SentimentModel interface {
	Predict(ctx context.Context, text string) (SentimentScore, error)
	// Metadata returns arbitrary model metadata (version, hash, training set id).
	Metadata() map[string]string
}

//──────────────────────────────────────────────────────────────────────────────
// Model registry – simplified in-process PoC
//──────────────────────────────────────────────────────────────────────────────

// ModelRegistry is a thread-safe, versioned registry of live ML artifacts.
type ModelRegistry interface {
	// Get returns the latest model for task "sentiment".
	Get(ctx context.Context, task string) (SentimentModel, error)
	// Subscribe emits registry change notifications.  Close the channel to detach.
	Subscribe(task string) (<-chan struct{}, error)
}

// inMemoryRegistry is a naive but thread-safe registry used in CI/testing.
type inMemoryRegistry struct {
	mtx      sync.RWMutex
	models   map[string]SentimentModel
	watchers map[string][]chan struct{}
}

var _ ModelRegistry = (*inMemoryRegistry)(nil)

func NewInMemoryRegistry() *inMemoryRegistry {
	return &inMemoryRegistry{
		models:   make(map[string]SentimentModel),
		watchers: make(map[string][]chan struct{}),
	}
}

func (r *inMemoryRegistry) Get(_ context.Context, task string) (SentimentModel, error) {
	r.mtx.RLock()
	defer r.mtx.RUnlock()
	m, ok := r.models[task]
	if !ok {
		return nil, fmt.Errorf("model for task %q not found", task)
	}
	return m, nil
}

func (r *inMemoryRegistry) put(task string, m SentimentModel) {
	r.mtx.Lock()
	defer r.mtx.Unlock()
	r.models[task] = m
	for _, ch := range r.watchers[task] {
		select {
		case ch <- struct{}{}:
		default:
		}
	}
}

func (r *inMemoryRegistry) Subscribe(task string) (<-chan struct{}, error) {
	r.mtx.Lock()
	defer r.mtx.Unlock()
	ch := make(chan struct{}, 1)
	r.watchers[task] = append(r.watchers[task], ch)
	return ch, nil
}

//──────────────────────────────────────────────────────────────────────────────
// Event bus abstractions – decouples processor from Kafka/NATS specifics
//──────────────────────────────────────────────────────────────────────────────

// Message represents a generic streaming message with ack semantics.
type Message interface {
	Value() []byte
	Ack() error
	Nack() error
}

// Consumer is a pull-based streaming consumer (Kafka, JetStream, Pulsar, etc.).
type Consumer interface {
	Subscribe(ctx context.Context, topic string) (<-chan Message, error)
	Close() error
}

// Producer pushes bytes onto a topic.
type Producer interface {
	Publish(ctx context.Context, topic string, value []byte, headers map[string]string) error
	Close() error
}

//──────────────────────────────────────────────────────────────────────────────
// SentimentStreamProcessor – the actual pipeline component
//──────────────────────────────────────────────────────────────────────────────

// SentimentStreamProcessor consumes raw SocialEvents, performs sentiment
// inference, and publishes annotated events onto a down-stream topic.
//
//   raw_social_events ---> [ sentiment processor ] ---> enriched_social_events
//
// It hot-swaps models whenever the ModelRegistry signals a newer artifact
// becoming "current" (typical blue/green or canary deployment scenario).
type SentimentStreamProcessor struct {
	log           *zap.Logger
	registry      ModelRegistry
	consumer      Consumer
	producer      Producer
	rawTopic      string
	enrichedTopic string

	// instrumentation
	metricInferenceLatency prometheus.Observer
	metricInferenceFail    prometheus.Counter
	metricMsgsIn           prometheus.Counter
	metricMsgsOut          prometheus.Counter

	// internal
	modelMu   sync.RWMutex
	currModel SentimentModel
	cancelFn  context.CancelFunc
	wg        sync.WaitGroup
}

// NewSentimentStreamProcessor wires up the processor with all collaborators
// ready to go, but does not start goroutines; call Run(ctx).
func NewSentimentStreamProcessor(
	registry ModelRegistry,
	consumer Consumer,
	producer Producer,
	rawTopic, enrichedTopic string,
	reg prometheus.Registerer,
	log *zap.Logger,
) (*SentimentStreamProcessor, error) {
	if registry == nil || consumer == nil || producer == nil {
		return nil, errors.New("nil dependency")
	}
	p := &SentimentStreamProcessor{
		log:           log.Named("sentiment_processor"),
		registry:      registry,
		consumer:      consumer,
		producer:      producer,
		rawTopic:      rawTopic,
		enrichedTopic: enrichedTopic,
	}

	// Init metrics.
	p.metricInferenceLatency = prometheus.NewHistogram(prometheus.HistogramOpts{
		Namespace: "echopulse",
		Subsystem: "sentiment",
		Name:      "inference_latency_seconds",
		Buckets:   prometheus.DefBuckets,
		Help:      "Model inference latency.",
	})
	p.metricInferenceFail = prometheus.NewCounter(prometheus.CounterOpts{
		Namespace: "echopulse",
		Subsystem: "sentiment",
		Name:      "inference_fail_total",
		Help:      "Number of model inference failures.",
	})
	p.metricMsgsIn = prometheus.NewCounter(prometheus.CounterOpts{
		Namespace: "echopulse",
		Subsystem: "sentiment",
		Name:      "messages_in_total",
		Help:      "Raw SocialEvent messages consumed.",
	})
	p.metricMsgsOut = prometheus.NewCounter(prometheus.CounterOpts{
		Namespace: "echopulse",
		Subsystem: "sentiment",
		Name:      "messages_out_total",
		Help:      "Enriched SocialEvent messages produced.",
	})

	if reg != nil {
		reg.MustRegister(
			p.metricInferenceLatency,
			p.metricInferenceFail,
			p.metricMsgsIn,
			p.metricMsgsOut,
		)
	}

	return p, nil
}

// Run starts all goroutines and blocks until ctx is cancelled or a fatal
// pipeline error occurs.
func (p *SentimentStreamProcessor) Run(parent context.Context) error {
	ctx, cancel := context.WithCancel(parent)
	p.cancelFn = cancel

	// fetch initial model
	m, err := p.registry.Get(ctx, "sentiment")
	if err != nil {
		return fmt.Errorf("fetch initial model: %w", err)
	}
	p.modelMu.Lock()
	p.currModel = m
	p.modelMu.Unlock()

	// watch for model updates
	regCh, err := p.registry.Subscribe("sentiment")
	if err != nil {
		return fmt.Errorf("registry.Subscribe: %w", err)
	}
	p.wg.Add(1)
	go func() {
		defer p.wg.Done()
		p.watchModels(ctx, regCh)
	}()

	// consume message stream
	msgCh, err := p.consumer.Subscribe(ctx, p.rawTopic)
	if err != nil {
		cancel()
		return fmt.Errorf("consumer.Subscribe(%s): %w", p.rawTopic, err)
	}
	p.wg.Add(1)
	go func() {
		defer p.wg.Done()
		p.handleMessages(ctx, msgCh)
	}()

	// block until ctx done
	<-ctx.Done()
	p.wg.Wait()
	_ = p.consumer.Close()
	_ = p.producer.Close()
	return nil
}

func (p *SentimentStreamProcessor) watchModels(ctx context.Context, regCh <-chan struct{}) {
	for {
		select {
		case <-ctx.Done():
			return
		case <-regCh:
			m, err := p.registry.Get(ctx, "sentiment")
			if err != nil {
				p.log.Error("failed to reload sentiment model", zap.Error(err))
				continue
			}
			p.modelMu.Lock()
			p.currModel = m
			p.modelMu.Unlock()
			p.log.Info("hot-swapped sentiment model", zap.Any("metadata", m.Metadata()))
		}
	}
}

func (p *SentimentStreamProcessor) handleMessages(ctx context.Context, msgCh <-chan Message) {
	for {
		select {
		case <-ctx.Done():
			return
		case msg, ok := <-msgCh:
			if !ok {
				p.log.Warn("message channel closed")
				p.cancelFn()
				return
			}
			p.metricMsgsIn.Inc()
			if err := p.processMessage(ctx, msg); err != nil {
				p.log.Error("processMessage failed", zap.Error(err))
				_ = msg.Nack()
				continue
			}
			_ = msg.Ack()
		}
	}
}

func (p *SentimentStreamProcessor) processMessage(ctx context.Context, msg Message) error {
	ev, err := UnmarshalSocialEvent(msg.Value())
	if err != nil {
		return fmt.Errorf("decode social event: %w", err)
	}

	// run inference
	p.modelMu.RLock()
	model := p.currModel
	p.modelMu.RUnlock()

	inferenceStart := time.Now()
	score, err := model.Predict(ctx, ev.Text)
	latency := time.Since(inferenceStart).Seconds()
	p.metricInferenceLatency.Observe(latency)

	if err != nil {
		p.metricInferenceFail.Inc()
		return fmt.Errorf("model predict: %w", err)
	}

	// enrich event
	if ev.Meta == nil {
		ev.Meta = make(map[string]string)
	}
	ev.Meta["sentiment_score"] = fmt.Sprintf("%.3f", score)

	// publish downstream
	bytes, _ := ev.MarshalBinary()
	if err := p.producer.Publish(ctx, p.enrichedTopic, bytes, nil); err != nil {
		return fmt.Errorf("publish enriched event: %w", err)
	}
	p.metricMsgsOut.Inc()
	return nil
}

//──────────────────────────────────────────────────────────────────────────────
// Fake model implementation – used for integration tests & local dev
//──────────────────────────────────────────────────────────────────────────────

// ruleBasedModel is a trivial model used for smoke testing.  Real deployments
// will load a gRPC-hosted onnxruntime server or similar.
type ruleBasedModel struct {
	ver string
}

func NewRuleBasedModel(version string) SentimentModel { return &ruleBasedModel{ver: version} }

func (m *ruleBasedModel) Predict(ctx context.Context, text string) (SentimentScore, error) {
	select {
	case <-ctx.Done():
		return 0, ctx.Err()
	default:
	}
	// extremely naive heuristic
	switch {
	case text == "":
		return 0, nil
	case containsAny(text, []string{"love", "great", "awesome"}):
		return 0.8, nil
	case containsAny(text, []string{"hate", "terrible", "worst"}):
		return -0.8, nil
	default:
		return 0, nil
	}
}

func (m *ruleBasedModel) Metadata() map[string]string {
	return map[string]string{"version": m.ver, "kind": "rule-based"}
}

func containsAny(s string, words []string) bool {
	for _, w := range words {
		if containsInsensitive(s, w) {
			return true
		}
	}
	return false
}

func containsInsensitive(s, substr string) bool {
	return len(s) >= len(substr) && ( // cheap guard
		// naive ASCII fold; real impl would handle Unicode normalization
		stringIndexFold(s, substr) >= 0)
}

func stringIndexFold(s, substr string) int {
	return indexFold(s, substr)
}

// indexFold is a small helper to perform case-folded substring search without
// allocations; pulled from Go stdlib strings.EqualFold internals.
func indexFold(s, substr string) int {
	needle := []rune(substr)
	n := len(needle)
Outer:
	for i, r := range s {
		if len([]rune(s[i:])) < n {
			return -1
		}
		for j := 0; j < n; j++ {
			if !runeEqualFold([]rune(s)[i+j], needle[j]) {
				continue Outer
			}
		}
		return i
	}
	return -1
}

func runeEqualFold(r1, r2 rune) bool {
	if r1 == r2 {
		return true
	}
	// ASCII fast path only – fine for demo.
	if 'A' <= r1 && r1 <= 'Z' {
		r1 += 32
	}
	if 'A' <= r2 && r2 <= 'Z' {
		r2 += 32
	}
	return r1 == r2
}
```