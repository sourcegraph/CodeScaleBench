/**
 * AgoraPulse: Real-Time Social Signal Intelligence
 * ------------------------------------------------
 * src/module_54.js
 *
 * Module 54 implements a streaming toxicity monitor that watches the continuous
 * flow of message–level toxicity scores coming from the inference layer.
 *
 *   • Aggregates scores in a sliding window (default: 60 s)
 *   • Detects threshold breaches (avg toxicity > configurable limit)
 *   • Emits structured alert events to a Kafka topic
 *   • Exposes Prometheus metrics for observability
 *
 * The implementation relies on RxJS for reactive composition, kafkajs for the
 * broker interface, prom-client for metrics, and debug for structured logging.
 *
 * The monitor is intended to run inside a long-lived Node.js service that owns
 * its own Kafka consumer group for toxicity-scored messages and publishes to
 * an alert topic that downstream systems (e.g., auto-moderation, retraining
 * orchestrator) subscribe to.
 */

'use strict';

/* ──────────────────────────────────────────────────────────────────────────────
 * External dependencies
 * ──────────────────────────────────────────────────────────────────────────── */
const { Subject, timer } = require('rxjs');
const {
  bufferTime,
  filter,
  groupBy,
  mergeMap,
  reduce,
  tap,
  catchError,
} = require('rxjs/operators');
const { Kafka, logLevel } = require('kafkajs');
const client = require('prom-client');
const debug = require('debug')('agorapulse:toxicity-monitor');

/* ──────────────────────────────────────────────────────────────────────────────
 * Prometheus metrics
 * ──────────────────────────────────────────────────────────────────────────── */
const register = client.register;

const metricToxicityAvg = new client.Gauge({
  name: 'agorapulse_toxicity_average',
  help: 'Average toxicity score of messages in the observation window',
  labelNames: ['platform', 'model_version'],
});

const metricToxicityAlerts = new client.Counter({
  name: 'agorapulse_toxicity_alerts_total',
  help: 'Total number of toxicity alerts emitted',
  labelNames: ['platform', 'model_version'],
});

/* ──────────────────────────────────────────────────────────────────────────────
 * Helper utilities
 * ──────────────────────────────────────────────────────────────────────────── */

/**
 * Computes average toxicity for an array of message objects.
 * @param {Array<Object>} messages - Messages buffered in the window.
 * @returns {number} Average toxicity score (0..1). Returns 0 for empty array.
 */
function averageToxicity(messages) {
  if (!messages.length) return 0;
  const sum = messages.reduce((acc, m) => acc + (m.toxicityScore || 0), 0);
  return sum / messages.length;
}

/**
 * Builds a high-quality topic message for alert publication.
 */
function buildAlertMessage({
  platform,
  modelVersion,
  windowMs,
  average,
  threshold,
  sampleSize,
  timestamp,
}) {
  return {
    key: `${platform}:${modelVersion}`,
    value: JSON.stringify({
      eventType: 'TOXICITY_THRESHOLD_BREACHED',
      platform,
      modelVersion,
      aggregate: {
        averageToxicity: average,
        sampleSize,
        windowMs,
      },
      threshold,
      triggeredAt: timestamp,
    }),
    headers: {
      'content-type': 'application/json',
      version: '1',
    },
  };
}

/**
 * Convenience wrapper that swallows producer errors but logs them.
 */
async function safeKafkaSend(producer, topic, messages) {
  if (!messages.length) return;
  try {
    await producer.send({ topic, messages });
  } catch (err) {
    // We do NOT throw; losing an alert is better than crashing the pipeline.
    debug('❌ Failed to send alert batch to Kafka: %O', err);
  }
}

/* ──────────────────────────────────────────────────────────────────────────────
 * ToxicityMonitor – public API
 * ──────────────────────────────────────────────────────────────────────────── */

/**
 * @typedef {Object} ToxicityMonitorConfig
 * @property {string[]} kafkaBrokers             List of broker addresses.
 * @property {string}   alertTopic               Kafka topic to publish alerts to.
 * @property {number}   threshold                Toxicity threshold (0..1).
 * @property {number}   windowMs                 Aggregation window in ms.
 * @property {number}   gracePeriodMs            Delay shutdown to flush buffers.
 * @property {boolean}  enableMetrics            Whether to expose Prom metrics.
 * @property {string}   clientId                 Kafka client id.
 */

/**
 * Streaming toxicity monitor.
 */
class ToxicityMonitor {
  /**
   * @param {ToxicityMonitorConfig} [cfg={}] - Monitor configuration.
   */
  constructor(cfg = {}) {
    /** @private */
    this.cfg = Object.freeze({
      kafkaBrokers: cfg.kafkaBrokers || ['localhost:9092'],
      alertTopic: cfg.alertTopic || 'alerts.toxicity',
      threshold: typeof cfg.threshold === 'number' ? cfg.threshold : 0.8,
      windowMs: cfg.windowMs || 60_000,
      gracePeriodMs: cfg.gracePeriodMs || 5_000,
      enableMetrics: cfg.enableMetrics !== false,
      clientId: cfg.clientId || 'agorapulse-toxicity-monitor',
    });

    /** @private */
    this.input$ = new Subject();

    /** @private */
    this.kafka = new Kafka({
      clientId: this.cfg.clientId,
      brokers: this.cfg.kafkaBrokers,
      logLevel: logLevel.ERROR,
    });

    /** @private */
    this.producer = this.kafka.producer({
      allowAutoTopicCreation: false,
      idempotent: true,
    });

    this._isRunning = false;
    this._subscriptions = [];
  }

