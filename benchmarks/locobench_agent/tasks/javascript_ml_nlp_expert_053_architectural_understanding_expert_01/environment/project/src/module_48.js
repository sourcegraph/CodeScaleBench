```javascript
/**
 * AgoraPulse: Real-Time Social Signal Intelligence
 * ------------------------------------------------
 * src/module_48.js
 *
 * RealtimeToxicityMonitor
 * -----------------------
 * Listens to the post-classification event stream, aggregates toxicity
 * predictions against human moderation feedback in a sliding window, and
 * emits ALERT events when the false-negative rate breaches a configurable
 * threshold.  Implements the Strategy and Observer patterns by:
 *
 *  • Using RxJS Observables as the reactive event channel
 *  • Abstracting aggregation logic behind interchangeable strategies
 *
 * Dependencies (peer):
 *  • kafkajs      – Kafka client
 *  • rxjs         – Reactive streams
 *  • lodash       – Utility helpers
 *  • uuid         – Unique identifiers for correlation IDs
 */

import { Kafka, logLevel } from 'kafkajs';
import {
  bufferTime,
  catchError,
  filter,
  map,
  merge,
  Observable,
  Subject,
  tap,
  timeout,
} from 'rxjs';
import { meanBy } from 'lodash';
import { v4 as uuid } from 'uuid';

/* -------------------------------------------------------------------------- */
/* Configuration                                                              */
/* -------------------------------------------------------------------------- */

const DEFAULT_CONFIG = Object.freeze({
  kafka: {
    clientId: 'agora-monitor-toxicity',
    brokers: process.env.KAFKA_BROKERS?.split(',') ?? ['localhost:9092'],
    groupId: 'toxicity-monitor-group',
    topics: {
      classified: 'nlp.classified', // model output with toxicity prediction
      moderated: 'moderation.feedback', // human feedback stream
      alert: 'ops.alerts', // emitted by this module
    },
  },
  window: {
    durationMs: 60_000, // sliding window length
    evaluateEveryMs: 10_000, // evaluation frequency
  },
  thresholds: {
    falseNegativeRate: 0.02, // 2%
  },
});

/* -------------------------------------------------------------------------- */
/* Utility types                                                              */
/* -------------------------------------------------------------------------- */

/**
 * @typedef {Object} ClassifiedEvent
 * @property {string} messageId
 * @property {number} toxicityScore          // [0,1]
 * @property {boolean} isToxic               // model binary decision
 * @property {string} modelVersion
 * @property {number} timestamp              // epoch milliseconds
 */

/**
 * @typedef {Object} ModerationEvent
 * @property {string} messageId
 * @property {boolean} isToxic               // actual label from moderator
 * @property {number} timestamp
 */

/**
 * @typedef {Object} AlertEvent
 * @property {string} type                   // e.g., "TOXICITY_FALSE_NEGATIVE_RATE_HIGH"
 * @property {number} rate                   // observed rate
 * @property {number} threshold              // configured threshold
 * @property {string} windowId
 * @property {number} startTs
 * @property {number} endTs
 * @property {string} correlationId
 */

/* -------------------------------------------------------------------------- */
/* Aggregation Strategies                                                     */
/* -------------------------------------------------------------------------- */

class FalseNegativeRateStrategy {
  /**
   * @param {Array<{ prediction: ClassifiedEvent, groundTruth: ModerationEvent }>} pairs
   * @returns {{ rate: number, total: number, falseNegative: number }}
   */
  compute(pairs) {
    const total = pairs.length;
    if (total === 0) {
      return { rate: 0, total: 0, falseNegative: 0 };
    }
    const falseNegative = pairs.filter(
      ({ prediction, groundTruth }) =>
        !prediction.isToxic && groundTruth.isToxic
    ).length;

    return {
      rate: falseNegative / total,
      total,
      falseNegative,
    };
  }
}

/* -------------------------------------------------------------------------- */
/* RealtimeToxicityMonitor                                                    */
/* -------------------------------------------------------------------------- */

export class RealtimeToxicityMonitor {
  /**
   * @param {Partial<typeof DEFAULT_CONFIG>} [config]
   */
  constructor(config = {}) {
    this.config = {
      ...DEFAULT_CONFIG,
      ...config,
      kafka: {
        ...DEFAULT_CONFIG.kafka,
        ...(config.kafka ?? {}),
        topics: { ...DEFAULT_CONFIG.kafka.topics, ...(config.kafka?.topics ?? {}) },
      },
      window: { ...DEFAULT_CONFIG.window, ...(config.window ?? {}) },
      thresholds: { ...DEFAULT_CONFIG.thresholds, ...(config.thresholds ?? {}) },
    };

    // Initialize Kafka client
    this.kafka = new Kafka({
      clientId: this.config.kafka.clientId,
      brokers: this.config.kafka.brokers,
      logLevel: logLevel.ERROR,
    });

    this.consumer = this.kafka.consumer({ groupId: this.config.kafka.groupId });
    this.producer = this.kafka.producer();
    this.classified$ = new Subject(); // stream of ClassifiedEvent
    this.moderated$ = new Subject(); // stream of ModerationEvent
    this.aggregationStrategy = new FalseNegativeRateStrategy();
    this._isRunning = false;
  }

  /* ---------------------------------------------------------------------- */
  /* Private helper methods                                                 */
  /* ---------------------------------------------------------------------- */

  /**
   * Deserializes Kafka messages into domain events based on topic.
   * Gracefully handles malformed JSON.
   * @param {string} topic
   * @param {import('kafkajs').KafkaMessage} message
   * @returns {void}
   */
  _handleMessage(topic, message) {
    try {
      const payload = JSON.parse(message.value.toString());

      switch (topic) {
        case this.config.kafka.topics.classified:
          this.classified$.next(payload);
          break;
        case this.config.kafka.topics.moderated:
          this.moderated$.next(payload);
          break;
        default:
          // ignore unknown topics
      }
    } catch (err) {
      console.error(
        `Failed to parse message on topic ${topic}: ${err.message}`
      );
    }
  }

  /**
   * Correlates predictions with human feedback by messageId.
   * Emits evaluation results at a fixed cadence.
   * @returns {Observable<AlertEvent>}
   */
  _createEvaluationStream() {
    const { durationMs, evaluateEveryMs } = this.config.window;
    const { falseNegativeRate } = this.config.thresholds;

    // Merge classified and moderated streams preserving type
    const merged$ = merge(
      this.classified$.pipe(map((e) => ({ type: 'prediction', data: e }))),
      this.moderated$.pipe(map((e) => ({ type: 'groundTruth', data: e })))
    );

    // Maintain in-memory sliding window
    let windowStore = new Map(); // messageId -> { prediction?, groundTruth? }

    return merged$.pipe(
      tap(({ type, data }) => {
        const entry = windowStore.get(data.messageId) ?? {};
        if (type === 'prediction') entry.prediction = data;
        else entry.groundTruth = data;

        windowStore.set(data.messageId, entry);
      }),
      bufferTime(evaluateEveryMs), // trigger every evaluateEveryMs
      map(() => {
        const now = Date.now();

        // drop expired entries
        for (const [id, { prediction, groundTruth }] of windowStore.entries()) {
          const ts = groundTruth?.timestamp ?? prediction?.timestamp ?? 0;
          if (now - ts > durationMs) {
            windowStore.delete(id);
          }
        }

        // take only fully paired items
        const paired = Array.from(windowStore.values()).filter(
          (v) => v.prediction && v.groundTruth
        );

        const { rate } = this.aggregationStrategy.compute(
          paired.map(({ prediction, groundTruth }) => ({ prediction, groundTruth }))
        );

        return { rate, now };
      }),
      filter(({ rate }) => rate > falseNegativeRate),
      map(({ rate, now }) => {
        /** @type {AlertEvent} */
        return {
          type: 'TOXICITY_FALSE_NEGATIVE_RATE_HIGH',
          rate,
          threshold: falseNegativeRate,
          windowId: uuid(),
          startTs: now - durationMs,
          endTs: now,
          correlationId: uuid(),
        };
      }),
      catchError((err, caught) => {
        console.error('Error in evaluation stream', err);
        return caught; // resume stream
      })
    );
  }

  /**
   * Publishes alert events back to Kafka.
   * @param {AlertEvent} alert
   */
  async _publishAlert(alert) {
    try {
      await this.producer.send({
        topic: this.config.kafka.topics.alert,
        messages: [{ key: alert.windowId, value: JSON.stringify(alert) }],
      });
      console.info(
        `Published alert ${alert.type} with rate ${(
          alert.rate * 100
        ).toFixed(2)}%`
      );
    } catch (err) {
      console.error('Failed to publish alert', err);
    }
  }

  /* ---------------------------------------------------------------------- */
  /* Public lifecycle methods                                               */
  /* ---------------------------------------------------------------------- */

  /**
   * Starts the monitor.
   */
  async start() {
    if (this._isRunning) return;
    this._isRunning = true;

    await this.consumer.connect();
    await this.producer.connect();

    await this.consumer.subscribe({
      topic: this.config.kafka.topics.classified,
      fromBeginning: false,
    });
    await this.consumer.subscribe({
      topic: this.config.kafka.topics.moderated,
      fromBeginning: false,
    });

    await this.consumer.run({
      eachMessage: async ({ topic, message }) =>
        this._handleMessage(topic, message),
    });

    // Kick off evaluation pipeline
    this._evaluationSub = this._createEvaluationStream().subscribe((alert) =>
      this._publishAlert(alert)
    );

    console.info('RealtimeToxicityMonitor started.');
  }

  /**
   * Stops the monitor gracefully.
   */
  async stop() {
    if (!this._isRunning) return;
    this._isRunning = false;

    this._evaluationSub?.unsubscribe();
    await Promise.all([this.consumer.disconnect(), this.producer.disconnect()]);
    console.info('RealtimeToxicityMonitor stopped.');
  }
}

/* -------------------------------------------------------------------------- */
/* CLI Entrypoint for standalone execution                                    */
/* -------------------------------------------------------------------------- */

if (require.main === module) {
  // Allow quick experimentation: `node src/module_48.js`
  (async () => {
    const monitor = new RealtimeToxicityMonitor();

    const shutdown = async () => {
      await monitor.stop();
      process.exit(0);
    };

    process.on('SIGINT', shutdown);
    process.on('SIGTERM', shutdown);

    try {
      await monitor.start();
    } catch (err) {
      console.error('Fatal error in RealtimeToxicityMonitor', err);
      await shutdown();
    }
  })();
}
```