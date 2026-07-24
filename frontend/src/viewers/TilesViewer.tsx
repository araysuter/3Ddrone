import { useEffect, useRef, useState } from "react";
import * as THREE from "three";
import { TilesRenderer } from "3d-tiles-renderer/three";
import { ReorientationPlugin } from "3d-tiles-renderer/three/plugins";
import { OrbitControls } from "three/addons/controls/OrbitControls.js";

export function TilesViewer({ url }: { url: string }) {
  const target = useRef<HTMLDivElement>(null);
  const [error, setError] = useState("");

  useEffect(() => {
    if (!target.current) return;
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
    const renderer = new THREE.WebGLRenderer({ antialias: true });
    renderer.setPixelRatio(Math.min(devicePixelRatio, 2));
    renderer.setSize(host.clientWidth, host.clientHeight);
    host.appendChild(renderer.domElement);
    const controls = new OrbitControls(camera, renderer.domElement);
    controls.enableDamping = true;
    scene.add(new THREE.HemisphereLight(0xffffff, 0x334455, 2.5));

    const tiles = new TilesRenderer(url);
    tiles.registerPlugin(new ReorientationPlugin({ recenter: true }));
    tiles.setCamera(camera);
    tiles.setResolutionFromRenderer(camera, renderer);
    scene.add(tiles.group);

    let fitFrame = 0;
    const fit = () => {
      fitFrame = window.requestAnimationFrame(() => {
        const sphere = new THREE.Sphere();
        tiles.group.updateMatrixWorld(true);
        if (!tiles.getBoundingSphere(sphere)) return;
        sphere.applyMatrix4(tiles.group.matrixWorld);
        const radius = Math.max(sphere.radius, 1);
        controls.target.copy(sphere.center);
        camera.position
          .copy(sphere.center)
          .add(new THREE.Vector3(radius * 1.4, radius * 0.9, radius * 1.4));
        camera.near = Math.max(0.01, radius / 1000);
        camera.far = Math.max(1000, radius * 100);
        camera.updateProjectionMatrix();
        controls.update();
      });
    };
    const loadError = () => setError("The 3D Tiles output could not be loaded.");
    tiles.addEventListener("load-tileset", fit);
    tiles.addEventListener("load-error", loadError);

    let frame = 0;
    const animate = () => {
      camera.updateMatrixWorld();
      tiles.setResolutionFromRenderer(camera, renderer);
      tiles.update();
      controls.update();
      renderer.render(scene, camera);
      frame = requestAnimationFrame(animate);
    };
    animate();

    const resize = new ResizeObserver(() => {
      renderer.setSize(host.clientWidth, host.clientHeight);
      camera.aspect = Math.max(1, host.clientWidth) / Math.max(1, host.clientHeight);
      camera.updateProjectionMatrix();
    });
    resize.observe(host);
    return () => {
      cancelAnimationFrame(frame);
      cancelAnimationFrame(fitFrame);
      resize.disconnect();
      tiles.removeEventListener("load-tileset", fit);
      tiles.removeEventListener("load-error", loadError);
      tiles.dispose();
      controls.dispose();
      renderer.dispose();
      renderer.domElement.remove();
    };
  }, [url]);

  return (
    <div className="three-viewer" ref={target}>
      {error && <div className="viewer-error">{error}</div>}
    </div>
  );
}
