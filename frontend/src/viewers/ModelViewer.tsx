import { useEffect, useRef } from "react";
import * as THREE from "three";
import { GLTFLoader } from "three/addons/loaders/GLTFLoader.js";
import { OrbitControls } from "three/addons/controls/OrbitControls.js";

export function ModelViewer({ url }: { url: string }) {
  const target = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!target.current) return;
    const host = target.current;
    const scene = new THREE.Scene();
    scene.background = new THREE.Color("#081018");
    const camera = new THREE.PerspectiveCamera(55, host.clientWidth / host.clientHeight, 0.01, 10000);
    camera.position.set(3, 2, 3);
    const renderer = new THREE.WebGLRenderer({ antialias: true });
    renderer.setPixelRatio(Math.min(devicePixelRatio, 2));
    renderer.setSize(host.clientWidth, host.clientHeight);
    host.appendChild(renderer.domElement);
    const controls = new OrbitControls(camera, renderer.domElement);
    controls.enableDamping = true;
    scene.add(new THREE.HemisphereLight(0xffffff, 0x334455, 2.5));
    new GLTFLoader().load(url, (gltf) => {
      scene.add(gltf.scene);
      const box = new THREE.Box3().setFromObject(gltf.scene);
      const size = box.getSize(new THREE.Vector3()).length();
      const center = box.getCenter(new THREE.Vector3());
      controls.target.copy(center);
      camera.position.copy(center).add(new THREE.Vector3(size * 0.7, size * 0.45, size * 0.7));
      camera.near = Math.max(0.01, size / 1000);
      camera.far = Math.max(1000, size * 10);
      camera.updateProjectionMatrix();
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
      cancelAnimationFrame(frame);
      resize.disconnect();
      renderer.dispose();
      renderer.domElement.remove();
    };
  }, [url]);

  return <div className="three-viewer" ref={target} />;
}
