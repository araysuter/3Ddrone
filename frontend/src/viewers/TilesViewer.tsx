import {
  useCallback,
  useEffect,
  useRef,
  useState,
  type ReactNode,
} from "react";
import * as THREE from "three";
import { TilesRenderer } from "3d-tiles-renderer/three";
import { ReorientationPlugin } from "3d-tiles-renderer/three/plugins";
import { OrbitControls } from "three/addons/controls/OrbitControls.js";
import { createGroundOrbitController } from "./groundOrbitControls";
import { ViewerProgress } from "./ViewerProgress";

function TilesScene({
  allowAboveGroundOrbit,
  fallbackAvailable,
  lockWhileStreaming,
  loadingLabel,
  onFailure,
  url,
}: {
  allowAboveGroundOrbit: boolean;
  fallbackAvailable: boolean;
  lockWhileStreaming: boolean;
  loadingLabel: string;
  onFailure: () => void;
  url: string;
}) {
  const target = useRef<HTMLDivElement>(null);
  const [loading, setLoading] = useState(true);
  const [interactionReady, setInteractionReady] = useState(false);
  const [progress, setProgress] = useState(0);
  const [error, setError] = useState("");

  useEffect(() => {
    if (!target.current) return;
    setLoading(true);
    setInteractionReady(false);
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
    camera.position.set(30, 20, 30);
    const renderer = new THREE.WebGLRenderer({
      antialias: true,
      powerPreference: "high-performance",
    });
    renderer.setPixelRatio(Math.min(devicePixelRatio, 1.25));
    renderer.setSize(host.clientWidth, host.clientHeight);
    renderer.outputColorSpace = THREE.SRGBColorSpace;
    host.appendChild(renderer.domElement);
    const controls = new OrbitControls(camera, renderer.domElement);
    controls.enabled = false;
    const navigation = createGroundOrbitController(
      controls,
      camera,
      renderer.domElement,
      { allowAboveGroundOrbit },
    );
    scene.add(new THREE.HemisphereLight(0xffffff, 0x334455, 2.5));

    const tiles = new TilesRenderer(url);
    tiles.registerPlugin(new ReorientationPlugin({ recenter: true }));
    const hardwareThreads = navigator.hardwareConcurrency || 4;
    tiles.downloadQueue.maxJobs = Math.min(
      8,
      Math.max(4, hardwareThreads),
    );
    tiles.parseQueue.maxJobs = Math.min(
      4,
      Math.max(2, Math.floor(hardwareThreads / 2)),
    );
    if (!lockWhileStreaming) {
      tiles.loadSiblings = false;
    }
    tiles.setCamera(camera);
    tiles.setResolutionFromRenderer(camera, renderer);
    scene.add(tiles.group);

    let fitFrame = 0;
    let loadedModel = false;
    let loadingPass = false;
    let lastProgress = 0;
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
      if (!lockWhileStreaming) {
        controls.enabled = true;
        setInteractionReady(true);
      }
    };
    const loadStart = () => {
      loadingPass = true;
      lastProgress = 0;
      setProgress(0);
      if (!loadedModel || !lockWhileStreaming) return;
      controls.enabled = false;
      setInteractionReady(false);
    };
    const loadEnd = () => {
      if (!loadedModel) return;
      loadingPass = false;
      lastProgress = 100;
      setProgress(100);
      controls.enabled = true;
      setInteractionReady(true);
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
    tiles.addEventListener("tiles-load-start", loadStart);
    tiles.addEventListener("tiles-load-end", loadEnd);
    tiles.addEventListener("load-error", loadError);

    let frame = 0;
    const animate = () => {
      camera.updateMatrixWorld();
      tiles.setResolutionFromRenderer(camera, renderer);
      tiles.update();
      if (loadingPass) {
        const nextProgress = Math.min(
          99,
          Math.max(
            lastProgress,
            Math.round(tiles.loadProgress * 100),
          ),
        );
        if (nextProgress !== lastProgress) {
          lastProgress = nextProgress;
          setProgress(nextProgress);
        }
      }
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
      tiles.removeEventListener("tiles-load-start", loadStart);
      tiles.removeEventListener("tiles-load-end", loadEnd);
      tiles.removeEventListener("load-error", loadError);
      tiles.dispose();
      navigation.dispose();
      controls.dispose();
      renderer.dispose();
      renderer.domElement.remove();
    };
  }, [
    allowAboveGroundOrbit,
    fallbackAvailable,
    lockWhileStreaming,
    loadingLabel,
    onFailure,
    url,
  ]);

  return (
    <div className="three-viewer" ref={target}>
      {loading && (
        <div className="viewer-loading viewer-overlay">
          <ViewerProgress
            label={`LOADING ${loadingLabel}`}
            progress={progress}
          />
        </div>
      )}
      {!loading && progress < 100 && (
        <div className="viewer-streaming viewer-streaming-progress">
          <ViewerProgress
            compact
            label={`${loadingLabel} DETAIL${
              interactionReady ? "" : " · LOCKED"
            }`}
            progress={progress}
          />
        </div>
      )}
      {error && <div className="viewer-error">{error}</div>}
    </div>
  );
}

export function TilesViewer({
  allowAboveGroundOrbit = false,
  fallback,
  lockWhileStreaming = false,
  loadingLabel = "3D TILES",
  url,
}: {
  allowAboveGroundOrbit?: boolean;
  fallback?: ReactNode;
  lockWhileStreaming?: boolean;
  loadingLabel?: string;
  url: string;
}) {
  const [failedUrl, setFailedUrl] = useState<string | null>(null);
  const handleFailure = useCallback(() => setFailedUrl(url), [url]);
  if (fallback && failedUrl === url) return fallback;
  return (
    <TilesScene
      allowAboveGroundOrbit={allowAboveGroundOrbit}
      fallbackAvailable={Boolean(fallback)}
      lockWhileStreaming={lockWhileStreaming}
      loadingLabel={loadingLabel}
      onFailure={handleFailure}
      url={url}
    />
  );
}
