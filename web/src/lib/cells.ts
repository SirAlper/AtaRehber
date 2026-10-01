// Colour fields that behave like cells: they roam the screen, cling to each other, pull apart, divide, and merge.
// They are drawn as a smooth field (each one adds r² / (d² + s²) and the colours mix by weight), so two of them flow
// into one shape when close and stretch apart before letting go, with no outline and no bright core.
//
// They follow the assistant in three phases:
// * idle: each cell drifts calmly towards a spot it picks anew every few seconds; its "mood" swings between
//   seeking company and keeping away, so small clusters form and break up;
// * gather (thinking): all head for a meeting point picked at random, cling together, and merge;
// * scatter (the answer is in): at the same pace they push apart, the merged mass divides, and every cell heads for
//   a spot of its own, picked at random far from the others' spots (so never the same layout twice), then they
//   calm down into idle.
// "energy" (0 calm .. 1 busy) sets how fast all of this goes; it stays up while they scatter.
//
// Nothing changes at once: a cell's colour eases towards its target colour, a merging cell melts into the other
// over a few seconds, and the halves of a divided cell start with the parent's colour.

export interface Cell {
  x: number;
  y: number;
  vx: number;
  vy: number;
  r: number;
  /** The colour shown, easing towards targetHue */
  hue: number;
  targetHue: number;
  /** Degrees per second the target colour shifts (sign: direction) */
  hueSpeed: number;
  /** Seconds since the cell appeared or last merged; young cells neither divide nor merge */
  age: number;
  /** The spot the cell is heading for, and the seconds until it picks a new one (idle) */
  tx: number;
  ty: number;
  retarget: number;
  /** Phase of the mood: sin(time + phase) > 0 seeks company, < 0 keeps away */
  phase: number;
  /** The cell this one is melting into (merging) */
  into?: Cell;
}

export type Phase = "idle" | "gather" | "scatter";

export interface World {
  width: number;
  height: number;
  cells: Cell[];
  /** Mood time (runs faster while busy) */
  time: number;
  phase: Phase;
  /** Seconds since the phase began */
  phaseTime: number;
  /** 0 calm .. 1 busy; eases towards 1 while gathering and scattering, towards 0 when idle */
  energy: number;
  /** Meeting point while gathering, and the seconds until it moves */
  gx: number;
  gy: number;
  regather: number;
}

export const MIN_CELLS = 4;
export const MAX_CELLS = 9;
// Teal to pink: random colours that still fit the purple theme
export const HUE_MIN = 175;
export const HUE_MAX = 335;
const MATURE_AGE = 3;
// How fast the shown colour follows the target colour (1/s), and at most how many degrees per second it moves
const HUE_EASE = 0.5;
const HUE_MAX_RATE = 12;
// How fast a merging cell hands its area over (1/s) and comes to the other's centre
const MELT_RATE = 0.7;
// How fast energy follows the phase (1/s): a few seconds to speed up or calm down
const ENERGY_RATE = 0.6;
// Scattering ends when the cells have reached their spots, or after this many seconds
const SCATTER_SECONDS = 8;
// Cells the scattered mass divides into (at most)
const SCATTER_CELLS = 7;

type Random = () => number;

function radii(world: Pick<World, "width" | "height">) {
  const size = Math.min(world.width, world.height);
  return { min: size * 0.08, max: size * 0.17 };
}

function clampHue(hue: number) {
  return Math.min(HUE_MAX, Math.max(HUE_MIN, hue));
}

function randomSpot(world: Pick<World, "width" | "height">, random: Random, inset = 0.08): [number, number] {
  return [
    world.width * (inset + random() * (1 - 2 * inset)),
    world.height * (inset + random() * (1 - 2 * inset)),
  ];
}

function pickTarget(cell: Cell, world: Pick<World, "width" | "height">, random: Random) {
  [cell.tx, cell.ty] = randomSpot(world, random);
  cell.retarget = 8 + random() * 10;
}

/** A random spot far from the spots other cells are scattering to and from the meeting point: of several random
 * candidates, the one with the most room around it. */
function spreadTarget(cell: Cell, world: World, random: Random) {
  const taken = world.cells.filter((c) => c !== cell && !c.into).map((c) => [c.tx, c.ty]);
  taken.push([world.gx, world.gy]);
  let best: [number, number] = randomSpot(world, random);
  let room = -1;
  for (let i = 0; i < 12; i++) {
    const spot = randomSpot(world, random);
    const nearest = Math.min(...taken.map(([x, y]) => Math.hypot(spot[0] - x, spot[1] - y)));
    if (nearest > room) [best, room] = [spot, nearest];
  }
  [cell.tx, cell.ty] = best;
  // They rest at their new spots a while before roaming on
  cell.retarget = 10 + random() * 10;
}

