```markdown
# PaletteFlow Plugin Manifest (`manifest.json`)

The **manifest** defines every public-facing detail of a PaletteFlow plugin.  
It is the single source of truth that the runtime, marketplace, and update
service rely on when **verifying**, **installing**, and **executing** your
plugin.

```text
<plugin-root>/
 ├── dist/                # Bundled code referenced from `main`
 ├── assets/              # Icon, previews, localized read-me, …
 ├── src/                 # Human-edited TypeScript sources
 ├── manifest.json        # <── YOU ARE HERE
 └── README.md
```

PaletteFlow reads the file once during application start-up and caches the
result. Updates ship through the auto-update service and are compared against
the fields in the manifest.

---

## Quick Example

```jsonc
{
  "$schema": "https://docs.paletteflow.app/schemas/plugin-manifest/v1.json",
  "id": "studio.contrib.markmap",
  "name": "Markmap Node",
  "version": "2.3.1",
  "description": "Interactive mind-map rendering for markdown headings.",
  "author": "PaletteFlow Contrib Team",
  "license": "MIT",
  "icon": "assets/icon.svg",
  "entrypoint": "dist/index.js",
  "engines": {
    "paletteflow": "^1.18.0"
  },
  "permissions": [
    "clipboard.read",
    "network.http"
  ],
  "keywords": ["markdown", "mindmap", "visualization"],
  "hooks": {
    "postInstall": "dist/hooks/postInstall.js",
    "preUninstall": "dist/hooks/preUninstall.js"
  },
  "contributes": {
    "nodes": [
      {
        "type": "markmap",
        "title": "Markmap",
        "icon": "assets/icon-node.svg",
        "editor": "dist/editor.js",
        "renderer": "dist/renderer.js"
      }
    ],
    "commands": [
      {
        "id": "markmap.toggleCollapse",
        "title": "Toggle Markmap Collapse",
        "shortcut": "Ctrl+Alt+M"
      }
    ]
  }
}
```

---

## TypeScript Declaration

`@paletteflow/plugin-sdk` ships an identical interface to guarantee
compile-time safety.

```ts
// node_modules/@paletteflow/plugin-sdk/types/manifest.d.ts
export interface PluginManifest {
  /** Semantic, unique id. Use reverse-DNS style to avoid collisions. */
  id: string;

  /** Display name shown in the marketplace. */
  name: string;

  /** SemVer string, required for update diffing. */
  version: string;

  /** Short explanation (≤120 chars). Markdown allowed. */
  description?: string;

  /** SPDX-compliant license identifier (e.g., "MIT"). */
  license?: string;

  /** Optional author, supports markdown links. */
  author?: string;

  /** Relative path to a 128×128 SVG/PNG used in UI listings. */
  icon?: string;

  /** Absolute (after resolve) path to the plugin’s main bundle. */
  entrypoint: string;

  /** Target engine versions. Uses npm-style semver ranges. */
  engines: {
    paletteflow: string;  // e.g. "^1.18.0"
  };

  /** Restricted capability declarations. */
  permissions?: Array<
    | "clipboard.read"
    | "clipboard.write"
    | "filesystem.read"
    | "filesystem.write"
    | "network.http"
    | "workspace.modify"
  >;

  /** Searchable metadata. */
  keywords?: string[];

  /** Lifecycle scripts executed by the runtime. */
  hooks?: {
    postInstall?: string;
    preUninstall?: string;
    activate?: string; // called every time the plugin is (re)loaded
  };

  /** Feature contributions exposed to the platform. */
  contributes?: {
    nodes?: Array<{
      type: string;           // must be unique per plugin
      title: string;
      icon?: string;
      editor: string;         // React/Preact component
      renderer: string;       // Ditto
    }>;
    commands?: Array<{
      id: string;             // namespace.id format
      title: string;
      shortcut?: string;      // OS-aware accelerator string
    }>;
    themes?: Array<{
      id: string;
      title: string;
      file: string;           // CSS / JSON theme payload
    }>;
  };
}
```

---

## Field-by-Field Reference

### `id` (string, **required**)
Reverse-DNS identifier. Must remain stable across releases.

### `name` (string, **required**)
Human-readable title. Localization is supported via
`assets/i18n/<lang>/manifest.json`.

### `version` (string, **required**)
SemVer. Every marketplace upload must increment
`MAJOR` or `MINOR` or `PATCH`.

### `entrypoint` (string, **required**)
Path to the JavaScript file exporting at least:

```ts
export function activate(ctx: PluginContext): void | Promise<void>;
export function deactivate?(): void | Promise<void>;
```

### `engines.paletteflow` (string, **required**)
Minimum and maximum runtime compatibility.  
`{"paletteflow":"^1.12.0 || 2.x"}` is valid.

### `permissions` (string[], optional)
Least-privilege policy. Attempts to call an API without the
declared permission leads to an immediate `SecurityError`.

### `contributes` (object, optional)
Declarative integrations—node types, commands, themes, menus.
Everything else should be wired in `activate()`.

---

## JSON Schema

The official schema lives at
`https://docs.paletteflow.app/schemas/plugin-manifest/v1.json`
and may be imported into IDEs for autocompletion.

