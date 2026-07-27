import { useEffect, useRef, useState } from "react";
import * as THREE from "three";
import { OrbitControls } from "three/addons/controls/OrbitControls.js";
import { LazWorkerClient } from "../lib/lazWorkerClient";
import { createGroundOrbitController } from "./groundOrbitControls";

export function PointCloudViewer({ url }: { url: string }) {
  const target = useRef<HTMLDivElement>(null);
  const [loading, setLoading] = useState(true);
  const [stage, setStage] = useState("DOWNLOADING");
  const [error, setError] = useState("");

  useEffect(() => {
    if (!target.current) return;
    setLoading(true);
    setStage("DOWNLOADING");
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
    const navigation = createGroundOrbitController(
      controls,
      camera,
      renderer.domElement,
    );

    let disposed = false;
    let points: THREE.Points | null = null;
    const abortController = new AbortController();
    const decoder = new LazWorkerClient();
    const installPoints = (decoded: Awaited<ReturnType<typeof decoder.decode>>) => {
      if (disposed) return;
      try {
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
        const radius = Math.max(decoded.radius, 1);
        geometry.boundingSphere = new THREE.Sphere(
          new THREE.Vector3(0, 0, 0),
          radius,
        );
        const material = new THREE.PointsMaterial({
          color: decoded.colors ? 0xffffff : 0xb8d8ef,
          size: Math.max(0.025, radius / 900),
          sizeAttenuation: true,
          vertexColors: Boolean(decoded.colors),
        });
        const loadedPoints = new THREE.Points(geometry, material);
        points = loadedPoints;
        scene.add(loadedPoints);
        controls.target.set(0, 0, 0);
        camera.position.set(radius * 1.2, radius * 0.8, radius * 1.2);
        navigation.setScene(radius);
        setLoading(false);
      } catch (reason: unknown) {
        const detail = reason instanceof Error ? reason.message : String(reason);
        setError(`The LAZ point cloud could not be loaded. ${detail}`);
        setLoading(false);
      }
    };
    void fetch(url, {
      credentials: "same-origin",
      signal: abortController.signal,
    })
      .then((response) => {
        if (!response.ok) {
          throw new Error(`Download failed with HTTP ${response.status}.`);
        }
        return response.arrayBuffer();
      })
      .then((buffer) => {
        if (disposed) return undefined;
        setStage("DECODING");
        return decoder.decode(buffer, { maxPoints: 6_000_000 });
      })
      .then((decoded) => {
        if (decoded) installPoints(decoded);
      })
      .catch((reason: unknown) => {
        if (disposed || abortController.signal.aborted) return;
        const detail = reason instanceof Error ? reason.message : String(reason);
        setError(`The LAZ point cloud could not be loaded. ${detail}`);
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
      decoder.dispose();
      cancelAnimationFrame(frame);
      resize.disconnect();
      navigation.dispose();
      controls.dispose();
      if (points) {
        points.geometry.dispose();
        (points.material as THREE.Material).dispose();
      }
      renderer.dispose();
      renderer.domElement.remove();
    };
  }, [url]);

  return (
    <div className="three-viewer" ref={target}>
      {loading && (
        <div className="viewer-loading viewer-overlay">
          {stage} POINT CLOUD…
        </div>
      )}
      {error && <div className="viewer-error">{error}</div>}
    </div>
  );
}
