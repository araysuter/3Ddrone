/// <reference lib="webworker" />

// @loaders.gl/las does not export its LAS 1.4-capable decoder, but it ships the
// generated module and declarations. Importing it directly avoids the package
// reader's per-point WASM calls while retaining its well-tested LAZ-RS codec.
import initLazRsWasm, {
  WasmLasZipDecompressor,
} from "../../node_modules/@loaders.gl/las/dist/libs/laz-rs-wasm/laz_rs_wasm.js";
import {
  lazSkipForBudget,
  parseLasHeader,
  type LazDecodeRequest,
  type LazDecodeResult,
} from "../lib/laz";

const DECODE_CHUNK_POINTS = 100_000;

let lazRsReady: Promise<unknown> | null = null;

function initializeLazRs() {
  lazRsReady ??= initLazRsWasm(undefined);
  return lazRsReady;
}

function colorByte(value: number, highColorDepth: boolean) {
  return highColorDepth ? Math.min(255, Math.round(value / 257)) : value;
}

function usesHighColorDepth(
  view: DataView,
  pointCount: number,
  pointRecordLength: number,
  colorOffset: number,
) {
  const sampleCount = Math.min(pointCount, 4096);
  const sampleStride = Math.max(1, Math.floor(pointCount / sampleCount));
  for (let index = 0; index < pointCount; index += sampleStride) {
    const base = index * pointRecordLength + colorOffset;
    if (
      view.getUint16(base, true) > 255 ||
      view.getUint16(base + 2, true) > 255 ||
      view.getUint16(base + 4, true) > 255
    ) {
      return true;
    }
  }
  return false;
}

self.onmessage = async (event: MessageEvent<LazDecodeRequest>) => {
  const { buffer, id, maxPoints, origin } = event.data;
  let decompressor: WasmLasZipDecompressor | null = null;
  try {
    const header = parseLasHeader(buffer);
    const sourcePointCount = header.pointCount;
    if (!sourcePointCount) throw new Error("The file contains no points.");
    const skip = lazSkipForBudget(buffer, maxPoints);
    const pointCount = Math.ceil(sourcePointCount / skip);
    const { maximum, minimum } = header.bounds;
    const centerX =
      origin?.[0] ?? (minimum[0] + maximum[0]) / 2;
    const centerY =
      origin?.[1] ?? (minimum[1] + maximum[1]) / 2;
    const groundZ = origin?.[2] ?? minimum[2];
    const positions = new Float32Array(pointCount * 3);
    const colors = header.colorOffset == null
      ? null
      : new Uint8Array(pointCount * 3);
    let radiusSquared = 0;
    let destinationPoint = 0;
    let sourcePoint = 0;
    let highColorDepth: boolean | null = null;

    if (header.compressed) {
      await initializeLazRs();
      decompressor = new WasmLasZipDecompressor(new Uint8Array(buffer));
    } else {
      const requiredBytes =
        header.pointsOffset + sourcePointCount * header.pointRecordLength;
      if (requiredBytes > buffer.byteLength) {
        throw new Error("The LAS point records are incomplete.");
      }
    }

    while (sourcePoint < sourcePointCount) {
      const chunkPointCount = Math.min(
        DECODE_CHUNK_POINTS,
        sourcePointCount - sourcePoint,
      );
      const byteLength = chunkPointCount * header.pointRecordLength;
      let chunk: Uint8Array;
      if (decompressor) {
        chunk = new Uint8Array(byteLength);
        // One call expands a complete chunk. The previous reader invoked this
        // once for every source point, which dominated load time.
        decompressor.decompress_many(chunk);
      } else {
        chunk = new Uint8Array(
          buffer,
          header.pointsOffset + sourcePoint * header.pointRecordLength,
          byteLength,
        );
      }
      const view = new DataView(
        chunk.buffer,
        chunk.byteOffset,
        chunk.byteLength,
      );
      if (header.colorOffset != null && highColorDepth == null) {
        highColorDepth = usesHighColorDepth(
          view,
          chunkPointCount,
          header.pointRecordLength,
          header.colorOffset,
        );
      }

      let localPoint = (skip - (sourcePoint % skip)) % skip;
      for (; localPoint < chunkPointCount; localPoint += skip) {
        const sourceByte = localPoint * header.pointRecordLength;
        const destinationIndex = destinationPoint * 3;
        const x =
          view.getInt32(sourceByte, true) * header.scale[0] +
          header.offset[0] -
          centerX;
        const y =
          view.getInt32(sourceByte + 8, true) * header.scale[2] +
          header.offset[2] -
          groundZ;
        const z = -(
          view.getInt32(sourceByte + 4, true) * header.scale[1] +
          header.offset[1] -
          centerY
        );
        positions[destinationIndex] = x;
        positions[destinationIndex + 1] = y;
        positions[destinationIndex + 2] = z;
        radiusSquared = Math.max(radiusSquared, x * x + y * y + z * z);

        if (
          colors &&
          header.colorOffset != null &&
          highColorDepth != null
        ) {
          const colorIndex = sourceByte + header.colorOffset;
          colors[destinationIndex] = colorByte(
            view.getUint16(colorIndex, true),
            highColorDepth,
          );
          colors[destinationIndex + 1] = colorByte(
            view.getUint16(colorIndex + 2, true),
            highColorDepth,
          );
          colors[destinationIndex + 2] = colorByte(
            view.getUint16(colorIndex + 4, true),
            highColorDepth,
          );
        }
        destinationPoint += 1;
      }
      sourcePoint += chunkPointCount;
    }

    const finalPositions =
      destinationPoint === pointCount
        ? positions
        : positions.slice(0, destinationPoint * 3);
    const finalColors =
      colors && destinationPoint !== pointCount
        ? colors.slice(0, destinationPoint * 3)
        : colors;
    const transfer: Transferable[] = [positions.buffer];
    if (finalPositions !== positions) {
      transfer[0] = finalPositions.buffer;
    }
    if (finalColors) transfer.push(finalColors.buffer);
    const result: LazDecodeResult = {
      type: "success",
      id,
      positions: finalPositions,
      colors: finalColors,
      pointCount: destinationPoint,
      sourcePointCount,
      radius: Math.sqrt(radiusSquared),
      skip,
    };
    self.postMessage(result, { transfer });
  } catch (reason: unknown) {
    const result: LazDecodeResult = {
      type: "error",
      id,
      message: reason instanceof Error ? reason.message : String(reason),
    };
    self.postMessage(result);
  } finally {
    decompressor?.free();
  }
};
