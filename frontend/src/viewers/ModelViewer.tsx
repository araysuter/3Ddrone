import { useEffect, useRef, useState } from "react";
import * as THREE from "three";
import { GLTFLoader } from "three/addons/loaders/GLTFLoader.js";
import { DRACOLoader } from "three/addons/loaders/DRACOLoader.js";
import { MTLLoader } from "three/addons/loaders/MTLLoader.js";
import { OBJLoader } from "three/addons/loaders/OBJLoader.js";
import { OrbitControls } from "three/addons/controls/OrbitControls.js";
import { createGroundOrbitController } from "./groundOrbitControls";
import { ViewerProgress } from "./ViewerProgress";

export function ModelViewer({
  fallbackUrl,
  fallbackSize,
  size,
  url,
}: {
  fallbackUrl?: string;
  fallbackSize?: number;
  size?: number;
  url: string;
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
    const camera = new THREE.PerspectiveCamera(55, host.clientWidth / host.clientHeight, 0.01, 10000);
    camera.position.set(3, 2, 3);
    const renderer = new THREE.WebGLRenderer({
      antialias: true,
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
    );
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
    draco.setWorkerLimit(
      Math.min(4, Math.max(2, (navigator.hardwareConcurrency || 4) - 1)),
    );
    draco.preload();
    const loadGlb = (glbUrl: string, expectedBytes?: number) =>
      new Promise<THREE.Object3D>((resolve, reject) => {
        const loader = new GLTFLoader();
        loader.setDRACOLoader(draco);
        // GLTFLoader normally prefers ImageBitmapLoader. Chrome can silently
        // upload these many embedded ODM texture atlases as blank white
        // surfaces under GPU memory pressure, even though the bitmaps decode.
        // Regular image textures use Chrome's more established upload path and
        // can be released normally when the viewer unmounts.
        loader.register((parser) => {
          const textureLoader = new THREE.TextureLoader(
            parser.options.manager,
          );
          textureLoader.setCrossOrigin(parser.options.crossOrigin);
          textureLoader.setRequestHeader(parser.options.requestHeader);
          parser.textureLoader = textureLoader;
          return { name: "ODM_html_image_textures" };
        });
        loader.load(
          glbUrl,
          (gltf) => resolve(gltf.scene),
          (event) => {
            const total = event.total || expectedBytes || 0;
            if (!total || !event.loaded) return;
            setProgress(
              Math.min(100, Math.round((event.loaded / total) * 100)),
            );
          },
          reject,
        );
      });
    const loadObj = (objUrl: string) =>
      new Promise<THREE.Object3D>((resolve, reject) => {
        const resourcePath = objUrl.slice(0, objUrl.lastIndexOf("/") + 1);
        const mtlUrl = objUrl.replace(/\.obj$/i, ".mtl");
        const manager = new THREE.LoadingManager();
        const failedTextures: string[] = [];
        let loadedObject: THREE.Object3D | null = null;
        manager.onError = (failedUrl) => failedTextures.push(failedUrl);
        manager.onProgress = (_item, loaded, total) => {
          if (total > 0) setProgress(Math.round((loaded / total) * 100));
        };
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
    const loadCandidate = (
      candidateUrl: string,
      expectedBytes?: number,
    ) =>
      candidateUrl.toLowerCase().endsWith(".obj")
        ? loadObj(candidateUrl)
        : loadGlb(candidateUrl, expectedBytes);
    const loadModel = async () => {
      try {
        return await loadCandidate(url, size);
      } catch (primaryError) {
        if (!fallbackUrl) throw primaryError;
        setProgress(null);
        return loadCandidate(fallbackUrl, fallbackSize);
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
            // GLTFLoader has already applied the glTF base-color texture,
            // color space, and material factor. Preserve that state rather
            // than forcing a second texture upload after Chrome has decoded
            // the image.
            material.side = THREE.DoubleSide;
            material.needsUpdate = true;
          }
        });
        // ODM's OBJ coordinates are Z-up, and its GLB export preserves those
        // vertex coordinates. Convert both compact model fallbacks to the same
        // Y-up, north-toward-negative-Z frame as the point-cloud viewers.
        model.rotation.x = -Math.PI / 2;
        model.updateMatrixWorld(true);
        const initialBox = new THREE.Box3().setFromObject(model);
        if (initialBox.isEmpty()) {
          throw new Error("The textured model contains no renderable geometry.");
        }
        const center = initialBox.getCenter(new THREE.Vector3());
        model.position.x -= center.x;
        model.position.y -= initialBox.min.y;
        model.position.z -= center.z;
        scene.add(model);
        const box = new THREE.Box3().setFromObject(model);
        const extent = box.getSize(new THREE.Vector3());
        const size = Math.max(
          new THREE.Vector3(extent.x / 2, extent.y, extent.z / 2).length(),
          1,
        );
        controls.target.set(0, 0, 0);
        camera.position.set(size * 1.4, size * 0.9, size * 1.4);
        navigation.setScene(size);
        controls.enabled = true;
        setProgress(100);
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
      navigation.update();
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
      navigation.dispose();
      controls.dispose();
      if (model) disposeObject(model);
      draco.dispose();
      renderer.dispose();
      renderer.domElement.remove();
    };
  }, [fallbackSize, fallbackUrl, size, url]);

  return (
    <div className="three-viewer" ref={target}>
      {loading && (
        <div className="viewer-loading viewer-overlay">
          <ViewerProgress
            label={
              progress === 100
                ? "PREPARING TEXTURED MODEL"
                : "LOADING TEXTURED MODEL"
            }
            progress={progress}
          />
        </div>
      )}
      {error && <div className="viewer-error">{error}</div>}
    </div>
  );
}
