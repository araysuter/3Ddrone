import { useCallback, useEffect, useRef, useState } from "react";
import * as THREE from "three";
import { OrbitControls } from "three/addons/controls/OrbitControls.js";
import {
  eptSceneFrame,
  selectEptNodes,
  type EptMetadata,
} from "../lib/ept";
import { LazWorkerClient } from "../lib/lazWorkerClient";
import { createGroundOrbitController } from "./groundOrbitControls";
import { PointCloudViewer } from "./PointCloudViewer";

const POINT_BUDGET = 6_000_000;
const DECODER_COUNT = 2;
const POINT_SIZE_DIVISOR = 800;

async function fetchJson<T>(url: string, signal: AbortSignal) {
  const response = await fetch(url, {
    credentials: "same-origin",
    signal,
  });
  if (!response.ok) {
    throw new Error(`Request failed with HTTP ${response.status}.`);
  }
  return (await response.json()) as T;
}

async function loadHierarchy(
  baseUrl: string,
  signal: AbortSignal,
  pointBudget: number,
) {
  const hierarchy: Record<string, number> = {};
  const queue = ["0-0-0-0"];
  const fetchedPages = new Set<string>();
  let discoveredPoints = 0;
  while (queue.length > 0 && discoveredPoints < pointBudget * 2) {
    const pageKey = queue.shift();
    if (!pageKey || fetchedPages.has(pageKey)) continue;
    fetchedPages.add(pageKey);
    const page = await fetchJson<Record<string, number>>(
      `${baseUrl}ept-hierarchy/${pageKey}.json`,
      signal,
    );
    for (const [key, pointCount] of Object.entries(page)) {
      if (pointCount === -1) {
        hierarchy[key] ??= -1;
        if (!fetchedPages.has(key)) queue.push(key);
        continue;
      }
      if ((hierarchy[key] ?? -1) >= 0) continue;
      hierarchy[key] = pointCount;
      if (pointCount > 0) discoveredPoints += pointCount;
    }
  }
  return hierarchy;
}

