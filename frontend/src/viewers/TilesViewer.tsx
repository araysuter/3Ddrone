import { useEffect, useRef, useState, type ReactNode } from "react";
import * as THREE from "three";
import { TilesRenderer } from "3d-tiles-renderer/three";
import { ReorientationPlugin } from "3d-tiles-renderer/three/plugins";
import { OrbitControls } from "three/addons/controls/OrbitControls.js";
import { createGroundOrbitController } from "./groundOrbitControls";

function TilesScene({
  fallbackAvailable,
  loadingLabel,
  onFailure,
  url,
}: {
  fallbackAvailable: boolean;
  loadingLabel: string;
  onFailure: () => void;
  url: string;
}) {
  const target = useRef<HTMLDivElement>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  useEffect(() => {
    if (!target.current) return;
    setLoading(true);
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
    camera.position.set(30, 20, 30);
    const renderer = new THREE.WebGLRenderer({
      antialias: true,
      powerPreference: "high-performance",
    });
    renderer.setPixelRatio(Math.min(devicePixelRatio, 1.5));
    renderer.setSize(host.clientWidth, host.clientHeight);
    renderer.outputColorSpace = THREE.SRGBColorSpace;
    host.appendChild(renderer.domElement);
    const controls = new OrbitControls(camera, renderer.domElement);
    const navigation = createGroundOrbitController(
      controls,
      camera,
      renderer.domElement,
    );
    scene.add(new THREE.HemisphereLight(0xffffff, 0x334455, 2.5));

    const tiles = new TilesRenderer(url);
    tiles.registerPlugin(new ReorientationPlugin({ recenter: true }));
    tiles.setCamera(camera);
    tiles.setResolutionFromRenderer(camera, renderer);
    scene.add(tiles.group);

    let fitFrame = 0;
    let loadedModel = false;
    const fit = () => {
      cancelAnimationFrame(fitFrame);
      fitFrame = window.requestAnimationFrame(() => {
        const box = new THREE.Box3();
        tiles.group.updateMatrixWorld(true);
        if (!tiles.getBoundingBox(box)) return;
        box.applyMatrix4(tiles.group.matrixWorld);
        const center = box.getCenter(new THREE.Vector3());
        const extent = box.getSize(new THREE.Vector3());
        const radius = Math.max(
          new THREE.Vector3(extent.x / 2, extent.y, extent.z / 2).length(),
          1,
        );
        controls.target.set(center.x, box.min.y, center.z);
        camera.position
          .copy(controls.target)
          .add(new THREE.Vector3(radius * 1.4, radius * 0.9, radius * 1.4));
        navigation.setScene(radius, box.min.y);
      });
    };
    const loadModel = () => {
      if (loadedModel) return;
      loadedModel = true;
      setLoading(false);
      fit();
    };
    const loadError = () => {
      if (loadedModel) return;
      if (fallbackAvailable) {
        onFailure();
      } else {
        setError("The 3D Tiles output could not be loaded.");
        setLoading(false);
      }
    };
    tiles.addEventListener("load-tileset", fit);
    tiles.addEventListener("load-model", loadModel);
    tiles.addEventListener("load-error", loadError);

    let frame = 0;
    const animate = () => {
      camera.updateMatrixWorld();
      tiles.setResolutionFromRenderer(camera, renderer);
      tiles.update();
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
      cancelAnimationFrame(frame);
      cancelAnimationFrame(fitFrame);
      resize.disconnect();
      tiles.removeEventListener("load-tileset", fit);
      tiles.removeEventListener("load-model", loadModel);
      tiles.removeEventListener("load-error", loadError);
      tiles.dispose();
      navigation.dispose();
      controls.dispose();
      renderer.dispose();
      renderer.domElement.remove();
    };
  }, [fallbackAvailable, loadingLabel, onFailure, url]);

  return (
    <div className="three-viewer" ref={target}>
      {loading && (
        <div className="viewer-loading viewer-overlay">
          LOADING {loadingLabel}…
        </div>
      )}
      {error && <div className="viewer-error">{error}</div>}
    </div>
  );
}

export function TilesViewer({
  fallback,
  loadingLabel = "3D TILES",
  url,
}: {
  fallback?: ReactNode;
  loadingLabel?: string;
  url: string;
}) {
  const [failedUrl, setFailedUrl] = useState<string | null>(null);
  if (fallback && failedUrl === url) return fallback;
  return (
    <TilesScene
      fallbackAvailable={Boolean(fallback)}
      loadingLabel={loadingLabel}
      onFailure={() => setFailedUrl(url)}
      url={url}
    />
  );
}
