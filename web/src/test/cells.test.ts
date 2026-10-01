import { describe, expect, it } from "vitest";

import { createWorld, HUE_MAX, HUE_MIN, MAX_CELLS, MIN_CELLS, render, step, type World } from "@/lib/cells";

// Repeatable "random" numbers
function seeded(seed: number) {
  return () => {
    seed = (seed * 1664525 + 1013904223) % 4294967296;
    return seed / 4294967296;
  };
}

function area(world: World) {
  return world.cells.reduce((sum, c) => sum + c.r * c.r, 0);
}

function run(energy: number, seconds: number, seed = 7) {
  const random = seeded(seed);
  const world = createWorld(170, 110, random);
  let travelled = 0;
  let counts = new Set<number>();
  for (let t = 0; t < seconds * 30; t++) {
    const before = world.cells.map((c) => [c.x, c.y]);
    step(world, 1 / 30, energy, random);
    if (world.cells.length === before.length) {
      travelled += world.cells.reduce((sum, c, i) => sum + Math.hypot(c.x - before[i][0], c.y - before[i][1]), 0);
    }
    counts = counts.add(world.cells.length);
  }
  return { world, travelled, counts };
}

describe("living colours", () => {
  it("move, divide, and merge more while the assistant thinks", () => {
    const calm = run(0, 60);
    const thinking = run(1, 60);
    expect(thinking.travelled).toBeGreaterThan(calm.travelled * 2);
    expect(thinking.counts.size).toBeGreaterThan(1);
  });

  it("stay within the number of cells, on screen, and in the colour range", () => {
    const { world, counts } = run(1, 120, 3);
    for (const count of counts) {
      expect(count).toBeGreaterThanOrEqual(MIN_CELLS - 1);
      expect(count).toBeLessThanOrEqual(MAX_CELLS + 1);
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

  it("keep their area when they divide or merge", () => {
    const random = seeded(11);
    const world = createWorld(170, 110, random);
    for (let t = 0; t < 600; t++) {
      const before = { count: world.cells.length, area: area(world) };
      step(world, 1 / 30, 1, random);
      if (world.cells.length !== before.count) {
        // Small cells regrow a little each step, so only that much may be added
        expect(area(world)).toBeGreaterThanOrEqual(before.area * 0.999);
        expect(area(world)).toBeLessThan(before.area * 1.05);
      }
    }
  });

  it("are drawn as soft colour: opaque inside, transparent far away, no hard rim", () => {
    const world = createWorld(60, 40, seeded(5));
    world.cells = [
      { x: 30, y: 20, vx: 0, vy: 0, r: 6, hue: 270, hueSpeed: 0, age: 0, tx: 30, ty: 20, retarget: 9, phase: 0 },
    ];
    const data = new Uint8ClampedArray(60 * 40 * 4);
    render(world, data, false, 0);
    const alpha = (x: number, y: number) => data[(y * 60 + x) * 4 + 3];
    expect(alpha(30, 20)).toBeGreaterThan(120);
    expect(alpha(0, 0)).toBe(0);
    // Along a line from the centre the colour fades step by step
    const line = Array.from({ length: 14 }, (_, i) => alpha(30 + i, 20));
    const jumps = line.slice(1).map((a, i) => line[i] - a);
    expect(Math.max(...jumps)).toBeLessThan(60);
  });
});
