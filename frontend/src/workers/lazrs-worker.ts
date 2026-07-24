/// <reference lib="webworker" />

import { LAZRsLoader } from "@loaders.gl/las";
import { ODM_LAZ_OPTIONS } from "../lib/laz";

type NumericArray = Float32Array | Float64Array;

self.onmessage = async (event: MessageEvent<{ buffer: ArrayBuffer }>) => {
  try {
    // The Rust/WASM decoder supports LAS/LAZ 1.4, including point formats 6-10
    // produced by current ODM/PDAL builds.
    const mesh = await LAZRsLoader.parse(event.data.buffer, ODM_LAZ_OPTIONS);
    const positionAttribute = mesh.attributes.POSITION;
    if (!positionAttribute || positionAttribute.size < 3) {
      throw new Error("The file does not contain XYZ positions.");
    }
    const values = positionAttribute.value as NumericArray;
    const pointCount =
      mesh.header?.vertexCount ??
      Math.floor(values.length / positionAttribute.size);
    if (!pointCount) throw new Error("The file contains no points.");

    const bounds = mesh.header?.boundingBox;
    const centerX = bounds ? (bounds[0][0] + bounds[1][0]) / 2 : values[0];
    const centerY = bounds ? (bounds[0][1] + bounds[1][1]) / 2 : values[1];
    const centerZ = bounds ? (bounds[0][2] + bounds[1][2]) / 2 : values[2];
    const positions = new Float32Array(pointCount * 3);
    const sourceColor = mesh.attributes.COLOR_0;
    const sourceColors = sourceColor?.value as Uint8Array | undefined;
    const colors = sourceColor ? new Uint8Array(pointCount * 3) : null;
    let radiusSquared = 0;

    for (let index = 0; index < pointCount; index += 1) {
      const sourceIndex = index * positionAttribute.size;
      const destinationIndex = index * 3;
      // ODM point clouds are Z-up. Center while values are still Float64 so
      // projected coordinates preserve local centimeter-scale detail.
      const x = values[sourceIndex] - centerX;
      const y = values[sourceIndex + 2] - centerZ;
      const z = -(values[sourceIndex + 1] - centerY);
      positions[destinationIndex] = x;
      positions[destinationIndex + 1] = y;
      positions[destinationIndex + 2] = z;
      radiusSquared = Math.max(radiusSquared, x * x + y * y + z * z);

      if (colors && sourceColors && sourceColor) {
        const colorIndex = index * sourceColor.size;
        colors[destinationIndex] = sourceColors[colorIndex];
        colors[destinationIndex + 1] = sourceColors[colorIndex + 1];
        colors[destinationIndex + 2] = sourceColors[colorIndex + 2];
      }
    }

    const transfer: Transferable[] = [positions.buffer];
    if (colors) transfer.push(colors.buffer);
    self.postMessage(
      {
        type: "success",
        positions,
        colors,
        pointCount,
        radius: Math.sqrt(radiusSquared),
      },
      { transfer },
    );
  } catch (reason: unknown) {
    self.postMessage({
      type: "error",
      message: reason instanceof Error ? reason.message : String(reason),
    });
  }
};
