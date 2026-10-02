// Lava lamp: the colour fields of src/lib/cells.ts moved like wax in a lamp instead of roaming. A blob warms up at
// the bottom, rises slowly, cools at the top, and sinks again; on the way blobs cling to each other, stretch, and
// let go (the field drawn by render() does that by itself). Shown behind the landing page. It moves the same
// world, so when the visitor goes on, the blobs roam away from where the lamp left them.

import { HUE_MAX, HUE_MIN, type Cell, type World } from "@/lib/cells";

// 0 cold (sinks) .. 1 hot (rises)
const heat = new WeakMap<Cell, number>();

// Share of the height at the bottom that warms a blob and at the top that cools it, and how fast (1/s)
const WARM_ZONE = 0.22;
const HEAT_RATE = 0.12;
// Lift of a fully hot blob and the fastest a blob moves, as shares of the height per second (squared for the lift)
const LIFT = 0.09;
const MAX_SPEED = 0.07;
// Thick liquid: speed lost per second
const DRAG = 0.9;
const HUE_EASE = 0.5;
const PALETTE_RATE_BACK = 10;

type Random = () => number;

function pickColumn(cell: Cell, world: World, random: Random) {
  cell.tx = world.width * (0.1 + random() * 0.8);
}

/** Advance the lamp by dt seconds. */
export function stepLava(world: World, dt: number, random: Random = Math.random) {
  const { cells, width, height } = world;
  const lift = height * LIFT;
  const maxSpeed = height * MAX_SPEED;
  const ease = 1 - Math.exp(-HUE_EASE * dt);

  // Coming from the chat: calm down and turn back to the theme's colours
  world.phase = "idle";
  world.phaseTime += dt;
  world.energy *= Math.exp(-0.6 * dt);
  world.paletteTarget = 0;
  const back = PALETTE_RATE_BACK * dt;
  world.paletteShift -= Math.max(-back, Math.min(back, world.paletteShift));

  for (const cell of cells) {
    // A blob that was melting into another one stays as it is
    cell.into = undefined;
    cell.age += dt;
    cell.targetHue += cell.hueSpeed * 0.25 * dt;
    if (cell.targetHue < HUE_MIN || cell.targetHue > HUE_MAX) {
      cell.targetHue = Math.min(HUE_MAX, Math.max(HUE_MIN, cell.targetHue));
      cell.hueSpeed = -cell.hueSpeed;
    }
    cell.hue += (cell.targetHue - cell.hue) * ease;

    // Warmed at the bottom, cooled at the top; in between a blob keeps its heat
    const was = heat.get(cell) ?? random();
    const level = cell.y / height;
    let now = was;
    if (level > 1 - WARM_ZONE) now = Math.min(1, was + HEAT_RATE * dt);
    else if (level < WARM_ZONE) now = Math.max(0, was - HEAT_RATE * dt);
    heat.set(cell, now);
    // Each trip up or down runs along a column of its own
    if (now !== was && (now === 0 || now === 1)) pickColumn(cell, world, random);

    cell.vy += (0.5 - now) * 2 * lift * dt;
    cell.vx += ((cell.tx - cell.x) * 0.15 + (random() - 0.5) * 1.5) * dt;

    // Passing blobs cling a little and never sink into each other fully
    for (const other of cells) {
      if (other === cell) continue;
      const dx = other.x - cell.x;
      const dy = other.y - cell.y;
      const d = Math.hypot(dx, dy) || 0.001;
      const touch = cell.r + other.r;
      let force = 0;
      if (d < touch * 1.8) force += 0.4 * (1 - d / (touch * 1.8));
      if (d < touch * 0.7) force -= 3 * (1 - d / (touch * 0.7));
      cell.vx += (dx / d) * force * dt;
      cell.vy += (dy / d) * force * dt;
    }

    // The glass: blobs rest half outside at the top and bottom, and stay between the sides
    const margin = cell.r * 0.4;
    if (cell.y < margin) cell.vy += 2 * lift * dt;
    if (cell.y > height - margin) cell.vy -= 2 * lift * dt;
    if (cell.x < -margin) cell.vx += 4 * dt;
    if (cell.x > width + margin) cell.vx -= 4 * dt;

    const damping = Math.exp(-DRAG * dt);
    cell.vx *= damping;
    cell.vy *= damping;
    const speed = Math.hypot(cell.vx, cell.vy);
    if (speed > maxSpeed) {
      cell.vx *= maxSpeed / speed;
      cell.vy *= maxSpeed / speed;
    }
    cell.x += cell.vx * dt;
    cell.y += cell.vy * dt;
  }
}
