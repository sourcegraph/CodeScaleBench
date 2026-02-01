package main

import (
	"bufio"
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"log"
	"math"
	"math/rand"
	"net/http"
	"os"
	"os/signal"
	"strings"
	"sync"
	"syscall"
	"time"

	"github.com/segmentio/kafka-go"

	"github.com/prometheus/client_golang/prometheus"
	"github.com/prometheus/client_golang/prometheus/promhttp"
)

// --------------------------------------------------------
// Domain Models
// --------------------------------------------------------

// SocialEvent represents the canonical event flowing through the EchoPulse
// backbone.  Down-stream services interpret or augment the event.
type SocialEvent struct {
	ID        string    `json:"id"`
	UserID    string    `json:"user_id"`
	Channel   string    `json:"channel"`
	Timestamp time.Time `json:"timestamp"`

	Text     string `json:"text,omitempty"`
	Emoji    string `json:"emoji,omitempty"`
	Reaction string `json:"reaction,omitempty"`
}

// HealthScoreEvent is emitted by this module after computing a real-time
// community health score for a single SocialEvent.
type HealthScoreEvent struct {
	SocialEventID  string             `json:"social_event_id"`
	Score          float64            `json:"score"`
	StrategyScores map[string]float64 `json:"strategy_scores"`
	GeneratedAt    time.Time          `json:"generated_at"`
}

// --------------------------------------------------------
// Config
// --------------------------------------------------------

type Config struct {
	KafkaBrokers      []string
	InputTopic        string
	OutputTopic       string
	GroupID           string
	MetricsHTTPAddr   string
	WorkerConcurrency int
	BatchSize         int
	CommitInterval    time.Duration
}

func loadConfig() Config {
	// In a real system we’d also support flags, config files, Vault, etc.
	brokers := strings.Split(getenvDefault("EP_KAFKA_BROKERS", "localhost:9092"), ",")
	return Config{
		KafkaBrokers:      brokers,
		InputTopic:        getenvDefault("EP_INPUT_TOPIC", "social_events"),
		OutputTopic:       getenvDefault("EP_OUTPUT_TOPIC", "health_scores"),
		GroupID:           getenvDefault("EP_GROUP_ID", "health_scoring_service"),
		MetricsHTTPAddr:   getenvDefault("EP_METRICS_ADDR", ":9090"),
		WorkerConcurrency: getenvIntDefault("EP_WORKERS", 8),
		BatchSize:         getenvIntDefault("EP_BATCH_SIZE", 1),
		CommitInterval:    getenvDurationDefault("EP_COMMIT_INTERVAL", 3*time.Second),
	}
}

// --------------------------------------------------------
// Strategy Registry
// --------------------------------------------------------

// ScoringStrategy is pluggable logic that converts a SocialEvent into a
// numerical score.  Higher scores imply healthier community interaction.
type ScoringStrategy interface {
	Name() string
	Score(ctx context.Context, e SocialEvent) (float64, error)
}

var (
	strategyRegistry = make(map[string]ScoringStrategy)
	registryMu       sync.RWMutex
)

func RegisterStrategy(s ScoringStrategy) {
	registryMu.Lock()
	defer registryMu.Unlock()
	if _, exists := strategyRegistry[s.Name()]; exists {
		log.Fatalf("strategy %q already registered", s.Name())
	}
	strategyRegistry[s.Name()] = s
}

func GetStrategies() []ScoringStrategy {
	registryMu.RLock()
	defer registryMu.RUnlock()
	strats := make([]ScoringStrategy, 0, len(strategyRegistry))
	for _, s := range strategyRegistry {
		strats = append(strats, s)
	}
	return strats
}

// --------------------------------------------------------
// Dummy Strategies (replace with ML models in production)
// --------------------------------------------------------

type SentimentStrategy struct{}

func (SentimentStrategy) Name() string { return "sentiment" }
func (SentimentStrategy) Score(_ context.Context, e SocialEvent) (float64, error) {
	if e.Text == "" {
		return 0.5, nil // neutral default
	}
	switch {
	case strings.Contains(strings.ToLower(e.Text), "love"):
		return 0.9, nil
	case strings.Contains(strings.ToLower(e.Text), "hate"):
		return 0.1, nil
	default:
		return 0.5 + rand.Float64()*0.1 - 0.05, nil
	}
}

