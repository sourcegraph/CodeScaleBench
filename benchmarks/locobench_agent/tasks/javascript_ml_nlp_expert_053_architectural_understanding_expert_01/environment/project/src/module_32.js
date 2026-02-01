```javascript
/**
 * src/module_32.js
 *
 * AgoraPulse: Real-Time Social Signal Intelligence — Model Monitoring
 *
 * This module implements an end-to-end, event-driven toxicity monitor that listens
 * to Kafka inference streams, aggregates model outputs with RxJS, and pushes
 * actionable alerts through pluggable strategies (Slack, e-mail, PagerDuty, etc.).
 *
 * Patterns used:
 *   • Observer / Reactive Streams (Kafka + RxJS)
 *   • Strategy (alerting channel implementations)
 *   • Factory (builds alert strategies from config)
 *   • Circuit-Breaker fallback for external integrations
 *
 * External deps (add to package.json):
 *   "kafkajs": "^2.2.4",
 *   "rxjs": "^7.8.1",
 *   "@slack/web-api": "^6.9.1",
 *   "nodemailer": "^6.9.3",
 *   "lodash": "^4.17.21",
 *   "opossum": "^7.2.3"                 // simple circuit-breaker lib
 */

'use strict';

import { Kafka } from 'kafkajs';
import { WebClient as SlackClient } from '@slack/web-api';
import nodemailer from 'nodemailer';
import * as Rx from 'rxjs';
import {
  map,
  filter,
  bufferTime,
  mergeMap,
  catchError,
  tap,
} from 'rxjs/operators';
import circuitBreaker from 'opossum';
import _ from 'lodash';

/* -------------------------------------------------------------------------- */
/*                                Configuration                               */
/* -------------------------------------------------------------------------- */

const DEFAULT_MONITOR_CONFIG = {
  kafka: {
    clientId: 'agorapulse-toxicity-monitor',
    brokers: process.env.KAFKA_BROKERS?.split(',') ?? ['localhost:9092'],
    groupId: 'toxicity-monitor-consumer-group',
    topic: 'agorapulse.inference.toxicity',
  },
  threshold: 0.85,               // Toxicity probability threshold
  windowMs: 10_000,              // Aggregation window
  minAlertsPerWindow: 3,         // How many violations trigger an alert
  alertChannels: ['slack'],      // default
  slack: { channel: '#moderators' },
  email: {                       // only used if 'email' is in alertChannels
    from: 'alerts@agorapulse.io',
    to: ['sre@agorapulse.io'],
  },
};

/* -------------------------------------------------------------------------- */
/*                         Alert Strategy Abstractions                        */
/* -------------------------------------------------------------------------- */

/**
 * @interface
 */
class AlertStrategy {
  /**
   * @param {object} payload
   * @returns {Promise<void>}
   */
  async sendAlert(payload) {
    throw new Error('sendAlert() must be implemented by subclass');
  }
}

/**
 * Slack alert strategy
 */
class SlackAlertStrategy extends AlertStrategy {
  /**
   * @param {object} options
   * @param {string} options.token – Slack Bot OAuth token
   * @param {string} options.channel – channel ID or name
   */
  constructor({ token = process.env.SLACK_TOKEN, channel }) {
    super();
    this.channel = channel;
    this.slack = new SlackClient(token);
    this.cb = circuitBreaker(
      (message) =>
        this.slack.chat.postMessage({
          text: message,
          channel: this.channel,
        }),
      { timeout: 5000, errorThresholdPercentage: 50, resetTimeout: 30_000 },
    );
  }

  async sendAlert({ violations, windowMs, threshold }) {
    const message = `🚨 *Toxicity spike detected*\n• Violations: *${violations}*\n• Window: *${windowMs /
      1000}s*\n• Threshold: *${threshold}*`;
    await this.cb.fire(message);
  }
}

/**
 * E-mail alert strategy
 */
class EmailAlertStrategy extends AlertStrategy {
  /**
   * @param {object} options
   * @param {string} options.from
   * @param {string[]} options.to
   * @param {object} [options.smtp]
   */
  constructor({ from, to, smtp = {} }) {
    super();
    this.transporter = nodemailer.createTransport({
      // Accepts SMTP_URL env var for convenience
      ...(process.env.SMTP_URL
        ? { url: process.env.SMTP_URL }
        : {
            host: smtp.host || 'localhost',
            port: smtp.port || 25,
            secure: false,
          }),
    });
    this.from = from;
    this.to = to;
    this.cb = circuitBreaker(
      (mail) => this.transporter.sendMail(mail),
      { timeout: 7000, errorThresholdPercentage: 25, resetTimeout: 60_000 },
    );
  }

  async sendAlert({ violations, windowMs, threshold }) {
    const subject = `[AgoraPulse] Toxicity spike (${violations} events)`;
    const text = `Detected ${violations} toxic messages in ${windowMs /
      1000}s (prob >= ${threshold}). Immediate attention recommended.`;
    await this.cb.fire({ from: this.from, to: this.to, subject, text });
  }
}

/**
 * @param {string[]} channels
 * @param {object} cfg
 * @returns {AlertStrategy[]}
 */
function buildAlertStrategies(channels, cfg) {
  return channels.map((ch) => {
    switch (ch) {
      case 'slack':
        return new SlackAlertStrategy({
          channel: cfg.slack.channel,
        });
      case 'email':
        return new EmailAlertStrategy({
          from: cfg.email.from,
          to: cfg.email.to,
        });
      default:
        throw new Error(`Unsupported alert channel "${ch}"`);
    }
  });
}

/* -------------------------------------------------------------------------- */
/*                               Core Monitor                                 */
/* -------------------------------------------------------------------------- */

export class ToxicityMonitor {
  /**
   * @param {Partial<typeof DEFAULT_MONITOR_CONFIG>} [config]
   */
  constructor(config = {}) {
    this.config = _.merge({}, DEFAULT_MONITOR_CONFIG, config);
    this.alertStrategies = buildAlertStrategies(
      this.config.alertChannels,
      this.config,
    );

    // Kafka config
    this.kafka = new Kafka({
      clientId: this.config.kafka.clientId,
      brokers: this.config.kafka.brokers,
    });
    this.consumer = this.kafka.consumer({
      groupId: this.config.kafka.groupId,
    });

    // Graceful shutdown support
    ['SIGINT', 'SIGTERM'].forEach((sig) =>
      process.on(sig, async () => {
        await this.stop();
        process.exit(0);
      }),
    );
  }

  /**
   * Connects to Kafka and starts consuming.
   */
  async start() {
    await this.consumer.connect();
    await this.consumer.subscribe({
      topic: this.config.kafka.topic,
      fromBeginning: false,
    });

    // Convert Kafka messages into an RxJS Observable
    const message$ = new Rx.Subject();

    await this.consumer.run({
      eachMessage: async ({ message }) => {
        try {
          message$.next({
            ...JSON.parse(message.value.toString('utf-8')),
            timestamp: Number(message.timestamp),
          });
        } catch (err) {
          // malformed JSON – log and skip
          console.error('[ToxicityMonitor] Malformed message', err);
        }
      },
    });

    // Build pipeline
    this.subscription = message$
      .pipe(
        filter((msg) => 'toxicity' in msg),
        map((msg) => ({
          toxicity: Number(msg.toxicity),
          ts: msg.timestamp ?? Date.now(),
        })),
        filter((msg) => !Number.isNaN(msg.toxicity)),
        bufferTime(this.config.windowMs), // aggregate by window
        filter((arr) => arr.length > 0),
        map((arr) => {
          const violations = arr.filter(
            (x) => x.toxicity >= this.config.threshold,
          ).length;
          return { violations };
        }),
        filter(
          ({ violations }) => violations >= this.config.minAlertsPerWindow,
        ),
        mergeMap(async (aggregated) => {
          // Dispatch alerts in parallel
          await Promise.allSettled(
            this.alertStrategies.map((s) =>
              s.sendAlert({
                ...aggregated,
                windowMs: this.config.windowMs,
                threshold: this.config.threshold,
              }),
            ),
          );
          return aggregated;
        }),
        tap(({ violations }) =>
          console.info(
            `[ToxicityMonitor] Alert dispatched (${violations} events)`,
          ),
        ),
        catchError((err, src) => {
          console.error('[ToxicityMonitor] pipeline error', err);
          return src; // keep observable alive
        }),
      )
      .subscribe();
  }

  /**
   * Stops consuming and cleans up.
   */
  async stop() {
    try {
      await this.subscription?.unsubscribe();
      await this.consumer.disconnect();
      console.info('[ToxicityMonitor] stopped');
    } catch (err) {
      console.error('[ToxicityMonitor] stop error', err);
    }
  }
}

/* -------------------------------------------------------------------------- */
/*                                 Entrypoint                                 */
/* -------------------------------------------------------------------------- */

if (require.main === module) {
  // Allow simple CLI execution: `node src/module_32.js`
  (async () => {
    const monitor = new ToxicityMonitor();
    await monitor.start();
    console.info('[ToxicityMonitor] running…');
  })().catch((err) => {
    console.error('[ToxicityMonitor] fatal', err);
    process.exit(1);
  });
}
```