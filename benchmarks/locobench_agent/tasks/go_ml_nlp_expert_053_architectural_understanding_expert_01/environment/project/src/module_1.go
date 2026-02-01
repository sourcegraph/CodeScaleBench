```go
// File: src/module_1.go
//
// EchoPulse – Real-Time Social Signal Processing Platform
//
// This module implements the core “bus connector + observer fan-out” layer
// used by most downstream services.  It demonstrates the Observer, Factory
// and Strategy patterns while hiding Kafka/NATS specifics behind a clean
// EventBus abstraction.  Down-stream components simply implement the
// Observer interface and register themselves with a Dispatcher instance.

package echopulse

import (
	"bufio"
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"log"
	"net"
	"sync"
	"time"

	kafka "github.com/segmentio/kafka-go"
	"github.com/sony/sonyflake"
)

// ---------------------------------------------------------------------------
// Canonical domain types
// ---------------------------------------------------------------------------

// SocialEvent models any user-generated artifact ingested by EchoPulse.
type SocialEvent struct {
	ID        string                 `json:"id"`         // Stable, unique ULID.
	Type      EventType              `json:"type"`       // Enum describing the event variety (TEXT, EMOJI, AUDIO …).
	UserID    string                 `json:"user_id"`    // Originating user.
	Timestamp time.Time              `json:"timestamp"`  // Event creation time (UTC).
	Content   string                 `json:"content"`    // Canonicalized payload (UTF-8 text, emoji tokens, ASR transcript …).
	Metadata  map[string]interface{} `json:"metadata"`   // Optional, schemaless KV.
}

// EventType enumerates supported social artifact categories.
type EventType string

const (
	TypeText  EventType = "TEXT"
	TypeEmoji EventType = "EMOJI"
	TypeAudio EventType = "AUDIO"
)

// ---------------------------------------------------------------------------
// Event Bus – abstraction over Kafka / NATS JetStream / etc.
// ---------------------------------------------------------------------------

// EventBus hides the underlying message broker so unit tests can stub it out.
type EventBus interface {
	Publish(ctx context.Context, topic string, evt SocialEvent) error
	Subscribe(ctx context.Context, topic string) (<-chan SocialEvent, error)
	Close() error
}

// NewEventBus is a tiny factory that can spin up concrete bus implementations
// from a DSN/protocol string (e.g.  kafka://localhost:9092, nats://…).  For
// the sake of brevity this sample only wires in Kafka.
func NewEventBus(dsn string) (EventBus, error) {
	switch {
	case dsn == "" || dsn[:8] == "kafka://":
		return newKafkaBus(dsn)
	default:
		return nil, fmt.Errorf("unsupported bus: %s", dsn)
	}
}

// ---------------------------------------------------------------------------
// Dispatcher – the “Subject” in the Observer pattern
// ---------------------------------------------------------------------------

// Observer is implemented by any service that needs to consume SocialEvents.
type Observer interface {
	HandleEvent(ctx context.Context, evt SocialEvent) error
	Name() string
}

// Dispatcher consumes from EventBus and fans out to registered observers.
// It isolates each observer in its own goroutine so that slow handlers do not
// block event ingestion.
type Dispatcher struct {
	bus       EventBus
	topic     string
	observers []Observer

	errCh     chan error
	wg        sync.WaitGroup
	cancelMux sync.Once
	cancel    context.CancelFunc
}

// NewDispatcher wires a new dispatcher for a given topic.
func NewDispatcher(bus EventBus, topic string) *Dispatcher {
	return &Dispatcher{
		bus:   bus,
		topic: topic,
		errCh: make(chan error, 32),
	}
}

// Register attaches an observer.  Can be called any time before Start.
func (d *Dispatcher) Register(obs Observer) {
	d.observers = append(d.observers, obs)
}

// Errors exposes async dispatch/handler errors.  Always drain this channel!
func (d *Dispatcher) Errors() <-chan error { return d.errCh }

// Start begins consuming the topic and routing events to observers.
func (d *Dispatcher) Start(parent context.Context) error {
	if len(d.observers) == 0 {
		return errors.New("dispatcher: must register at least one observer")
	}

	ctx, cancel := context.WithCancel(parent)
	d.cancel = cancel

	ch, err := d.bus.Subscribe(ctx, d.topic)
	if err != nil {
		return fmt.Errorf("dispatcher: subscribe: %w", err)
	}

	d.wg.Add(1)
	go d.loop(ctx, ch)
	return nil
}

// Stop cancels subscriptions and waits until goroutines exit.
func (d *Dispatcher) Stop() {
	d.cancelMux.Do(func() {
		if d.cancel != nil {
			d.cancel()
		}
		d.wg.Wait()
		close(d.errCh)
	})
}

func (d *Dispatcher) loop(ctx context.Context, in <-chan SocialEvent) {
	defer d.wg.Done()

	for {
		select {
		case <-ctx.Done():
			return
		case evt, ok := <-in:
			if !ok {
				return
			}
			for _, obs := range d.observers {
				obs := obs // capture
				d.wg.Add(1)
				go func() {
					defer d.wg.Done()
					if err := obs.HandleEvent(ctx, evt); err != nil {
						select {
						case d.errCh <- fmt.Errorf("%s: %w", obs.Name(), err):
						default: // channel full, drop to avoid blocking.
						}
					}
				}()
			}
		}
	}
}

// ---------------------------------------------------------------------------
// Concrete Observer example – Sentiment Analysis
// ---------------------------------------------------------------------------

// SentimentStrategy embodies a pluggable algorithm (Rule-based, Transformer,
// commercial API, etc.).  This demonstrates the Strategy pattern.
type SentimentStrategy interface {
	Analyze(text string) (score float64, err error) // Score ∈ [-1,1].
}

// NaiveBayesSentiment is a toy implementation.  Replace with ML model.
type NaiveBayesSentiment struct{}

func (NaiveBayesSentiment) Analyze(text string) (float64, error) {
	// Extremely naive sentiment heuristic.
	switch {
	case text == "":
		return 0.0, nil
	case containsAny(text, "😊", "👍", "❤️"):
		return 0.7, nil
	case containsAny(text, "😡", "👎", "💔", "toxic"):
		return -0.8, nil
	default:
		return 0.1, nil
	}
}

func containsAny(s string, tokens ...string) bool {
	for _, t := range tokens {
		if contains := (len(t) > 0 && (containsRune(s, []rune(t)[0]))); contains {
			return true
		}
	}
	return false
}

func containsRune(s string, r rune) bool {
	for _, c := range s {
		if c == r {
			return true
		}
	}
	return false
}

// SentimentAnalyzer consumes events, analyzes the text content and publishes
// an “enriched” event back onto the bus.
type SentimentAnalyzer struct {
	bus      EventBus
	strategy SentimentStrategy
	outTopic string
}

func NewSentimentAnalyzer(bus EventBus, strategy SentimentStrategy, outTopic string) *SentimentAnalyzer {
	return &SentimentAnalyzer{bus: bus, strategy: strategy, outTopic: outTopic}
}

func (s *SentimentAnalyzer) Name() string { return "SentimentAnalyzer" }

func (s *SentimentAnalyzer) HandleEvent(ctx context.Context, evt SocialEvent) error {
	score, err := s.strategy.Analyze(evt.Content)
	if err != nil {
		return fmt.Errorf("analyze: %w", err)
	}

	evt.Metadata = ensureMetadata(evt.Metadata)
	evt.Metadata["sentiment_score"] = score

	return s.bus.Publish(ctx, s.outTopic, evt)
}

func ensureMetadata(m map[string]interface{}) map[string]interface{} {
	if m == nil {
		return make(map[string]interface{})
	}
	return m
}

// ---------------------------------------------------------------------------
// Kafka EventBus implementation – backed by github.com/segmentio/kafka-go
// ---------------------------------------------------------------------------

type kafkaBus struct {
	producer *kafka.Writer
	// consumer is not stored directly to allow multiple topic subscriptions.
	brokers []string
}

func newKafkaBus(dsn string) (EventBus, error) {
	// Accept “kafka://host1:port,host2:port”.
	const prefix = "kafka://"
	if dsn == "" {
		dsn = "kafka://localhost:9092"
	}
	if len(dsn) < len(prefix) {
		return nil, fmt.Errorf("malformed kafka dsn: %s", dsn)
	}

	brokersCSV := dsn[len(prefix):]
	brokers := splitNonEmpty(brokersCSV, ",")

	return &kafkaBus{
		producer: &kafka.Writer{
			Addr:         kafka.TCP(brokers...),
			RequiredAcks: kafka.RequireOne,
			Async:        true,
			BatchTimeout: 10 * time.Millisecond,
		},
		brokers: brokers,
	}, nil
}

func (k *kafkaBus) Publish(ctx context.Context, topic string, evt SocialEvent) error {
	raw, err := json.Marshal(evt)
	if err != nil {
		return fmt.Errorf("marshal: %w", err)
	}

	msg := kafka.Message{
		Key:   []byte(evt.ID),
		Value: raw,
		Time:  evt.Timestamp,
	}

	msg.Topic = topic
	return k.producer.WriteMessages(ctx, msg)
}

func (k *kafkaBus) Subscribe(ctx context.Context, topic string) (<-chan SocialEvent, error) {
	r := kafka.NewReader(kafka.ReaderConfig{
		Brokers:  k.brokers,
		GroupID:  fmt.Sprintf("echopulse-%s", topic),
		Topic:    topic,
		MaxBytes: 10e6,
	})

	out := make(chan SocialEvent, 256)

	go func() {
		defer close(out)
		defer r.Close()

		for {
			m, err := r.FetchMessage(ctx)
			if err != nil {
				if errors.Is(err, context.Canceled) {
					return
				}
				log.Printf("kafka reader error: %v", err)
				continue
			}

			var evt SocialEvent
			if err := json.Unmarshal(m.Value, &evt); err != nil {
				log.Printf("unmarshal: %v", err)
				continue
			}
			select {
			case out <- evt:
			case <-ctx.Done():
				return
			}
		}
	}()

	return out, nil
}

func (k *kafkaBus) Close() error { return k.producer.Close() }

// ---------------------------------------------------------------------------
// Utilities
// ---------------------------------------------------------------------------

// ULID generator (monotonic, globally unique)
var flake = sonyflake.NewSonyflake(sonyflake.Settings{})

// NewEventID returns a sortable, k-ordered 64-bit ULID string.
func NewEventID() string {
	id, err := flake.NextID()
	if err != nil {
		panic(err) // should never happen; fail loud
	}
	return fmt.Sprintf("%016x", id)
}

func splitNonEmpty(s, sep string) []string {
	scanner := bufio.NewScanner(strings.NewReader(s))
	scanner.Split(func(data []byte, atEOF bool) (advance int, token []byte, err error) {
		for i := 0; i < len(data); i++ {
			if string(data[i]) == sep {
				return i + 1, data[:i], nil
			}
		}
		if atEOF && len(data) != 0 {
			return len(data), data, nil
		}
		return 0, nil, nil
	})

	var tokens []string
	for scanner.Scan() {
		tok := strings.TrimSpace(scanner.Text())
		if tok != "" {
			tokens = append(tokens, tok)
		}
	}
	return tokens
}

// Debug helper to ensure TCP connectivity before spinning a Reader/Writer.
// Not bulletproof but aids early failure detection.
func waitForTCP(target string, timeout time.Duration) error {
	dl := time.Now().Add(timeout)
	for time.Now().Before(dl) {
		conn, err := net.DialTimeout("tcp", target, 500*time.Millisecond)
		if err == nil {
			conn.Close()
			return nil
		}
		time.Sleep(500 * time.Millisecond)
	}
	return fmt.Errorf("timeout waiting for %s", target)
}
```