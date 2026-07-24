import { useEffect, useRef, useState } from "react";
import * as THREE from "three";
import { GLTFLoader } from "three/addons/loaders/GLTFLoader.js";
import { DRACOLoader } from "three/addons/loaders/DRACOLoader.js";
import { OrbitControls } from "three/addons/controls/OrbitControls.js";

export function ModelViewer({ url }: { url: string }) {
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
    const camera = new THREE.PerspectiveCamera(55, host.clientWidth / host.clientHeight, 0.01, 10000);
    camera.position.set(3, 2, 3);
    const renderer = new THREE.WebGLRenderer({ antialias: true });
    renderer.setPixelRatio(Math.min(devicePixelRatio, 2));
    renderer.setSize(host.clientWidth, host.clientHeight);
    renderer.outputColorSpace = THREE.SRGBColorSpace;
    host.appendChild(renderer.domElement);
    const controls = new OrbitControls(camera, renderer.domElement);
    controls.enableDamping = true;
    scene.add(new THREE.HemisphereLight(0xffffff, 0x334455, 2.5));
    let disposed = false;
    let model: THREE.Object3D | null = null;

    const disposeObject = (object: THREE.Object3D) => {
      object.traverse((child) => {
        const mesh = child as THREE.Mesh;
        mesh.geometry?.dispose();
        const materials = Array.isArray(mesh.material)
          ? mesh.material
          : mesh.material
            ? [mesh.material]
            : [];
        for (const material of materials) {
          for (const value of Object.values(material)) {
            if (value instanceof THREE.Texture) value.dispose();
          }
          material.dispose();
        }
      });
    };

    const draco = new DRACOLoader();
    draco.setDecoderPath("/draco/");
    draco.setWorkerLimit(2);
    draco.preload();
    const loader = new GLTFLoader();
    loader.setDRACOLoader(draco);
    loader.load(
      url,
      (gltf) => {
        if (disposed) {
          disposeObject(gltf.scene);
          return;
        }
        model = gltf.scene;
        const initialBox = new THREE.Box3().setFromObject(model);
        const center = initialBox.getCenter(new THREE.Vector3());
        model.position.sub(center);
        scene.add(model);
        const box = new THREE.Box3().setFromObject(model);
        const size = Math.max(box.getSize(new THREE.Vector3()).length(), 1);
        controls.target.set(0, 0, 0);
        camera.position.set(size * 0.7, size * 0.45, size * 0.7);
        camera.near = Math.max(0.01, size / 1000);
        camera.far = Math.max(1000, size * 10);
        camera.updateProjectionMatrix();
        controls.update();
        setLoading(false);
      },
      undefined,
      (reason) => {
        if (disposed) return;
        const detail = reason instanceof Error ? reason.message : String(reason);
        setError(`The textured GLB could not be loaded. ${detail}`);
        setLoading(false);
      },
    );
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
      if (model) disposeObject(model);
      draco.dispose();
      renderer.dispose();
      renderer.domElement.remove();
    };
  }, [url]);

  return (
    <div className="three-viewer" ref={target}>
      {loading && <div className="viewer-loading viewer-overlay">LOADING 3D MODEL…</div>}
      {error && <div className="viewer-error">{error}</div>}
    </div>
  );
}
