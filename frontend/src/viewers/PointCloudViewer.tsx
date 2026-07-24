import { useEffect, useRef, useState } from "react";
import { load } from "@loaders.gl/core";
import { LASLoader } from "@loaders.gl/las";
import lasWorkerUrl from "@loaders.gl/las/las-worker.js?url";
import * as THREE from "three";
import { OrbitControls } from "three/addons/controls/OrbitControls.js";

type NumericArray =
  | Float32Array
  | Float64Array
  | Int8Array
  | Uint8Array
  | Uint8ClampedArray
  | Int16Array
  | Uint16Array
  | Int32Array
  | Uint32Array;

export function PointCloudViewer({ url }: { url: string }) {
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
    camera.position.set(3, 2, 3);
    const renderer = new THREE.WebGLRenderer({ antialias: true });
    renderer.setPixelRatio(Math.min(devicePixelRatio, 2));
    renderer.setSize(host.clientWidth, host.clientHeight);
    renderer.outputColorSpace = THREE.SRGBColorSpace;
    host.appendChild(renderer.domElement);
    const controls = new OrbitControls(camera, renderer.domElement);
    controls.enableDamping = true;

    let disposed = false;
    let points: THREE.Points | null = null;

    void load(url, LASLoader, {
      las: {
        colorDepth: "auto",
        fp64: true,
        workerUrl: lasWorkerUrl,
      },
    })
      .then((mesh) => {
        const source = mesh.attributes.POSITION;
        if (!source || source.size < 3) {
          throw new Error("The LAZ file does not contain XYZ positions.");
        }
        const values = source.value as NumericArray;
        const vertexCount =
          mesh.header?.vertexCount ?? Math.floor(values.length / source.size);
        if (!vertexCount) {
          throw new Error("The LAZ file contains no points.");
        }

        const bounds = mesh.header?.boundingBox;
        const centerX = bounds ? (bounds[0][0] + bounds[1][0]) / 2 : values[0];
        const centerY = bounds ? (bounds[0][1] + bounds[1][1]) / 2 : values[1];
        const centerZ = bounds ? (bounds[0][2] + bounds[1][2]) / 2 : values[2];
        const positions = new Float32Array(vertexCount * 3);
        for (let index = 0; index < vertexCount; index += 1) {
          const sourceIndex = index * source.size;
          const destinationIndex = index * 3;
          // ODM point clouds are Z-up. Center before converting to Float32 so
          // projected UTM coordinates retain centimeter-scale local detail.
          positions[destinationIndex] = values[sourceIndex] - centerX;
          positions[destinationIndex + 1] = values[sourceIndex + 2] - centerZ;
          positions[destinationIndex + 2] = -(values[sourceIndex + 1] - centerY);
        }

        const geometry = new THREE.BufferGeometry();
        geometry.setAttribute("position", new THREE.BufferAttribute(positions, 3));
        const sourceColor = mesh.attributes.COLOR_0;
        if (sourceColor) {
          const colorValues = sourceColor.value as NumericArray;
          const colors = new Uint8Array(vertexCount * 3);
          for (let index = 0; index < vertexCount; index += 1) {
            const sourceIndex = index * sourceColor.size;
            const destinationIndex = index * 3;
            colors[destinationIndex] = Number(colorValues[sourceIndex]);
            colors[destinationIndex + 1] = Number(colorValues[sourceIndex + 1]);
            colors[destinationIndex + 2] = Number(colorValues[sourceIndex + 2]);
          }
          geometry.setAttribute(
            "color",
            new THREE.BufferAttribute(colors, 3, true),
          );
        }
        geometry.computeBoundingSphere();
        const radius = Math.max(geometry.boundingSphere?.radius ?? 1, 1);
        const material = new THREE.PointsMaterial({
          color: sourceColor ? 0xffffff : 0xb8d8ef,
          size: Math.max(0.025, radius / 900),
          sizeAttenuation: true,
          vertexColors: Boolean(sourceColor),
        });
        const loadedPoints = new THREE.Points(geometry, material);
        if (disposed) {
          geometry.dispose();
          material.dispose();
          return;
        }
        points = loadedPoints;
        scene.add(loadedPoints);
        controls.target.set(0, 0, 0);
        camera.position.set(radius * 1.2, radius * 0.8, radius * 1.2);
        camera.near = Math.max(0.01, radius / 1000);
        camera.far = Math.max(1000, radius * 100);
        camera.updateProjectionMatrix();
        controls.update();
        setLoading(false);
      })
      .catch((reason: unknown) => {
        if (disposed) return;
        const detail = reason instanceof Error ? reason.message : String(reason);
        setError(`The LAZ point cloud could not be loaded. ${detail}`);
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
      camera.aspect =
        Math.max(1, host.clientWidth) / Math.max(1, host.clientHeight);
      camera.updateProjectionMatrix();
    });
    resize.observe(host);

    return () => {
      disposed = true;
      cancelAnimationFrame(frame);
      resize.disconnect();
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
      {loading && <div className="viewer-loading viewer-overlay">LOADING POINT CLOUD…</div>}
      {error && <div className="viewer-error">{error}</div>}
    </div>
  );
}
