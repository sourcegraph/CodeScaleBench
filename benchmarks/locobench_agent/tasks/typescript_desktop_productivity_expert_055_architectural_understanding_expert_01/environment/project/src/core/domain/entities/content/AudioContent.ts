```typescript
/**************************************************************************
 * PaletteFlow Studio – Core Domain
 * File: src/core/domain/entities/content/AudioContent.ts
 *
 * Description:
 *   Immutable domain entity that models an audio payload attached to a
 *   CanvasNode.  The entity contains only business-critical state—raw PCM
 *   buffers and UI-concerns are purposely excluded to keep the core layer
 *   framework-agnostic.  Behaviour that manipulates the entity (trimming,
 *   transcript injection, etc.) is expressed as pure functions that return
 *   a NEW instance, thereby preserving referential transparency while still
 *   enabling snapshotting and time-travel within higher layers (view-models
 *   and persistence mappers).
 *
 *   NOTE: All helper types used here (UniqueEntityID, Result, etc.) exist
 *   in the domain’s shared kernel.  They are referenced rather than
 *   re-implemented to keep concerns separated.
 **************************************************************************/

import { v4 as uuid } from 'uuid';                         // Small helper, no runtime burden
import deepFreeze from 'deep-freeze-strict';               // Guarantees immutability
import { Result, success, failure } from '../../common/Result';
import { DomainEvent, EventPublisher } from '../../common/events';
import { Guard } from '../../common/Guard';
import { Duration } from '../../value-objects/Duration';
import { UniqueEntityID } from '../../value-objects/UniqueEntityID';
import { Content } from './Content';
import { ContentType } from './ContentType';

/* ---------------------------------------------------------------------- */
/*                              Value Objects                              */
/* ---------------------------------------------------------------------- */

/**
 * A self-contained fragment of an automatic transcript.
 */
export interface TranscriptSegment {
  readonly startTime: number;      // Seconds from zero
  readonly endTime: number;        // Seconds from zero
  readonly text: string;
  readonly confidence: number;     // 0.0 – 1.0
}

/**
 * Simple aggregate for audio codec information.
 */
export interface AudioCodecInfo {
  readonly codec: 'pcm' | 'aac' | 'opus' | 'flac' | 'alac' | 'mp3' | string;
  readonly sampleRate: number;     // Hz
  readonly bitDepth: number;       // Bits
  readonly channels: number;       // 1 = mono, 2 = stereo, etc.
}

/* ---------------------------------------------------------------------- */
/*                              Domain Events                              */
/* ---------------------------------------------------------------------- */

export class AudioContentTranscribed implements DomainEvent {
  readonly name = 'audio-content.transcribed';
  readonly occurredOn: Date;
  constructor(
    public readonly audioContentId: UniqueEntityID,
    public readonly segments: readonly TranscriptSegment[]
  ) {
    this.occurredOn = new Date();
  }
}

export class AudioContentTrimmed implements DomainEvent {
  readonly name = 'audio-content.trimmed';
  readonly occurredOn: Date;
  constructor(
    public readonly audioContentId: UniqueEntityID,
    public readonly originalDuration: Duration,
    public readonly newDuration: Duration
  ) {
    this.occurredOn = new Date();
  }
}

/* ---------------------------------------------------------------------- */
/*                                Entity                                   */
/* ---------------------------------------------------------------------- */

export interface AudioContentProps {
  readonly sourceUri: string;                           // E.g. file:///tmp/foo.m4a
  readonly duration: Duration;                          // Total play length
  readonly codecInfo: AudioCodecInfo;                   // Sampling details
  readonly waveformPreview?: Readonly<Float32Array>;    // Down-sampled envelope
  readonly transcript?: readonly TranscriptSegment[];   // Optional speech-to-text
  readonly createdAt?: Date;
  readonly updatedAt?: Date;
  readonly version?: number;
}

export class AudioContent implements Content<AudioContentProps> {
  /* Domain identity */
  public readonly id: UniqueEntityID;
  public readonly type: ContentType = ContentType.AUDIO;

  /* Immutable state */
  private readonly props: AudioContentProps;

  /* ------------------------------------------------------------------ */
  /*                            Constructor                             */
  /* ------------------------------------------------------------------ */

  private constructor(id: UniqueEntityID, props: AudioContentProps) {
    this.id = id;
    this.props = deepFreeze({            // Freeze to prevent accidental mutation
      ...props,
      version: props.version ?? 1,
      createdAt: props.createdAt ?? new Date(),
      updatedAt: props.updatedAt ?? new Date(),
      transcript: props.transcript ?? []
    });
  }

  /* ------------------------------------------------------------------ */
  /*                         Static Factories                           */
  /* ------------------------------------------------------------------ */

  /**
   * Factory that validates invariants before creating the entity.
   */
  public static create(
    props: AudioContentProps,
    id: UniqueEntityID = new UniqueEntityID(uuid())
  ): Result<AudioContent> {
    const nullOrUndefinedGuard = Guard.againstNullOrUndefinedBulk([
      { argument: props.sourceUri, argumentName: 'sourceUri' },
      { argument: props.duration, argumentName: 'duration' },
      { argument: props.codecInfo, argumentName: 'codecInfo' }
    ]);

    if (!nullOrUndefinedGuard.succeeded) {
      return failure<AudioContent>(nullOrUndefinedGuard.message);
    }

    if (props.duration.milliseconds <= 0) {
      return failure<AudioContent>('Duration must be greater than zero.');
    }

    if (props.transcript && !AudioContent.isTranscriptValid(props.transcript)) {
      return failure<AudioContent>('Transcript segments are not ordered or overlap.');
    }

    return success<AudioContent>(new AudioContent(id, props));
  }

  /* ------------------------------------------------------------------ */
  /*                               Getters                              */
  /* ------------------------------------------------------------------ */

  get sourceUri(): string {
    return this.props.sourceUri;
  }

  get duration(): Duration {
    return this.props.duration;
  }

  get codecInfo(): AudioCodecInfo {
    return this.props.codecInfo;
  }

  get transcript(): readonly TranscriptSegment[] {
    return this.props.transcript ?? [];
  }

  get waveformPreview(): Readonly<Float32Array> | undefined {
    return this.props.waveformPreview;
  }

  get createdAt(): Date {
    return this.props.createdAt!;
  }

  get updatedAt(): Date {
    return this.props.updatedAt!;
  }

  get version(): number {
    return this.props.version!;
  }

  /* ------------------------------------------------------------------ */
  /*                          Business Methods                          */
  /* ------------------------------------------------------------------ */

  /**
   * Adds or replaces a transcript.  Returns a _new_ AudioContent instance
   * plus a domain event describing the change.
   */
  public withTranscript(
    segments: readonly TranscriptSegment[],
    publisher?: EventPublisher
  ): Result<AudioContent> {
    if (!AudioContent.isTranscriptValid(segments)) {
      return failure<AudioContent>('Transcript segments are not ordered or overlap.');
    }

    const nextProps: AudioContentProps = {
      ...this.props,
      transcript: segments,
      updatedAt: new Date(),
      version: this.version + 1
    };

    const created = AudioContent.create(nextProps, this.id);
    if (created.isFailure) return created;

    const event = new AudioContentTranscribed(this.id, segments);
    publisher?.publish(event);

    return created;
  }

  /**
   * Trims the audio by returning a NEW AudioContent whose duration and
   * transcript have been cropped accordingly.
   */
  public trimmed(
    startOffsetSec: number,
    endOffsetSec: number,
    publisher?: EventPublisher
  ): Result<AudioContent> {
    /* Validate parameters */
    if (startOffsetSec < 0 || endOffsetSec < 0) {
      return failure('Offsets must be non-negative.');
    }
    if (startOffsetSec >= endOffsetSec) {
      return failure('Start offset must be smaller than end offset.');
    }
    if (endOffsetSec > this.duration.seconds) {
      return failure('End offset exceeds audio length.');
    }

    /* Create new transcript by slicing segments fully contained within the range */
    const newSegments = this.transcript
      .filter(s => s.startTime >= startOffsetSec && s.endTime <= endOffsetSec)
      .map<TranscriptSegment>(s => ({
        ...s,
        startTime: s.startTime - startOffsetSec,
        endTime: s.endTime - startOffsetSec
      }));

    const newDuration = Duration.fromSeconds(endOffsetSec - startOffsetSec);

    const nextProps: AudioContentProps = {
      ...this.props,
      duration: newDuration,
      transcript: newSegments,
      updatedAt: new Date(),
      version: this.version + 1
    };

    const result = AudioContent.create(nextProps, this.id);
    if (result.isFailure) return result;

    publisher?.publish(new AudioContentTrimmed(this.id, this.duration, newDuration));

    return result;
  }

  /* ------------------------------------------------------------------ */
  /*                             Utilities                              */
  /* ------------------------------------------------------------------ */

  private static isTranscriptValid(
    segments: readonly TranscriptSegment[]
  ): boolean {
    for (let i = 0; i < segments.length; i++) {
      const seg = segments[i];
      if (seg.startTime < 0 || seg.endTime <= seg.startTime) return false;
      if (seg.confidence < 0 || seg.confidence > 1) return false;
      if (i > 0) {
        const prev = segments[i - 1];
        if (prev.endTime > seg.startTime) return false; // Overlap
      }
    }
    return true;
  }

  /* Prevent leaking frozen props in spread operations */
  public toJSON(): unknown {
    return {
      id: this.id.toString(),
      type: this.type,
      ...this.props,
      duration: this.duration.seconds          // Serialise duration as seconds
    };
  }
}

/* ---------------------------------------------------------------------- */
/*                           MODULE AUGMENTATION                           */
/* ---------------------------------------------------------------------- */

/**
 * Content type registration for the plugin system.  The interface
 * augmentation makes the concrete entity discoverable by generic factory
 * helpers (parseContent, migrateContent, etc.) without introducing
 * circular dependencies.
 */
declare module './ContentTypeRegistry' {
  interface ContentTypeRegistry {
    [ContentType.AUDIO]: AudioContent;
  }
}
```
