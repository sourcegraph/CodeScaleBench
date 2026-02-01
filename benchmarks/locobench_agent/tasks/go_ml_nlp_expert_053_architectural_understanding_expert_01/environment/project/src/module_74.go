```go
// File: src/module_74.go
//
// EchoPulse :: Real-Time Social Signal Processing Platform
//
// Module 74 – Toxicity Classification Micro-Pipeline
//
// The code in this file wires together a Kafka-backed event processor that
// consumes canonical SocialEvents, applies one (or many) classification
// strategies, and publishes enriched ClassificationEvents back to the event
// bus.  It showcases Observer / Strategy / Pipeline patterns while following
// Go production best-practices: context propagation, graceful shutdown,
// concurrency control, structured logging, metrics, and error handling.

package processor

import (
	"bufio"
	"context"
	"encoding/json"
	"errors"
	"math/rand"
	"net"
	"os"
	"os/signal"
	"strings"
	"sync"
	"syscall"
	"time"

	"github.com/segmentio/kafka-go"
	"go.uber.org/zap"
)

// -------------------------------------------------------------------------
// Canonical domain types
// -------------------------------------------------------------------------

// SocialEvent is the canonical ingest artefact used across EchoPulse.
type SocialEvent struct {
	ID        string            `json:"id"`
	UserID    string            `json:"user_id"`
	ChannelID string            `json:"channel_id"`
	Payload   string            `json:"payload"` // unified text representation
	Metadata  map[string]string `json:"metadata,omitempty"`
	Timestamp time.Time         `json:"timestamp"`
}

// ClassificationEvent is produced by analytic components downstream.
type ClassificationEvent struct {
	SocialEventID string            `json:"social_event_id"`
	Class         string            `json:"class"`
	Score         float64           `json:"score"` // confidence ∈ [0,1]
	Strategy      string            `json:"strategy"`
	Metadata      map[string]string `json:"metadata,omitempty"`
	Timestamp     time.Time         `json:"timestamp"`
}

// -------------------------------------------------------------------------
// Strategy pattern
// -------------------------------------------------------------------------

// ClassifierStrategy defines the behavioural contract for any classifier.
type ClassifierStrategy interface {
	// Name returns a short identifier (e.g. "toxicity_v1")
	Name() string
	// Classify blocks until the SocialEvent is classified or fails.
	Classify(ctx context.Context, ev SocialEvent) (ClassificationEvent, error)
}

// -------------------------------------------------------------------------
// Toxicity classifier (naïve keyword + model ensemble stub)
// -------------------------------------------------------------------------

// ToxicityStrategy is a demonstration classifier.
// In production this would wrap a model served over gRPC / REST.
type ToxicityStrategy struct {
	// trigram dictionary loaded at start-up
	toxicLexicon map[string]struct{}
	log          *zap.Logger
}

func NewToxicityStrategy(dictPath string, log *zap.Logger) (*ToxicityStrategy, error) {
	file, err := os.Open(dictPath)
	if err != nil {
		return nil, err
	}
	defer file.Close()

	lexicon := make(map[string]struct{})
	scanner := bufio.NewScanner(file)
	for scanner.Scan() {
		w := strings.TrimSpace(scanner.Text())
		if w != "" {
			lexicon[w] = struct{}{}
		}
	}
	if err := scanner.Err(); err != nil {
		return nil, err
	}

	return &ToxicityStrategy{
		toxicLexicon: lexicon,
		log:          log.Named("toxicity_strategy"),
	}, nil
}

func (s *ToxicityStrategy) Name() string { return "toxicity_v1" }

func (s *ToxicityStrategy) Classify(ctx context.Context, ev SocialEvent) (ClassificationEvent, error) {
	// A very naïve heuristic: count toxic words to compute score
	words := strings.Fields(strings.ToLower(ev.Payload))
	var toxicCount int
	for _, w := range words {
		if _, ok := s.toxicLexicon[w]; ok {
			toxicCount++
		}
	}

	// Simulate ensemble model jitter
	rand.Seed(time.Now().UnixNano())
	noise := rand.Float64() * 0.1

	score := float64(toxicCount)/float64(len(words)+1) + noise // normalize
	if score > 1 {
		score = 1
	}

	classification := "non_toxic"
	if score >= 0.5 {
		classification = "toxic"
	}

	return ClassificationEvent{
		SocialEventID: ev.ID,
		Class:         classification,
		Score:         score,
		Strategy:      s.Name(),
		Timestamp:     time.Now().UTC(),
	}, nil
}

// -------------------------------------------------------------------------
// Pipeline Orchestrator
// -------------------------------------------------------------------------

// ProcessorConfig encapsulates wiring parameters for Processor.
type ProcessorConfig struct {
	Brokers        []string
	GroupID        string
	SourceTopic    string
	SinkTopic      string
	Concurrency    int
	MaxBatchBytes  int
	Strategy       ClassifierStrategy
	Log            *zap.Logger
	CommitInterval time.Duration
}

// Processor consumes SocialEvents and publishes ClassificationEvents.
type Processor struct {
	cfg     ProcessorConfig
	reader  *kafka.Reader
	writer  *kafka.Writer
	log     *zap.Logger
	wg      sync.WaitGroup
	ctx     context.Context
	cancel  context.CancelFunc
	started bool
}

// NewProcessor is the factory constructor.
func NewProcessor(cfg ProcessorConfig) (*Processor, error) {
	if cfg.Strategy == nil {
		return nil, errors.New("processor: strategy must not be nil")
	}
	if cfg.Concurrency <= 0 {
		cfg.Concurrency = 4
	}
	if cfg.Log == nil {
		cfg.Log = zap.NewNop()
	}

	reader := kafka.NewReader(kafka.ReaderConfig{
		Brokers:        cfg.Brokers,
		GroupID:        cfg.GroupID,
		Topic:          cfg.SourceTopic,
		MinBytes:       1e3,  // 1KB
		MaxBytes:       10e6, // 10MB
		MaxWait:        250 * time.Millisecond,
		CommitInterval: cfg.CommitInterval,
	})
	reader.SetOffset(kafka.LastOffset) // catch-up from tail

	writer := &kafka.Writer{
		Addr:         kafka.TCP(cfg.Brokers...),
		Topic:        cfg.SinkTopic,
		Balancer:     &kafka.Hash{},
		RequiredAcks: kafka.RequireOne,
		Async:        true,
	}

	ctx, cancel := context.WithCancel(context.Background())

	return &Processor{
		cfg:    cfg,
		reader: reader,
		writer: writer,
		log:    cfg.Log.Named("processor"),
		ctx:    ctx,
		cancel: cancel,
	}, nil
}

// Start launches the worker pool and begins consuming messages.
func (p *Processor) Start() {
	if p.started {
		return
	}
	p.started = true

	p.log.Info("processor starting",
		zap.String("source_topic", p.cfg.SourceTopic),
		zap.String("sink_topic", p.cfg.SinkTopic),
		zap.Int("concurrency", p.cfg.Concurrency),
		zap.String("strategy", p.cfg.Strategy.Name()),
	)

	// fan-out worker pool
	for i := 0; i < p.cfg.Concurrency; i++ {
		p.wg.Add(1)
		go p.worker(i)
	}
}

// Stop flushes and terminates all goroutines gracefully.
func (p *Processor) Stop(ctx context.Context) error {
	if !p.started {
		return nil
	}
	p.cancel()
	done := make(chan struct{})

	go func() {
		defer close(done)
		p.wg.Wait()
	}()

	select {
	case <-ctx.Done():
		return ctx.Err()
	case <-done:
		// continue
	}

	if err := p.writer.Close(); err != nil {
		return err
	}
	if err := p.reader.Close(); err != nil {
		return err
	}

	p.log.Info("processor stopped")
	return nil
}

// worker runs in a tight loop consuming -> classify -> produce.
func (p *Processor) worker(id int) {
	defer p.wg.Done()
	log := p.log.With(zap.Int("worker_id", id))
	log.Info("worker up")

	for {
		select {
		case <-p.ctx.Done():
			log.Info("worker shutting down")
			return
		default:
		}

		m, err := p.reader.FetchMessage(p.ctx)
		if err != nil {
			// The Reader returns ctx.Err upon cancellation—noisy but expected
			if errors.Is(err, context.Canceled) {
				return
			}
			log.Warn("fetch message error", zap.Error(err))
			continue
		}

		var se SocialEvent
		if err := json.Unmarshal(m.Value, &se); err != nil {
			log.Error("unmarshal social event", zap.Error(err))
			_ = p.reader.CommitMessages(p.ctx, m) // commit poison pill to avoid retry loop
			continue
		}

		ce, err := p.cfg.Strategy.Classify(p.ctx, se)
		if err != nil {
			log.Error("classify error", zap.Error(err))
			continue
		}

		payload, _ := json.Marshal(ce)

		msg := kafka.Message{
			Key:   []byte(ce.SocialEventID),
			Value: payload,
			Time:  time.Now(),
		}

		// Asynchronous writer; handle error in completion.
		if err := p.writer.WriteMessages(p.ctx, msg); err != nil {
			log.Error("write message error", zap.Error(err))
			// Optionally retry or store in DLQ
		}

		if err := p.reader.CommitMessages(p.ctx, m); err != nil {
			log.Warn("commit offset error", zap.Error(err))
		}
	}
}

// -------------------------------------------------------------------------
// Bootstrap (optional) :: run as standalone binary
// -------------------------------------------------------------------------

// Main is separated to allow the file to compile as part of a larger repo
// without forcing inclusion in cmd/... packages.  The build tag ensures it
// is only included when desired.
//
//	//go:build module74main
//
// To run locally:
// $ go run -tags=module74main ./src/module_74.go -brokers localhost:9092
//

//go:build module74main
// +build module74main

package main

import (
	"flag"
	"time"

	"go.uber.org/zap"
)

func main() {
	var (
		broker       = flag.String("brokers", "localhost:9092", "comma-delimited list of brokers")
		group        = flag.String("group", "echopulse_toxicity", "consumer group id")
		sourceTopic  = flag.String("source", "social_events", "source topic")
		sinkTopic    = flag.String("sink", "classification_events", "sink topic")
		dictPath     = flag.String("dict", "./toxicity_lexicon.txt", "path to toxicity dictionary")
		concurrency  = flag.Int("concurrency", 8, "number of workers")
		commitMillis = flag.Int("commit_interval_ms", 500, "offset commit interval (ms)")
	)
	flag.Parse()

	log, _ := zap.NewProduction()
	defer log.Sync()

	strategy, err := NewToxicityStrategy(*dictPath, log)
	if err != nil {
		log.Fatal("failed to init strategy", zap.Error(err))
	}

	cfg := ProcessorConfig{
		Brokers:        strings.Split(*broker, ","),
		GroupID:        *group,
		SourceTopic:    *sourceTopic,
		SinkTopic:      *sinkTopic,
		Concurrency:    *concurrency,
		MaxBatchBytes:  10e6,
		Strategy:       strategy,
		Log:            log,
		CommitInterval: time.Duration(*commitMillis) * time.Millisecond,
	}

	processor, err := NewProcessor(cfg)
	if err != nil {
		log.Fatal("failed to create processor", zap.Error(err))
	}

	processor.Start()

	// Wait for SIGINT/SIGTERM
	sig := make(chan os.Signal, 2)
	signal.Notify(sig, syscall.SIGINT, syscall.SIGTERM)
	<-sig
	log.Info("shutdown signal received")

	ctx, cancel := context.WithTimeout(context.Background(), 30*time.Second)
	defer cancel()

	if err := processor.Stop(ctx); err != nil {
		log.Error("graceful stop failed", zap.Error(err))
	}
}

// -----------------------------------------------------------------------------
// Utility helpers
// -----------------------------------------------------------------------------

// isPortOpen checks if the network endpoint is reachable (used by health probes).
func isPortOpen(addr string, timeout time.Duration) bool {
	conn, err := net.DialTimeout("tcp", addr, timeout)
	if err != nil {
		return false
	}
	_ = conn.Close()
	return true
}
