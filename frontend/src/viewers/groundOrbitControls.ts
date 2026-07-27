import { MOUSE, type PerspectiveCamera } from "three";
import type { OrbitControls } from "three/addons/controls/OrbitControls.js";

const ORBIT_ZOOM_BASE = 0.95;
const LINEAR_ZOOM_PER_DELTA = 0.0008;
const CONSTANT_PAN_PER_PIXEL = 0.0015;
const MIN_SCENE_SCALE = 0.000001;
const OVERHEAD_POLAR_LIMIT = 0.01;
const GROUND_HORIZON_POLAR_LIMIT = Math.PI / 2 - 0.01;

export function normalizedWheelDelta(event: Pick<WheelEvent, "ctrlKey" | "deltaMode" | "deltaY">) {
  let delta = event.deltaY;
  if (event.deltaMode === WheelEvent.DOM_DELTA_LINE) delta *= 16;
  if (event.deltaMode === WheelEvent.DOM_DELTA_PAGE) delta *= 100;
  if (event.ctrlKey) delta *= 10;
  return delta;
}

export function linearZoomSpeed(
  distance: number,
  sceneScale: number,
  normalizedDelta: number,
) {
  const deltaMagnitude = Math.abs(normalizedDelta);
  if (!Number.isFinite(distance) || distance <= 0 || deltaMagnitude === 0) return 1;

  const safeScale = Math.max(sceneScale, MIN_SCENE_SCALE);
  const step = safeScale * LINEAR_ZOOM_PER_DELTA * deltaMagnitude;
  const minimumDistance = safeScale * 1e-7;
  const nextDistance =
    normalizedDelta < 0
      ? Math.max(minimumDistance, distance - step)
      : distance + step;
  const orbitScale =
    normalizedDelta < 0 ? nextDistance / distance : distance / nextDistance;
  const orbitDelta = deltaMagnitude * 0.01;
  if (orbitScale <= 0 || orbitScale === 1 || orbitDelta === 0) return 1;
  return Math.log(orbitScale) / Math.log(ORBIT_ZOOM_BASE) / orbitDelta;
}

export function constantPanSpeed(
  distance: number,
  sceneScale: number,
  viewportHeight: number,
  verticalFovDegrees: number,
) {
  const projectedHalfHeight =
    Math.max(distance, MIN_SCENE_SCALE) *
    Math.tan((verticalFovDegrees * Math.PI) / 360);
  if (projectedHalfHeight <= 0) return 1;
  const worldUnitsPerPixel = Math.max(sceneScale, MIN_SCENE_SCALE) * CONSTANT_PAN_PER_PIXEL;
  return (
    (worldUnitsPerPixel * Math.max(viewportHeight, 1)) /
    (2 * projectedHalfHeight)
  );
}

export interface GroundOrbitController {
  setScene: (sceneScale: number, groundY?: number) => void;
  update: () => void;
  dispose: () => void;
}

export interface GroundOrbitOptions {
  allowAboveGroundOrbit?: boolean;
}

export function groundOrbitPolarLimits(
  initialPolarAngle: number,
  allowAboveGroundOrbit = false,
) {
  return allowAboveGroundOrbit
    ? {
        minimum: OVERHEAD_POLAR_LIMIT,
        maximum: GROUND_HORIZON_POLAR_LIMIT,
      }
    : {
        minimum: initialPolarAngle,
        maximum: initialPolarAngle,
      };
}

export function configureGroundMouseButtons(
  controls: Pick<OrbitControls, "mouseButtons">,
) {
  controls.mouseButtons.MIDDLE = MOUSE.PAN;
}

export function createGroundOrbitController(
  controls: OrbitControls,
  camera: PerspectiveCamera,
  element: HTMLElement,
  options: GroundOrbitOptions = {},
): GroundOrbitController {
  let sceneScale = 1;
  let groundY = 0;

  controls.enableDamping = true;
  controls.dampingFactor = 0.08;
  controls.screenSpacePanning = false;
  controls.zoomToCursor = false;
  controls.minDistance = 0;
  controls.maxDistance = Infinity;
  controls.minTargetRadius = 0;
  controls.maxTargetRadius = Infinity;
  configureGroundMouseButtons(controls);

  const updateNavigationRates = () => {
    const distance = controls.getDistance();
    controls.panSpeed = constantPanSpeed(
      distance,
      sceneScale,
      element.clientHeight,
      camera.fov,
    );
    controls.keyPanSpeed = controls.panSpeed * 16;

    const nextNear = Math.max(sceneScale * 1e-7, distance * 0.0005);
    const nextFar = Math.max(sceneScale * 100, distance * 20);
    if (
      Math.abs(camera.near - nextNear) / Math.max(camera.near, MIN_SCENE_SCALE) >
        0.1 ||
      Math.abs(camera.far - nextFar) / Math.max(camera.far, MIN_SCENE_SCALE) >
        0.1
    ) {
      camera.near = nextNear;
      camera.far = nextFar;
      camera.updateProjectionMatrix();
    }
  };

  const handleWheel = (event: WheelEvent) => {
    const delta = normalizedWheelDelta(event);
    controls.zoomSpeed = linearZoomSpeed(
      controls.getDistance(),
      sceneScale,
      delta,
    );
  };
  const handlePointerDown = (event: PointerEvent) => {
    if (event.pointerType === "touch" || event.button === 1) {
      controls.zoomSpeed = 1;
    }
  };
  element.addEventListener("wheel", handleWheel, {
    capture: true,
    passive: true,
  });
  element.addEventListener("pointerdown", handlePointerDown, {
    capture: true,
    passive: true,
  });

  return {
    setScene(nextSceneScale, nextGroundY = 0) {
      sceneScale = Math.max(nextSceneScale, MIN_SCENE_SCALE);
      groundY = nextGroundY;
      controls.target.y = groundY;
      controls.update();
      const polarLimits = groundOrbitPolarLimits(
        controls.getPolarAngle(),
        options.allowAboveGroundOrbit,
      );
      controls.minPolarAngle = polarLimits.minimum;
      controls.maxPolarAngle = polarLimits.maximum;
      updateNavigationRates();
      controls.update();
      controls.saveState();
    },
    update() {
      controls.target.y = groundY;
      updateNavigationRates();
      controls.update();
    },
    dispose() {
      element.removeEventListener("wheel", handleWheel, true);
      element.removeEventListener("pointerdown", handlePointerDown, true);
    },
  };
}
