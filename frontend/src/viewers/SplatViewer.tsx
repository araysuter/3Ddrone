import { useEffect, useRef } from "react";
import * as THREE from "three";
import { SparkRenderer, SplatMesh } from "@sparkjsdev/spark";
import { OrbitControls } from "three/addons/controls/OrbitControls.js";

export function SplatViewer({ url }: { url: string }) {
  const target = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!target.current) return;
    const host = target.current;
    const scene = new THREE.Scene();
    scene.background = new THREE.Color("#081018");
    const camera = new THREE.PerspectiveCamera(60, host.clientWidth / host.clientHeight, 0.01, 2000);
    camera.position.set(0, 1.5, 4);
    const renderer = new THREE.WebGLRenderer({ antialias: true });
    renderer.setPixelRatio(Math.min(devicePixelRatio, 2));
    renderer.setSize(host.clientWidth, host.clientHeight);
    host.appendChild(renderer.domElement);
    const spark = new SparkRenderer({ renderer });
    scene.add(spark);
    const splat = new SplatMesh({ url });
    scene.add(splat);
    const controls = new OrbitControls(camera, renderer.domElement);
    controls.enableDamping = true;
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
