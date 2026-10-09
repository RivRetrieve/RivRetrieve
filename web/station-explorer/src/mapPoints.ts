/** Group projected points in fixed screen cells; map zoom changes their separation. */
export function groupPoints<T extends { x: number; y: number }>(
  points: T[],
  cellSize: number,
): { x: number; y: number; members: T[] }[] {
  const cells = new Map<string, { x: number; y: number; members: T[] }>();
  for (const point of points) {
    const key = `${Math.floor(point.x / cellSize)},${Math.floor(point.y / cellSize)}`;
    const group = cells.get(key);
    if (group) {
      group.x += point.x;
      group.y += point.y;
      group.members.push(point);
    } else cells.set(key, { x: point.x, y: point.y, members: [point] });
  }
  const groups = [...cells.values()].map((group) => ({
    ...group,
    x: group.x / group.members.length,
    y: group.y / group.members.length,
  }));
  // Merge nearby cell centroids until 44px count bubbles have a 4px gap.
  const minimumDistance = cellSize * 0.75;
  let merged = true;
  while (merged) {
    merged = false;
    outer: for (let i = 0; i < groups.length; i++) {
      for (let j = i + 1; j < groups.length; j++) {
        const a = groups[i],
          b = groups[j];
        if ((a.x - b.x) ** 2 + (a.y - b.y) ** 2 >= minimumDistance ** 2)
          continue;
        const count = a.members.length + b.members.length;
        a.x = (a.x * a.members.length + b.x * b.members.length) / count;
        a.y = (a.y * a.members.length + b.y * b.members.length) / count;
        a.members.push(...b.members);
        groups.splice(j, 1);
        merged = true;
        break outer;
      }
    }
  }
  return groups;
}