function newCell(world: Pick<World, "width" | "height">, random: Random): Cell {
  const { min, max } = radii(world);
  const hue = HUE_MIN + random() * (HUE_MAX - HUE_MIN);
  const cell: Cell = {
    x: random() * world.width,
    y: random() * world.height,
    vx: (random() - 0.5) * 1.5,
    vy: (random() - 0.5) * 1.5,
    r: min * 1.4 + random() * (max - min * 1.4),
    hue,
    targetHue: hue,
    hueSpeed: (random() < 0.5 ? -1 : 1) * (3 + random() * 5),
    age: MATURE_AGE,
    tx: 0,
    ty: 0,
    retarget: 0,
    phase: random() * Math.PI * 2,
  };
  pickTarget(cell, world, random);
  return cell;
}

export function createWorld(width: number, height: number, random: Random = Math.random): World {
  const world: World = {
    ...{ width, height, cells: [], time: 0 },
    ...{ phase: "idle", phaseTime: 0, energy: 0, gx: width / 2, gy: height / 2, regather: 0 },
  };
  for (let i = 0; i < 6; i++) world.cells.push(newCell(world, random));
  return world;
}

/** New canvas size: positions and sizes follow, so the picture keeps its layout. */
export function resizeWorld(world: World, width: number, height: number) {
  const sx = width / world.width;
  const sy = height / world.height;
  const scale = Math.min(width, height) / Math.min(world.width, world.height);
  for (const cell of world.cells) {
    cell.x *= sx;
    cell.y *= sy;
    cell.tx *= sx;
    cell.ty *= sy;
    cell.r *= scale;
  }
  world.gx *= sx;
  world.gy *= sy;
  world.width = width;
  world.height = height;
}

function divide(world: World, cell: Cell, random: Random) {
  const angle = random() * Math.PI * 2;
  const push = 1.5 + random() * 1.5;
  const r = cell.r / Math.SQRT2; // two halves on the same spot look exactly like the parent
  const [dx, dy] = [Math.cos(angle), Math.sin(angle)];
  const daughter = (sign: number): Cell => {
    const next: Cell = {
      x: cell.x + sign * dx * r * 0.15,
      y: cell.y + sign * dy * r * 0.15,
      vx: cell.vx + sign * dx * push,
      vy: cell.vy + sign * dy * push,
      r,
      // Both start with the parent's colour and drift to neighbouring colours as they go their own ways
      hue: cell.hue,
      targetHue: clampHue(cell.targetHue + sign * (12 + random() * 18)),
      hueSpeed: sign * Math.abs(cell.hueSpeed),
      age: 0,
      tx: cell.tx,
      ty: cell.ty,
      retarget: 0,
      phase: cell.phase + sign * 1.2,
    };
    return next;
  };
  const halves = [daughter(1), daughter(-1)];
  world.cells.splice(world.cells.indexOf(cell), 1, ...halves);
  for (const half of halves) {
    if (world.phase === "scatter") spreadTarget(half, world, random);
    else if (world.phase === "idle") pickTarget(half, world, random);
  }
}

/** b starts melting into a; a's colour heads for the mix of both. */
function startMerge(a: Cell, b: Cell) {
  const wa = a.r * a.r;
  const wb = b.r * b.r;
  a.targetHue = (a.targetHue * wa + b.targetHue * wb) / (wa + wb);
  b.into = a;
}

/** Hand part of a melting cell's area to the cell it melts into; true when it is gone. */
function melt(cell: Cell, dt: number, min: number): boolean {
  const target = cell.into!;
  const k = 1 - Math.exp(-MELT_RATE * dt);
  cell.x += (target.x - cell.x) * k;
  cell.y += (target.y - cell.y) * k;
  cell.vx = target.vx;
  cell.vy = target.vy;
  const area = cell.r * cell.r;
  const moved = cell.r < min * 0.25 ? area : area * k;
  target.r = Math.sqrt(target.r * target.r + moved);
  cell.r = Math.sqrt(area - moved);
  if (cell.r > 0) return false;
  target.age = 0;
  return true;
}

