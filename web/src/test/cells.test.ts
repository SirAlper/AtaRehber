import { describe, expect, it } from "vitest";

import { createWorld, HUE_MAX, HUE_MIN, MAX_CELLS, MIN_CELLS, render, step, type World } from "@/lib/cells";
import { parseOklch, turnedPalette } from "@/lib/palette";

// Repeatable "random" numbers
function seeded(seed: number) {
  return () => {
    seed = (seed * 1664525 + 1013904223) % 4294967296;
    return seed / 4294967296;
  };
}

const FRAME = 1 / 30;
const live = (world: World) => world.cells.filter((c) => !c.into);

function area(world: World) {
  return world.cells.reduce((sum, c) => sum + c.r * c.r, 0);
}

/** Mean distance between the cells' centres */
function spread(world: World) {
  const cells = live(world);
  let sum = 0;
  let pairs = 0;
  for (let i = 0; i < cells.length; i++) {
    for (let j = i + 1; j < cells.length; j++) {
      sum += Math.hypot(cells[i].x - cells[j].x, cells[i].y - cells[j].y);
      pairs++;
    }
  }
  return pairs ? sum / pairs : 0;
}

/** Runs the world for some seconds; reports the fastest cell (canvas pixels per second). */
function run(world: World, seconds: number, thinking: boolean, random: () => number, each?: () => void) {
  let fastest = 0;
  for (let t = 0; t < seconds * 30; t++) {
    const before = new Map(world.cells.map((c) => [c, [c.x, c.y]]));
    step(world, FRAME, thinking, random);
    for (const cell of live(world)) {
      const was = before.get(cell);
      if (was) fastest = Math.max(fastest, Math.hypot(cell.x - was[0], cell.y - was[1]) / FRAME);
    }
    each?.();
  }
  return fastest;
}

