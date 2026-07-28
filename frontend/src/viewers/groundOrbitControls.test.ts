import { MOUSE } from "three";
import { describe, expect, it } from "vitest";
import {
  configureGroundMouseButtons,
  constantPanSpeed,
  groundOrbitPolarLimits,
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

describe("configureGroundMouseButtons", () => {
  it("maps a held scroll wheel to pan without changing normal wheel zoom", () => {
    const controls = {
      mouseButtons: {
        LEFT: MOUSE.ROTATE,
        MIDDLE: MOUSE.DOLLY,
        RIGHT: MOUSE.PAN,
      },
    };

    configureGroundMouseButtons(controls);

    expect(controls.mouseButtons).toEqual({
      LEFT: MOUSE.ROTATE,
      MIDDLE: MOUSE.PAN,
      RIGHT: MOUSE.PAN,
    });
  });
});

describe("groundOrbitPolarLimits", () => {
  it("lets point clouds and textured models orbit from overhead to the ground horizon", () => {
    const limits = groundOrbitPolarLimits(1.1, true);

    expect(limits.minimum).toBeGreaterThan(0);
    expect(limits.minimum).toBeLessThan(0.02);
    expect(limits.maximum).toBeLessThan(Math.PI / 2);
    expect(limits.maximum).toBeGreaterThan(Math.PI / 2 - 0.02);
  });

  it("keeps the fixed-elevation behavior when overhead orbit is not enabled", () => {
    expect(groundOrbitPolarLimits(1.1)).toEqual({
      minimum: 1.1,
      maximum: 1.1,
    });
  });
});
