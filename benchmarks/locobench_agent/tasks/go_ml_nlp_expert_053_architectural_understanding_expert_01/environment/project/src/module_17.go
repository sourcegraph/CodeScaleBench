```go
// Copyright 2024
//
// EchoPulse — Real-Time Social Signal Processing Platform
//
// Module 17: Realtime NLP Processing Pipeline
//
// This file implements a concurrent, pluggable processing pipeline that
// consumes SocialEvents from an input channel, enriches them through a set of
// Processor stages (Strategy Pattern), publishes diagnostic information to a
// Kafka topic (Observer Pattern), and returns the fully-processed event stream
// to downstream consumers.
//
// The implementation showcases the following architectural concerns:
//
//   • Pipeline Pattern         – Ordered, streaming data-flow
//   • Strategy Pattern         – Hot-swappable per-stage processors
//   • Observer Pattern         – Out-of-band publish of processing metrics
//   • Factory Pattern          – Declarative processor construction
//   • Robust Concurrency       – Context-aware goroutines & back-pressure
//
package echopulse

import (
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"log"
	"os"
	"strings"
	"sync"
	"time"

	"github.com/segmentio/kafka-go"
)

// ==== Domain Model =================================================================

// SocialEvent is the canonical representation of any user-generated content.
type SocialEvent struct {
	ID        string            `json:"id"`
	UserID    string            `json:"user_id"`
	Timestamp time.Time         `json:"ts"`
	Channel   string            `json:"channel"` // e.g. #general, @user
	Payload   string            `json:"payload"` // raw text, emoji, etc.
	Metadata  map[string]string `json:"meta,omitempty"`

	// Enriched fields ‑- progressively filled by processors
	Language  string            `json:"language,omitempty"`
	Sentiment float64           `json:"sentiment,omitempty"` // ‑1 .. 1
	Toxicity  float64           `json:"toxicity,omitempty"`  // 0 .. 1
	Features  map[string]any    `json:"features,omitempty"`  // arbitrary feature map
	Err       error             `json:"-"`                   // Processing error (not serialized)
}

// Clone returns a deep copy so processors can be side-effect free.
func (e SocialEvent) Clone() SocialEvent {
	out := e
	out.Metadata = make(map[string]string, len(e.Metadata))
	for k, v := range e.Metadata {
		out.Metadata[k] = v
	}
	out.Features = make(map[string]any, len(e.Features))
	for k, v := range e.Features {
		out.Features[k] = v
	}
	return out
}

// ==== Processor Contracts ===========================================================

// Processor represents one step in the NLP pipeline.
type Processor interface {
	// Name returns a unique, human-friendly identifier for metrics/logging.
	Name() string
	// Process mutates the event (or clone) and returns it along with an error
	// if the enrichment could not be performed.
	Process(ctx context.Context, ev SocialEvent) (SocialEvent, error)
}

// Factory constructs processors from declarative configuration.
// Example cfg:
//   {
//     "type": "sentiment",
//     "endpoint": "grpc://sentiment-svc:50051",
//     "timeout": "250ms"
//   }
type Factory interface {
	NewProcessor(cfg map[string]any) (Processor, error)
}

// ==== Pipeline Implementation =======================================================

// Pipeline orchestrates a set of Processor stages.
type Pipeline struct {
	stages   []Processor
	observer Observer // optional
}

// NewPipeline returns a ready-to-use Pipeline.
func NewPipeline(stages []Processor, o Observer) *Pipeline {
	return &Pipeline{
		stages:   stages,
		observer: o,
	}
}

// Run consumes SocialEvents from 'in', processes them, and emits the enriched
// events through the returned channel. A separate error channel carries fatal
// pipeline errors (e.g. processor misconfiguration).  Both channels are closed
// when ctx is cancelled or when 'in' is closed.
func (p *Pipeline) Run(ctx context.Context, in <-chan SocialEvent) (<-chan SocialEvent, <-chan error) {
	out := make(chan SocialEvent)
	errC := make(chan error, 1) // buffer 1 so send won't block on fatal error

	go func() {
		defer close(out)
		defer close(errC)

		for {
			select {
			case <-ctx.Done():
				return
			case ev, ok := <-in:
				if !ok {
					return // upstream closed
				}

				processed, err := p.processOne(ctx, ev)
				if p.observer != nil {
					p.observer.Notify(processed, err)
				}

				// Soft error: annotate event but still pass it downstream.
				processed.Err = err
				select {
				case <-ctx.Done():
					return
				case out <- processed:
				}
			}
		}
	}()

	return out, errC
}

// processOne runs a single event through all configured stages.
func (p *Pipeline) processOne(ctx context.Context, ev SocialEvent) (SocialEvent, error) {
	var err error
	cur := ev.Clone()

	for _, stage := range p.stages {
		select {
		case <-ctx.Done():
			return cur, ctx.Err()
		default:
		}

		start := time.Now()
		cur, err = stage.Process(ctx, cur)
		duration := time.Since(start)

		if p.observer != nil {
			p.observer.NotifyStage(stage.Name(), duration, err)
		}
		if err != nil {
			// Do not abort pipeline; surface the error and continue.
			// Optionally break here to short-circuit.
			log.Printf("pipeline: stage %q failed for event %s: %v", stage.Name(), cur.ID, err)
		}
	}
	return cur, err
}

// ==== Observer (Metrics / Diagnostics) =============================================

// Observer receives notifications about pipeline activity.
type Observer interface {
	Notify(ev SocialEvent, stageErr error)
	NotifyStage(stageName string, dur time.Duration, stageErr error)
}

// kafkaObserver publishes pipeline telemetry to a Kafka topic.
// It is safe for concurrent use.
type kafkaObserver struct {
	w *kafka.Writer
}

func NewKafkaObserver(brokers []string, topic string) (Observer, error) {
	if len(brokers) == 0 {
		return nil, errors.New("kafka observer: brokers must not be empty")
	}
	w := kafka.NewWriter(kafka.WriterConfig{
		Brokers:          brokers,
		Topic:            topic,
		Balancer:         &kafka.LeastBytes{},
		AllowAutoTopicCreation: true,
		BatchTimeout:     500 * time.Millisecond,
		RequiredAcks:     kafka.RequireAll,
	})
	return &kafkaObserver{w: w}, nil
}

func (k *kafkaObserver) Notify(ev SocialEvent, stageErr error) {
	payload, _ := json.Marshal(struct {
		Type  string       `json:"type"`
		Event SocialEvent  `json:"event"`
		Error string       `json:"error,omitempty"`
	}{
		Type:  "event_processed",
		Event: ev,
		Error: errString(stageErr),
	})

	k.emit(payload)
}

func (k *kafkaObserver) NotifyStage(stageName string, dur time.Duration, stageErr error) {
	payload, _ := json.Marshal(struct {
		Type      string  `json:"type"`
		Stage     string  `json:"stage"`
		Duration  float64 `json:"ms"`
		Error     string  `json:"error,omitempty"`
		Timestamp int64   `json:"ts"`
	}{
		Type:      "stage_metrics",
		Stage:     stageName,
		Duration:  float64(dur.Milliseconds()),
		Error:     errString(stageErr),
		Timestamp: time.Now().UnixMilli(),
	})
	k.emit(payload)
}

func (k *kafkaObserver) emit(msg []byte) {
	// Async fire-and-forget; drop on error
	_ = k.w.WriteMessages(context.Background(), kafka.Message{
		Key:   nil,
		Value: msg,
		Time:  time.Now(),
	})
}

func errString(err error) string {
	if err == nil {
		return ""
	}
	return err.Error()
}

// ==== Built-in Processor Implementations ===========================================

// LanguageDetector infers the language of the payload using a simple heuristic
// or a remote ML service (depending on config).
type LanguageDetector struct {
	name     string
	useMLAPI bool
	apiURL   string
	timeout  time.Duration
}

func NewLanguageDetector(cfg map[string]any) (Processor, error) {
	p := &LanguageDetector{
		name:    "lang_detect",
		timeout: 150 * time.Millisecond,
	}

	if v, ok := cfg["name"].(string); ok && v != "" {
		p.name = v
	}
	if v, ok := cfg["timeout"].(string); ok {
		if d, err := time.ParseDuration(v); err == nil {
			p.timeout = d
		}
	}
	if url, ok := cfg["endpoint"].(string); ok && url != "" {
		p.useMLAPI = true
		p.apiURL = url
	}
	return p, nil
}

func (ld *LanguageDetector) Name() string { return ld.name }

func (ld *LanguageDetector) Process(ctx context.Context, ev SocialEvent) (SocialEvent, error) {
	ctx, cancel := context.WithTimeout(ctx, ld.timeout)
	defer cancel()

	if ld.useMLAPI {
		// Simulate remote call. Replace with actual HTTP/gRPC client.
		select {
		case <-ctx.Done():
			return ev, ctx.Err()
		case <-time.After(60 * time.Millisecond):
			// Pretend we obtained a prediction.
		}
		ev.Language = "en" // example result
		return ev, nil
	}

	// Fallback heuristic: inspect unicode ranges or simple word list.
	lower := strings.ToLower(ev.Payload)
	switch {
	case strings.Contains(lower, "the"):
		ev.Language = "en"
	case strings.Contains(lower, "le") || strings.Contains(lower, "la"):
		ev.Language = "fr"
	default:
		ev.Language = "unknown"
	}
	return ev, nil
}

// SentimentAnalyzer calls a sentiment model over gRPC; falls back to lexicon.
type SentimentAnalyzer struct {
	name      string
	grpcAddr  string
	timeout   time.Duration
	threshold float64 // classification neutrality threshold
}

func NewSentimentAnalyzer(cfg map[string]any) (Processor, error) {
	s := &SentimentAnalyzer{
		name:      "sentiment",
		grpcAddr:  "sentiment-svc:50051",
		timeout:   250 * time.Millisecond,
		threshold: 0.05,
	}
	if addr, ok := cfg["endpoint"].(string); ok {
		s.grpcAddr = addr
	}
	if v, ok := cfg["timeout"].(string); ok {
		if d, err := time.ParseDuration(v); err == nil {
			s.timeout = d
		}
	}
	return s, nil
}

func (sa *SentimentAnalyzer) Name() string { return sa.name }

func (sa *SentimentAnalyzer) Process(ctx context.Context, ev SocialEvent) (SocialEvent, error) {
	ctx, cancel := context.WithTimeout(ctx, sa.timeout)
	defer cancel()

	// TODO: replace with real gRPC call
	select {
	case <-ctx.Done():
		return ev, ctx.Err()
	case <-time.After(80 * time.Millisecond):
	}

	// Dummy rule-based sentiment score
	lower := strings.ToLower(ev.Payload)
	switch {
	case strings.Contains(lower, "love") || strings.Contains(lower, "great"):
		ev.Sentiment = 0.8
	case strings.Contains(lower, "hate") || strings.Contains(lower, "terrible"):
		ev.Sentiment = -0.7
	default:
		ev.Sentiment = 0.0
	}
	return ev, nil
}

// ToxicityClassifier labels toxic content; demonstrates offline fallback.
type ToxicityClassifier struct {
	name        string
	modelLoaded bool
	mutex       sync.RWMutex
}

func NewToxicityClassifier(cfg map[string]any) (Processor, error) {
	return &ToxicityClassifier{name: "toxicity"}, nil
}

func (tc *ToxicityClassifier) Name() string { return tc.name }

func (tc *ToxicityClassifier) Process(ctx context.Context, ev SocialEvent) (SocialEvent, error) {
	tc.ensureModelLoaded()

	// Toy heuristic
	lower := strings.ToLower(ev.Payload)
	if strings.Contains(lower, "idiot") || strings.Contains(lower, "stupid") {
		ev.Toxicity = 0.9
	} else {
		ev.Toxicity = 0.1
	}
	return ev, nil
}

// ensureModelLoaded lazily loads a local model weights file.
func (tc *ToxicityClassifier) ensureModelLoaded() {
	tc.mutex.RLock()
	if tc.modelLoaded {
		tc.mutex.RUnlock()
		return
	}
	tc.mutex.RUnlock()

	tc.mutex.Lock()
	defer tc.mutex.Unlock()
	if tc.modelLoaded {
		return
	}

	// Simulate I/O
	time.Sleep(20 * time.Millisecond)
	tc.modelLoaded = true
}

// ==== Processor Factory Registry ====================================================

// processorRegistry maps a 'type' token to a factory function.
var processorRegistry = map[string]func(map[string]any) (Processor, error){
	"language":  NewLanguageDetector,
	"sentiment": NewSentimentAnalyzer,
	"toxicity":  NewToxicityClassifier,
}

// BuildProcessors constructs pipeline processors from a JSON/YAML-decoded slice
// of config objects. Unknown processor types return an error.
func BuildProcessors(cfgs []map[string]any) ([]Processor, error) {
	var stages []Processor
	for i, cfg := range cfgs {
		typ, ok := cfg["type"].(string)
		if !ok {
			return nil, fmt.Errorf("pipeline config index %d: missing 'type'", i)
		}
		factory, ok := processorRegistry[typ]
		if !ok {
			return nil, fmt.Errorf("pipeline config index %d: unknown type %q", i, typ)
		}
		stage, err := factory(cfg)
		if err != nil {
			return nil, fmt.Errorf("pipeline config index %d (%s): %w", i, typ, err)
		}
		stages = append(stages, stage)
	}
	return stages, nil
}

// ==== Example Runner (for tests / demos) ============================================

// This function wires up the pipeline with config read from environment variables
// and runs it against a test stream. It demonstrates idiomatic usage while
// keeping the public API clean for production callers.
func ExampleRun() {
	ctx, cancel := context.WithCancel(context.Background())
	defer cancel()

	// 1. Build processors from static configuration (could be from config file).
	procCfg := []map[string]any{
		{"type": "language"},
		{"type": "sentiment"},
		{"type": "toxicity"},
	}
	stages, err := BuildProcessors(procCfg)
	if err != nil {
		log.Fatalf("config error: %v", err)
	}

	// 2. Optional: set up Kafka observer if KAFKA_BROKERS env var is defined.
	var obs Observer
	if brokers := os.Getenv("KAFKA_BROKERS"); brokers != "" {
		list := strings.Split(brokers, ",")
		obs, err = NewKafkaObserver(list, "echopulse.pipeline.metrics")
		if err != nil {
			log.Printf("warning: disabling kafka observer: %v", err)
		}
	}

	pl := NewPipeline(stages, obs)

	// 3. Create a dummy source channel.
	src := make(chan SocialEvent)
	go func() {
		defer close(src)
		for i := 0; i < 3; i++ {
			src <- SocialEvent{
				ID:        fmt.Sprintf("ev-%d", i),
				UserID:    "u123",
				Timestamp: time.Now(),
				Channel:   "#general",
				Payload:   []string{"I love this!", "You are an idiot!", "Just okay."}[i],
				Metadata:  map[string]string{"demo": "true"},
			}
		}
	}()

	// 4. Run the pipeline.
	out, errC := pl.Run(ctx, src)

	// 5. Collect results.
	for ev := range out {
		b, _ := json.MarshalIndent(ev, "", "  ")
		fmt.Printf("%s\n", b)
	}

	// Check for fatal pipeline error.
	if err := <-errC; err != nil {
		log.Fatalf("pipeline terminated: %v", err)
	}
}
```