```typescript
/**
 * PulseSphere SocialOps
 * File: src/module_19.ts
 *
 * Social Virality Surge Predictor
 * -------------------------------------------------------------
 * Watches real-time social-interaction signals and predicts near-future
 * request-per-second (RPS) load in order to enable proactive capacity
 * orchestration.  Utilises Strategy & Observer patterns and pushes
 * prediction events to Kafka so that other services (e.g. auto-scalers,
 * alerting pipelines) can react.
 */

import { EventEmitter } from 'events';
import { Kafka, Producer, RecordMetadata } from 'kafkajs';
import { z } from 'zod'; // For runtime schema validation
import * as uuid from 'uuid';

/* ------------------------------------------------------------------ */
/*                                Types                               */
/* ------------------------------------------------------------------ */

/**
 * Raw social-interaction metric as emitted by telemetry collectors.
 */
export interface SocialMetric {
  readonly timestamp: Date;
  readonly likes: number;
  readonly comments: number;
  readonly shares: number;
  readonly activeViewers: number;
}

/**
 * Prediction result produced by a predictor strategy.
 */
export interface PredictionResult {
  readonly id: string; // uuid
  readonly predictedAt: Date;
  readonly windowStart: Date;
  readonly windowEnd: Date;
  readonly predictedRps: number;
  readonly confidence: number; // 0..1
  readonly reasoning: string;
}

/* ------------------------------------------------------------------ */
/*                         Strategy Interfaces                        */
/* ------------------------------------------------------------------ */

/**
 * Contract every Predictor Strategy must follow.
 */
export interface PredictorStrategy {
  /**
   * Called with one or more metrics (can be stream or batch). Implementations
   * are expected to maintain internal state (e.g. sliding window) if helpful.
   */
  ingest(metric: SocialMetric): void;

  /**
   * Produces an RPS prediction derived from currently ingested data.
   */
  predict(): PredictionResult | null;
}

/* ------------------------------------------------------------------ */
/*                   Concrete Predictor Strategy: SMA                 */
/* ------------------------------------------------------------------ */

/**
 * SimpleMovingAverageStrategy
 * Uses a classic sliding window SMA over active social interaction counts
 * to approximate future RPS.  Suitable for low-variance workloads.
 */
export class SimpleMovingAverageStrategy implements PredictorStrategy {
  private readonly window: number;
  private readonly data: SocialMetric[] = [];

  constructor(window: number = 30) {
    if (window <= 0) throw new Error('window must be > 0');
    this.window = window;
  }

  ingest(metric: SocialMetric): void {
    this.data.push(metric);
    // Keep only last N entries
    if (this.data.length > this.window) {
      this.data.shift();
    }
  }

  predict(): PredictionResult | null {
    if (this.data.length === 0) return null;

    const slice = this.data.slice(-this.window);
    const avgLikes = slice.reduce((acc, m) => acc + m.likes, 0) / slice.length;
    const avgComments = slice.reduce((acc, m) => acc + m.comments, 0) / slice.length;
    const avgShares = slice.reduce((acc, m) => acc + m.shares, 0) / slice.length;
    const avgViewers = slice.reduce((acc, m) => acc + m.activeViewers, 0) / slice.length;

    // Very naive RPS estimation formula (could be substituted by ML model)
    const predictedRps =
      avgViewers * 0.5 +
      avgLikes * 0.2 +
      avgComments * 0.2 +
      avgShares * 0.1;

    const confidence = Math.min(1, slice.length / this.window);

    return {
      id: uuid.v4(),
      predictedAt: new Date(),
      windowStart: slice[0].timestamp,
      windowEnd: slice[slice.length - 1].timestamp,
      predictedRps,
      confidence,
      reasoning: `SMA over ${slice.length} samples`
    };
  }
}

/* ------------------------------------------------------------------ */
/*                Predictor Context / Observer / Publisher            */
/* ------------------------------------------------------------------ */

export interface SurgePredictorOptions {
  /**
   * Event name to emit when confidence‐weighted predicted RPS crosses this.
   */
  surgeThreshold: number;

  /**
   * Kafka topic to publish predictions to.
   */
  kafkaTopic: string;

  /**
   * Optional override for Kafka producer (mocking/unit testing)
   */
  producer?: Producer;
}

/**
 * Validates SurgePredictorOptions at runtime.
 */
const optionsSchema = z.object({
  surgeThreshold: z.number().positive(),
  kafkaTopic: z.string().min(1)
});

/**
 * SurgePredictor
 * Manages a PredictionStrategy, emits local events, and publishes to Kafka.
 */
export class SurgePredictor extends EventEmitter {
  private strategy: PredictorStrategy;
  private readonly surgeThreshold: number;
  private readonly kafkaProducer: Producer;
  private readonly kafkaTopic: string;

  constructor(
    strategy: PredictorStrategy = new SimpleMovingAverageStrategy(),
    opts: SurgePredictorOptions
  ) {
    super();

    const parsed = optionsSchema.safeParse(opts);
    if (!parsed.success) {
      throw new Error(`Invalid SurgePredictorOptions: ${parsed.error.message}`);
    }

    const { surgeThreshold, kafkaTopic, producer } = parsed.data;

    this.strategy = strategy;
    this.surgeThreshold = surgeThreshold;
    this.kafkaTopic = kafkaTopic;
    this.kafkaProducer = producer ?? new Kafka({ brokers: process.env.KAFKA_BROKERS?.split(',') ?? ['localhost:9092'] }).producer();

    this.bootstrapProducer().catch((err) => {
      // Emit but don't crash—caller might attach listener after construction
      this.emit('error', err);
    });
  }

  /* ------------------------------------------------------------------ */
  /*                             Public API                             */
  /* ------------------------------------------------------------------ */

  /**
   * Provide a new PredictorStrategy at runtime.
   */
  switchStrategy(strategy: PredictorStrategy): void {
    this.strategy = strategy;
    this.emit('strategy-switched', strategy.constructor.name);
  }

  /**
   * Accepts a raw social metric, feeds it to the strategy,
   * and orchestrates publishing/emitting if threshold crossed.
   */
  async handleMetric(metric: SocialMetric): Promise<void> {
    try {
      this.strategy.ingest(metric);

      const prediction = this.strategy.predict();
      if (!prediction) return;

      await this.publishPrediction(prediction);

      // Local event for in-process subscribers
      this.emit('prediction', prediction);

      // Check for surge
      if (prediction.predictedRps >= this.surgeThreshold * prediction.confidence) {
        this.emit('surge-detected', prediction);
      }
    } catch (err) {
      this.emit('error', err);
    }
  }

  /* ------------------------------------------------------------------ */
  /*                           Private Helpers                          */
  /* ------------------------------------------------------------------ */

  private async bootstrapProducer(): Promise<void> {
    if (!this.kafkaProducer) return;
    await this.kafkaProducer.connect();
    this.emit('producer-ready');
  }

  private async publishPrediction(prediction: PredictionResult): Promise<RecordMetadata[] | void> {
    if (!this.kafkaProducer) return;

    const message = {
      key: prediction.id,
      value: JSON.stringify(prediction),
      headers: {
        'content-type': 'application/json',
        'pulse-message-type': 'surge-prediction'
      }
    };

    try {
      return await this.kafkaProducer.send({
        topic: this.kafkaTopic,
        messages: [message]
      });
    } catch (err) {
      // Bubble up but ensure service continues
      this.emit('error', err);
      return;
    }
  }
}

/* ------------------------------------------------------------------ */
/*                         Example (Self-Test)                         */
/* ------------------------------------------------------------------ */

if (process.env.NODE_ENV === 'development' && require.main === module) {
  // Quick sanity check when executed directly
  (async () => {
    const predictor = new SurgePredictor(new SimpleMovingAverageStrategy(10), {
      surgeThreshold: 5000,
      kafkaTopic: 'pulse.surge.prediction.dev'
    });

    predictor.on('surge-detected', (p: PredictionResult) => {
      console.log('🔥 Surge detected!', p);
    });

    predictor.on('error', (err) => {
      console.error('Predictor error', err);
    });

    // Simulate ingest
    setInterval(() => {
      const metric: SocialMetric = {
        timestamp: new Date(),
        likes: Math.random() * 1000,
        comments: Math.random() * 500,
        shares: Math.random() * 300,
        activeViewers: 10000 + Math.random() * 5000
      };
      predictor.handleMetric(metric).catch(console.error);
    }, 1000);
  })();
}
```