describe("living colours", () => {
  it("gather and merge while the assistant thinks, then scatter at the same pace and calm down", () => {
    const random = seeded(7);
    const world = createWorld(170, 110, random);
    const calmSpeed = run(world, 20, false, random);
    const idleSpread = spread(world);
    const idleCount = live(world).length;

    const thinkingSpeed = run(world, 25, true, random);
    expect(world.phase).toBe("gather");
    expect(spread(world)).toBeLessThan(idleSpread * 0.6);
    expect(live(world).length).toBeLessThanOrEqual(idleCount);
    const gathered = { spread: spread(world), count: live(world).length };

    // The answer is in: as fast as while thinking, they push apart and the mass divides
    let energyWhileScattering = 1;
    run(world, 3, false, random, () => (energyWhileScattering = Math.min(energyWhileScattering, world.energy)));
    expect(energyWhileScattering).toBeGreaterThan(0.85);
    run(world, 7, false, random);
    expect(spread(world)).toBeGreaterThan(gathered.spread * 1.6);
    expect(live(world).length).toBeGreaterThan(gathered.count);

    run(world, 10, false, random);
    expect(world.phase).toBe("idle");
    expect(world.energy).toBeLessThan(0.3);

    // Canvas pixels per second (a canvas pixel is about 8 screen pixels)
    expect(calmSpeed).toBeLessThan(3);
    expect(thinkingSpeed).toBeGreaterThan(calmSpeed * 1.5);
    expect(thinkingSpeed).toBeLessThan(9);
  });

  it("scatter to different places every time", () => {
    const random = seeded(21);
    const world = createWorld(170, 110, random);
    const layouts: number[][][] = [];
    for (let round = 0; round < 2; round++) {
      run(world, 15, true, random);
      run(world, 12, false, random);
      layouts.push(live(world).map((c) => [c.x, c.y]));
    }
    // How far each cell of the second layout is from the nearest cell of the first one, on average
    const [first, second] = layouts;
    const offset =
      second.reduce((sum, [x, y]) => sum + Math.min(...first.map(([a, b]) => Math.hypot(x - a, y - b))), 0) /
      second.length;
    expect(offset).toBeGreaterThan(110 * 0.08);
  });

  it("turn the palette to a new one per question and back to the theme after the answer, smoothly", () => {
    const random = seeded(9);
    const world = createWorld(170, 110, random);
    const turns: number[] = [];
    let largestStep = 0;
    const watch = () => {
      const before = world.paletteShift;
      return () => (largestStep = Math.max(largestStep, Math.abs(world.paletteShift - before)));
    };
    for (let round = 0; round < 3; round++) {
      for (let t = 0; t < 15 * 30; t++) {
        const done = watch();
        step(world, FRAME, true, random);
        done();
      }
      turns.push(world.paletteShift);
      expect(Math.abs(world.paletteShift)).toBeGreaterThan(50);
      expect(Math.abs(world.paletteShift)).toBeLessThanOrEqual(150);
      // Halfway back after a few seconds of scattering, the theme's own colours once calm
      for (let t = 0; t < 4 * 30; t++) step(world, FRAME, false, random);
      expect(Math.abs(world.paletteShift)).toBeLessThan(Math.abs(turns[round]));
      expect(Math.abs(world.paletteShift)).toBeGreaterThan(0);
      for (let t = 0; t < 20 * 30; t++) {
        const done = watch();
        step(world, FRAME, false, random);
        done();
      }
      expect(world.paletteShift).toBe(0);
    }
    // A new palette each time, reached at most 18 degrees per second
    expect(new Set(turns.map((turn) => Math.round(turn))).size).toBe(3);
    expect(largestStep).toBeLessThanOrEqual(18 * FRAME + 1e-9);
  });

  it("turn the site's brand colours by the same angle", () => {
    expect(parseOklch("oklch(60.6% .25 292.717)")).toEqual(["60.6%", 0.25, 292.717]);
    expect(parseOklch("#8b5cf6")).toBeNull();
    const base = new Map([["--color-violet-500", parseOklch("oklch(60.6% .25 292.717)")!]]);
    expect(turnedPalette(base, 100).get("--color-violet-500")).toBe("oklch(60.6% 0.25 32.72)");
    expect(turnedPalette(base, -300).get("--color-violet-500")).toBe("oklch(60.6% 0.25 352.72)");
  });

  it("change colour gradually, also when they divide or merge", () => {
    const random = seeded(4);
    const world = createWorld(170, 110, random);
    let largest = 0;
    let events = 0;
    for (let round = 0; round < 3; round++) {
      for (const [seconds, thinking] of [
        [20, true],
        [15, false],
      ] as const) {
        for (let t = 0; t < seconds * 30; t++) {
          const before = new Map(world.cells.map((c) => [c, c.hue]));
          const count = world.cells.length;
          step(world, FRAME, thinking, random);
          if (world.cells.length !== count) events++;
          for (const cell of world.cells) {
            // A new half starts with its parent's colour
            const was = before.get(cell) ?? cell.hue;
            largest = Math.max(largest, Math.abs(cell.hue - was));
          }
        }
      }
    }
    expect(events).toBeGreaterThan(5);
    // At most 12 degrees per second
    expect(largest).toBeLessThanOrEqual(12 * FRAME + 1e-9);
  });

  it("stay within the number of cells, on screen, in the colour range, and keep their area", () => {
    const random = seeded(3);
    const world = createWorld(170, 110, random);
    for (let round = 0; round < 3; round++) {
      for (const thinking of [true, false]) {
        for (let t = 0; t < 20 * 30; t++) {
          const before = area(world);
          step(world, FRAME, thinking, random);
          // Small cells regrow a little each step, nothing else adds or removes area
          expect(area(world)).toBeGreaterThanOrEqual(before * 0.999);
          expect(area(world)).toBeLessThan(before * 1.01);
          const count = live(world).length;
          expect(count).toBeGreaterThanOrEqual(MIN_CELLS - 1);
          expect(count).toBeLessThanOrEqual(MAX_CELLS + 1);
        }
      }
    }
    for (const cell of world.cells) {
      expect(cell.x).toBeGreaterThan(-cell.r * 2);
      expect(cell.x).toBeLessThan(world.width + cell.r * 2);
      expect(cell.y).toBeGreaterThan(-cell.r * 2);
      expect(cell.y).toBeLessThan(world.height + cell.r * 2);
      expect(cell.hue).toBeGreaterThanOrEqual(HUE_MIN);
      expect(cell.hue).toBeLessThanOrEqual(HUE_MAX);
    }
  });

  it("are drawn as soft colour: opaque inside, transparent far away, no hard rim", () => {
    const world = createWorld(60, 40, seeded(5));
    world.cells = [
      {
        ...{ x: 30, y: 20, vx: 0, vy: 0, r: 6, hue: 270, targetHue: 270, hueSpeed: 0 },
        ...{ age: 0, tx: 30, ty: 20, retarget: 9, phase: 0 },
      },
    ];
    const data = new Uint8ClampedArray(60 * 40 * 4);
    render(world, data, false);
    const alpha = (x: number, y: number) => data[(y * 60 + x) * 4 + 3];
    expect(alpha(30, 20)).toBeGreaterThan(120);
    expect(alpha(0, 0)).toBe(0);
    // Along a line from the centre the colour fades step by step
    const line = Array.from({ length: 14 }, (_, i) => alpha(30 + i, 20));
    const jumps = line.slice(1).map((a, i) => line[i] - a);
    expect(Math.max(...jumps)).toBeLessThan(60);
  });
});
