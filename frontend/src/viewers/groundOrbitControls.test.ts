import { describe, expect, it } from "vitest";
import {
  constantPanSpeed,
  linearZoomSpeed,
} from "./groundOrbitControls";

const ZOOM_BASE = 0.95;

describe("linearZoomSpeed", () => {
  it("moves by the same world distance at near and far camera ranges", () => {
    const delta = -100;
    const sceneScale = 100;
    const farDistance = 200;
    const nearDistance = 40;
    const farSpeed = linearZoomSpeed(farDistance, sceneScale, delta);
    const nearSpeed = linearZoomSpeed(nearDistance, sceneScale, delta);
    const farResult = farDistance * ZOOM_BASE ** farSpeed;
    const nearResult = nearDistance * ZOOM_BASE ** nearSpeed;

    expect(farDistance - farResult).toBeCloseTo(8);
    expect(nearDistance - nearResult).toBeCloseTo(8);
  });

  it("has no artificial zoom-out distance cap", () => {
    const speed = linearZoomSpeed(10_000, 100, 100);
    const result = 10_000 / ZOOM_BASE ** speed;

    expect(result).toBeCloseTo(10_008);
  });
});

describe("constantPanSpeed", () => {
  it("compensates for camera distance so a drag covers constant world space", () => {
    const far = constantPanSpeed(200, 100, 800, 55);
    const near = constantPanSpeed(40, 100, 800, 55);
    const projection = (distance: number, speed: number) =>
      (2 * 10 * speed * distance * Math.tan((55 * Math.PI) / 360)) / 800;

    expect(projection(200, far)).toBeCloseTo(1.5);
    expect(projection(40, near)).toBeCloseTo(1.5);
  });
});
