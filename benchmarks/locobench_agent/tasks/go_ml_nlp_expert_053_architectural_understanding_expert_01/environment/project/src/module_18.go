```go
// File: src/module_18.go
//
// Package processor contains high-throughput, pluggable NLP pipelines that fan-out from the
// Social-Event bus.  This module focuses on real-time toxicity classification and demonstrates
// how EchoPulse composes the Observer, Strategy and Pipeline patterns while embracing Go’s
// powerful concurrency primitives.
package processor

import (
	"bufio"
	"context"
	"errors"
	"log"
	"os"
	"os/signal"
	"strings"
	"sync"
	"syscall"
	"time"

	"github.com/segmentio/kafka-go"
	"github.com/prometheus/client_golang/prometheus"
	"github.com/prometheus/client_golang/prometheus/promauto"
	"golang.org/x/sync/errgroup"
)

// -----------------------------------------------------------------------------------------
// DOMAIN TYPES -----------------------------------------------------------------------------
// -----------------------------------------------------------------------------------------

// SocialEvent is the canonical message shape on the EchoPulse event bus.
// In the production code-base this lives in a shared `domain` package, re-defined
// here for standalone compilation.
type SocialEvent struct {
	ID        string            `json:"id"`
	UserID    string            `json:"user_id"`
	Timestamp time.Time         `json:"ts"`
	Channel   string            `json:"channel"` // e.g. #general, @streamer, /voice-room/42
	Payload   string            `json:"payload"` // raw textual content
	Meta      map[string]string `json:"meta"`    // arbitrary kv pairs (e.g. language hints)
}

// ModerationEvent is emitted whenever a SocialEvent is deemed toxic/unsafe.
// It is consumed by downstream moderation bots or dashboards.
type ModerationEvent struct {
	EventID      string    `json:"event_id"`
	UserID       string    `json:"user_id"`
	Channel      string    `json:"channel"`
	ToxicityScore float64   `json:"toxicity_score"`
	IsToxic      bool      `json:"is_toxic"`
	CreatedAt    time.Time `json:"created_at"`
	Reason       string    `json:"reason"`
}

// -----------------------------------------------------------------------------------------
// STRATEGY PATTERN: Toxicity Classifiers ---------------------------------------------------
// -----------------------------------------------------------------------------------------

// ClassifierStrategy encapsulates an arbitrary NLP model or heuristic that can
// assign a toxicity score to a SocialEvent.
type ClassifierStrategy interface {
	// Name returns a human-friendly identifier, used for metrics and logging.
	Name() string
	// Classify returns a score within [0,1] along with a binary toxic flag.
	Classify(ctx context.Context, evt SocialEvent) (score float64, isToxic bool, err error)
}

// RuleBasedClassifier is a fast, deterministic strategy that flags events
// containing words from a configurable deny-list.
type RuleBasedClassifier struct {
	denyList map[string]struct{}
	threshold float64
}

// NewRuleBasedClassifier builds a RuleBasedClassifier from a newline-delimited
// file containing disallowed words/phrases.  If path == "", an embedded default
// list is used.
func NewRuleBasedClassifier(path string, threshold float64) (*RuleBasedClassifier, error) {
	var (
		deny = make(map[string]struct{})
		err  error
	)
	load := func(r *bufio.Scanner) {
		for r.Scan() {
			line := strings.TrimSpace(r.Text())
			if line != "" && !strings.HasPrefix(line, "#") {
				deny[strings.ToLower(line)] = struct{}{}
			}
		}
	}

	if path == "" {
		// Built-in minimal list.
		defaultWords := []string{"idiot", "stupid", "moron"}
		for _, w := range defaultWords {
			deny[w] = struct{}{}
		}
	} else {
		f, e := os.Open(path)
		if e != nil {
			return nil, e
		}
		defer f.Close()
		load(bufio.NewScanner(f))
	}

	return &RuleBasedClassifier{denyList: deny, threshold: threshold}, err
}

// Name implements ClassifierStrategy.
func (r *RuleBasedClassifier) Name() string { return "rule_based_v1" }

// Classify implements ClassifierStrategy.
func (r *RuleBasedClassifier) Classify(_ context.Context, evt SocialEvent) (float64, bool, error) {
	// Simple heuristic: toxicity score = (#denyWords)/(totalWords).
	if evt.Payload == "" {
		return 0, false, errors.New("payload empty")
	}
	words := strings.Fields(strings.ToLower(evt.Payload))
	if len(words) == 0 {
		return 0, false, errors.New("payload contained no tokenizable words")
	}

	var hits int
	for _, w := range words {
		if _, ok := r.denyList[w]; ok {
			hits++
		}
	}

	score := float64(hits) / float64(len(words))
	return score, score >= r.threshold, nil
}

// -----------------------------------------------------------------------------------------
// KAFKA OBSERVER: Consumer & Producer ------------------------------------------------------
// -----------------------------------------------------------------------------------------

// KafkaConfig bundles connection details for both consumer & producer.
type KafkaConfig struct {
	Brokers     []string
	GroupID     string
	ConsumeTopic string
	ProduceTopic string
}

// NewConsumer returns a configured Kafka reader.
func NewConsumer(cfg KafkaConfig) *kafka.Reader {
	return kafka.NewReader(kafka.ReaderConfig{
		Brokers: cfg.Brokers,
		GroupID: cfg.GroupID,
		Topic:   cfg.ConsumeTopic,
		// Tune for high throughput / low latency
		MinBytes: 10e3, // 10KB
		MaxBytes: 10e6, // 10MB
	})
}

// NewProducer returns a Kafka writer for moderation events.
func NewProducer(cfg KafkaConfig) *kafka.Writer {
	return &kafka.Writer{
		Addr:         kafka.TCP(cfg.Brokers...),
		Topic:        cfg.ProduceTopic,
		Balancer:     &kafka.LeastBytes{},
		RequiredAcks: kafka.RequireAll,
		Async:        false,
	}
}

// -----------------------------------------------------------------------------------------
// METRICS ---------------------------------------------------------------------------------
// -----------------------------------------------------------------------------------------

var (
	eventsConsumed = promauto.NewCounterVec(prometheus.CounterOpts{
		Name: "echopulse_toxicity_events_consumed_total",
		Help: "Total number of social events consumed by toxicity service.",
	}, []string{"channel"})

	eventsProduced = promauto.NewCounterVec(prometheus.CounterOpts{
		Name: "echopulse_toxicity_events_produced_total",
		Help: "Total number of moderation events produced by toxicity service.",
	}, []string{"channel", "toxic"})

	classifierErrors = promauto.NewCounterVec(prometheus.CounterOpts{
		Name: "echopulse_toxicity_classifier_errors_total",
		Help: "Total classification errors by strategy.",
	}, []string{"strategy"})
)

// -----------------------------------------------------------------------------------------
// PIPELINE RUNNER -------------------------------------------------------------------------
// -----------------------------------------------------------------------------------------

// ToxicityService wires together a Kafka consumer, a producer, a classifier
// strategy, and a worker-pool to perform near-real-time moderation scoring.
type ToxicityService struct {
	cfg        KafkaConfig
	consumer   *kafka.Reader
	producer   *kafka.Writer
	classifier ClassifierStrategy
	workers    int
}

// NewToxicityService is the constructor.
func NewToxicityService(cfg KafkaConfig, classifier ClassifierStrategy, workers int) *ToxicityService {
	return &ToxicityService{
		cfg:        cfg,
		consumer:   NewConsumer(cfg),
		producer:   NewProducer(cfg),
		classifier: classifier,
		workers:    workers,
	}
}

// Run blocks until ctx is canceled or fatal error occurs.
func (s *ToxicityService) Run(ctx context.Context) error {
	g, ctx := errgroup.WithContext(ctx)

	// Fan-out worker goroutines reading from shared consumer.
	for i := 0; i < s.workers; i++ {
		g.Go(func() error {
			for {
				m, err := s.consumer.FetchMessage(ctx)
				if err != nil {
					// context canceled?
					if errors.Is(err, context.Canceled) {
						return nil
					}
					return err
				}

				var evt SocialEvent
				if err := jsonUnmarshal(m.Value, &evt); err != nil {
					log.Printf("WARN: invalid payload: %v", err)
					// commit offset anyway to skip bad message.
					_ = s.consumer.CommitMessages(ctx, m)
					continue
				}

				eventsConsumed.WithLabelValues(evt.Channel).Inc()
				score, toxic, err := s.classifier.Classify(ctx, evt)
				if err != nil {
					classifierErrors.WithLabelValues(s.classifier.Name()).Inc()
					log.Printf("ERROR: classification failed: %v", err)
					// Do NOT commit offset; we may want to retry later
					continue
				}

				mod := ModerationEvent{
					EventID:       evt.ID,
					UserID:        evt.UserID,
					Channel:       evt.Channel,
					ToxicityScore: score,
					IsToxic:       toxic,
					CreatedAt:     time.Now().UTC(),
					Reason:        s.classifier.Name(),
				}

				if err := s.publish(ctx, mod); err != nil {
					log.Printf("ERROR: failed to publish moderation event: %v", err)
					// do NOT commit offset to allow retry
					continue
				}

				eventsProduced.WithLabelValues(evt.Channel, boolToString(toxic)).Inc()
				_ = s.consumer.CommitMessages(ctx, m)
			}
		})
	}

	return g.Wait()
}

// publish sends a ModerationEvent to the Kafka producer with simple
// retry/backoff logic to handle transient network partitions.
func (s *ToxicityService) publish(ctx context.Context, mod ModerationEvent) error {
	const (
		maxRetries = 5
		baseDelay  = 100 * time.Millisecond
	)

	payload, err := jsonMarshal(mod)
	if err != nil {
		return err
	}

	var attempt int
	for {
		err = s.producer.WriteMessages(ctx, kafka.Message{
			Key:   []byte(mod.EventID),
			Value: payload,
			Time:  time.Now(),
		})
		if err == nil {
			return nil
		}

		if attempt >= maxRetries {
			return err
		}
		attempt++
		sleep := baseDelay * time.Duration(1<<attempt)
		select {
		case <-time.After(sleep):
		case <-ctx.Done():
			return ctx.Err()
		}
	}
}

// -----------------------------------------------------------------------------------------
// BOOTSTRAP -------------------------------------------------------------------------------
// -----------------------------------------------------------------------------------------

// jsonMarshal / jsonUnmarshal wrap the standard json calls behind an alias to
// facilitate future migration to a faster library (e.g. jsoniter) without
// touching call-sites.
func jsonMarshal(v any) ([]byte, error)   { return json.Marshal(v) }
func jsonUnmarshal(data []byte, v any) error { return json.Unmarshal(data, v) }

// boolToString helper.
func boolToString(b bool) string {
	if b {
		return "true"
	}
	return "false"
}

// Entrypoint wires signals, context, and launches the toxicity service.
// This file can be built as a stand-alone command via: go build -o toxicity cmd/toxicity/main.go
func main() {
	// Accept config from env or CLI flags in real code-base; simplified here.
	cfg := KafkaConfig{
		Brokers:      strings.Split(os.Getenv("KAFKA_BROKERS"), ","),
		GroupID:      "echopulse-toxicity-service",
		ConsumeTopic: "social.events.raw",
		ProduceTopic: "moderation.events",
	}

	classifier, err := NewRuleBasedClassifier(os.Getenv("DENYLIST_PATH"), 0.1)
	if err != nil {
		log.Fatalf("failed to init classifier: %v", err)
	}

	svc := NewToxicityService(cfg, classifier, 8)

	ctx, cancel := signal.NotifyContext(context.Background(), syscall.SIGINT, syscall.SIGTERM)
	defer cancel()

	if err := svc.Run(ctx); err != nil && !errors.Is(err, context.Canceled) {
		log.Fatalf("toxicity service exited: %v", err)
	}
}

// -----------------------------------------------------------------------------------------
// MISC IMPORTS ----------------------------------------------------------------------------
// -----------------------------------------------------------------------------------------

// The imports below are grouped here to centralize dependencies and avoid
// linter warnings for “blank” imports used exclusively for side effects.
import (
	"encoding/json"
)
```