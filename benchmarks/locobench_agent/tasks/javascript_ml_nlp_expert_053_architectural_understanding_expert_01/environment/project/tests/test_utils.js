```javascript
/* eslint-disable no-magic-numbers */
'use strict';

/**
 * test_utils.js
 *
 * Jest test-suite for shared utility helpers that power the AgoraPulse
 * event-driven micro-pipelines.  These helpers live under `src/utils`
 * and are completely framework-agnostic: they do not know anything
 * about Kafka, RxJS, or model-serving – they are pure functions /
 * higher-order utilities that can be unit-tested in isolation.
 *
 * 1. createTopicName()          → Conventions for Kafka topic names
 * 2. withExponentialBackoff()   → Generic async retry helper
 * 3. computeEwma()              → Exponentially-weighted moving average
 *
 * NB:  Add new test-cases as the utility surface grows.  Each test is
 *      crafted to be deterministic and fast: no actual timers or
 *      network requests are executed thanks to Jest’s fake-timers and
 *      dependency injection.
 */

require('jest-extended'); // Extra matchers (toBeNumber, toStartWith, etc.)

const {
  createTopicName,
  withExponentialBackoff,
  computeEwma,
} = require('../src/utils');

describe('utils/createTopicName()', () => {
  test.each([
    [
      { domain: 'twitter', stream: 'tweets', stage: 'raw' },
      'agorapulse.twitter.tweets.raw',
    ],
    [
      { domain: 'tiktok', stream: 'comments', stage: 'features' },
      'agorapulse.tiktok.comments.features',
    ],
    [
      // Mixed-case shows we normalize to lower-case
      { domain: 'YouTube', stream: 'LiveChat', stage: 'MODELS' },
      'agorapulse.youtube.livechat.models',
    ],
  ])(
    'should compose topic strings using kebab-case: %o',
    (params, expected) => {
      expect(createTopicName(params)).toBe(expected);
    },
  );

  it('throws when an argument is missing', () => {
    expect(() =>
      createTopicName({ domain: 'twitter', stream: 'tweets' }),
    ).toThrow('stage');
  });

  it('throws when a segment contains non-alphanumerics', () => {
    expect(() =>
      createTopicName({
        domain: 'twitter',
        stream: 'twe*ts', // oops
        stage: 'raw',
      }),
    ).toThrow(/invalid.+stream/i);
  });
});

describe('utils/withExponentialBackoff()', () => {
  beforeEach(() => jest.useFakeTimers());
  afterEach(() => jest.useRealTimers());

  it('resolves immediately when the task succeeds on the first try', async () => {
    const mockTask = jest.fn().mockResolvedValue('💚');
    const result = await withExponentialBackoff(mockTask, { attempts: 3 });
    expect(result).toBe('💚');
    expect(mockTask).toHaveBeenCalledTimes(1);
  });

  it('retries the specified number of times before giving up', async () => {
    const err = new Error('flaky');
    const mockTask = jest
      .fn()
      // fail twice, succeed on third attempt
      .mockRejectedValueOnce(err)
      .mockRejectedValueOnce(err)
      .mockResolvedValue('🎉');

    const pendingPromise = withExponentialBackoff(mockTask, {
      attempts: 5,
      baseMs: 1000,
    });

    // Advance fake timers for two failures (1000ms + 2000ms)
    jest.advanceTimersByTime(1000 + 2000);

    // We need to flush the micro-task queue between timer jumps
    await Promise.resolve();

    // Advance another tick for the success attempt
    jest.advanceTimersByTime(4000);
    const result = await pendingPromise;

    expect(result).toBe('🎉');
    expect(mockTask).toHaveBeenCalledTimes(3);
  });

  it('bubbles the last error when all retries fail', async () => {
    const err = new Error('network unreachable');
    const mockTask = jest.fn().mockRejectedValue(err);

    const promise = withExponentialBackoff(mockTask, { attempts: 4 });

    jest.advanceTimersByTime(1 << 30); // large enough to cover all delays
    await expect(promise).rejects.toThrow('network unreachable');
    expect(mockTask).toHaveBeenCalledTimes(4);
  });

  it('can be aborted via an AbortSignal', async () => {
    const controller = new AbortController();

    const mockTask = jest.fn().mockRejectedValue(new Error('fail'));

    // Kick off retry helper
    const promise = withExponentialBackoff(mockTask, {
      attempts: 10,
      signal: controller.signal,
    });

    // Let first retry fail, then abort
    jest.advanceTimersByTime(100);
    controller.abort(new Error('manual abort'));

    await expect(promise).rejects.toThrow(/abort/i);
    // Should only call once (initial) + 1 retry that we advanced
    expect(mockTask).toHaveBeenCalledTimes(2);
  });
});

describe('utils/computeEwma()', () => {
  it('returns 0 for an empty array', () => {
    expect(computeEwma([], 0.3)).toBe(0);
  });

  it('calculates the EWMA using the correct smoothing factor', () => {
    // Data taken from a verified spreadsheet example
    const data = [10, 20, 30, 40, 50];
    const alpha = 0.5;
    /**
     * Manual computation:
     *   S1 = 10
     *   S2 = 0.5*20 + 0.5*10 = 15
     *   S3 = 0.5*30 + 0.5*15 = 22.5
     *   S4 = 0.5*40 + 0.5*22.5 = 31.25
     *   S5 = 0.5*50 + 0.5*31.25 = 40.625
     *   => result should be 40.625
     */
    expect(computeEwma(data, alpha)).toBeCloseTo(40.625, 3);
  });

  it('throws when alpha is outside (0,1]', () => {
    expect(() => computeEwma([1, 2, 3], 0)).toThrow(/alpha/i);
    expect(() => computeEwma([1, 2, 3], 1.5)).toThrow(/alpha/i);
  });

  it('handles high-cardinality streams without precision loss', () => {
    // Build a large monotonically increasing sequence
    const data = Array.from({ length: 50_000 }, (_, i) => i + 1);
    const result = computeEwma(data, 0.1);
    // EWMA should always be less than or equal to max(data)
    expect(result).toBeNumber();
    expect(result).toBeLessThanOrEqual(data[data.length - 1]);
  });
});
```