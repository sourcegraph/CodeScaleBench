```go
// Code generated for EchoPulse.
// File: src/module_26.go
//
// Description:
// StancePipeline is a real-time pipeline stage that observes the
// SocialEvent bus, classifies the stance of every textual artifact
// (support / neutral / oppose), and emits a StanceEvent onto the next
// topic in the processing graph.
//
// Patterns demonstrated:
//   • Observer          – subscribes to a high-throughput event bus
//   • Strategy          – interchangeable stance-classification engines
//   • Factory           – produces classifier strategies based on runtime
//                         configuration & model registry metadata
//   • Pipeline          – forms a discrete, parallelizable stage in the
//                         larger EchoPulse processing DAG
//
// NOTE: GPU/ML heavy logic is mocked.  Production builds would replace
// the stubbed model invocation with actual calls (e.g. ONNX runtime,
// TensorRT, or gRPC TensorFlow Serving).

package pipeline

import (
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"sync"
	"time"

	"github.com/rs/zerolog"
	"github.com/rs/zerolog/log"
)

// -----------------------------------------------------------------------
// Domain types
// -----------------------------------------------------------------------

// SocialEvent is the canonical envelope for all user-generated content
// inside EchoPulse.  (A slim subset is re-declared here to keep the file
// self-contained.)
type SocialEvent struct {
	ID        string            `json:"id"`
	UserID    string            `json:"user_id"`
	Timestamp time.Time         `json:"ts"`
	Text      string            `json:"text"`
	Meta      map[string]string `json:"meta,omitempty"`
}

// StanceLabel enumerates supported stance classes.
type StanceLabel string

const (
	StanceSupport StanceLabel = "support"
	StanceNeutral StanceLabel = "neutral"
	StanceOppose  StanceLabel = "oppose"
)

// StanceEvent is produced after classification and forwarded downstream.
type StanceEvent struct {
	SocialEvent
	Stance   StanceLabel `json:"stance"`
	ModelID  string      `json:"model_id"`
	Conf     float32     `json:"confidence"`
	ExecTime time.Duration `json:"exec_time_ms"`
}

// -----------------------------------------------------------------------
// Event Bus Contracts (simplified interfaces)
// -----------------------------------------------------------------------

// EventConsumer provides a pull-based interface for the Observer.
type EventConsumer interface {
	Fetch(ctx context.Context) (SocialEvent, error)
	Close() error
}

// EventProducer publishes enriched events downstream.
type EventProducer interface {
	Publish(ctx context.Context, event StanceEvent) error
	Close() error
}

// -----------------------------------------------------------------------
// Strategy pattern – stance classifiers
// -----------------------------------------------------------------------

// StanceClassifier implements a pluggable stance detector.
type StanceClassifier interface {
	ID() string
	Classify(ctx context.Context, text string) (StanceLabel, float32, error)
}

// RuleBasedClassifier is a lightweight heuristic fallback.
type RuleBasedClassifier struct{}

func (RuleBasedClassifier) ID() string { return "stance_rb_v1" }

func (RuleBasedClassifier) Classify(_ context.Context, text string) (StanceLabel, float32, error) {
	switch {
	case len(text) == 0:
		return StanceNeutral, 0.0, nil
	case containsAny(text, []string{":)", "💯"}):
		return StanceSupport, 0.65, nil
	case containsAny(text, []string{":(", "💢"}):
		return StanceOppose, 0.70, nil
	default:
		return StanceNeutral, 0.30, nil
	}
}

// TransformerClassifier mocks a remote deep-learning service call.
type TransformerClassifier struct {
	modelID string
	latency time.Duration
}

func NewTransformerClassifier(modelID string, p95Latency time.Duration) *TransformerClassifier {
	return &TransformerClassifier{
		modelID: modelID,
		latency: p95Latency,
	}
}

func (t *TransformerClassifier) ID() string { return t.modelID }

func (t *TransformerClassifier) Classify(ctx context.Context, text string) (StanceLabel, float32, error) {
	// Simulate network + inference latency
	select {
	case <-time.After(t.latency):
	case <-ctx.Done():
		return "", 0, ctx.Err()
	}

	// Naïve randomization stub using text length
	scoreSeed := len(text) % 100
	switch {
	case scoreSeed < 33:
		return StanceSupport, 0.85, nil
	case scoreSeed < 66:
		return StanceNeutral, 0.60, nil
	default:
		return StanceOppose, 0.80, nil
	}
}

// containsAny is a helper to search for tokens.
func containsAny(s string, needles []string) bool {
	for _, n := range needles {
		if n != "" && len(s) >= len(n) && contains(s, n) {
			return true
		}
	}
	return false
}

// naive O(n*m) substring search to remove external deps.
func contains(haystack, needle string) bool {
	return len(needle) > 0 && (len(haystack) >= len(needle)) && (indexOf(haystack, needle) >= 0)
}

func indexOf(s, substr string) int {
outer:
	for i := 0; i+len(substr) <= len(s); i++ {
		for j := range substr {
			if s[i+j] != substr[j] {
				continue outer
			}
		}
		return i
	}
	return -1
}

// -----------------------------------------------------------------------
// Factory – picks classifier based on runtime config / registry metadata
// -----------------------------------------------------------------------

type ModelRegistry interface {
	// Resolve returns the active model ID for a task such as "stance".
	Resolve(task string) (modelID string, err error)
}

// StanceClassifierFactory instantiates classifiers.
type StanceClassifierFactory struct {
	registry ModelRegistry
	logger   zerolog.Logger
}

func NewStanceClassifierFactory(r ModelRegistry) *StanceClassifierFactory {
	return &StanceClassifierFactory{
		registry: r,
		logger:   log.With().Str("component", "classifier_factory").Logger(),
	}
}

// Build returns a StanceClassifier ready for production traffic.
func (f *StanceClassifierFactory) Build() (StanceClassifier, error) {
	modelID, err := f.registry.Resolve("stance")
	if err != nil {
		return nil, fmt.Errorf("resolve stance model: %w", err)
	}

	// Example mapping rules
	switch modelID {
	case "":
		// fall back to RB if registry empty
		f.logger.Warn().Msg("registry empty, using rule-based classifier")
		return RuleBasedClassifier{}, nil
	case "stance_rb_v1":
		return RuleBasedClassifier{}, nil
	default:
		// Transformer / DL models
		return NewTransformerClassifier(modelID, 35*time.Millisecond), nil
	}
}

// -----------------------------------------------------------------------
// Pipeline stage
// -----------------------------------------------------------------------

// StancePipeline consumes SocialEvents and emits StanceEvents.
type StancePipeline struct {
	consumer   EventConsumer
	producer   EventProducer
	classifier StanceClassifier
	wg         sync.WaitGroup
	logger     zerolog.Logger

	workerCount int
}

// NewStancePipeline constructs a fully wired pipeline stage.
func NewStancePipeline(
	cons EventConsumer,
	prod EventProducer,
	clf StanceClassifier,
	workers int,
) *StancePipeline {
	if workers <= 0 {
		workers = 1
	}
	return &StancePipeline{
		consumer:    cons,
		producer:    prod,
		classifier:  clf,
		workerCount: workers,
		logger:      log.With().Str("stage", "stance").Logger(),
	}
}

// Start launches background processors until ctx is cancelled.
func (p *StancePipeline) Start(ctx context.Context) error {
	p.logger.Info().
		Int("workers", p.workerCount).
		Str("model", p.classifier.ID()).
		Msg("starting stance pipeline workers")

	p.wg.Add(p.workerCount)
	for i := 0; i < p.workerCount; i++ {
		go func(workerID int) {
			defer p.wg.Done()
			p.runWorker(ctx, workerID)
		}(i)
	}
	return nil
}

// Wait blocks until all workers have shut down gracefully.
func (p *StancePipeline) Wait() {
	p.wg.Wait()
	_ = p.consumer.Close()
	_ = p.producer.Close()
	p.logger.Info().Msg("all workers exited")
}

// runWorker is the core event-processing loop.
func (p *StancePipeline) runWorker(ctx context.Context, id int) {
	workerLog := p.logger.With().Int("worker", id).Logger()

	for {
		select {
		case <-ctx.Done():
			workerLog.Debug().Msg("context canceled; exiting worker")
			return
		default:
		}

		ev, err := p.consumer.Fetch(ctx)
		if errors.Is(err, io.EOF) {
			workerLog.Debug().Msg("event stream closed")
			return
		}
		if err != nil {
			workerLog.Error().Err(err).Msg("fetch event")
			continue
		}

		start := time.Now()
		stance, conf, err := p.classifier.Classify(ctx, ev.Text)
		if err != nil {
			workerLog.Error().Err(err).
				Str("event_id", ev.ID).
				Msg("classify stance")
			continue
		}

		sEv := StanceEvent{
			SocialEvent: ev,
			Stance:      stance,
			ModelID:     p.classifier.ID(),
			Conf:        conf,
			ExecTime:    time.Since(start).Truncate(time.Millisecond),
		}

		if err := p.producer.Publish(ctx, sEv); err != nil {
			workerLog.Error().Err(err).
				Str("event_id", ev.ID).
				Msg("publish stance")
		}
	}
}

// -----------------------------------------------------------------------
// Example registry & bus implementations (scaled-down stubs)
// -----------------------------------------------------------------------

// memRegistry is a simple in-memory registry useful for local dev/tests.
type memRegistry struct {
	models map[string]string
}

func NewMemoryRegistry() *memRegistry { // nolint:revive
	return &memRegistry{models: map[string]string{
		"stance": "stance_rb_v1",
	}}
}

func (m *memRegistry) Resolve(task string) (string, error) {
	if id, ok := m.models[task]; ok {
		return id, nil
	}
	return "", fmt.Errorf("model for task %q not found", task)
}

// channelConsumer/Producer are minimalist channel shims for demonstration.
// They provide deterministic, fully-in-memory behaviour for unit tests.

type channelConsumer struct {
	ch <-chan SocialEvent
}

func NewChannelConsumer(ch <-chan SocialEvent) EventConsumer {
	return &channelConsumer{ch: ch}
}

func (c *channelConsumer) Fetch(ctx context.Context) (SocialEvent, error) {
	select {
	case ev, ok := <-c.ch:
		if !ok {
			return SocialEvent{}, io.EOF
		}
		return ev, nil
	case <-ctx.Done():
		return SocialEvent{}, ctx.Err()
	}
}

func (c *channelConsumer) Close() error { return nil }

type channelProducer struct {
	ch chan<- StanceEvent
}

func NewChannelProducer(ch chan<- StanceEvent) EventProducer {
	return &channelProducer{ch: ch}
}

func (p *channelProducer) Publish(ctx context.Context, ev StanceEvent) error {
	select {
	case p.ch <- ev:
		return nil
	case <-ctx.Done():
		return ctx.Err()
	}
}

func (p *channelProducer) Close() error {
	close(p.ch)
	return nil
}

// -----------------------------------------------------------------------
// Bootstrap helper (non-production): wiring everything for local tests
// -----------------------------------------------------------------------

// BootStancePipeline wires an in-memory end-to-end graph.
// This function is intended for CLI tools, integration tests, or examples.
func BootStancePipeline(ctx context.Context, workers int) (
	ingest chan<- SocialEvent,
	output <-chan StanceEvent,
	done func(),
) {
	ingestCh := make(chan SocialEvent, 2048)
	outputCh := make(chan StanceEvent, 2048)

	reg := NewMemoryRegistry()
	factory := NewStanceClassifierFactory(reg)
	clf, err := factory.Build()
	if err != nil {
		log.Fatal().Err(err).Msg("failed to create classifier")
	}

	pipeline := NewStancePipeline(
		NewChannelConsumer(ingestCh),
		NewChannelProducer(outputCh),
		clf,
		workers,
	)

	if err := pipeline.Start(ctx); err != nil {
		log.Fatal().Err(err).Msg("failed to start pipeline")
	}

	go func() {
		<-ctx.Done()
		pipeline.Wait()
	}()

	return ingestCh, outputCh, func() { pipeline.Wait() }
}

// -----------------------------------------------------------------------
// JSON helpers (useful for CLI or debugging)
// -----------------------------------------------------------------------

// MarshalStanceEvent pretty-prints stance events.
func MarshalStanceEvent(ev StanceEvent) []byte {
	data, _ := json.MarshalIndent(ev, "", "  ")
	return data
}
