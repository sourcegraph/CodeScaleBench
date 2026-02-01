```typescript
/**
 * PaletteFlow Studio
 * core/domain/value-objects/Color.ts
 *
 * A rich, immutable value-object that models a color in several color spaces.
 *
 * The implementation purposefully avoids 3rd-party runtime dependencies so it
 * can live inside the pure domain layer.  If you need fancier color science
 * (OKLab, CAM16, …) pull that into the infrastructure layer and convert back
 * to this canonical representation before persisting the value-object.
 */

type Float0_1 = number;        // 0 ≤ n ≤ 1
type UInt8    = number;        // 0 ≤ n ≤ 255

/**
 * Utility domain-level exception type.
 * Keeping it here avoids coupling the VO to higher-level error abstractions.
 */
export class DomainError extends Error {
  constructor(message: string) {
    super(message);
    this.name = 'DomainError';
  }
}

/**
 * Subset of CSS color keywords we want to support out-of-the-box.
 * NOTE:  We intentionally keep this list minimal; the plugin system can expand
 *        it at runtime by wrapping Color.parse().
 */
const NAMED_COLORS: Record<string, string> = {
  black:  '#000000',
  white:  '#ffffff',
  red:    '#ff0000',
  green:  '#00ff00',
  blue:   '#0000ff',
  yellow: '#ffff00',
  magenta:'#ff00ff',
  cyan:   '#00ffff',
  transparent: '#00000000'
};

export interface RgbaTuple { r: UInt8; g: UInt8; b: UInt8; a: Float0_1; }

/**
 * Value-Object representing a color.
 * Comparison is done by structural equality (RGBA).
 */
export class Color {

  /** Factory: Parse from arbitrary input (HEX, rgb(), hsl(), keyword). */
  public static parse(input: string): Color {
    input = input.trim().toLowerCase();

    // Named keyword
    if (NAMED_COLORS[input]) {
      return Color.fromHex(NAMED_COLORS[input]);
    }

    // Hex ‑ #rgb[a]? | #rrggbb[aa]?
    if (/^#([0-9a-f]{3,8})$/i.test(input)) {
      return Color.fromHex(input);
    }

    // rgb(a)
    const rgbMatch = /^rgba?\((.+)\)$/i.exec(input);
    if (rgbMatch) {
      const parts = rgbMatch[1]
        .split(',')
        .map(s => s.trim())
        .filter(Boolean);

      if (parts.length < 3 || parts.length > 4) {
        throw new DomainError(`Invalid rgb() expression: ${input}`);
      }

      const [r, g, b] = parts.slice(0, 3).map(Color.#parseRgbChannel);
      const a        = parts[3] !== undefined ? Color.#parseAlpha(parts[3]) : 1;
      return new Color({ r, g, b, a });
    }

    // hsl(a)
    const hslMatch = /^hsla?\((.+)\)$/i.exec(input);
    if (hslMatch) {
      const parts = hslMatch[1]
        .split(',')
        .map(s => s.trim())
        .filter(Boolean);

      if (parts.length < 3 || parts.length > 4) {
        throw new DomainError(`Invalid hsl() expression: ${input}`);
      }

      const h = Color.#parseHue(parts[0]);
      const s = Color.#parsePercentage(parts[1]);
      const l = Color.#parsePercentage(parts[2]);
      const a = parts[3] !== undefined ? Color.#parseAlpha(parts[3]) : 1;

      return Color.fromHsl({ h, s, l, a });
    }

    throw new DomainError(`Unsupported color format: ${input}`);
  }

  /** Factory: Create from #hex string (#RRGGBB[AA] or #RGB[A]). */
  public static fromHex(hex: string): Color {
    let clean = hex.replace('#', '').trim();

    if (![3, 4, 6, 8].includes(clean.length)) {
      throw new DomainError(`Invalid hex color: ${hex}`);
    }

    // Expand shorthand #rgb / #rgba to full length
    if (clean.length <= 4) {
      clean = clean.split('').map(ch => ch + ch).join('');
    }

    const r = parseInt(clean.slice(0, 2), 16);
    const g = parseInt(clean.slice(2, 4), 16);
    const b = parseInt(clean.slice(4, 6), 16);
    const a = clean.length === 8 ? parseInt(clean.slice(6, 8), 16) / 255 : 1;
    return new Color({ r, g, b, a });
  }

  /** Factory: Create from RGBA channels. */
  public static fromRgb(tuple: { r: UInt8; g: UInt8; b: UInt8; a?: Float0_1 }): Color {
    return new Color({
      r: Color.#clampUInt8(tuple.r),
      g: Color.#clampUInt8(tuple.g),
      b: Color.#clampUInt8(tuple.b),
      a: tuple.a !== undefined ? Color.#clampAlpha(tuple.a) : 1
    });
  }

  /** Factory: Create from HSLA channels. */
  public static fromHsl(tuple: { h: number; s: Float0_1; l: Float0_1; a?: Float0_1 }): Color {
    const { h, s, l } = tuple;
    const a = tuple.a !== undefined ? Color.#clampAlpha(tuple.a) : 1;

    // HSL -> RGB conversion
    // see https://en.wikipedia.org/wiki/HSL_and_HSV#HSL_to_RGB_alternative
    const c = (1 - Math.abs(2 * l - 1)) * s;
    const hp = (h / 60) % 6;
    const x = c * (1 - Math.abs((hp % 2) - 1));

    let [r1, g1, b1]: [number, number, number];

    if (hp >= 0 && hp < 1) [r1, g1, b1] = [c, x, 0];
    else if (hp >= 1 && hp < 2) [r1, g1, b1] = [x, c, 0];
    else if (hp >= 2 && hp < 3) [r1, g1, b1] = [0, c, x];
    else if (hp >= 3 && hp < 4) [r1, g1, b1] = [0, x, c];
    else if (hp >= 4 && hp < 5) [r1, g1, b1] = [x, 0, c];
    else [r1, g1, b1] = [c, 0, x];

    const m = l - c / 2;
    const r = Math.round((r1 + m) * 255);
    const g = Math.round((g1 + m) * 255);
    const b = Math.round((b1 + m) * 255);

    return new Color({ r, g, b, a });
  }

  //--------------------------------------------------------------------------
  //  Public instance API
  //--------------------------------------------------------------------------

  /** Red channel (0-255). */
  get r(): UInt8 { return this.#rgba.r; }
  /** Green channel (0-255). */
  get g(): UInt8 { return this.#rgba.g; }
  /** Blue channel (0-255). */
  get b(): UInt8 { return this.#rgba.b; }
  /** Alpha channel (0-1). */
  get a(): Float0_1 { return this.#rgba.a; }

  /** Return #rrggbb or #rrggbbaa if alpha ≠ 1. */
  public toHex(includeAlpha = false): string {
    const { r, g, b, a } = this.#rgba;
    const hex = (n: number) => n.toString(16).padStart(2, '0');
    return (
      '#' +
      hex(r) +
      hex(g) +
      hex(b) +
      (includeAlpha || a !== 1 ? hex(Math.round(a * 255)) : '')
    );
  }

  /** Return a valid CSS rgba() string. */
  public toRgbaString(): string {
    const { r, g, b, a } = this.#rgba;
    return `rgba(${r}, ${g}, ${b}, ${+a.toFixed(3)})`;
  }

  /** Convert to HSLA representation. */
  public toHsl(): { h: number; s: Float0_1; l: Float0_1; a: Float0_1 } {
    const { r, g, b, a } = this.#rgba;
    const rf = r / 255;
    const gf = g / 255;
    const bf = b / 255;

    const max = Math.max(rf, gf, bf);
    const min = Math.min(rf, gf, bf);
    const delta = max - min;

    let h: number = 0;
    if (delta !== 0) {
      if (max === rf)      h = 60 * (((gf - bf) / delta) % 6);
      else if (max === gf) h = 60 * (((bf - rf) / delta) + 2);
      else                 h = 60 * (((rf - gf) / delta) + 4);
    }
    if (h < 0) h += 360;

    const l = (max + min) / 2;
    const s = delta === 0 ? 0 : delta / (1 - Math.abs(2 * l - 1));

    return { h, s, l, a };
  }

  /** Linear interpolation between this color and another.  t ∈ [0,1] */
  public mix(other: Color, t: Float0_1): Color {
    t = Color.#clamp01(t);

    const lerp = (a: number, b: number) => Math.round(a + (b - a) * t);
    const aLerp = (a: number, b: number) => +(a + (b - a) * t).toFixed(3);

    return new Color({
      r: lerp(this.r, other.r),
      g: lerp(this.g, other.g),
      b: lerp(this.b, other.b),
      a: aLerp(this.a, other.a)
    });
  }

  /** Return a new color with adjusted lightness (+/-). Percentage in [-1,1]. */
  public lighten(amount: number): Color {
    const hsl = this.toHsl();
    hsl.l = Color.#clamp01(hsl.l + amount);
    return Color.fromHsl(hsl);
  }

  /** Darken shorthand (negative lighten). */
  public darken(amount: number): Color {
    return this.lighten(-amount);
  }

  /** Return a copy with a different alpha channel. */
  public withAlpha(alpha: Float0_1): Color {
    return new Color({ ...this.#rgba, a: Color.#clampAlpha(alpha) });
  }

  /** WCAG 2.0 contrast ratio against another color. */
  public contrastRatio(other: Color): number {
    const lum1 = Color.#relativeLuminance(this);
    const lum2 = Color.#relativeLuminance(other);

    const brightest = Math.max(lum1, lum2);
    const darkest   = Math.min(lum1, lum2);

    return +( (brightest + 0.05) / (darkest + 0.05) ).toFixed(2);
  }

  /** Value-Object equality. */
  public equals(other: Color): boolean {
    return (
      other instanceof Color &&
      this.r === other.r &&
      this.g === other.g &&
      this.b === other.b &&
      Math.abs(this.a - other.a) < 1e-5 // float tolerance
    );
  }

  /** String representation defaults to hex. */
  public toString(): string {
    return this.toHex(this.a !== 1);
  }

  /** JSON serialization (used by JSON.stringify). */
  public toJSON(): string {
    return this.toString();
  }

  //--------------------------------------------------------------------------
  //  Internals
  //--------------------------------------------------------------------------

  /** Underlying data is private and frozen to guarantee immutability. */
  #rgba: Readonly<RgbaTuple>;

  private constructor(tuple: RgbaTuple) {
    this.#rgba = Object.freeze({ ...tuple });
    Object.freeze(this); // Deep immutability at the instance level.
  }

  //----------------------------------------------------------------------
  //  Parsing helpers
  //----------------------------------------------------------------------

  static #parseRgbChannel(token: string): UInt8 {
    // Can be either percentage or absolute integer
    if (token.endsWith('%')) {
      const pct = parseFloat(token);
      if (isNaN(pct)) throw new DomainError(`Invalid RGB percentage: ${token}`);
      return Color.#clampUInt8((pct / 100) * 255);
    } else {
      const n = parseInt(token, 10);
      if (isNaN(n)) throw new DomainError(`Invalid RGB integer: ${token}`);
      return Color.#clampUInt8(n);
    }
  }

  static #parsePercentage(token: string): Float0_1 {
    if (!token.endsWith('%')) {
      throw new DomainError(`Expected percentage value: ${token}`);
    }
    const pct = parseFloat(token);
    if (isNaN(pct)) throw new DomainError(`Invalid percentage: ${token}`);
    return Color.#clamp01(pct / 100);
  }

  static #parseHue(token: string): number {
    const h = parseFloat(token);
    if (isNaN(h)) throw new DomainError(`Invalid hue value: ${token}`);
    return ((h % 360) + 360) % 360; // normalize to [0,360)
  }

  static #parseAlpha(token: string): Float0_1 {
    if (token.endsWith('%')) {
      return Color.#clamp01(parseFloat(token) / 100);
    }
    return Color.#clampAlpha(parseFloat(token));
  }

  //----------------------------------------------------------------------
  //  Math helpers
  //----------------------------------------------------------------------

  static #clampUInt8(n: number): UInt8 {
    if (Number.isNaN(n)) throw new DomainError('Channel is NaN');
    return Math.min(255, Math.max(0, Math.round(n)));
  }

  static #clamp01(n: number): Float0_1 {
    if (Number.isNaN(n)) throw new DomainError('Channel is NaN');
    return Math.min(1, Math.max(0, n));
  }

  static #clampAlpha(a: number): Float0_1 {
    return Color.#clamp01(+a.toFixed(3));
  }

  /** Relative luminance per WCAG 2.0 */
  static #relativeLuminance(color: Color): number {
    const transform = (c: number) => {
      const cs = c / 255;
      return cs <= 0.03928 ? cs / 12.92 : Math.pow((cs + 0.055) / 1.055, 2.4);
    };
    const { r, g, b } = color;
    return 0.2126 * transform(r) + 0.7152 * transform(g) + 0.0722 * transform(b);
  }
}

```