// Decorative backdrop: soft drifting purple glows, a faint dot grid fading towards the edges, and a light grain.
// Purely visual (aria-hidden); animations stop for users who prefer reduced motion (index.css).

export function Background() {
  return (
    <div aria-hidden className="pointer-events-none fixed inset-0 -z-10 overflow-hidden">
      <div className="absolute inset-0 bg-gradient-to-br from-violet-50 via-white to-fuchsia-50 dark:from-[#0c0718] dark:via-[#110a24] dark:to-[#1a0b2e]" />
      <div className="animate-float-slow absolute -top-40 -left-32 h-[34rem] w-[34rem] rounded-full bg-violet-400/30 blur-3xl dark:bg-violet-600/25" />
      <div className="animate-float-slower absolute top-1/3 -right-40 h-[30rem] w-[30rem] rounded-full bg-fuchsia-400/25 blur-3xl dark:bg-fuchsia-600/20" />
      <div className="animate-float-slow absolute -bottom-48 left-1/4 h-[28rem] w-[28rem] rounded-full bg-indigo-300/30 blur-3xl dark:bg-indigo-600/20" />
      <div
        className="absolute inset-0 opacity-[0.35] dark:opacity-[0.18]"
        style={{
          backgroundImage: "radial-gradient(rgb(124 58 237 / 0.35) 1px, transparent 1px)",
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
          <stop offset="0" stopColor="#8b5cf6" />
          <stop offset="1" stopColor="#d946ef" />
        </linearGradient>
      </defs>
      <rect width="64" height="64" rx="16" fill="url(#logo-gradient)" />
      <path
        d="M20 22h24a4 4 0 0 1 4 4v12a4 4 0 0 1-4 4H30l-8 6v-6h-2a4 4 0 0 1-4-4V26a4 4 0 0 1 4-4z"
        fill="#fff"
        fillOpacity=".95"
      />
      <circle cx="26" cy="32" r="2.5" fill="#8b5cf6" />
      <circle cx="32" cy="32" r="2.5" fill="#a855f7" />
      <circle cx="38" cy="32" r="2.5" fill="#d946ef" />
    </svg>
  );
}
