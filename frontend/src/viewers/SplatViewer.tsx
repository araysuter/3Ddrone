import { useEffect, useRef, useState } from "react";
import * as THREE from "three";
import { SparkRenderer, SplatMesh } from "@sparkjsdev/spark";
import { OrbitControls } from "three/addons/controls/OrbitControls.js";

export function SplatViewer({
  url,
  fallbackUrl,
}: {
  url: string;
  fallbackUrl?: string;
}) {
  const target = useRef<HTMLDivElement>(null);
  const [loading, setLoading] = useState(true);
  const [progress, setProgress] = useState<number | null>(null);
  const [error, setError] = useState("");

  useEffect(() => {
    if (!target.current) return;
    setLoading(true);
    setProgress(null);
    setError("");
    const host = target.current;
    const scene = new THREE.Scene();
    scene.background = new THREE.Color("#081018");
    const camera = new THREE.PerspectiveCamera(
      60,
      Math.max(1, host.clientWidth) / Math.max(1, host.clientHeight),
      0.01,
      100000,
    );
    camera.position.set(0, 1.5, 4);
    const renderer = new THREE.WebGLRenderer({ antialias: true });
    renderer.setPixelRatio(Math.min(devicePixelRatio, 2));
    renderer.setSize(host.clientWidth, host.clientHeight);
    renderer.outputColorSpace = THREE.SRGBColorSpace;
    host.appendChild(renderer.domElement);
    const spark = new SparkRenderer({ renderer });
    scene.add(spark);
    let disposed = false;
    let activeSplat: SplatMesh | null = null;
    const controls = new OrbitControls(camera, renderer.domElement);
    controls.enableDamping = true;

    const loadSplat = async (candidateUrl: string) => {
      const candidate = new SplatMesh({
        url: candidateUrl,
        onProgress: (event) => {
          if (disposed || !event.lengthComputable || !event.total) return;
          setProgress(
            Math.min(100, Math.round((event.loaded / event.total) * 100)),
          );
        },
      });
      activeSplat = candidate;
      scene.add(candidate);
      try {
        return await candidate.initialized;
      } catch (reason) {
        if (activeSplat === candidate) {
          scene.remove(candidate);
          candidate.dispose();
          activeSplat = null;
        }
        throw reason;
      }
    };

    const loadWithFallback = async () => {
      try {
        return await loadSplat(url);
      } catch (primaryReason) {
        if (!fallbackUrl || disposed) throw primaryReason;
        setProgress(null);
        return loadSplat(fallbackUrl);
      }
    };

    void loadWithFallback()
      .then((loadedSplat) => {
        if (disposed) return;
        const box = loadedSplat.getBoundingBox(true);
        if (box.isEmpty()) {
          throw new Error("The exported splat contains no visible Gaussian points.");
        }
        const center = box.getCenter(new THREE.Vector3());
        const radius = Math.max(box.getSize(new THREE.Vector3()).length() / 2, 0.1);
        loadedSplat.position.sub(center);
        controls.target.set(0, 0, 0);
        camera.position.set(radius * 1.25, radius * 0.8, radius * 1.25);
        camera.near = Math.max(0.001, radius / 1000);
        camera.far = Math.max(1000, radius * 100);
        camera.updateProjectionMatrix();
        controls.update();
        setProgress(100);
        setLoading(false);
      })
      .catch((reason: unknown) => {
        if (disposed) return;
        const detail = reason instanceof Error ? reason.message : String(reason);
        setError(`The Gaussian splat could not be loaded. ${detail}`);
        setLoading(false);
      });

    let frame = 0;
    const animate = () => {
      controls.update();
      renderer.render(scene, camera);
      frame = requestAnimationFrame(animate);
    };
    animate();
    const resize = new ResizeObserver(() => {
      renderer.setSize(host.clientWidth, host.clientHeight);
      camera.aspect = host.clientWidth / host.clientHeight;
      camera.updateProjectionMatrix();
    });
    resize.observe(host);
    return () => {
      disposed = true;
      cancelAnimationFrame(frame);
      resize.disconnect();
      controls.dispose();
      if (activeSplat) {
        scene.remove(activeSplat);
        activeSplat.dispose();
        activeSplat = null;
      }
      spark.dispose();
      renderer.dispose();
      renderer.domElement.remove();
    };
  }, [fallbackUrl, url]);

  return (
    <div className="three-viewer" ref={target}>
      {loading && (
        <div className="viewer-loading viewer-overlay">
          LOADING GAUSSIAN SPLAT{progress == null ? "…" : ` · ${progress}%`}
        </div>
      )}
      {error && <div className="viewer-error">{error}</div>}
    </div>
  );
}
