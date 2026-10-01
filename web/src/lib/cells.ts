// Colour fields that behave like cells: they roam the screen, cling to each other, pull apart, divide, and merge.
// They are drawn as a smooth field (each one adds r² / (d² + s²) and the colours mix by weight), so two of them flow
// into one shape when close and stretch apart before letting go, with no outline and no bright core. Each cell
// heads for a spot on the screen it picks anew every few seconds, and its "mood" swings between seeking company
// and keeping away, so clusters form and break up. "energy" (0 calm .. 1 thinking) sets how fast all of this goes.

export interface Cell {
  x: number;
  y: number;
  vx: number;
  vy: number;
  r: number;
  hue: number;
  /** Degrees per second the colour shifts (sign: direction) */
  hueSpeed: number;
  /** Seconds since the cell appeared; young cells neither divide nor merge */
  age: number;
  /** The spot the cell is heading for, and the seconds until it picks a new one */
  tx: number;
  ty: number;
  retarget: number;
  /** Phase of the mood: sin(time + phase) > 0 seeks company, < 0 keeps away */
  phase: number;
}

export interface World {
  width: number;
  height: number;
  cells: Cell[];
  /** Mood time (runs faster while thinking) */
  time: number;
}

export const MIN_CELLS = 4;
export const MAX_CELLS = 9;
// Teal to pink: random colours that still fit the purple theme
export const HUE_MIN = 175;
export const HUE_MAX = 335;
const MATURE_AGE = 2.5;

type Random = () => number;

function radii(world: Pick<World, "width" | "height">) {
  const size = Math.min(world.width, world.height);
  return { min: size * 0.08, max: size * 0.17 };
}

function clampHue(hue: number) {
  return Math.min(HUE_MAX, Math.max(HUE_MIN, hue));
}

function pickTarget(cell: Cell, world: Pick<World, "width" | "height">, random: Random) {
  cell.tx = world.width * (0.08 + random() * 0.84);
  cell.ty = world.height * (0.08 + random() * 0.84);
  cell.retarget = 6 + random() * 9;
}

