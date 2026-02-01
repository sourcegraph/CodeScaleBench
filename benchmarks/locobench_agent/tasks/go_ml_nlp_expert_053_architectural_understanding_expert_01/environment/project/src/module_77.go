```go
// Copyright 2024 EchoPulse.
//
// Licensed under the Apache License, Version 2.0 (the "License");
// you may not use this file except in compliance with the License.
// You may obtain a copy of the License at
//
//     http://www.apache.org/licenses/LICENSE-2.0
//
// Module:        module_77.go
// Description:   Real-time sentiment routing component.  Consumes canonical
//                SocialEvents, dynamically selects an inference strategy
//                (high-accuracy vs low-latency) via the Strategy pattern,
//                emits Prediction artifacts to downstream observers, and
//                reports basic metrics.  Intended to sit behind the event
//                bus consumer group and in front of the feature store.
//
// NOTE: This file is self-contained for illustrative purposes.  In a real
//       code-base the ModelClient, registry, and protobufs would live in
//       dedicated packages and be code-generated from .proto definitions.

package pipeline

import (
	"context"
	"errors"
	"fmt"
	"log"
	"math/rand"
	"net"
	"sync"
	"time"

	"google.golang.org/grpc"
)

// ========================= Domain Objects ================================

// SocialEvent is the canonical unit emitted by upstream ingestion pipelines.
type SocialEvent struct {
	ID        string            `json:"id"`
	Timestamp time.Time         `json:"ts"`
	Text      string            `json:"text"`
	Metadata  map[string]string `json:"meta,omitempty"`
	Priority  int               `json:"priority"` // 0 == best-effort, larger == more important
}

// Prediction is the result of running an ML model against a SocialEvent.
type Prediction struct {
	EventID   string    `json:"event_id"`
	Sentiment float64   `json:"sentiment"` // (−1 .. 1)
	ModelName string    `json:"model"`
	Latency   time.Duration
	CreatedAt time.Time `json:"ts"`
}

// ========================= Observer Pattern ==============================

// Observer receives Predictions.
type Observer interface {
	Notify(Prediction)
}

// ObserverFunc is a functional adapter so ordinary funcs can be observers.
type ObserverFunc func(Prediction)

func (f ObserverFunc) Notify(p Prediction) { f(p) }

// ========================= Model Registry ===============================

// ModelRegistry knows how to resolve logical model names to runnable endpoints.
type ModelRegistry interface {
	Resolve(ctx context.Context, name, version string) (Endpoint, error)
}

// Endpoint describes how a model can be reached.
type Endpoint struct {
	HostPort string // host:port of the gRPC model server
	Timeout  time.Duration
}

// simpleRegistry is a toy in-memory registry.
type simpleRegistry struct {
	mu   sync.RWMutex
	data map[string]Endpoint
}

func NewSimpleRegistry() *simpleRegistry {
	return &simpleRegistry{data: make(map[string]Endpoint)}
}

func (r *simpleRegistry) Register(name, version, hostport string, timeout time.Duration) {
	r.mu.Lock()
	defer r.mu.Unlock()
	key := fmt.Sprintf("%s:%s", name, version)
	r.data[key] = Endpoint{HostPort: hostport, Timeout: timeout}
}

func (r *simpleRegistry) Resolve(ctx context.Context, name, version string) (Endpoint, error) {
	r.mu.RLock()
	defer r.mu.RUnlock()
	key := fmt.Sprintf("%s:%s", name, version)
	ep, ok := r.data[key]
	if !ok {
		return Endpoint{}, errors.New("model not found in registry")
	}
	return ep, nil
}

// ========================= Model Client =================================

// ModelClient hides transport-level details and exposes a stateless Predict call.
type ModelClient interface {
	Predict(ctx context.Context, text string) (float64, error)
	Close() error
}

type grpcModelClient struct {
	cc       *grpc.ClientConn
	model    string
	latency  time.Duration // artificial latency for the demo
	failRate float64       // chance to cause an error
}

func newGRPCModelClient(model string, ep Endpoint) (*grpcModelClient, error) {
	ctx, cancel := context.WithTimeout(context.Background(), ep.Timeout)
	defer cancel()
	conn, err := grpc.DialContext(ctx, ep.HostPort, grpc.WithInsecure(), grpc.WithBlock())
	if err != nil {
		return nil, err
	}
	return &grpcModelClient{
		cc:       conn,
		model:    model,
		latency:  time.Millisecond * time.Duration(rand.Intn(20)+5),
		failRate: 0.05, // 5% simulated failure
	}, nil
}

func (c *grpcModelClient) Predict(ctx context.Context, text string) (float64, error) {
	if rand.Float64() < c.failRate {
		return 0, errors.New("simulated inference failure")
	}
	select {
	case <-time.After(c.latency):
		// Fake deterministic sentiment for the demo.
		hash := 0
		for _, r := range text {
			hash += int(r)
		}
		sentiment := (float64(hash%200) / 100.0) - 1.0 // −1 .. +1
		return sentiment, nil
	case <-ctx.Done():
		return 0, ctx.Err()
	}
}

func (c *grpcModelClient) Close() error { return c.cc.Close() }

// ========================= Strategy Pattern =============================

// PredictorStrategy chooses an implementation at runtime.
type PredictorStrategy interface {
	Predict(ctx context.Context, ev SocialEvent) (Prediction, error)
}

// highAccuracyStrategy may be slower but more accurate.
type highAccuracyStrategy struct {
	client ModelClient
	model  string
}

func (s *highAccuracyStrategy) Predict(ctx context.Context, ev SocialEvent) (Prediction, error) {
	start := time.Now()
	val, err := s.client.Predict(ctx, ev.Text)
	if err != nil {
		return Prediction{}, err
	}
	return Prediction{
		EventID:   ev.ID,
		Sentiment: val,
		ModelName: s.model,
		Latency:   time.Since(start),
		CreatedAt: time.Now(),
	}, nil
}

// lowLatencyStrategy returns a quick heuristic.
type lowLatencyStrategy struct {
	model string
}

func (s *lowLatencyStrategy) Predict(_ context.Context, ev SocialEvent) (Prediction, error) {
	// Extremely naive bag-of-words approach for the demo.
	words := 0
	neg := 0
	for _, tok := range []byte(ev.Text) {
		if tok == ' ' {
			words++
		}
		if tok == '!' || tok == '?' || tok == ':' {
			neg++
		}
	}
	sentiment := 1.0 - float64(neg)/float64(words+1) // crude heuristic
	return Prediction{
		EventID:   ev.ID,
		Sentiment: sentiment,
		ModelName: s.model,
		Latency:   0,
		CreatedAt: time.Now(),
	}, nil
}

// ========================= Router (Context Object) ======================

// SentimentRouter routes events to an appropriate predictor then fans out
// results to observers.  It encapsulates the Strategy & Observer patterns.
type SentimentRouter struct {
	workers       int
	registry      ModelRegistry
	obsMu         sync.RWMutex
	observers     []Observer
	eventCh       chan SocialEvent
	ctx           context.Context
	cancel        context.CancelFunc
	wg            sync.WaitGroup
	accClientOnce sync.Once
	accClient     ModelClient // high-accuracy shared client
}

func NewSentimentRouter(workers int, registry ModelRegistry) *SentimentRouter {
	if workers <= 0 {
		workers = 4
	}
	ctx, cancel := context.WithCancel(context.Background())
	return &SentimentRouter{
		workers:  workers,
		registry: registry,
		eventCh:  make(chan SocialEvent, workers*2),
		ctx:      ctx,
		cancel:   cancel,
	}
}

// Subscribe adds an observer that will receive Prediction notifications.
func (r *SentimentRouter) Subscribe(obs Observer) {
	r.obsMu.Lock()
	defer r.obsMu.Unlock()
	r.observers = append(r.observers, obs)
}

// Push queues an event for asynchronous processing.
func (r *SentimentRouter) Push(ev SocialEvent) error {
	select {
	case r.eventCh <- ev:
		return nil
	case <-r.ctx.Done():
		return r.ctx.Err()
	}
}

// Start launches the worker pool.
func (r *SentimentRouter) Start() {
	r.wg.Add(r.workers)
	for i := 0; i < r.workers; i++ {
		go r.worker(i)
	}
}

// Stop gracefully shuts down the router.
func (r *SentimentRouter) Stop() {
	r.cancel()
	r.wg.Wait()
	if r.accClient != nil {
		_ = r.accClient.Close()
	}
	close(r.eventCh)
}

// ========================= Internal Helpers =============================

func (r *SentimentRouter) worker(id int) {
	defer r.wg.Done()
	log.Printf("[router] worker #%d online", id)

	for {
		select {
		case ev := <-r.eventCh:
			r.processEvent(ev)
		case <-r.ctx.Done():
			return
		}
	}
}

func (r *SentimentRouter) processEvent(ev SocialEvent) {
	ctx, cancel := context.WithTimeout(r.ctx, 500*time.Millisecond)
	defer cancel()

	var strat PredictorStrategy
	// Simulated heuristics:
	//   High-priority events -> high-accuracy model
	//   Otherwise -> low-latency model
	if ev.Priority > 5 {
		client, err := r.getAccurateClient(ctx)
		if err != nil {
			log.Printf("[router] resolve err (%s): %v; falling back", ev.ID, err)
			strat = &lowLatencyStrategy{model: "heuristic_v1"}
		} else {
			strat = &highAccuracyStrategy{
				client: client,
				model:  "bert-sentiment:10",
			}
		}
	} else {
		strat = &lowLatencyStrategy{model: "heuristic_v1"}
	}

	pred, err := strat.Predict(ctx, ev)
	if err != nil {
		log.Printf("[router] prediction failed (%s): %v", ev.ID, err)
		return
	}
	r.notify(pred)
}

func (r *SentimentRouter) getAccurateClient(ctx context.Context) (ModelClient, error) {
	var err error
	r.accClientOnce.Do(func() {
		ep, e := r.registry.Resolve(ctx, "bert-sentiment", "10")
		if e != nil {
			err = e
			return
		}
		// If the model server isn't already running, spin up a local fake.
		if ep.HostPort == "inproc" {
			ep.HostPort, e = launchInprocModelServer()
			if e != nil {
				err = e
				return
			}
		}
		r.accClient, err = newGRPCModelClient("bert-sentiment:10", ep)
	})
	return r.accClient, err
}

func (r *SentimentRouter) notify(p Prediction) {
	r.obsMu.RLock()
	defer r.obsMu.RUnlock()
	for _, o := range r.observers {
		// Fan-out in a separate goroutine to avoid blocking slow observers.
		go o.Notify(p)
	}
}

// ========================= Demo / Local Driver ==========================

// launchInprocModelServer starts a dummy gRPC service on a random port.
// EchoPulse defers to dedicated model-serving clusters in prod; here we mock.
func launchInprocModelServer() (string, error) {
	l, err := net.Listen("tcp", "127.0.0.1:0") // random port
	if err != nil {
		return "", err
	}
	go func() {
		s := grpc.NewServer()
		// pb.RegisterInferenceServiceServer(s, &fakeServer{})
		if err = s.Serve(l); err != nil {
			log.Printf("[inproc-model] serve err: %v", err)
		}
	}()
	return l.Addr().String(), nil
}

// ========================= Usage Example ================================

// This function is NOT executed automatically; it serves as documentation
// for developers and will be triggered from unit/integration tests.
func example() {
	// 1. Setup registry with a mock endpoint.
	reg := NewSimpleRegistry()
	reg.Register("bert-sentiment", "10", "inproc", 3*time.Second)

	// 2. Build router and observer.
	router := NewSentimentRouter(8, reg)
	router.Subscribe(ObserverFunc(func(p Prediction) {
		log.Printf("[observer] %+v", p)
	}))
	router.Start()
	defer router.Stop()

	// 3. Stream in some events.
	for i := 0; i < 20; i++ {
		ev := SocialEvent{
			ID:        fmt.Sprintf("ev-%02d", i),
			Timestamp: time.Now(),
			Text:      fmt.Sprintf("hello world %d!", i),
			Priority:  rand.Intn(10),
		}
		if err := router.Push(ev); err != nil {
			log.Printf("push err: %v", err)
		}
	}

	time.Sleep(2 * time.Second) // allow async processing
}
```