```json
{
  "$id": "https://docs.paletteflow.app/schemas/plugin-manifest/v1.json",
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "title": "PaletteFlow Plugin Manifest",
  "type": "object",
  "required": ["id", "name", "version", "entrypoint", "engines"],
  "additionalProperties": false,
  "properties": {
    "id": { "type": "string", "pattern": "^[a-z0-9]+(\\.[a-z0-9]+)+$" },
    "name": { "type": "string", "minLength": 1 },
    "version": { "type": "string", "pattern": "^(0|[1-9]\\d*)\\.(0|[1-9]\\d*)\\.(0|[1-9]\\d*)(-.+)?$" },
    "description": { "type": "string" },
    "author": { "type": "string" },
    "license": { "type": "string" },
    "icon": { "type": "string" },
    "entrypoint": { "type": "string" },
    "engines": {
      "type": "object",
      "required": ["paletteflow"],
      "properties": {
        "paletteflow": { "type": "string" }
      }
    },
    "permissions": {
      "type": "array",
      "items": {
        "enum": [
          "clipboard.read",
          "clipboard.write",
          "filesystem.read",
          "filesystem.write",
          "network.http",
          "workspace.modify"
        ]
      }
    },
    "keywords": {
      "type": "array",
      "items": { "type": "string" },
      "uniqueItems": true
    },
    "hooks": {
      "type": "object",
      "properties": {
        "postInstall": { "type": "string" },
        "preUninstall": { "type": "string" },
        "activate": { "type": "string" }
      },
      "additionalProperties": false
    },
    "contributes": { "$ref": "#/$defs/contributes" }
  },
  "$defs": {
    "contributes": {
      "type": "object",
      "properties": {
        "nodes": {
          "type": "array",
          "items": { "$ref": "#/$defs/nodeContribution" }
        },
        "commands": {
          "type": "array",
          "items": { "$ref": "#/$defs/commandContribution" }
        },
        "themes": {
          "type": "array",
          "items": { "$ref": "#/$defs/themeContribution" }
        }
      },
      "additionalProperties": false
    },
    "nodeContribution": {
      "type": "object",
      "required": ["type", "title", "editor", "renderer"],
      "properties": {
        "type": { "type": "string" },
        "title": { "type": "string" },
        "icon": { "type": "string" },
        "editor": { "type": "string" },
        "renderer": { "type": "string" }
      },
      "additionalProperties": false
    },
    "commandContribution": {
      "type": "object",
      "required": ["id", "title"],
      "properties": {
        "id": { "type": "string" },
        "title": { "type": "string" },
        "shortcut": { "type": "string" }
      },
      "additionalProperties": false
    },
    "themeContribution": {
      "type": "object",
      "required": ["id", "title", "file"],
      "properties": {
        "id": { "type": "string" },
        "title": { "type": "string" },
        "file": { "type": "string" }
      },
      "additionalProperties": false
    }
  }
}
```

---

## Best Practices & Gotchas

• **Lock your dependencies.** Re-evaluate security advisories before bumping  
  major versions that your plugin bundles.

• **Avoid breaking API changes.** If you must, release under a new `id`
  instead of forcing existing users to migrate.

• **Use `permissions` sparingly.** Each extra capability lowers trust and
  may cause auto-install policies to reject your plugin.

• **Ship source maps.** They remain on disk only, never uploaded, but they
  drastically improve crash diagnostics.

• **Treat hooks as side-effect free.** They must finish within 3 seconds or
  the runtime assumes failure.

---

## Validating Your Manifest

The CLI bundled with PaletteFlow Studio can lint and test your manifest.

```bash
npx paletteflow validate ./manifest.json
```

A successful run yields:

```text
✔ Manifest schema validation passed
✔ Engine compatibility (>=1.18.0 <2.0.0) satisfied
✔ Entrypoint dist/index.js exists
```

---

## Changelog

### v1 (current)
• Initial stable schema shipped with PaletteFlow 1.18.0  

Future versions will always be backwards compatible for fields that exist
today. New **optional** fields may be added, but existing semantics never
break within the same major (`1.x`) line.

---

© 2024 PaletteFlow Inc.
```