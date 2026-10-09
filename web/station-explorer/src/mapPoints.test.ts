import { describe, it, expect } from "vitest";
import { groupPoints } from "./mapPoints";
const points = [
  { x: 10, y: 10, key: "a" },
  { x: 20, y: 20, key: "b" },
  { x: 110, y: 20, key: "c" },
];
describe("screen-space gauge groups", () => {
  it("groups nearby points and preserves every member exactly once", () => {
    const groups = groupPoints(points, 64);
    expect(
      groups.map((g) => ({
        x: g.x,
        y: g.y,
        keys: g.members.map((p) => p.key),
      })),
    ).toEqual([
      { x: 15, y: 15, keys: ["a", "b"] },
      { x: 110, y: 20, keys: ["c"] },
    ]);
  });
  it("splits a group as map zoom separates projected points", () => {
    expect(groupPoints(points.slice(0, 2), 64)).toHaveLength(1);
    expect(
      groupPoints(
        [
          { x: 10, y: 10, key: "a" },
          { x: 100, y: 100, key: "b" },
        ],
        64,
      ),
    ).toHaveLength(2);
  });
  it("retains coincident gauge identities for group inspection", () => {
    expect(
      groupPoints(
        [
          { x: 10, y: 10, key: "a" },
          { x: 10, y: 10, key: "b" },
        ],
        64,
      )[0].members.map((p) => p.key),
    ).toEqual(["a", "b"]);
    expect(groupPoints([], 64)).toEqual([]);
  });
});

it("merges neighboring cell groups so count bubbles do not overlap", () => {
  const groups = groupPoints(
    [
      { x: 63, y: 20, key: "left" },
      { x: 65, y: 20, key: "right" },
    ],
    64,
  );
  expect(groups).toHaveLength(1);
  expect(groups[0].members.map((point) => point.key)).toEqual([
    "left",
    "right",
  ]);
});
