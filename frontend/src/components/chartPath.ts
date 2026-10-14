/**
 * Pure geometry for the trend charts.
 *
 * A null value is a gap (I1: missing is missing): the line breaks there, nothing is
 * bridged or interpolated, and no point is drawn for it. A stretch of one point between
 * gaps is drawn as a dot, never as a line.
 */

export interface Pt {
  readonly x: number;
  readonly y: number;
}

/** Runs of consecutive non-null points, in order. A null ends the current run. */
export function runs(points: readonly (Pt | null)[]): Pt[][] {
  const out: Pt[][] = [];
  let current: Pt[] = [];
  for (const p of points) {
    if (p === null) {
      if (current.length > 0) out.push(current);
      current = [];
    } else {
      current.push(p);
    }
  }
  if (current.length > 0) out.push(current);
  return out;
}

const pair = (p: Pt) => `${p.x},${p.y}`;

/** "M x,y L x,y ..." for each run of two or more points; "" when there is no line to draw. */
export function linePath(points: readonly (Pt | null)[]): string {
  return runs(points)
    .filter((r) => r.length >= 2)
    .map((r) => `M${r.map(pair).join("L")}`)
    .join("");
}

/** Closed area under each run of two or more points, down to `baseline`. */
export function areaPath(points: readonly (Pt | null)[], baseline: number): string {
  return runs(points)
    .filter((r) => r.length >= 2)
    .map((r) => {
      const first = r[0];
      const last = r[r.length - 1];
      return `M${r.map(pair).join("L")}L${last.x},${baseline}L${first.x},${baseline}Z`;
    })
    .join("");
}

/** Points that stand alone between gaps (or alone in the series). */
export function isolatedPoints(points: readonly (Pt | null)[]): Pt[] {
  return runs(points)
    .filter((r) => r.length === 1)
    .map((r) => r[0]);
}

/** x for index i of n evenly spaced bins across [left, left + width]. */
export function xByIndex(i: number, n: number, left: number, width: number): number {
  return n <= 1 ? left : left + (i / (n - 1)) * width;
}

/**
 * x for each timestamp (ms), proportional to elapsed time across [left, left + width].
 * Returns null unless the times are finite and strictly increasing, so the caller falls
 * back to even spacing instead of drawing from nonsense.
 */
export function xByTime(times: readonly number[], left: number, width: number): number[] | null {
  if (times.length < 2) return null;
  for (let i = 0; i < times.length; i++) {
    if (!Number.isFinite(times[i])) return null;
    if (i > 0 && times[i] <= times[i - 1]) return null;
  }
  const t0 = times[0];
  const span = times[times.length - 1] - t0;
  return times.map((t) => left + ((t - t0) / span) * width);
}

/** "now", "-45m", "-3h", "-5h45m": how long before the latest bin, whole minutes. */
export function agoLabel(minutes: number): string {
  const m = Math.max(0, Math.round(minutes));
  if (m === 0) return "now";
  if (m < 60) return `-${m}m`;
  const h = Math.floor(m / 60);
  const rest = m % 60;
  return rest === 0 ? `-${h}h` : `-${h}h${rest}m`;
}

/** The non-null values, in order. */
export function present(values: readonly (number | null)[]): number[] {
  return values.filter((v): v is number => v !== null);
}

/** Indexes of the bins that get an axis label: first, middle, last, without repeats. */
export function labelIndexes(n: number): number[] {
  if (n <= 0) return [];
  return [...new Set([0, Math.floor(n / 2), n - 1])];
}
