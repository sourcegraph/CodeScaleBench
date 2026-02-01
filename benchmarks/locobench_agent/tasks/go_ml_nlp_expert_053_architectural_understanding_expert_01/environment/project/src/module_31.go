```go
// File: src/module_31.go
//
// Package pipeline implements a high-throughput feature-extraction stage
// that consumes canonical SocialEvents from NATS JetStream, enriches the
// events with NLP-derived features (sentiment score, emoji density, etc.),
// persists the results in the Feature Store, and publishes a downstream
// FeatureVector message for follow-up stages (e.g. stance detection,
// trend surfacing).  The component demonstrates idiomatic, production-
// quality Go with attention to observability, back-pressure handling,
// and graceful shutdown semantics.
package pipeline

import (
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"log"
	"runtime/debug"
	"strings"
	"sync"
	"time"

	"github.com/go-redis/redis/v8"         // Feature cache
	"github.com/google/uuid"               // Event correlation
	"github.com/jonreiter/govader"         // Sentiment analysis
	"github.com/nats-io/nats.go"           // Event bus
	"go.opentelemetry.io/otel"             // Tracing
	"go.opentelemetry.io/otel/attribute"   //
	"go.opentelemetry.io/otel/trace"       //
	"google.golang.org/grpc"               // Feature-store client transport
	pb "ml_nlp/proto/featurestore/v1"      // Feature-store protobuf stubs
)

// ----------------------------------------------------------------------------
// Domain Models
// ----------------------------------------------------------------------------

// SocialEvent represents the canonical event produced by the ingestion tier.
type SocialEvent struct {
	ID          string            `json:"id"`
	UserID      string            `json:"user_id"`
	ChannelID   string            `json:"channel_id"`
	Payload     string            `json:"payload"`      // Text, emoji, transcript
	CreatedAt   time.Time         `json:"created_at"`   // Original timestamp
	Metadata    map[string]string `json:"metadata"`     // Arbitrary k/v
	ContentType string            `json:"content_type"` // "text", "emoji", "voice"
}

// FeatureVector is the downstream message created by this module.
type FeatureVector struct {
	EventID        string            `json:"event_id"`
	UserID         string            `json:"user_id"`
	ChannelID      string            `json:"channel_id"`
	Sentiment      float64           `json:"sentiment"` // Normalized compound score
	EmojiDensity   float64           `json:"emoji_density"`
	WordCount      int               `json:"word_count"`
	Language       string            `json:"language"`
	GeneratedAt    time.Time         `json:"generated_at"`
	AdditionalMeta map[string]string `json:"additional_meta"`
}

// ----------------------------------------------------------------------------
// Configuration
// ----------------------------------------------------------------------------

// ExtractorConfig captures the dependencies and runtime knobs required by
// FeatureExtractorService.
type ExtractorConfig struct {
	NATSURL              string        // NATS connection string
	Subject              string        // NATS subject to subscribe to
	FeatureVectorSubject string        // NATS subject to publish FeatureVector
	ConsumerGroup        string        // JetStream durable consumer name
	RedisURL             string        // Optional Redis cache ("" disables cache)
	GRPCFeatureStoreURL  string        // Feature store endpoint (host:port)
	Concurrency          int           // Worker pool size
	Prefetch             int           // In-flight pull batch size
	AckWait              time.Duration // Max time given to process a message
}

// Validate sanity-checks the configuration.
func (c ExtractorConfig) Validate() error {
	switch {
	case c.NATSURL == "":
		return errors.New("NATSURL is required")
	case c.Subject == "":
		return errors.New("Subject is required")
	case c.FeatureVectorSubject == "":
		return errors.New("FeatureVectorSubject is required")
	case c.Concurrency <= 0:
		return errors.New("Concurrency must be > 0")
	case c.Prefetch <= 0 || c.Prefetch > 1024:
		return errors.New("Prefetch must be between 1 and 1024")
	case c.AckWait < 10*time.Second:
		return errors.New("AckWait too small")
	default:
		return nil
	}
}

// ----------------------------------------------------------------------------
// FeatureExtractorService
// ----------------------------------------------------------------------------

// FeatureExtractorService coordinates subscription, worker pool, NLP, and I/O.
type FeatureExtractorService struct {
	cfg       ExtractorConfig
	nc        *nats.Conn
	js        nats.JetStreamContext
	sub       *nats.Subscription
	redis     *redis.Client
	fsClient  pb.FeatureStoreServiceClient
	tracer    trace.Tracer
	analyzer  *govader.SentimentIntensityAnalyzer
	wg        sync.WaitGroup
	ctx       context.Context
	cancel    context.CancelFunc
	startOnce sync.Once
	stopOnce  sync.Once
}

// NewFeatureExtractor constructs a ready-to-start service.
func NewFeatureExtractor(cfg ExtractorConfig) (*FeatureExtractorService, error) {
	if err := cfg.Validate(); err != nil {
		return nil, err
	}

	// NATS connection.
	nc, err := nats.Connect(cfg.NATSURL,
		nats.Name("EchoPulse/FeatureExtractor"),
		nats.MaxReconnects(-1),
	)
	if err != nil {
		return nil, fmt.Errorf("connect nats: %w", err)
	}

	js, err := nc.JetStream()
	if err != nil {
		return nil, fmt.Errorf("create jetstream ctx: %w", err)
	}

	// Optional redis cache (used by drift detectors, etc.).
	var rdb *redis.Client
	if cfg.RedisURL != "" {
		rdb = redis.NewClient(&redis.Options{
			Addr: cfg.RedisURL,
		})
		if pingErr := rdb.Ping(context.Background()).Err(); pingErr != nil {
			return nil, fmt.Errorf("ping redis: %w", pingErr)
		}
	}

	// Feature store gRPC client.
	conn, err := grpc.Dial(cfg.GRPCFeatureStoreURL,
		grpc.WithInsecure(), // In production use TLS
		grpc.WithBlock(),
		grpc.WithTimeout(5*time.Second),
	)
	if err != nil {
		return nil, fmt.Errorf("dial feature store: %w", err)
	}

	fsClient := pb.NewFeatureStoreServiceClient(conn)

	ctx, cancel := context.WithCancel(context.Background())

	return &FeatureExtractorService{
		cfg:      cfg,
		nc:       nc,
		js:       js,
		redis:    rdb,
		fsClient: fsClient,
		tracer:   otel.Tracer("echopulse/feature-extractor"),
		analyzer: govader.NewSentimentIntensityAnalyzer(),
		ctx:      ctx,
		cancel:   cancel,
	}, nil
}

// Start boots the subscription and the worker pool.
func (s *FeatureExtractorService) Start() error {
	var err error
	s.startOnce.Do(func() {
		err = s.start()
	})
	return err
}

// internal start logic separated for testability.
func (s *FeatureExtractorService) start() error {
	// Create / bind durable consumer.
	sub, err := s.js.PullSubscribe(
		s.cfg.Subject,
		s.cfg.ConsumerGroup,
		nats.BindStream("SocialEvents"),
		nats.AckWait(s.cfg.AckWait),
		nats.ManualAck(),
	)
	if err != nil {
		return fmt.Errorf("create pull subscription: %w", err)
	}
	s.sub = sub

	// Launch worker pool.
	for i := 0; i < s.cfg.Concurrency; i++ {
		s.wg.Add(1)
		go s.workerLoop(i)
	}

	log.Printf("[FeatureExtractor] Started with %d workers", s.cfg.Concurrency)
	return nil
}

// Stop gracefully drains the subscription, waits for workers, and frees resources.
func (s *FeatureExtractorService) Stop() {
	s.stopOnce.Do(func() {
		log.Println("[FeatureExtractor] Shutting down")
		s.cancel()

		// Drain subscription.
		if s.sub != nil {
			_ = s.sub.Drain()
		}
		s.wg.Wait()

		// Close NATS.
		if s.nc != nil && !s.nc.IsClosed() {
			s.nc.Close()
		}

		// Close Redis.
		if s.redis != nil {
			_ = s.redis.Close()
		}
	})
}

// workerLoop polls JetStream for new messages and processes them serially.
func (s *FeatureExtractorService) workerLoop(id int) {
	defer func() {
		if rec := recover(); rec != nil {
			log.Printf("[FeatureExtractor] worker %d panic: %v\n%s", id, rec, string(debug.Stack()))
		}
		s.wg.Done()
	}()

	for {
		select {
		case <-s.ctx.Done():
			return
		default:
		}

		// Pull a batch.
		msgs, err := s.sub.Fetch(s.cfg.Prefetch, nats.Context(s.ctx))
		if err != nil {
			if errors.Is(err, context.Canceled) || errors.Is(err, nats.ErrTimeout) {
				continue // Retry until service is stopped
			}
			log.Printf("[FeatureExtractor] worker %d fetch error: %v", id, err)
			continue
		}

		for _, msg := range msgs {
			if procErr := s.processMessage(msg); procErr != nil {
				log.Printf("[FeatureExtractor] worker %d processing error: %v", id, procErr)
				_ = msg.Term() // Negative ack – send to DLQ if configured
				continue
			}
			_ = msg.Ack()
		}
	}
}

// processMessage contains the business logic to transform SocialEvent -> FeatureVector.
func (s *FeatureExtractorService) processMessage(msg *nats.Msg) error {
	var se SocialEvent
	if err := json.Unmarshal(msg.Data, &se); err != nil {
		return fmt.Errorf("json decode: %w", err)
	}

	ctx, span := s.tracer.Start(s.ctx, "process_social_event",
		trace.WithAttributes(attribute.String("event.id", se.ID)))
	defer span.End()

	// NLP feature extraction
	fv := s.extractFeatures(&se)

	// Persist to Feature Store
	if err := s.persistFeatureVector(ctx, fv); err != nil {
		span.RecordError(err)
		return fmt.Errorf("persist feature vector: %w", err)
	}

	// Optional cache
	if s.redis != nil {
		key := fmt.Sprintf("fv:%s", fv.EventID)
		b, _ := json.Marshal(fv)
		if err := s.redis.Set(ctx, key, b, 30*time.Minute).Err(); err != nil {
			log.Printf("[FeatureExtractor] redis set error: %v", err)
		}
	}

	// Publish downstream
	out, _ := json.Marshal(fv)
	if err := s.js.Publish(ctx, s.cfg.FeatureVectorSubject, out); err != nil {
		span.RecordError(err)
		return fmt.Errorf("publish: %w", err)
	}

	return nil
}

// extractFeatures runs simple text analytics.  In production this could call
// a more sophisticated pipeline (spaCy server, transformer model, etc.).
func (s *FeatureExtractorService) extractFeatures(se *SocialEvent) *FeatureVector {
	payload := se.Payload
	// Basic heuristics
	wordCount := len(strings.Fields(payload))
	emojiCount := countEmojis(payload)
	var emojiDensity float64
	if wordCount > 0 {
		emojiDensity = float64(emojiCount) / float64(wordCount)
	}

	// Sentiment
	sentiment := s.analyzer.PolarityScores(payload)
	compound := sentiment.Compound // -1.0 .. 1.0

	return &FeatureVector{
		EventID:      se.ID,
		UserID:       se.UserID,
		ChannelID:    se.ChannelID,
		Sentiment:    compound,
		EmojiDensity: emojiDensity,
		WordCount:    wordCount,
		Language:     se.Metadata["lang"],
		GeneratedAt:  time.Now().UTC(),
		AdditionalMeta: map[string]string{
			"extractor_version": "v1.3.2",
			"correlation_id":    uuid.NewString(),
		},
	}
}

// persistFeatureVector upserts the vector in the Feature Store via gRPC.
func (s *FeatureExtractorService) persistFeatureVector(ctx context.Context, fv *FeatureVector) error {
	req := &pb.PutFeatureVectorRequest{
		Vector: &pb.FeatureVector{
			EventId:      fv.EventID,
			UserId:       fv.UserID,
			ChannelId:    fv.ChannelID,
			Sentiment:    fv.Sentiment,
			EmojiDensity: fv.EmojiDensity,
			WordCount:    int32(fv.WordCount),
			Language:     fv.Language,
			GeneratedAt:  fv.GeneratedAt.UnixNano(),
			Metadata:     fv.AdditionalMeta,
		},
	}
	_, err := s.fsClient.PutFeatureVector(ctx, req)
	return err
}

// ----------------------------------------------------------------------------
// Utility
// ----------------------------------------------------------------------------

// countEmojis is a naive emoji detection helper.
func countEmojis(s string) int {
	count := 0
	for _, r := range s {
		// Rough range for emoticons + unicode supplemental symbols.
		switch {
		case r >= 0x1F600 && r <= 0x1F64F,
			r >= 0x1F300 && r <= 0x1F5FF,
			r >= 0x1F680 && r <= 0x1F6FF,
			r >= 0x2600 && r <= 0x26FF:
			count++
		}
	}
	return count
}
```