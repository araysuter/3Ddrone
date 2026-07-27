import { describe, expect, it } from "vitest";
import { eptSceneFrame, selectEptNodes } from "./ept";

describe("selectEptNodes", () => {
  it("loads coarse hierarchy levels before deeper detail", () => {
    const selected = selectEptNodes(
      {
        "2-0-0-0": 200,
        "0-0-0-0": 100,
        "1-0-0-0": 150,
        "1-1-0-0": 150,
      },
      450,
    );

    expect(selected.map((node) => node.key)).toEqual([
      "0-0-0-0",
      "1-0-0-0",
      "1-1-0-0",
    ]);
  });
});

describe("eptSceneFrame", () => {
  it("centers horizontally and anchors the scene to its ground elevation", () => {
    const frame = eptSceneFrame({
      bounds: [0, 0, 0, 20, 40, 10],
      boundsConforming: [2, 4, 6, 18, 36, 14],
      dataType: "laszip",
      hierarchyType: "json",
      points: 1,
    });

    expect(frame.origin).toEqual([10, 20, 6]);
    expect(frame.radius).toBeCloseTo(Math.hypot(8, 8, 16));
  });
});
