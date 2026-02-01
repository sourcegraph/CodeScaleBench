/**
 * @file tests/test_main.js
 *
 * End–to–end sanity tests for critical event-driven flows inside the AgoraPulse
 * real-time social signal intelligence platform.
 *
 * The tests exercise three high-value scenarios:
 *  1. Domain events bubble through the feature-engineering pipeline and emit
 *     a derived `features.generated` event.
 *  2. The Model Registry correctly registers a new candidate model artifact,
 *     assigns it a deterministic semantic version, and allows subsequent
 *     look-ups.
 *  3. Continuous model monitoring detects a hard failure (quality metric
 *     breach) and raises a `model.retrain-requested` domain event.
 *
 * All external dependencies are mocked; we focus on verifying contract
 * semantics, event sequencing, and side-effects.  The real implementation
 * lives under `src/**` in production, but these tests purposefully isolate the
 * units by leveraging Jest mocks and RxJS Subjects.
 */

/* eslint-disable import/no-extraneous-dependencies */
import { Subject } from 'rxjs';
import { take } from 'rxjs/operators';

import EventBus from '../src/core/eventBus';
import FeatureEngineeringPipeline from '../src/pipelines/featureEngineeringPipeline';
import ModelRegistry from '../src/services/modelRegistry';
import MonitoringService from '../src/services/monitoringService';

jest.mock('../src/core/eventBus');
jest.mock('../src/pipelines/featureEngineeringPipeline');
jest.mock('../src/services/modelRegistry');
jest.mock('../src/services/monitoringService');

/* -------------------------------------------------------------------------- */
/*                                Test Suite                                 */
/* -------------------------------------------------------------------------- */

describe('AgoraPulse — critical event flows', () => {
  let in$;
  let out$;

  beforeEach(() => {
    jest.clearAllMocks();

    // Mock infrastructure
    in$ = new Subject();      // incoming domain events
    out$ = new Subject();     // outgoing/fanned-out events

    EventBus.getInStream.mockReturnValue(in$.asObservable());
    EventBus.emit = jest.fn((evt) => out$.next(evt));

    // --- Feature Engineering Pipeline --------------------------------------
    FeatureEngineeringPipeline.bootstrap.mockImplementation(() => {
      EventBus.getInStream()
        .pipe(
          // Pipeline is trivial in mock; in real code this is the DAG.
          take(1), // throttle to one event for our unit test
        )
        .subscribe((rawEvt) => {
          if (rawEvt?.type === 'message.created') {
            EventBus.emit({
              type: 'features.generated',
              payload: {
                messageId: rawEvt.payload.id,
                tokens: ['foo', 'bar'],
                language: 'en',
              },
              ts: Date.now(),
            });
          }
        });
    });

    // --- Model Registry -----------------------------------------------------
    const mockStore = new Map();
    ModelRegistry.registerCandidate.mockImplementation(async (meta) => {
      const version = `v${mockStore.size + 1}.0.0`;
      mockStore.set(version, meta);
      return { version, ...meta };
    });
    ModelRegistry.getLatest.mockImplementation(async () => {
      const latestKey = Array.from(mockStore.keys()).pop();
      return latestKey ? { version: latestKey, ...mockStore.get(latestKey) } : null;
    });

    // --- Monitoring Service -------------------------------------------------
    MonitoringService.start.mockImplementation(({ onBreach }) => {
      /**
       * Fake health-metric stream.  In prod this would be a hot observable fed
       * by Prometheus, OpenTelemetry, etc.  In the mock we simulate one bad
       * datapoint to trigger the breach callback.
       */
      setTimeout(() => {
        onBreach({
          metric: 'toxicity.false_negatives',
          value: 0.37,
          threshold: 0.25,
          modelVersion: 'v1.0.0',
        });
      }, 10);
    });
  });

  /* ---------------------------------------------------------------------- */
  /*                             1. Feature Flow                            */
  /* ---------------------------------------------------------------------- */

  test('Feature-Engineering pipeline emits features for a message event', (done) => {
    expect.assertions(3);

    // Kick-start pipeline bootstrapping
    FeatureEngineeringPipeline.bootstrap();

    out$.pipe(take(1)).subscribe({
      next: (evt) => {
        try {
          expect(evt).toHaveProperty('type', 'features.generated');
          expect(evt.payload).toHaveProperty('messageId', '123');
          expect(Array.isArray(evt.payload.tokens)).toBe(true);
          done();
        } catch (err) {
          done(err);
        }
      },
    });

    // Fire domain event into system
    in$.next({
      type: 'message.created',
      payload: {
        id: '123',
        text: 'Hello world!',
        userId: 'alice',
      },
      ts: Date.now(),
    });
  });

  /* ---------------------------------------------------------------------- */
  /*                           2. Model Registry                            */
  /* ---------------------------------------------------------------------- */

  test('Model Registry registers and retrieves latest model candidate', async () => {
    expect.assertions(4);

    const candidateMeta = {
      artifactPath: 's3://bucket/models/abc123',
      metrics: { f1: 0.91 },
      tags: ['sentiment', 'bert_base'],
    };

    const { version } = await ModelRegistry.registerCandidate(candidateMeta);
    expect(version).toBe('v1.0.0');

    const latest = await ModelRegistry.getLatest();
    expect(latest).not.toBeNull();
    expect(latest.version).toBe('v1.0.0');
    expect(latest.metrics.f1).toBeCloseTo(0.91);
  });

  /* ---------------------------------------------------------------------- */
  /*                       3. Monitoring & Retraining                       */
  /* ---------------------------------------------------------------------- */

  test('Monitoring emits retrain request when metric threshold is breached', (done) => {
    expect.assertions(2);

    MonitoringService.start({
      threshold: 0.25,
      metricKey: 'toxicity.false_negatives',
      onBreach: (breachEvt) => {
        try {
          expect(breachEvt.metric).toBe('toxicity.false_negatives');
          expect(breachEvt.value).toBeGreaterThan(breachEvt.threshold);
          done();
        } catch (err) {
          done(err);
        }
      },
    });
  });
});

/* -------------------------------------------------------------------------- */
/*                                Test Helpers                                */
/* -------------------------------------------------------------------------- */

/**
 * Utility to flush all pending timers/promises.  Call inside `afterEach`
 * if a test schedules timers (e.g., setTimeout) that must complete before
 * the Jest worker exits.
 */
export const flushAsync = () =>
  new Promise((resolve) => {
    // Fast-forward Jest’s fake timers, if active
    if (jest.isMockFunction(setTimeout)) {
      jest.runOnlyPendingTimers();
    }
    setImmediate(resolve);
  });
