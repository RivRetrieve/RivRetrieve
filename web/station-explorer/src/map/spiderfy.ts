export interface SpiderOffset {
  x: number;
  y: number;
}

const CIRCLE_THRESHOLD = 8;
const CIRCLE_STEP_SEPARATION = 34;
const SPIRAL_START_ANGLE = Math.PI / 6;
const SPIRAL_SEPARATION = 28;
const SPIRAL_LENGTH_STEP = 12;

/**
 * Compute pixel offsets around a shared cluster point so co-located gauges
 * fan out cleanly into non-overlapping clickable pins (circle up to 8, spiral above).
 */
export function computeSpiderOffsets(count: number): SpiderOffset[] {
  if (count <= 0) return [];
  if (count <= CIRCLE_THRESHOLD) {
    const circumference = count * CIRCLE_STEP_SEPARATION;
    const radius = Math.max(24, circumference / (Math.PI * 2));
    const step = (Math.PI * 2) / count;
    const offsets: SpiderOffset[] = [];
    for (let i = 0; i < count; i++) {
      const angle = i * step;
      offsets.push({
        x: Math.round(radius * Math.cos(angle)),
        y: Math.round(radius * Math.sin(angle)),
      });
    }
    return offsets;
  }

  let legLength = 24;
  let angle = SPIRAL_START_ANGLE;
  const offsets: SpiderOffset[] = [];
  for (let i = 0; i < count; i++) {
    angle += SPIRAL_SEPARATION / legLength;
    offsets.push({
      x: Math.round(legLength * Math.cos(angle)),
      y: Math.round(legLength * Math.sin(angle)),
    });
    legLength += (Math.PI * 2 * SPIRAL_LENGTH_STEP) / angle;
  }
  return offsets;
}
