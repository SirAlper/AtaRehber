// Decorative backdrop: living colour fields (src/lib/cells.ts), a faint dot grid fading towards the edges, and a
// light grain. Purely visual (aria-hidden).

import { useEffect, useRef } from "react";

import { isLanding, isThinking } from "@/lib/activity";
import { createWorld, render, resizeWorld, step, type World } from "@/lib/cells";
import { stepLava } from "@/lib/lava";
import { setHueShift } from "@/lib/palette";

// The field is drawn at most this many pixels and scaled up by the browser, which also softens its edges (a blur
// filter would render as speckles without GPU acceleration)
const MAX_FIELD_PIXELS = 20_000;
const FRAME_MS = 33;

function fieldSize() {
  const scale = Math.max(8, Math.sqrt((window.innerWidth * window.innerHeight) / MAX_FIELD_PIXELS));
  return [Math.ceil(window.innerWidth / scale), Math.ceil(window.innerHeight / scale)];
}

/** Calm while idle; gathering and merging while the assistant thinks (the site's colours turn to a new palette),
 * scattering to new places when the answer is in (the colours turn back). Behind the landing page they rise and
 * sink like a lava lamp (src/lib/lava.ts). Still for users who prefer reduced motion. */
function LivingColors() {
  const canvasRef = useRef<HTMLCanvasElement>(null);

  useEffect(() => {
    const canvas = canvasRef.current;
    const context = canvas?.getContext("2d");
    if (!canvas || !context) return;
    const still = window.matchMedia?.("(prefers-reduced-motion: reduce)").matches ?? false;
    const [width, height] = fieldSize();
    const world: World = createWorld(width, height);
    let image = context.createImageData(width, height);
    canvas.width = width;
    canvas.height = height;

    let last = performance.now();
    let frame = 0;
    const draw = (now: number) => {
      frame = requestAnimationFrame(draw);
      const elapsed = now - last;
      if (elapsed < (still ? 1000 : FRAME_MS)) return;
      last = now;
      if (!still) {
        // Hidden tabs pause; a long gap must not throw the cells across the screen
        const dt = Math.min(elapsed / 1000, 0.1);
        if (isLanding()) stepLava(world, dt);
        else step(world, dt, isThinking());
        // The site's brand colours turn with the background
        setHueShift(world.paletteShift);
      }
      render(world, image.data, document.documentElement.classList.contains("dark"));
      context.putImageData(image, 0, 0);
    };
    frame = requestAnimationFrame(draw);

    const onResize = () => {
      const [w, h] = fieldSize();
      if (w === world.width && h === world.height) return;
      resizeWorld(world, w, h);
      canvas.width = w;
      canvas.height = h;
      image = context.createImageData(w, h);
    };
    window.addEventListener("resize", onResize);
    return () => {
      cancelAnimationFrame(frame);
      setHueShift(0);
      window.removeEventListener("resize", onResize);
    };
  }, []);

  return <canvas ref={canvasRef} className="absolute inset-0 h-full w-full" />;
}

export function Background() {
  return (
    <div aria-hidden className="pointer-events-none fixed inset-0 -z-10 overflow-hidden">
      <div className="absolute inset-0 bg-gradient-to-br from-violet-50 via-white to-fuchsia-50 dark:from-night-950 dark:via-night-900 dark:to-night-800" />
      <LivingColors />
      <div
        className="absolute inset-0 opacity-[0.35] dark:opacity-[0.18]"
        style={{
          backgroundImage: "radial-gradient(color-mix(in oklab, var(--color-violet-600) 35%, transparent) 1px, transparent 1px)",
          backgroundSize: "22px 22px",
          maskImage: "radial-gradient(ellipse at center, black 30%, transparent 75%)",
          WebkitMaskImage: "radial-gradient(ellipse at center, black 30%, transparent 75%)",
        }}
      />
      <svg className="absolute inset-0 h-full w-full opacity-[0.04] mix-blend-overlay dark:opacity-[0.07]">
        <filter id="grain">
          <feTurbulence type="fractalNoise" baseFrequency="0.9" numOctaves="2" stitchTiles="stitch" />
        </filter>
        <rect width="100%" height="100%" filter="url(#grain)" />
      </svg>
    </div>
  );
}

export function Logo({ className = "h-9 w-9" }: { className?: string }) {
  return (
    <svg viewBox="0 0 64 64" className={className} aria-hidden>
      <defs>
        <linearGradient id="logo-gradient" x1="0" y1="0" x2="1" y2="1">
          <stop offset="0" style={{ stopColor: "var(--color-violet-500)" }} />
          <stop offset="1" style={{ stopColor: "var(--color-fuchsia-500)" }} />
        </linearGradient>
      </defs>
      <rect width="64" height="64" rx="16" fill="url(#logo-gradient)" />
      <path
        d="M20 22h24a4 4 0 0 1 4 4v12a4 4 0 0 1-4 4H30l-8 6v-6h-2a4 4 0 0 1-4-4V26a4 4 0 0 1 4-4z"
        fill="#fff"
        fillOpacity=".95"
      />
      <circle cx="26" cy="32" r="2.5" style={{ fill: "var(--color-violet-500)" }} />
      <circle cx="32" cy="32" r="2.5" style={{ fill: "var(--color-purple-500)" }} />
      <circle cx="38" cy="32" r="2.5" style={{ fill: "var(--color-fuchsia-500)" }} />
    </svg>
  );
}