type ToxicityStrategy struct{}

func (ToxicityStrategy) Name() string { return "toxicity" }
func (ToxicityStrategy) Score(_ context.Context, e SocialEvent) (float64, error) {
	// Lower score => less toxic
	if e.Text == "" {
		return 0.9, nil
	}
	switch {
	case strings.Contains(strings.ToLower(e.Text), "idiot"):
		return 0.2, nil
	case strings.Contains(strings.ToLower(e.Text), "kill"):
		return 0.1, nil
	default:
		return 0.8 + rand.Float64()*0.2 - 0.1, nil
	}
}

// --------------------------------------------------------
// Prometheus Metrics
// --------------------------------------------------------

var (
	processedEvents = prometheus.NewCounter(
		prometheus.CounterOpts{
			Name: "echopulse_health_processed_events_total",
			Help: "Total number of SocialEvents processed by the health scoring service.",
		},
	)

	strategyLatency = prometheus.NewHistogramVec(
		prometheus.HistogramOpts{
			Name:    "echopulse_health_strategy_latency_seconds",
			Help:    "Latency distribution for each scoring strategy.",
			Buckets: prometheus.DefBuckets,
		},
		[]string{"strategy"},
	)

	aggregateLatency = prometheus.NewHistogram(
		prometheus.HistogramOpts{
			Name:    "echopulse_health_aggregate_latency_seconds",
			Help:    "Latency distribution for computing the aggregated health score.",
			Buckets: prometheus.DefBuckets,
		},
	)
)

func init() {
	// Register builtin strategies
	RegisterStrategy(SentimentStrategy{})
	RegisterStrategy(ToxicityStrategy{})

	// Register metrics
	prometheus.MustRegister(processedEvents, strategyLatency, aggregateLatency)
}

// --------------------------------------------------------
// Aggregator
// --------------------------------------------------------

type Aggregator struct {
	cfg        Config
	strategies []ScoringStrategy

	reader *kafka.Reader
	writer *kafka.Writer
}

// NewAggregator composes all required sub-systems for the health scoring loop.
func NewAggregator(cfg Config) *Aggregator {
	reader := kafka.NewReader(kafka.ReaderConfig{
		Brokers:        cfg.KafkaBrokers,
		GroupID:        cfg.GroupID,
		Topic:          cfg.InputTopic,
		MinBytes:       1e4, // 10KB
		MaxBytes:       10e6,
		CommitInterval: cfg.CommitInterval, // explicit commits below
	})
	writer := &kafka.Writer{
		Addr:         kafka.TCP(cfg.KafkaBrokers...),
		Topic:        cfg.OutputTopic,
		RequiredAcks: kafka.RequireAll,
		Balancer:     &kafka.Hash{},
	}

	return &Aggregator{
		cfg:        cfg,
		strategies: GetStrategies(),
		reader:     reader,
		writer:     writer,
	}
}

func (a *Aggregator) Start(ctx context.Context) error {
	log.Printf("[aggregator] launching with %d worker(s)", a.cfg.WorkerConcurrency)
	wg := &sync.WaitGroup{}
	ctx, cancel := context.WithCancel(ctx)

	// Fan-out workers
	for i := 0; i < a.cfg.WorkerConcurrency; i++ {
		wg.Add(1)
		go func(id int) {
			defer wg.Done()
			a.workerLoop(ctx, id)
		}(i)
	}

	// Block until context cancelled
	<-ctx.Done()
	log.Println("[aggregator] shutting down workers…")
	cancel()
	wg.Wait()

	if err := a.reader.Close(); err != nil {
		return fmt.Errorf("close reader: %w", err)
	}
	if err := a.writer.Close(); err != nil {
		return fmt.Errorf("close writer: %w", err)
	}
	return nil
}

