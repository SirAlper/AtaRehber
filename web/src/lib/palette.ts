// The site's brand colours turned by a hue angle at runtime. Tailwind defines every colour as a CSS variable in
// oklch (--color-violet-500: oklch(60.6% 0.25 292.717)); setting the same variables on <html> with the hue turned
// recolours every button, heading, badge, and gradient that uses them, without touching the markup. The colours
// that carry a meaning (green success, amber warning, red error) and the greys stay as they are.

const FAMILIES = ["violet", "purple", "fuchsia", "indigo", "night"];
const SHADES = [50, 100, 200, 300, 400, 500, 600, 700, 800, 850, 900, 950];

export type Oklch = [lightness: string, chroma: number, hue: number];

const OKLCH = /^oklch\(\s*([\d.]+%?)\s+([\d.]+)\s+([\d.]+)/;

/** "oklch(60.6% .25 292.717)" -> ["60.6%", 0.25, 292.717]; null for anything else. */
export function parseOklch(value: string): Oklch | null {
  const match = OKLCH.exec(value.trim());
  return match ? [match[1], Number(match[2]), Number(match[3])] : null;
}

/** The colours turned by `degrees` (0: the original values). */
export function turnedPalette(base: Map<string, Oklch>, degrees: number): Map<string, string> {
  const turned = new Map<string, string>();
  for (const [name, [lightness, chroma, hue]] of base) {
    const h = (((hue + degrees) % 360) + 360) % 360;
    turned.set(name, `oklch(${lightness} ${chroma} ${h.toFixed(2)})`);
  }
  return turned;
}

let base: Map<string, Oklch> | null = null;
let current = 0;

/** The theme's own values, read once before anything is overridden. */
function themeColours(): Map<string, Oklch> {
  if (base) return base;
  base = new Map();
  const style = getComputedStyle(document.documentElement);
  for (const family of FAMILIES) {
    for (const shade of SHADES) {
      const name = `--color-${family}-${shade}`;
      const value = parseOklch(style.getPropertyValue(name));
      if (value) base.set(name, value);
    }
  }
  return base;
}

/** Turn the site's brand colours by `degrees`; 0 restores the theme. Small changes are skipped, so a slowly
 * turning value restyles the page a few times per second, not on every frame. */
export function setHueShift(degrees: number) {
  if (Math.abs(degrees - current) < 0.75 && !(degrees === 0 && current !== 0)) return;
  current = degrees;
  const root = document.documentElement;
  const colours = themeColours();
  if (Math.abs(degrees) < 0.5) {
    for (const name of colours.keys()) root.style.removeProperty(name);
    current = 0;
    return;
  }
  for (const [name, value] of turnedPalette(colours, degrees)) root.style.setProperty(name, value);
}