/** Phase changes: thinking starts a gathering at a new random meeting point; its end starts a scattering. */
function updatePhase(world: World, thinking: boolean, dt: number, random: Random) {
  world.phaseTime += dt;
  if (thinking && world.phase !== "gather") {
    world.phase = "gather";
    world.phaseTime = 0;
    [world.gx, world.gy] = randomSpot(world, random, 0.25);
    world.regather = 10 + random() * 6;
  } else if (!thinking && world.phase === "gather") {
    world.phase = "scatter";
    world.phaseTime = 0;
    for (const cell of world.cells) if (!cell.into) spreadTarget(cell, world, random);
  } else if (world.phase === "scatter") {
    const settled = world.cells.every(
      (c) => c.into || Math.hypot(c.tx - c.x, c.ty - c.y) < Math.min(world.width, world.height) * 0.12,
    );
    if (world.phaseTime > SCATTER_SECONDS || (settled && world.phaseTime > 3)) {
      world.phase = "idle";
      world.phaseTime = 0;
    }
  } else if (world.phase === "gather") {
    // A long answer: the meeting point moves now and then, so the cluster keeps travelling
    world.regather -= dt;
    if (world.regather <= 0) {
      [world.gx, world.gy] = randomSpot(world, random, 0.25);
      world.regather = 10 + random() * 6;
    }
  }
  const busy = world.phase === "idle" ? 0 : 1;
  world.energy += (busy - world.energy) * (1 - Math.exp(-ENERGY_RATE * dt));
}