func (a *Aggregator) workerLoop(ctx context.Context, workerID int) {
	for {
		select {
		case <-ctx.Done():
			return
		default:
		}

		msg, err := a.reader.FetchMessage(ctx)
		if err != nil {
			if errors.Is(err, context.Canceled) {
				return
			}
			log.Printf("[worker %d] fetch error: %v", workerID, err)
			continue
		}

		startAggregate := time.Now()
		var se SocialEvent
		if err := json.Unmarshal(msg.Value, &se); err != nil {
			log.Printf("[worker %d] unmarshal error: %v", workerID, err)
			_ = a.reader.CommitMessages(ctx, msg) // swallow error
			continue
		}

		healthEvent, err := a.scoreEvent(ctx, se)
		if err != nil {
			log.Printf("[worker %d] scoring error: %v", workerID, err)
			_ = a.reader.CommitMessages(ctx, msg) // swallow error
			continue
		}

		aggregateLatency.Observe(time.Since(startAggregate).Seconds())

		if err := a.publishHealth(ctx, healthEvent); err != nil {
			log.Printf("[worker %d] publish error: %v", workerID, err)
			// do not commit so we can retry
			continue
		}

		if err := a.reader.CommitMessages(ctx, msg); err != nil {
			log.Printf("[worker %d] commit error: %v", workerID, err)
		}
		processedEvents.Inc()
	}
}

func (a *Aggregator) scoreEvent(ctx context.Context, se SocialEvent) (HealthScoreEvent, error) {
	var wg sync.WaitGroup
	scoreMap := sync.Map{}
	errChan := make(chan error, len(a.strategies))

	for _, strat := range a.strategies {
		wg.Add(1)
		go func(s ScoringStrategy) {
			defer wg.Done()
			start := time.Now()
			score, err := s.Score(ctx, se)
			if err != nil {
				errChan <- fmt.Errorf("%s: %w", s.Name(), err)
				return
			}
			strategyLatency.WithLabelValues(s.Name()).Observe(time.Since(start).Seconds())
			scoreMap.Store(s.Name(), score)
		}(strat)
	}

	wg.Wait()
	close(errChan)
	for err := range errChan {
		return HealthScoreEvent{}, err
	}

	combined := 0.0
	scoreMap.Range(func(key, value interface{}) bool {
		combined += value.(float64)
		return true
	})
	combined = combined / float64(len(a.strategies)) // mean

	// clamp between 0 and 1
	combined = math.Max(0, math.Min(1, combined))

	m := make(map[string]float64)
	scoreMap.Range(func(k, v interface{}) bool {
		m[k.(string)] = v.(float64)
		return true
	})

	return HealthScoreEvent{
		SocialEventID:  se.ID,
		Score:          combined,
		StrategyScores: m,
		GeneratedAt:    time.Now(),
	}, nil
}

func (a *Aggregator) publishHealth(ctx context.Context, h HealthScoreEvent) error {
	b, err := json.Marshal(h)
	if err != nil {
		return fmt.Errorf("marshal health event: %w", err)
	}
	msg := kafka.Message{
		Key:   []byte(h.SocialEventID),
		Value: b,
		Time:  time.Now(),
	}
	return a.writer.WriteMessages(ctx, msg)
}

// --------------------------------------------------------
// Main
// --------------------------------------------------------

func main() {
	cfg := loadConfig()

	// Spawn metrics server
	go func() {
		http.Handle("/metrics", promhttp.Handler())
		log.Printf("[metrics] listening on %s", cfg.MetricsHTTPAddr)
		if err := http.ListenAndServe(cfg.MetricsHTTPAddr, nil); err != nil {
			log.Fatalf("[metrics] %v", err)
		}
	}()

	aggregator := NewAggregator(cfg)

	ctx, stop := signal.NotifyContext(context.Background(), os.Interrupt, syscall.SIGTERM)
	defer stop()

	if err := aggregator.Start(ctx); err != nil {
		log.Fatalf("[main] aggregator stopped with error: %v", err)
	}

	log.Println("[main] graceful shutdown complete")
}

// --------------------------------------------------------
// Helpers
// --------------------------------------------------------

func getenvDefault(key, def string) string {
	if v := strings.TrimSpace(os.Getenv(key)); v != "" {
		return v
	}
	return def
}

func getenvIntDefault(key string, def int) int {
	if v := strings.TrimSpace(os.Getenv(key)); v != "" {
		if i, err := parseInt(v); err == nil {
			return i
		}
	}
	return def
}

func getenvDurationDefault(key string, def time.Duration) time.Duration {
	if v := strings.TrimSpace(os.Getenv(key)); v != "" {
		if d, err := time.ParseDuration(v); err == nil {
			return d
		}
	}
	return def
}

func parseInt(s string) (int, error) {
	r := bufio.NewReader(strings.NewReader(s))
	var x int
	_, err := fmt.Fscan(r, &x)
	return x, err
}