function newCell(world: Pick<World, "width" | "height">, random: Random): Cell {
  const { min, max } = radii(world);
  const cell: Cell = {
    x: random() * world.width,
    y: random() * world.height,
    vx: (random() - 0.5) * 2,
    vy: (random() - 0.5) * 2,
    r: min * 1.4 + random() * (max - min * 1.4),
    hue: HUE_MIN + random() * (HUE_MAX - HUE_MIN),
    hueSpeed: (random() < 0.5 ? -1 : 1) * (6 + random() * 10),
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
  const world: World = { width, height, cells: [], time: 0 };
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
  world.width = width;
  world.height = height;
}

function divide(world: World, cell: Cell, random: Random) {
  const angle = random() * Math.PI * 2;
  const push = 3 + random() * 3;
  const r = cell.r / Math.SQRT2; // the two halves keep the area
  const [dx, dy] = [Math.cos(angle), Math.sin(angle)];
  const daughter = (sign: number): Cell => {
    const next: Cell = {
      x: cell.x + sign * dx * r * 0.3,
      y: cell.y + sign * dy * r * 0.3,
      vx: cell.vx + sign * dx * push,
      vy: cell.vy + sign * dy * push,
      r,
      // Daughters drift to neighbouring colours and go their own ways
      hue: clampHue(cell.hue + sign * (12 + random() * 18)),
      hueSpeed: sign * Math.abs(cell.hueSpeed),
      age: 0,
      tx: 0,
      ty: 0,
      retarget: 0,
      phase: cell.phase + sign * 1.2,
    };
    pickTarget(next, world, random);
    return next;
  };
  world.cells.splice(world.cells.indexOf(cell), 1, daughter(1), daughter(-1));
}

function merge(world: World, a: Cell, b: Cell) {
  const wa = a.r * a.r;
  const wb = b.r * b.r;
  const total = wa + wb;
  Object.assign(a, {
    x: (a.x * wa + b.x * wb) / total,
    y: (a.y * wa + b.y * wb) / total,
    vx: (a.vx * wa + b.vx * wb) / total,
    vy: (a.vy * wa + b.vy * wb) / total,
    r: Math.sqrt(total),
    hue: (a.hue * wa + b.hue * wb) / total,
    age: 0,
  });
  world.cells.splice(world.cells.indexOf(b), 1);
}

/** Advance the world by dt seconds. */
export function step(world: World, dt: number, energy: number, random: Random = Math.random) {
  const { min, max } = radii(world);
  const { cells, width, height } = world;
  const wander = 4 + 26 * energy;
  const maxSpeed = 2.5 + 14 * energy;
  const seek = 1 + 4.5 * energy;
  const company = 0.7 + 1.5 * energy;
  const reach = Math.min(width, height) * 0.2;
  world.time += dt * (0.12 + 0.5 * energy);

  for (const cell of cells) {
    // Roaming: towards a spot on the screen, picked anew every few seconds (more often while thinking)
    cell.retarget -= dt * (1 + 2 * energy);
    if (cell.retarget <= 0) pickTarget(cell, world, random);
    const toX = cell.tx - cell.x;
    const toY = cell.ty - cell.y;
    const toTarget = Math.hypot(toX, toY) || 0.001;
    const pull = seek * Math.min(1, toTarget / reach);
    cell.vx += ((toX / toTarget) * pull + (random() - 0.5) * wander) * dt;
    cell.vy += ((toY / toTarget) * pull + (random() - 0.5) * wander) * dt;
    // Neighbours: drawn together in a sociable mood, pushed off otherwise; never sinking in fully
    const mood = Math.sin(world.time + cell.phase);
    for (const other of cells) {
      if (other === cell) continue;
      const dx = other.x - cell.x;
      const dy = other.y - cell.y;
      const d = Math.hypot(dx, dy) || 0.001;
      const touch = cell.r + other.r;
      const social = (mood + Math.sin(world.time + other.phase)) / 2;
      let force = 0;
      if (d < touch * 2.2) force += social * company * (1 - d / (touch * 2.2));
      if (d < touch * 0.7) force -= 4 * (1 - d / (touch * 0.7));
      cell.vx += (dx / d) * force * dt;
      cell.vy += (dy / d) * force * dt;
    }
    // Kept on screen (partly outside is fine)
    const margin = cell.r * 0.4;
    if (cell.x < -margin) cell.vx += 6 * dt;
    if (cell.x > width + margin) cell.vx -= 6 * dt;
    if (cell.y < -margin) cell.vy += 6 * dt;
    if (cell.y > height + margin) cell.vy -= 6 * dt;
    // Friction and a speed limit
    const damping = Math.exp(-0.6 * dt);
    cell.vx *= damping;
    cell.vy *= damping;
    const speed = Math.hypot(cell.vx, cell.vy);
    if (speed > maxSpeed) {
      cell.vx *= maxSpeed / speed;
      cell.vy *= maxSpeed / speed;
    }
    cell.x += cell.vx * dt;
    cell.y += cell.vy * dt;
    // Colours shift, turning back at the ends of the range
    cell.hue += cell.hueSpeed * (0.15 + 1.6 * energy) * dt;
    if (cell.hue < HUE_MIN || cell.hue > HUE_MAX) {
      cell.hue = clampHue(cell.hue);
      cell.hueSpeed = -cell.hueSpeed;
    }
    cell.age += dt;
  }

  // Two mature cells that sank into each other sometimes become one
  const mergeChance = (0.08 + 0.9 * energy) * dt;
  for (let i = 0; i < cells.length && cells.length > MIN_CELLS; i++) {
    for (let j = i + 1; j < cells.length; j++) {
      const [a, b] = [cells[i], cells[j]];
      if (a.age < MATURE_AGE || b.age < MATURE_AGE) continue;
      if (Math.hypot(a.x - b.x, a.y - b.y) > (a.r + b.r) * 0.55) continue;
      if (Math.hypot(a.r, b.r) > max * 1.35 || random() > mergeChance) continue;
      merge(world, a, b);
      break;
    }
  }

  // Large mature cells sometimes divide; too few cells always lets the largest one divide
  const divideChance = (0.02 + 0.5 * energy) * dt;
  const ready = cells.filter((c) => c.age >= MATURE_AGE && c.r / Math.SQRT2 >= min);
  if (cells.length < MIN_CELLS && ready.length) {
    divide(world, ready.reduce((a, b) => (b.r > a.r ? b : a)), random);
  } else {
    for (const cell of ready) {
      if (world.cells.length >= MAX_CELLS) break;
      if (random() < divideChance) divide(world, cell, random);
    }
  }
  // Cells too small to divide again regain size slowly, so the picture never fades to specks
  for (const cell of world.cells) {
    if (cell.r < min * 1.4) cell.r += min * 0.05 * dt;
  }
}

function hslToRgb(h: number, s: number, l: number): [number, number, number] {
  const k = (n: number) => (n + h / 30) % 12;
  const a = s * Math.min(l, 1 - l);
  const f = (n: number) => l - a * Math.max(-1, Math.min(k(n) - 3, Math.min(9 - k(n), 1)));
  return [f(0) * 255, f(8) * 255, f(4) * 255];
}

/** The field as RGBA pixels: colours mixed by each cell's weight, transparent where the field is weak. */
export function render(world: World, data: Uint8ClampedArray, dark: boolean, energy: number) {
  const { cells, width, height } = world;
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
    soft[i] = 0.3 * r2[i];
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
      data[p] = red / field;
      data[p + 1] = green / field;
      data[p + 2] = blue / field;
      data[p + 3] = t * t * (3 - 2 * t) * maxAlpha * 255;
      p += 4;
    }
  }
}
