```typescript
/**
 * PaletteFlow Studio – Node Data-Transfer-Object
 *
 * This DTO is used to move “Node” data across process / layer boundaries
 * (e.g. IPC, WebSocket, persistence, plugin sandbox, etc.) without leaking
 * domain-layer implementation details.  Because PaletteFlow is highly
 * extensible, the DTO is able to carry arbitrary plugin-specific payloads
 * through the loosely-typed `payload` field while still preserving strong
 * typing for the built-in properties that the rest of the application relies
 * on.
 *
 * ────────────────────────────────────────────────────────────────────────────
 * Placement
 * src/core/application/dtos/NodeDto.ts
 * ────────────────────────────────────────────────────────────────────────────
 */

import { z } from 'zod';
import { Node } from '../../domain/entities/Node';
import { NodeId } from '../../domain/valueObjects/NodeId';
import { Vector2 } from '../../domain/valueObjects/Vector2';

/**
 * “Wire-ready” representation of a Node.
 *
 * Because plugins can augment nodes with their own data, {@link payload}
 * intentionally remains `unknown`.  An optional generic can be supplied by
 * downstream callers that _know_ the concrete type carried inside `payload`.
 */
export interface NodeDto<Payload = unknown> {
  /** Unique identifier (UUID v4) */
  id: string;

  /** Plugin-defined node type identifier (dash-case) – e.g. “markdown”, “sketch”, “my-org.custom-jira-ticket” */
  type: string;

  /** Position of the node on the infinite canvas (CSS px in document space) */
  position: {
    x: number;
    y: number;
  };

  /**
   * Optional dimensions (some nodes may prefer letting the renderer compute
   * their size at run-time; hence the fields are optional).
   */
  size?: {
    width: number;
    height: number;
  };

  /** Date ISO string */
  createdAt: string;
  /** Date ISO string */
  updatedAt: string;

  /** Array of _outgoing_ link identifiers (edges are stored separately – this field is for quick reference) */
  links: string[];

  /**
   * Arbitrary plugin-specific state.  Example: the markdown node stores the
   * markdown source string, the audio node stores the waveform meta, etc.
   */
  payload: Payload;
}

/* ──────────────────────────────── */
/* Runtime validation/schema (zod) */
/* ──────────────────────────────── */

/**
 * Type-guard & schema validation for untrusted payloads (IPC, JSON import, …)
 */
export const NodeDtoSchema: z.ZodType<NodeDto> = z.object({
  id: z.string().uuid(),
  type: z.string().min(1, 'Node.type must be a non-empty string'),
  position: z.object({
    x: z.number().finite(),
    y: z.number().finite(),
  }),
  size: z
    .object({
      width: z.number().positive(),
      height: z.number().positive(),
    })
    .partial()
    .optional(),
  createdAt: z.string().datetime(),
  updatedAt: z.string().datetime(),
  links: z.array(z.string().uuid()),
  payload: z.unknown(),
});

/* ────────────────────────────── */
/* Mapper between Domain & DTO   */
/* ────────────────────────────── */

export class NodeDtoMapper {
  /**
   * Transforms a domain `Node` entity into a serialisable `NodeDto`.
   * All date objects are converted to ISO-8601 strings and value
   * objects are unwrapped.
   */
  public static toDto(domain: Node): NodeDto {
    return {
      id: domain.id.value,
      type: domain.type, // domain.type is already a string
      position: {
        x: domain.position.x,
        y: domain.position.y,
      },
      size: domain.size
        ? {
            width: domain.size.width,
            height: domain.size.height,
          }
        : undefined,
      createdAt: domain.createdAt.toISOString(),
      updatedAt: domain.updatedAt.toISOString(),
      links: domain.links.map((l) => l.value),
      payload: domain.payload,
    };
  }

  /**
   * Hydrates a domain `Node` from a `NodeDto`.  Validation errors are
   * surfaced as `Error` instances that callers can map to user-visible
   * messaging or logging.
   *
   * If the DTO is untrusted (imported JSON, remote message, …) it should be
   * validated with `NodeDtoSchema.safeParse` before calling this method.
   */
  public static toDomain(dto: NodeDto): Node {
    // Basic defensive programming – ensure dto is shaped correctly.
    const parseResult = NodeDtoSchema.safeParse(dto);
    if (!parseResult.success) {
      throw new Error(
        `Invalid NodeDto: ${parseResult.error.flatten().fieldErrors}`
      );
    }

    const node = new Node({
      id: new NodeId(dto.id),
      type: dto.type,
      position: new Vector2(dto.position.x, dto.position.y),
      size:
        dto.size !== undefined
          ? { width: dto.size.width, height: dto.size.height }
          : undefined,
      createdAt: new Date(dto.createdAt),
      updatedAt: new Date(dto.updatedAt),
      links: dto.links.map((l) => new NodeId(l)),
      payload: dto.payload,
    });

    return node;
  }
}

/* ────────────────────────────────────────────────────────────── */
/* Re-export helpers so callers can do                             */
/*     import { NodeDto, NodeDtoMapper } from '…/NodeDto';        */
/* ────────────────────────────────────────────────────────────── */
export type { Vector2 }; // convenience re-export (commonly used together)
```