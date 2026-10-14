import { describe, expect, it } from "vitest";
import {
  agoLabel,
  areaPath,
  isolatedPoints,
  labelIndexes,
  linePath,
  present,
  runs,
  xByIndex,
  xByTime,
  type Pt,
} from "./chartPath";

const pt = (x: number, y = 0): Pt => ({ x, y });

/** x values of every drawn segment, parsed back out of a "M x,y L x,y ..." path. */
function segmentXs(path: string): number[][] {
  return path
    .split("M")
    .filter((s) => s.length > 0)
    .map((s) => s.split("L").map((pair) => Number(pair.split(",")[0])));
}

describe("runs", () => {
  it("returns one run for a series without gaps", () => {
    expect(runs([pt(0), pt(1), pt(2)])).toEqual([[pt(0), pt(1), pt(2)]]);
  });

  it("splits at every null and drops empty runs", () => {
    const series = [null, pt(1), pt(2), null, null, pt(5), null];
    expect(runs(series)).toEqual([[pt(1), pt(2)], [pt(5)]]);
  });

  it("returns nothing for an empty or all-null series", () => {
    expect(runs([])).toEqual([]);
    expect(runs([null, null])).toEqual([]);
  });
});

describe("linePath", () => {
  it("draws one segment per run and never bridges a gap", () => {
    const series = [pt(0, 5), pt(1, 6), null, null, pt(4, 7), pt(5, 8)];
    const segments = segmentXs(linePath(series));
    expect(segments).toEqual([
      [0, 1],
      [4, 5],
    ]);
  });

  it("never connects points that are not adjacent bins", () => {
    // 24 bins with gaps at 3, 9-11 and 23: every drawn step must be exactly one bin.
    const gaps = new Set([3, 9, 10, 11, 23]);
    const series = Array.from({ length: 24 }, (_, i) => (gaps.has(i) ? null : pt(i, i % 7)));
    for (const segment of segmentXs(linePath(series))) {
      segment.slice(1).forEach((x, i) => expect(x - segment[i]).toBe(1));
    }
  });

  it("draws a trailing gap as a line that ends at the last reading", () => {
    const series = [pt(0), pt(1), pt(2), null, null];
    expect(segmentXs(linePath(series))).toEqual([[0, 1, 2]]);
  });

  it("draws nothing for a single reading or no readings", () => {
    expect(linePath([pt(0)])).toBe("");
    expect(linePath([null, pt(3), null])).toBe("");
    expect(linePath([null, null])).toBe("");
  });

  it("formats a simple path", () => {
    expect(linePath([pt(0, 1), pt(2, 3)])).toBe("M0,1L2,3");
  });
});

describe("isolatedPoints", () => {
  it("returns readings that stand alone between gaps", () => {
    const series = [pt(0), null, pt(2), pt(3), null, pt(5)];
    expect(isolatedPoints(series)).toEqual([pt(0), pt(5)]);
  });

  it("returns a series of one reading", () => {
    expect(isolatedPoints([pt(7)])).toEqual([pt(7)]);
  });
});

describe("areaPath", () => {
  it("closes each run down to the baseline and skips lone readings", () => {
    const series = [pt(0, 2), pt(1, 3), null, pt(3, 4), null, pt(5, 6), pt(6, 7)];
    expect(areaPath(series, 10)).toBe("M0,2L1,3L1,10L0,10ZM5,6L6,7L6,10L5,10Z");
  });

  it("is empty without a drawable run", () => {
    expect(areaPath([null, pt(1), null], 10)).toBe("");
  });
});

describe("xByIndex", () => {
  it("spreads bins evenly from left to left + width", () => {
    expect([0, 1, 2, 3].map((i) => xByIndex(i, 4, 10, 30))).toEqual([10, 20, 30, 40]);
  });

  it("puts a single bin at the left edge", () => {
    expect(xByIndex(0, 1, 10, 30)).toBe(10);
  });
});

describe("xByTime", () => {
  const MIN = 60_000;

  it("places bins in proportion to elapsed time, so a gap leaves a gap", () => {
    const times = [0, 15 * MIN, 30 * MIN, 75 * MIN];
    expect(xByTime(times, 0, 150)).toEqual([0, 30, 60, 150]);
  });

  it("returns null when times are unusable so callers fall back to even spacing", () => {
    expect(xByTime([0], 0, 100)).toBeNull();
    expect(xByTime([0, Number.NaN, 2], 0, 100)).toBeNull();
    expect(xByTime([0, 5, 5], 0, 100)).toBeNull();
    expect(xByTime([10, 5], 0, 100)).toBeNull();
    expect(xByTime([Date.parse("06:30"), Date.parse("07:00")], 0, 100)).toBeNull();
  });
});

describe("agoLabel", () => {
  it.each([
    [0, "now"],
    [-3, "now"],
    [15, "-15m"],
    [45, "-45m"],
    [60, "-1h"],
    [180, "-3h"],
    [345, "-5h45m"],
    [359.6, "-6h"],
  ])("%s min -> %s", (minutes, label) => {
    expect(agoLabel(minutes)).toBe(label);
  });
});

describe("present", () => {
  it("keeps zero and drops nulls", () => {
    expect(present([0, null, 3, null, 0])).toEqual([0, 3, 0]);
  });
});

describe("labelIndexes", () => {
  it.each([
    [0, []],
    [1, [0]],
    [2, [0, 1]],
    [3, [0, 1, 2]],
    [24, [0, 12, 23]],
  ])("%s bins -> %j", (n, expected) => {
    expect(labelIndexes(n)).toEqual(expected);
  });
});
