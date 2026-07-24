import { copyFile, mkdir } from "node:fs/promises";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const frontendRoot = resolve(dirname(fileURLToPath(import.meta.url)), "..");
const sourceRoot = resolve(
  frontendRoot,
  "node_modules/three/examples/jsm/libs/draco/gltf",
);
const destinationRoot = resolve(frontendRoot, "public/draco");
const decoderFiles = [
  "draco_decoder.js",
  "draco_decoder.wasm",
  "draco_wasm_wrapper.js",
];

await mkdir(destinationRoot, { recursive: true });
await Promise.all(
  decoderFiles.map((filename) =>
    copyFile(resolve(sourceRoot, filename), resolve(destinationRoot, filename)),
  ),
);
