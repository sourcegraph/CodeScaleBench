```typescript
/**
 * Integration-style unit tests for the most critical coordination path:
 *   1) Social/Infra metric correlation (SentimentCorrelator)
 *   2) Capacity remediation trigger (CapacityOrchestrator)
 *
 * The tests lean on Jest’s mocking facilities to isolate collaborators while still
 * exercising real-world behaviour (e.g. strategy selection, error bubbling, etc.).
 *
 * NOTE:
 *   – All imports reference the “src/” tree as it exists in the production code-base.
 *   – test setup/teardown is idempotent so the file can be executed in parallel CI.
 */

import { jest } from '@jest/globals';
import { SentimentCorrelator } from '../src/core/analytics/SentimentCorrelator';
import { CapacityOrchestrator } from '../src/core/orchestration/CapacityOrchestrator';
import { MetricSample } from '../src/types/metrics';
import { SocialEvent } from '../src/types/social';
import { ScaleCommand } from '../src/core/orchestration/commands/ScaleCommand';
import { Logger } from '../src/shared/logging/Logger';

/* -------------------------------------------------------------------------- */
/*                        ── Shared mocks & test scaffolding ──               */
/* -------------------------------------------------------------------------- */

// A deterministic timestamp used throughout this test-suite.
const NOW = new Date('2033-04-05T12:00:00.000Z');

// Freeze time so every component acts as if “now” is our constant value.
jest.useFakeTimers().setSystemTime(NOW);

// Mock the cross-cutting logger so the test output stays clean.
jest.mock('../src/shared/logging/Logger', () => ({
  Logger: {
    child: jest.fn().mockReturnValue({
      info: jest.fn(),
      warn: jest.fn(),
      error: jest.fn(),
      debug: jest.fn(),
    }),
  },
}));

/* -------------------------------------------------------------------------- */
/*                               ── Fixtures ──                               */
/* -------------------------------------------------------------------------- */

const sampleMetrics: MetricSample[] = [
  {
    timestamp: new Date(NOW.getTime() - 30_000), // 30 seconds ago
    podId: 'api-gateway-66dd98cc7b-xzsa1',
    cpu: 0.83,
    mem: 0.71,
    rps: 14_200,
  },
  {
    timestamp: new Date(NOW.getTime() - 10_000), // 10 seconds ago
    podId: 'api-gateway-66dd98cc7b-xzsa1',
    cpu: 0.91,
    mem: 0.77,
    rps: 17_300,
  },
];

const socialEvents: SocialEvent[] = [
  {
    timestamp: new Date(NOW.getTime() - 32_000), // ~ same timeframe
    type: 'HASHTAG_TREND',
    payload: {
      hashtag: '#SolarEclipse',
      region: 'US-CA',
      projectedReach: 1_800_000,
    },
  },
  {
    timestamp: new Date(NOW.getTime() - 11_000),
    type: 'INFLUENCER_LIVE',
    payload: {
      influencerId: '0xF00DBABE',
      followerCount: 3_400_000,
    },
  },
];

/* -------------------------------------------------------------------------- */
/*                        ── SentimentCorrelator tests ──                     */
/* -------------------------------------------------------------------------- */

describe('SentimentCorrelator', () => {
  it('correlates infra metrics with social spikes correctly', async () => {
    const correlator = new SentimentCorrelator();

    const result = await correlator.correlate(sampleMetrics, socialEvents);

    expect(result).toMatchObject({
      correlationWindow: { from: expect.any(Date), to: expect.any(Date) },
      correlatedMetrics: expect.arrayContaining(sampleMetrics),
      socialAmplifiers: expect.arrayContaining(socialEvents),
      correlationScore: expect.any(Number),
    });

    // Ensure the correlation score is > 0 (meaning there is some influence).
    expect(result.correlationScore).toBeGreaterThan(0.5);
  });

  it('returns an empty correlation when no temporal overlap exists', async () => {
    const correlator = new SentimentCorrelator();

    const farPastMetrics: MetricSample[] = [
      {
        timestamp: new Date('2029-01-01T00:00:00Z'),
        podId: 'legacy-pod-123',
        cpu: 0.22,
        mem: 0.18,
        rps: 120,
      },
    ];

    const result = await correlator.correlate(farPastMetrics, socialEvents);

    expect(result.correlationScore).toBe(0);
    expect(result.socialAmplifiers).toHaveLength(0);
    expect(result.correlatedMetrics).toHaveLength(0);
  });

  it('fails fast when invoked with malformed data', async () => {
    const correlator = new SentimentCorrelator();

    // @ts-expect-error – intentionally passing invalid payload to test guard-rails
    await expect(correlator.correlate(null, undefined)).rejects.toThrow(
      /Invalid .* payload/i,
    );
  });
});

/* -------------------------------------------------------------------------- */
/*                     ── CapacityOrchestrator integration tests ──           */
/* -------------------------------------------------------------------------- */

describe('CapacityOrchestrator', () => {
  const mockSendCommand = jest.fn();
  const orchestrator = new CapacityOrchestrator({
    commandBus: {
      send: mockSendCommand,
    } as never, // Narrowing for test purposes
    logger: Logger.child({ module: 'CapacityOrchestratorTest' }),
  });

  afterEach(() => {
    jest.clearAllMocks();
  });

  it('emits a ScaleCommand when correlation score breaches SLA', async () => {
    const mockCorrelation = {
      correlationWindow: {
        from: new Date(NOW.getTime() - 60_000),
        to: NOW,
      },
      correlatedMetrics: sampleMetrics,
      socialAmplifiers: socialEvents,
      correlationScore: 0.92,
    };

    await orchestrator.evaluateAndAct(mockCorrelation);

    expect(mockSendCommand).toHaveBeenCalledTimes(1);

    const [command] = mockSendCommand.mock.calls[0];
    expect(command).toBeInstanceOf(ScaleCommand);
    expect((command as ScaleCommand).desiredReplicas).toBeGreaterThan(0);
  });

  it('does not emit ScaleCommand when system is within healthy bounds', async () => {
    const healthyCorrelation = {
      correlationWindow: {
        from: new Date(NOW.getTime() - 60_000),
        to: NOW,
      },
      correlatedMetrics: sampleMetrics,
      socialAmplifiers: [],
      correlationScore: 0.1, // Low score => normal ops
    };

    await orchestrator.evaluateAndAct(healthyCorrelation);

    expect(mockSendCommand).not.toHaveBeenCalled();
  });

  it('logs & bubbles up unexpected errors from downstream handlers', async () => {
    const faultyCorrelation = {
      correlationWindow: {
        from: new Date(NOW.getTime() - 60_000),
        to: NOW,
      },
      correlatedMetrics: sampleMetrics,
      socialAmplifiers: socialEvents,
      correlationScore: 0.88,
    };

    // Force the command bus to throw.
    mockSendCommand.mockImplementationOnce(() => {
      throw new Error('Kafka timeout');
    });

    await expect(orchestrator.evaluateAndAct(faultyCorrelation)).rejects.toThrow(
      /Kafka timeout/,
    );
  });
});
```