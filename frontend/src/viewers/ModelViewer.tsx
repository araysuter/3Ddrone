import { useEffect, useRef, useState } from "react";
import * as THREE from "three";
import { GLTFLoader } from "three/addons/loaders/GLTFLoader.js";
import { DRACOLoader } from "three/addons/loaders/DRACOLoader.js";
import { MTLLoader } from "three/addons/loaders/MTLLoader.js";
import { OBJLoader } from "three/addons/loaders/OBJLoader.js";
import { OrbitControls } from "three/addons/controls/OrbitControls.js";

export function ModelViewer({
  url,
  fallbackUrl,
}: {
  url: string;
  fallbackUrl?: string;
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
    const loadGlb = (glbUrl: string) =>
      new Promise<THREE.Object3D>((resolve, reject) => {
        const loader = new GLTFLoader();
        loader.setDRACOLoader(draco);
        loader.load(glbUrl, (gltf) => resolve(gltf.scene), undefined, reject);
      });
    const loadObj = (objUrl: string) =>
      new Promise<THREE.Object3D>((resolve, reject) => {
        const resourcePath = objUrl.slice(0, objUrl.lastIndexOf("/") + 1);
        const mtlUrl = objUrl.replace(/\.obj$/i, ".mtl");
        const manager = new THREE.LoadingManager();
        const failedTextures: string[] = [];
        let loadedObject: THREE.Object3D | null = null;
        manager.onError = (failedUrl) => failedTextures.push(failedUrl);
        manager.onLoad = () => {
          if (!loadedObject) return;
          if (failedTextures.length) {
            reject(
              new Error(
                `ODM texture sidecars could not be loaded: ${failedTextures
                  .slice(0, 3)
                  .join(", ")}`,
              ),
            );
            return;
          }
          resolve(loadedObject);
        };
        const mtlLoader = new MTLLoader(manager);
        mtlLoader.setResourcePath(resourcePath);
        mtlLoader.setMaterialOptions({
          ignoreZeroRGBs: true,
          side: THREE.DoubleSide,
        });
        mtlLoader.load(
          mtlUrl,
          (materials) => {
            materials.preload();
            const objLoader = new OBJLoader(manager);
            objLoader.setMaterials(materials);
            objLoader.load(
              objUrl,
              (object) => {
                loadedObject = object;
              },
              undefined,
              reject,
            );
          },
          undefined,
          reject,
        );
      });
    const loadModel = async () => {
      try {
        return url.toLowerCase().endsWith(".obj")
          ? await loadObj(url)
          : await loadGlb(url);
      } catch (primaryError) {
        if (!fallbackUrl) throw primaryError;
        return loadGlb(fallbackUrl);
      }
    };
    void loadModel()
      .then((loadedModel) => {
        if (disposed) {
          disposeObject(loadedModel);
          return;
        }
        model = loadedModel;
        model.traverse((child) => {
          const mesh = child as THREE.Mesh;
          const materials = Array.isArray(mesh.material)
            ? mesh.material
            : mesh.material
              ? [mesh.material]
              : [];
          for (const material of materials) {
            const textured = material as THREE.MeshPhongMaterial;
            if (textured.map) {
              textured.map.colorSpace = THREE.SRGBColorSpace;
              textured.map.needsUpdate = true;
              textured.color.set(0xffffff);
            }
            textured.side = THREE.DoubleSide;
            textured.needsUpdate = true;
          }
        });
        const initialBox = new THREE.Box3().setFromObject(model);
        if (initialBox.isEmpty()) {
          throw new Error("The textured model contains no renderable geometry.");
        }
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
      })
      .catch((reason: unknown) => {
        if (disposed) return;
        const detail = reason instanceof Error ? reason.message : String(reason);
        setError(`The textured model could not be loaded. ${detail}`);
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
      if (model) disposeObject(model);
      draco.dispose();
      renderer.dispose();
      renderer.domElement.remove();
    };
  }, [fallbackUrl, url]);

  return (
    <div className="three-viewer" ref={target}>
      {loading && <div className="viewer-loading viewer-overlay">LOADING 3D MODEL…</div>}
      {error && <div className="viewer-error">{error}</div>}
    </div>
  );
}