  /**
   * Pushes a new inference message into the monitor pipeline.
   * @param {Object} msg - Real-time inference result.
   * @param {string} msg.platform - Source platform (e.g., twitter, discord).
   * @param {string} msg.modelVersion - ML model version that produced score.
   * @param {number} msg.toxicityScore - Score ∈ [0,1].
   * @param {number} [msg.timestamp] - Epoch ms; defaults to Date.now().
   */
  ingest(msg) {
    if (!this._isRunning) return;
    this.input$.next({
      timestamp: msg.timestamp || Date.now(),
      ...msg,
    });
  }

  /**
   * Starts the streaming pipeline and the Kafka producer.
   */
  async start() {
    if (this._isRunning) return;
    await this.producer.connect();
    this._isRunning = true;
    this._bootstrapPipeline();
    debug(
      '🚀 Toxicity monitor started with threshold=%d window=%dms topic=%s brokers=%o',
      this.cfg.threshold,
      this.cfg.windowMs,
      this.cfg.alertTopic,
      this.cfg.kafkaBrokers,
    );
  }

  /**
   * Graceful shutdown: flush buffers and close Kafka connection.
   */
  async shutdown() {
    if (!this._isRunning) return;
    this._isRunning = false;

    // Allow in-flight buffers to be processed.
    await new Promise((res) => setTimeout(res, this.cfg.gracePeriodMs));

    this._subscriptions.forEach((sub) => sub.unsubscribe());
    await this.producer.disconnect();
    this.input$.complete();
    debug('🛑 Toxicity monitor stopped');
  }

  /* ──────────────────────────────────────────────────────────────────────────
   * Internal
   * ──────────────────────────────────────────────────────────────────────── */

  /**
   * Constructs the RxJS pipeline for aggregation and alerting.
   * @private
   */
  _bootstrapPipeline() {
    const sub = this.input$
      .pipe(
        bufferTime(this.cfg.windowMs),
        filter((arr) => arr.length > 0),

        // Group buffered messages by platform & model version
        mergeMap((buffer) =>
          // rxjs groupBy returns grouped Observables
          buffer
            .reduce((acc, msg) => {
              const key = `${msg.platform}|${msg.modelVersion}`;
              acc[key] = acc[key] || [];
              acc[key].push(msg);
              return acc;
            }, {})
            .entries(),
        ),
        mergeMap(([key, messages]) => {
          const [platform, modelVersion] = key.split('|');
          const avg = averageToxicity(messages);

          // Update Prometheus gauge
          if (this.cfg.enableMetrics) {
            metricToxicityAvg
              .labels(platform, modelVersion)
              .set(avg);
          }

          const breach = avg >= this.cfg.threshold;
          return breach
            ? [
                {
                  platform,
                  modelVersion,
                  average: avg,
                  sampleSize: messages.length,
                  windowMs: this.cfg.windowMs,
                },
              ]
            : [];
        }),
        tap((alert) => {
          metricToxicityAlerts
            .labels(alert.platform, alert.modelVersion)
            .inc();
        }),
        catchError((err, caught) => {
          debug('⚠️ Stream error: %O', err);
          return caught; // resume stream
        }),
      )
      .subscribe((alert) => this._publishAlert(alert));

    this._subscriptions.push(sub);

    // Optionally export Prometheus metrics endpoint (default: :9464/metrics)
    if (this.cfg.enableMetrics) {
      this._setupMetricsEndpoint();
    }
  }

  /**
   * Publishes a toxicity alert to Kafka.
   * @private
   * @param {Object} alert - Alert data from stream.
   */
  async _publishAlert(alert) {
    const message = buildAlertMessage({
      ...alert,
      threshold: this.cfg.threshold,
      timestamp: Date.now(),
    });
    await safeKafkaSend(this.producer, this.cfg.alertTopic, [message]);
    debug(
      '🔔 Toxicity alert published – platform=%s model=%s avg=%d sample=%d',
      alert.platform,
      alert.modelVersion,
      alert.average.toFixed(4),
      alert.sampleSize,
    );
  }

  /**
   * Launches an HTTP server exposing /metrics for Prometheus scraping.
   * Uses the default prom-client registry.
   * @private
   */
  _setupMetricsEndpoint() {
    const http = require('http');
    const PORT = process.env.TOXICITY_MONITOR_METRICS_PORT || 9464;

    http
      .createServer(async (req, res) => {
        if (req.url === '/metrics') {
          res.writeHead(200, { 'Content-Type': register.contentType });
          res.end(await register.metrics());
        } else {
          res.writeHead(404);
          res.end();
        }
      })
      .listen(PORT, () => {
        debug('📈 Prometheus metrics exposed on :%d/metrics', PORT);
      })
      .on('error', (err) =>
        debug('❌ Failed to start metrics endpoint: %O', err),
      );
  }
}

/* ──────────────────────────────────────────────────────────────────────────────
 * Module exports
 * ──────────────────────────────────────────────────────────────────────────── */

module.exports = {
  ToxicityMonitor,
  averageToxicity,
};