function EptScene({
  fallbackAvailable,
  onFailure,
  url,
}: {
  fallbackAvailable: boolean;
  onFailure: () => void;
  url: string;
}) {
  const target = useRef<HTMLDivElement>(null);
  const [loading, setLoading] = useState(true);
  const [progress, setProgress] = useState(0);
  const [error, setError] = useState("");

  useEffect(() => {
    if (!target.current) return;
    setLoading(true);
    setProgress(0);
    setError("");
    const host = target.current;
    const scene = new THREE.Scene();
    scene.background = new THREE.Color("#081018");
    const camera = new THREE.PerspectiveCamera(
      55,
      Math.max(1, host.clientWidth) / Math.max(1, host.clientHeight),
      0.01,
      100000,
    );
    camera.position.set(3, 2, 3);
    const renderer = new THREE.WebGLRenderer({
      antialias: false,
      powerPreference: "high-performance",
    });
    renderer.setPixelRatio(Math.min(devicePixelRatio, 1.5));
    renderer.setSize(host.clientWidth, host.clientHeight);
    renderer.outputColorSpace = THREE.SRGBColorSpace;
    host.appendChild(renderer.domElement);
    const controls = new OrbitControls(camera, renderer.domElement);
    controls.enabled = false;
    const navigation = createGroundOrbitController(
      controls,
      camera,
      renderer.domElement,
      { allowAboveGroundOrbit: true },
    );
    const abortController = new AbortController();
    const decoders = Array.from(
      { length: DECODER_COUNT },
      () => new LazWorkerClient(),
    );
    const pointGroups: THREE.Points[] = [];
    const material = new THREE.PointsMaterial({
      color: 0xb8d8ef,
      sizeAttenuation: true,
      vertexColors: false,
    });
    let disposed = false;
    let sceneRadius = 1;

    const run = async () => {
      const metadata = await fetchJson<EptMetadata>(
        url,
        abortController.signal,
      );
      if (metadata.dataType !== "laszip" || metadata.hierarchyType !== "json") {
        throw new Error(
          `Unsupported EPT encoding (${metadata.dataType}/${metadata.hierarchyType}).`,
        );
      }
      const baseUrl = new URL(".", new URL(url, window.location.href)).toString();
      const frame = eptSceneFrame(metadata);
      sceneRadius = frame.radius;
      // Preserve the apparent coverage of the old mixed-density selection
      // while complete EPT levels keep that coverage uniform across the map.
      material.size = Math.max(0.025, sceneRadius / POINT_SIZE_DIVISOR);
      controls.target.set(0, 0, 0);
      camera.position.set(
        sceneRadius * 1.2,
        sceneRadius * 0.8,
        sceneRadius * 1.2,
      );
      navigation.setScene(sceneRadius);

      const hierarchy = await loadHierarchy(
        baseUrl,
        abortController.signal,
        POINT_BUDGET,
      );
      const nodes = selectEptNodes(hierarchy, POINT_BUDGET);
      if (nodes.length === 0) {
        throw new Error("The EPT hierarchy contains no point nodes.");
      }
      const targetPoints = nodes.reduce(
        (total, node) => total + node.pointCount,
        0,
      );
      let cursor = 0;
      let loadedPoints = 0;
      let loadedNodes = 0;
      let lastProgress = 0;

      const loadNext = async (decoder: LazWorkerClient) => {
        while (!disposed) {
          const node = nodes[cursor];
          cursor += 1;
          if (!node) return;
          try {
            const response = await fetch(
              `${baseUrl}ept-data/${node.key}.laz`,
              {
                credentials: "same-origin",
                signal: abortController.signal,
              },
            );
            if (!response.ok) {
              throw new Error(`HTTP ${response.status}`);
            }
            const decoded = await decoder.decode(await response.arrayBuffer(), {
              maxPoints: node.pointCount,
              origin: frame.origin,
            });
            if (disposed) return;
            if (loadedNodes === 0) {
              material.vertexColors = Boolean(decoded.colors);
              material.color.set(decoded.colors ? 0xffffff : 0xb8d8ef);
              material.needsUpdate = true;
            }
            const geometry = new THREE.BufferGeometry();
            geometry.setAttribute(
              "position",
              new THREE.BufferAttribute(decoded.positions, 3),
            );
            if (decoded.colors) {
              geometry.setAttribute(
                "color",
                new THREE.BufferAttribute(decoded.colors, 3, true),
              );
            }
            geometry.boundingSphere = new THREE.Sphere(
              new THREE.Vector3(0, 0, 0),
              sceneRadius,
            );
            const points = new THREE.Points(geometry, material);
            pointGroups.push(points);
            scene.add(points);
            loadedNodes += 1;
            loadedPoints += decoded.pointCount;
            const nextProgress = Math.min(
              100,
              Math.round((loadedPoints / Math.max(1, targetPoints)) * 100),
            );
            if (nextProgress !== lastProgress) {
              lastProgress = nextProgress;
              setProgress(nextProgress);
            }
            if (loadedNodes === 1) setLoading(false);
          } catch (reason) {
            if (abortController.signal.aborted) return;
            // Individual hierarchy nodes can be absent in interrupted legacy
            // exports. Continue with the remaining additive EPT nodes.
            if (reason instanceof Error && reason.name === "AbortError") return;
          }
        }
      };
      await Promise.all(decoders.map((decoder) => loadNext(decoder)));
      if (!disposed && loadedNodes === 0) {
        throw new Error("No EPT point nodes could be decoded.");
      }
      if (!disposed) {
        setProgress(100);
        controls.enabled = true;
      }
    };

    void run().catch((reason: unknown) => {
      if (disposed || abortController.signal.aborted) return;
      if (fallbackAvailable) {
        onFailure();
        return;
      }
      const detail = reason instanceof Error ? reason.message : String(reason);
      setError(`The EPT point cloud could not be loaded. ${detail}`);
      setLoading(false);
    });

    let frame = 0;
    const animate = () => {
      navigation.update();
      renderer.render(scene, camera);
      frame = requestAnimationFrame(animate);
    };
    animate();
    const resize = new ResizeObserver(() => {
      renderer.setSize(host.clientWidth, host.clientHeight);
      camera.aspect =
        Math.max(1, host.clientWidth) / Math.max(1, host.clientHeight);
      camera.updateProjectionMatrix();
    });
    resize.observe(host);

    return () => {
      disposed = true;
      abortController.abort();
      for (const decoder of decoders) decoder.dispose();
      cancelAnimationFrame(frame);
      resize.disconnect();
      navigation.dispose();
      controls.dispose();
      for (const points of pointGroups) {
        scene.remove(points);
        points.geometry.dispose();
      }
      material.dispose();
      renderer.dispose();
      renderer.domElement.remove();
    };
  }, [fallbackAvailable, onFailure, url]);

  return (
    <div className="three-viewer" ref={target}>
      {loading ? (
        <div className="viewer-loading viewer-overlay">
          LOADING COARSE POINT CLOUD…
        </div>
      ) : progress < 100 ? (
        <div className="viewer-streaming">
          DETAIL {progress}% · LOCKED
        </div>
      ) : null}
      {error && <div className="viewer-error">{error}</div>}
    </div>
  );
}

export function EptPointCloudViewer({
  fallbackUrl,
  url,
}: {
  fallbackUrl?: string;
  url: string;
}) {
  const [failedUrl, setFailedUrl] = useState<string | null>(null);
  const handleFailure = useCallback(() => setFailedUrl(url), [url]);
  if (fallbackUrl && failedUrl === url) {
    return <PointCloudViewer url={fallbackUrl} />;
  }
  return (
    <EptScene
      fallbackAvailable={Boolean(fallbackUrl)}
      onFailure={handleFailure}
      url={url}
    />
  );
}
