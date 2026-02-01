```javascript
/**
 * AgoraPulse – Real-Time Social Signal Intelligence
 *
 * src/module_3.js
 *
 * “RealTimeSentimentMonitor” – consumes fine-grained sentiment-analysis events,
 * performs windowed aggregation using a pluggable strategy pattern, publishes
 * roll-ups to a monitoring topic, and emits alert events whenever guard-rails
 * are violated (e.g., negativity spikes or drift from historical baselines).
 *
 * ‑ Uses kafkajs for event I/O
 * ‑ Uses rxjs for reactive windowing / back-pressure
 * ‑ Implements Strategy + Factory patterns for aggregation algorithm selection
 */

import dotenv from 'dotenv';
import { Kafka, logLevel } from 'kafkajs';
import { Subject, operators as ops } from 'rxjs';
import { mean, sum } from 'lodash-es';

dotenv.config();

/* -------------------------------------------------------------------------- */
/*                                Configuration                               */
/* -------------------------------------------------------------------------- */

const cfg = {
  kafka: {
    clientId: process.env.KAFKA_CLIENT_ID || 'agorapulse-monitor',
    brokers: (process.env.KAFKA_BROKERS || 'localhost:9092').split(','),
    groupId: process.env.KAFKA_GROUP_ID || 'sentiment-monitor',
  },
  topics: {
    sentiment: process.env.TOPIC_SENTIMENT || 'analysis.sentiment',
    aggregate: process.env.TOPIC_SENTIMENT_AGG || 'monitoring.sentiment.aggregate',
    alert: process.env.TOPIC_SENTIMENT_ALERT || 'monitoring.alerts',
  },
  monitor: {
    windowMs: Number(process.env.MONITOR_WINDOW_MS) || 15_000,
    slideMs: Number(process.env.MONITOR_SLIDE_MS) || 5_000,
    negativityThreshold: Number(process.env.NEG_THRESHOLD) || 0.65, // 65% negative
    aggregator: process.env.AGGREGATOR_STRATEGY || 'mean', // 'mean' | 'ewma'
    ewmaAlpha: Number(process.env.EWMA_ALPHA) || 0.3,
  },
};

/* -------------------------------------------------------------------------- */
/*                           Aggregator Strategies                            */
/* -------------------------------------------------------------------------- */

/**
 * @interface AggregatorStrategy
 * @method update Accepts the new numeric value and mutates internal state.
 * @method value  Returns current aggregate for the window.
 */

/**
 * Mean (arithmetic average) aggregator
 */
class MeanAggregator {
  #buffer = [];

  update(v) {
    if (typeof v === 'number' && !Number.isNaN(v)) {
      this.#buffer.push(v);
    }
  }

  value() {
    return this.#buffer.length ? mean(this.#buffer) : null;
  }

  /** Reset internal buffer for next window */
  reset() {
    this.#buffer = [];
  }
}

/**
 * EWMA (Exponentially Weighted Moving Average)
 */
class EwmaAggregator {
  #alpha;
  #current = null;

  constructor(alpha = 0.3) {
    this.#alpha = alpha;
  }

  update(v) {
    if (typeof v !== 'number' || Number.isNaN(v)) return;
    if (this.#current === null) {
      this.#current = v;
    } else {
      this.#current = this.#alpha * v + (1 - this.#alpha) * this.#current;
    }
  }

  value() {
    return this.#current;
  }

  reset() {
    // EWMA is inherently rolling; we keep state.
  }
}

/* -------------------------------------------------------------------------- */
/*                          Aggregator Strategy Factory                       */
/* -------------------------------------------------------------------------- */

class AggregatorFactory {
  /**
   * @param {string} name
   * @returns {AggregatorStrategy}
   */
  static create(name) {
    switch (name) {
      case 'mean':
        return new MeanAggregator();
      case 'ewma':
        return new EwmaAggregator(cfg.monitor.ewmaAlpha);
      default:
        throw new Error(`Unknown aggregator strategy: ${name}`);
    }
  }
}

/* -------------------------------------------------------------------------- */
/*                          Real-Time Sentiment Monitor                       */
/* -------------------------------------------------------------------------- */

export class RealTimeSentimentMonitor {
  #kafka;
  #consumer;
  #producer;
  #stream$ = new Subject();
  #aggregator;
  #isRunning = false;

  constructor() {
    this.#aggregator = AggregatorFactory.create(cfg.monitor.aggregator);

    this.#kafka = new Kafka({
      logLevel: logLevel.NOTHING,
      clientId: cfg.kafka.clientId,
      brokers: cfg.kafka.brokers,
    });

    this.#consumer = this.#kafka.consumer({ groupId: cfg.kafka.groupId });
    this.#producer = this.#kafka.producer();
  }

  /* ---------------------------------------------------------------------- */
  /*                             Lifecycle                                  */
  /* ---------------------------------------------------------------------- */

  async start() {
    if (this.#isRunning) return;
    await this.#consumer.connect();
    await this.#producer.connect();
    await this.#consumer.subscribe({ topic: cfg.topics.sentiment, fromBeginning: false });

    // Bridge Kafka messages to RxJS
    this.#consumer.run({
      autoCommit: true,
      eachMessage: async ({ message }) => {
        const payload = this.#decodeMessage(message);
        if (!payload) return; // decoding failed
        this.#stream$.next(payload);
      },
    });

    // Reactive pipeline: windowing + aggregation + alerting
    this.#stream$
      .pipe(
        // Sliding time windows
        ops.bufferTime(cfg.monitor.windowMs, cfg.monitor.slideMs),
        ops.filter((buf) => buf.length > 0),
        ops.map((windowMsgs) => this.#processWindow(windowMsgs)),
      )
      .subscribe({
        next: async ({ aggregate, negativeRatio, count }) => {
          await this.#publishAggregate({ aggregate, negativeRatio, count });
          if (negativeRatio >= cfg.monitor.negativityThreshold) {
            await this.#publishAlert(negativeRatio, count);
          }
        },
        error: (err) => console.error('[RealTimeSentimentMonitor] stream error', err),
      });

    this.#isRunning = true;
    console.info('RealTimeSentimentMonitor started…');
  }

  async stop() {
    if (!this.#isRunning) return;
    await Promise.allSettled([this.#consumer.disconnect(), this.#producer.disconnect()]);
    this.#stream$.complete();
    this.#isRunning = false;
    console.info('RealTimeSentimentMonitor stopped.');
  }

  /* ---------------------------------------------------------------------- */
  /*                           Internal Helpers                             */
  /* ---------------------------------------------------------------------- */

  /**
   * Decodes a Kafka JS message value to JSON.
   * @param {import('kafkajs').KafkaMessage} message
   * @returns {{ sentiment: number, label: 'positive'|'negative'|'neutral', meta: object } | null}
   */
  #decodeMessage(message) {
    try {
      return JSON.parse(message.value.toString('utf8'));
    } catch (err) {
      console.warn('[RealTimeSentimentMonitor] JSON parse failure', err);
      return null;
    }
  }

  /**
   * Process a window of messages – update aggregator, compute metrics.
   * @param {Array<Object>} windowMsgs
   * @returns {{ aggregate: number|null, negativeRatio: number, count: number }}
   */
  #processWindow(windowMsgs) {
    // Reset aggregator for discrete window if strategy supports it
    if (typeof this.#aggregator.reset === 'function') {
      this.#aggregator.reset();
    }

    let negatives = 0;

    for (const msg of windowMsgs) {
      if (typeof msg.sentiment === 'number') {
        this.#aggregator.update(msg.sentiment);
      }
      if (msg.label === 'negative') negatives += 1;
    }

    const aggregate = this.#aggregator.value();
    const count = windowMsgs.length;
    const negativeRatio = count ? negatives / count : 0;

    return { aggregate, negativeRatio, count };
  }

  /**
   * Publish aggregated metrics to monitoring topic.
   */
  async #publishAggregate({ aggregate, negativeRatio, count }) {
    try {
      const payload = {
        ts: Date.now(),
        aggregate,
        negativeRatio,
        count,
        strategy: cfg.monitor.aggregator,
      };

      await this.#producer.send({
        topic: cfg.topics.aggregate,
        messages: [{ value: JSON.stringify(payload) }],
      });
    } catch (err) {
      console.error('[RealTimeSentimentMonitor] failed to publish aggregate', err);
    }
  }

  /**
   * Emit alert event.
   */
  async #publishAlert(negativeRatio, count) {
    try {
      const alertEvt = {
        ts: Date.now(),
        type: 'NEGATIVITY_SPIKE',
        description: `Negative sentiment ratio ${negativeRatio.toFixed(
          2,
        )} exceeds threshold (${cfg.monitor.negativityThreshold})`,
        meta: { negativeRatio, count },
      };

      await this.#producer.send({
        topic: cfg.topics.alert,
        messages: [{ value: JSON.stringify(alertEvt) }],
      });

      console.warn('[RealTimeSentimentMonitor] ALERT emitted', alertEvt);
    } catch (err) {
      console.error('[RealTimeSentimentMonitor] failed to publish alert', err);
    }
  }
}

/* -------------------------------------------------------------------------- */
/*                                Bootstrapping                               */
/* -------------------------------------------------------------------------- */

if (import.meta.url === `file://${process.argv[1]}`) {
  // Execute directly – useful for local dev / Docker health-checks
  const monitor = new RealTimeSentimentMonitor();
  monitor
    .start()
    .catch((err) => {
      console.error('[RealTimeSentimentMonitor] fatal', err);
      process.exit(1);
    });

  // Graceful shutdown
  const shutdown = async () => {
    await monitor.stop();
    process.exit(0);
  };
  process.on('SIGINT', shutdown);
  process.on('SIGTERM', shutdown);
}
```