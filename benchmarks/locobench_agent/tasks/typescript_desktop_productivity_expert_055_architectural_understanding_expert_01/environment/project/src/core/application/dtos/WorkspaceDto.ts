```typescript
/**********************************************************************************************************************
 * PaletteFlow Studio – Workspace Data-Transfer Objects
 * ====================================================================================================================
 * This file defines the *shape* of a Workspace when it crosses a process / layer / transport boundary.
 *
 * Layer:   core › application › dtos
 * Author:  PaletteFlow Studio Core Team
 *
 * Rationale
 * ---------
 *   • The DTO is intentionally **serialisation-friendly** – only primitives, arrays, plain objects.
 *   • No behaviour, no class instances, no methods – just data.
 *   • A dedicated `WorkspaceDtoMapper` converts to / from rich Domain Entities so the rest of the
 *     system stays blissfully unaware of transport concerns.
 *
 * NOTE:  When introducing breaking-schema changes remember to bump `schemaVersion` and provide a
 *        migration in `src/core/infrastructure/persistence/migrations`.
 *********************************************************************************************************************/

import { z } from 'zod';

import { Workspace } from '../../domain/entities/Workspace';
import { Canvas }    from '../../domain/entities/Canvas';
import { Node }      from '../../domain/entities/Node';
import { Link }      from '../../domain/entities/Link';
import { Theme }     from '../../domain/valueObjects/Theme';

import { Result }            from '../../shared/core/Result';
import { UnexpectedError }   from '../../shared/core/UnexpectedError';

/* ================================================================================================================= */
/* DTO DEFINITION                                                                                                    */
/* ================================================================================================================= */

/**
 * A serialisable representation of a full PaletteFlow workspace (root aggregate).
 */
export interface WorkspaceDto {
  /**
   * Unique, stable, ULID-style identifier. Persisted across exports / imports.
   */
  id: string;

  /**
   * Human-friendly label chosen by the user.
   */
  name: string;

  /**
   * Optional Markdown-flavoured blurb shown in the Workspace switcher.
   */
  description?: string;

  /**
   * Semantic version of the Workspace *schema* – not to be confused with the
   * application’s version (although they are often released together).
   */
  schemaVersion: string; // e.g. "2.1.0"

  /**
   * RFC3339 timestamps for auditing / autosave rotations.
   */
  createdAt: string;
  updatedAt: string;

  /**
   * Visual node canvases. Empty array means the Workspace is brand-new.
   */
  canvases: CanvasDto[];

  /**
   * Active theme customisations (may override the globally installed theme).
   */
  theme?: ThemeDto;

  /**
   * User or plugin-defined key/value blob that shouldn’t touch business rules
   * yet must travel with the Workspace (e.g. cursor positions, collapsed groups).
   */
  userState?: Record<string, unknown>;

  /**
   * Opaque states namespaced by plugin ID.
   */
  pluginState?: Record<string, unknown>;
}

export interface CanvasDto {
  id: string;
  name: string;
  nodes: NodeDto[];
  links: LinkDto[];
}

export interface NodeDto {
  id: string;
  type: string; // Provided by plugin or “core”
  position: { x: number; y: number };
  data: unknown;                       // JSON-serialisable payload (markdown, path to file, etc.)
  meta?: Record<string, unknown>;      // Presentation-only data (collapsed, selected, etc.)
}

export interface LinkDto {
  id: string;
  sourceNodeId: string;
  targetNodeId: string;
  label?: string;
}

export interface ThemeDto {
  id: string;
  name: string;
  variables: Record<string, string | number>; // e.g. { "--pf-accent": "#FFC832" }
}

/* ================================================================================================================= */
/* VALIDATION SCHEMAS (zod)                                                                                          */
/* ================================================================================================================= */

const isoDateRegex =
  /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?Z$/;

const NodeDtoSchema = z.object({
  id: z.string().min(1),
  type: z.string().min(1),
  position: z.object({ x: z.number(), y: z.number() }),
  data: z.any(),
  meta: z.record(z.any()).optional(),
});

const LinkDtoSchema = z.object({
  id: z.string().min(1),
  sourceNodeId: z.string().min(1),
  targetNodeId: z.string().min(1),
  label: z.string().optional(),
});

const CanvasDtoSchema = z.object({
  id: z.string().min(1),
  name: z.string().min(1),
  nodes: z.array(NodeDtoSchema),
  links: z.array(LinkDtoSchema),
});

const ThemeDtoSchema = z.object({
  id: z.string().min(1),
  name: z.string().min(1),
  variables: z.record(z.union([z.string(), z.number()])),
});

const WorkspaceDtoSchema = z.object({
  id: z.string().min(1),
  name: z.string().min(1),
  description: z.string().optional(),
  schemaVersion: z.string().min(1),
  createdAt: z.string().regex(isoDateRegex),
  updatedAt: z.string().regex(isoDateRegex),
  canvases: z.array(CanvasDtoSchema),
  theme: ThemeDtoSchema.optional(),
  userState: z.record(z.any()).optional(),
  pluginState: z.record(z.any()).optional(),
});

/* ================================================================================================================= */
/* MAPPER UTILS                                                                                                      */
/* ================================================================================================================= */

/**
 * Converts between Domain Entities and plain DTO objects.
 *
 * All heavy lifting (instance creation, validation, invariants) stays inside each Domain class.
 * The mapper is little more than a _shape translator_.
 */
export class WorkspaceDtoMapper {
  /* ------------------------------------------------------------------------------------------------------------- */
  /* TO DTO                                                                                                        */
  /* ------------------------------------------------------------------------------------------------------------- */

  /**
   * Serialises a fully-formed Workspace Aggregate into a DTO ready for IPC,
   * persistence, or network transport.
   */
  public static toDto(workspace: Workspace): WorkspaceDto {
    return {
      id: workspace.id.value,
      name: workspace.name,
      description: workspace.description,
      schemaVersion: workspace.schemaVersion,
      createdAt: workspace.createdAt.toISOString(),
      updatedAt: workspace.updatedAt.toISOString(),
      canvases: workspace.canvases.map(WorkspaceDtoMapper.canvasToDto),
      theme: workspace.theme
        ? WorkspaceDtoMapper.themeToDto(workspace.theme)
        : undefined,
      userState: workspace.userState,
      pluginState: workspace.pluginState,
    };
  }

  private static canvasToDto(canvas: Canvas): CanvasDto {
    return {
      id: canvas.id.value,
      name: canvas.name,
      nodes: canvas.nodes.map(WorkspaceDtoMapper.nodeToDto),
      links: canvas.links.map(WorkspaceDtoMapper.linkToDto),
    };
  }

  private static nodeToDto(node: Node): NodeDto {
    return {
      id: node.id.value,
      type: node.type,
      position: { ...node.position },
      data: node.data,
      meta: node.meta,
    };
  }

  private static linkToDto(link: Link): LinkDto {
    return {
      id: link.id.value,
      sourceNodeId: link.sourceNodeId.value,
      targetNodeId: link.targetNodeId.value,
      label: link.label,
    };
  }

  private static themeToDto(theme: Theme): ThemeDto {
    return {
      id: theme.id,
      name: theme.name,
      variables: theme.variables,
    };
  }

  /* ------------------------------------------------------------------------------------------------------------- */
  /* TO DOMAIN                                                                                                     */
  /* ------------------------------------------------------------------------------------------------------------- */

  /**
   * Hydrates a DTO into Domain Entities.
   *
   * The method returns a `Result` to surface validation errors or failing invariants
   * *without throwing*. Callers decide how to propagate the error (UI toast, log, retry, etc.).
   */
  public static toDomain(dto: WorkspaceDto): Result<Workspace> {
    /* ----- 1. Validate DTO shape -------------------------------------------------------------------------------- */
    const parse = WorkspaceDtoSchema.safeParse(dto);
    if (!parse.success) {
      return Result.fail(
        `Workspace DTO validation error: ${parse.error.toString()}`
      );
    }

    try {
      /* ----- 2. Build Domain objects ---------------------------------------------------------------------------- */
      const canvases: Canvas[] = dto.canvases.map((c) =>
        Canvas.create(
          {
            name: c.name,
            nodes: c.nodes.map((n) =>
              Node.create({
                type: n.type,
                position: n.position,
                data: n.data,
                meta: n.meta,
                id: n.id,
              })
            ),
            links: c.links.map((l) =>
              Link.create({
                sourceNodeId: l.sourceNodeId,
                targetNodeId: l.targetNodeId,
                label: l.label,
                id: l.id,
              })
            ),
          },
          c.id
        ).getValue() // Canvas.create returns Result<Canvas>
      );

      const theme = dto.theme
        ? Theme.create(dto.theme).getValue()
        : undefined;

      /* Workspace.create handles business invariants such as “must have ≥ 1
         canvas” or “name ≤ 256 chars”. */
      const workspaceOrError = Workspace.create(
        {
          name: dto.name,
          description: dto.description,
          schemaVersion: dto.schemaVersion,
          createdAt: new Date(dto.createdAt),
          updatedAt: new Date(dto.updatedAt),
          canvases,
          theme,
          userState: dto.userState,
          pluginState: dto.pluginState,
        },
        dto.id
      );

      return workspaceOrError;
    } catch (err: unknown) {
      /* ----- 3. Convert any unexpected exception into a domain-level Result ------------------------------------ */
      return Result.fail(
        UnexpectedError.create(err instanceof Error ? err : new Error(String(err)))
      );
    }
  }
}

/* ================================================================================================================= */
/* MODULE AUGMENTATION (Plugin Safety)                                                                               */
/* ================================================================================================================= */

/**
 * Allow plugins to augment `WorkspaceDto` with their own strongly-typed namespaces
 * without having to fork core code. Plugins declare:
 *
 *   declare module "@palette-flow/core/application/dtos/WorkspaceDto" {
 *     interface PluginStateExtension {
 *       "com.acme.my-plugin"?: { foo: string; bar: number }
 *     }
 *   }
 *
 * The extra keys become magically available in TypeScript.
 */
export interface PluginStateExtension {} // eslint-disable-line @typescript-eslint/no-empty-interface

type ExtendedPluginState = WorkspaceDto['pluginState'] & PluginStateExtension;

declare module './WorkspaceDto' {
  // eslint-disable-next-line @typescript-eslint/consistent-type-definitions
  interface WorkspaceDto {
    pluginState?: ExtendedPluginState;
  }
}
```