/** Advance the world by dt seconds; thinking: the assistant is preparing an answer. */
export function step(world: World, dt: number, thinking: boolean, random: Random = Math.random) {
  updatePhase(world, thinking, dt, random);
  const { min, max } = radii(world);
  const { cells, width, height, energy, phase } = world;
  const wander = 2.5 + 9 * energy;
  const maxSpeed = 2 + 6.5 * energy;
  const seek = 0.7 + 2.6 * energy;
  const company = 0.5 + 1.2 * energy;
  const reach = Math.min(width, height) * 0.2;
  const colourPace = 0.25 + 0.75 * energy;
  const ease = 1 - Math.exp(-HUE_EASE * dt);
  const maxShift = HUE_MAX_RATE * dt;
  world.time += dt * (0.1 + 0.3 * energy);

  for (const cell of cells) {
    // Colour: the target shifts slowly (turning back at the ends of the range), the shown colour follows it
    cell.targetHue += cell.hueSpeed * colourPace * dt;
    if (cell.targetHue < HUE_MIN || cell.targetHue > HUE_MAX) {
      cell.targetHue = clampHue(cell.targetHue);
      cell.hueSpeed = -cell.hueSpeed;
    }
    cell.hue += Math.max(-maxShift, Math.min(maxShift, (cell.targetHue - cell.hue) * ease));
    cell.age += dt;
    if (cell.into) continue; // moved by melt() below

    // Where to: the meeting point while gathering, the cell's own spot otherwise (idle: picked anew now and then)
    if (phase === "idle") {
      cell.retarget -= dt;
      if (cell.retarget <= 0) pickTarget(cell, world, random);
    }
    const [goalX, goalY] = phase === "gather" ? [world.gx, world.gy] : [cell.tx, cell.ty];
    const toX = goalX - cell.x;
    const toY = goalY - cell.y;
    const toGoal = Math.hypot(toX, toY) || 0.001;
    const pull = seek * Math.min(1, toGoal / reach);
    cell.vx += ((toX / toGoal) * pull + (random() - 0.5) * wander) * dt;
    cell.vy += ((toY / toGoal) * pull + (random() - 0.5) * wander) * dt;
    // Neighbours: drawn together when gathering or in a sociable mood, pushed off when scattering or in an
    // unsociable one; never sinking in fully
    const mood = Math.sin(world.time + cell.phase);
    for (const other of cells) {
      if (other === cell || other.into) continue;
      const dx = other.x - cell.x;
      const dy = other.y - cell.y;
      const d = Math.hypot(dx, dy) || 0.001;
      const touch = cell.r + other.r;
      const social =
        phase === "gather" ? 1 : phase === "scatter" ? -1 : (mood + Math.sin(world.time + other.phase)) / 2;
      let force = 0;
      if (d < touch * 2.2) force += social * company * (1 - d / (touch * 2.2));
      if (d < touch * 0.7) force -= 3 * (1 - d / (touch * 0.7));
      cell.vx += (dx / d) * force * dt;
      cell.vy += (dy / d) * force * dt;
    }
    // Kept on screen (partly outside is fine)
    const margin = cell.r * 0.4;
    if (cell.x < -margin) cell.vx += 4 * dt;
    if (cell.x > width + margin) cell.vx -= 4 * dt;
    if (cell.y < -margin) cell.vy += 4 * dt;
    if (cell.y > height + margin) cell.vy -= 4 * dt;
    // Friction and a speed limit
    const damping = Math.exp(-0.8 * dt);
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

  // Melting cells hand over their area; gone ones leave the world
  world.cells = cells.filter((cell) => !(cell.into && melt(cell, dt, min)));

  // Two mature cells that sank into each other start to merge: often while gathering, never while scattering
  const live = world.cells.filter((c) => !c.into);
  const isTarget = (cell: Cell) => world.cells.some((c) => c.into === cell);
  const mergeChance = (phase === "gather" ? 0.6 : phase === "scatter" ? 0 : 0.05) * dt;
  const maxMerged = phase === "gather" ? max * 1.6 : max * 1.35;
  if (live.length > MIN_CELLS && mergeChance > 0) {
    search: for (let i = 0; i < live.length; i++) {
      for (let j = i + 1; j < live.length; j++) {
        const [a, b] = [live[i], live[j]];
        if (a.age < MATURE_AGE || b.age < MATURE_AGE || isTarget(b)) continue;
        if (Math.hypot(a.x - b.x, a.y - b.y) > (a.r + b.r) * 0.55) continue;
        if (Math.hypot(a.r, b.r) > maxMerged || random() > mergeChance) continue;
        // The smaller one melts into the larger one
        if (a.r >= b.r) startMerge(a, b);
        else if (!isTarget(a)) startMerge(b, a);
        break search;
      }
    }
  }

  // Cells divide: rarely while idle or gathering; while scattering the merged mass breaks up at once
  const count = () => world.cells.filter((c) => !c.into).length;
  const scatterReady = phase === "scatter" && count() < SCATTER_CELLS;
  const ready = world.cells.filter(
    (c) => !c.into && !isTarget(c) && (c.age >= MATURE_AGE || scatterReady) && c.r / Math.SQRT2 >= min,
  );
  if ((count() < MIN_CELLS || scatterReady) && ready.length) {
    divide(world, ready.reduce((a, b) => (b.r > a.r ? b : a)), random);
  } else {
    const divideChance = 0.015 * dt;
    for (const cell of ready) {
      if (count() >= MAX_CELLS) break;
      if (random() < divideChance) divide(world, cell, random);
    }
  }
  // Cells too small to divide again regain size slowly, so the picture never fades to specks
  for (const cell of world.cells) {
    if (!cell.into && cell.r < min * 1.4) cell.r += min * 0.05 * dt;
  }
}

function hslToRgb(h: number, s: number, l: number): [number, number, number] {
  const k = (n: number) => (n + h / 30) % 12;
  const a = s * Math.min(l, 1 - l);
  const f = (n: number) => l - a * Math.max(-1, Math.min(k(n) - 3, Math.min(9 - k(n), 1)));
  return [f(0) * 255, f(8) * 255, f(4) * 255];
}

/** The field as RGBA pixels: colours mixed by each cell's weight, transparent where the field is weak. */
export function render(world: World, data: Uint8ClampedArray, dark: boolean) {
  const { cells, width, height, energy } = world;
  const n = cells.length;
  const xs = new Float32Array(n);
  const ys = new Float32Array(n);
  const r2 = new Float32Array(n);
  const soft = new Float32Array(n);
  const rgb = new Float32Array(n * 3);
  cells.forEach((cell, i) => {
    xs[i] = cell.x;
    ys[i] = cell.y;
    r2[i] = cell.r * cell.r;
    // Flattens the field at the centre: a small cell inside a large one tints it instead of glowing as a dot
    soft[i] = 0.3 * r2[i] + 0.01;
    rgb.set(hslToRgb(cell.hue, dark ? 0.72 : 0.82, dark ? 0.52 : 0.7), i * 3);
  });
  const maxAlpha = (dark ? 0.5 : 0.55) + 0.1 * energy;
  // The field fades in from 0.3 and is full at 1.6 (soft edges, no rim)
  const [low, high] = [0.3, 1.6];

  let p = 0;
  for (let y = 0; y < height; y++) {
    for (let x = 0; x < width; x++) {
      let field = 0;
      let red = 0;
      let green = 0;
      let blue = 0;
      for (let i = 0; i < n; i++) {
        const dx = x - xs[i];
        const dy = y - ys[i];
        const f = r2[i] / (dx * dx + dy * dy + soft[i]);
        field += f;
        red += f * rgb[i * 3];
        green += f * rgb[i * 3 + 1];
        blue += f * rgb[i * 3 + 2];
      }
      const t = Math.min(1, Math.max(0, (field - low) / (high - low)));
      const weight = field || 1;
      data[p] = red / weight;
      data[p + 1] = green / weight;
      data[p + 2] = blue / weight;
      data[p + 3] = t * t * (3 - 2 * t) * maxAlpha * 255;
      p += 4;
    }
  }
}
