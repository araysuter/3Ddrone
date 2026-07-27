export interface LazDecodeRequest {
  id: number;
  buffer: ArrayBuffer;
  maxPoints?: number;
  origin?: [x: number, y: number, groundZ: number];
}

export interface LazDecodeSuccess {
  type: "success";
  id: number;
  positions: Float32Array;
  colors: Uint8Array | null;
  pointCount: number;
  sourcePointCount: number;
  radius: number;
  skip: number;
}

export interface LazDecodeError {
  type: "error";
  id: number;
  message: string;
}

export type LazDecodeResult = LazDecodeSuccess | LazDecodeError;

export interface LasHeader {
  bounds: {
    maximum: [number, number, number];
    minimum: [number, number, number];
  };
  colorOffset: number | null;
  compressed: boolean;
  offset: [number, number, number];
  pointCount: number;
  pointFormat: number;
  pointRecordLength: number;
  pointsOffset: number;
  scale: [number, number, number];
}

const COLOR_OFFSETS: Record<number, number> = {
  2: 20,
  3: 28,
  5: 28,
  7: 30,
  8: 30,
  10: 30,
};

function safePointCount(view: DataView, byteLength: number) {
  const legacyCount = view.getUint32(107, true);
  const versionMajor = view.getUint8(24);
  const versionMinor = view.getUint8(25);
  if (versionMajor === 1 && versionMinor >= 4 && byteLength >= 255) {
    const extendedCount = view.getBigUint64(247, true);
    if (extendedCount > 0n) {
      return Number(
        extendedCount > BigInt(Number.MAX_SAFE_INTEGER)
          ? BigInt(Number.MAX_SAFE_INTEGER)
          : extendedCount,
      );
    }
  }
  return legacyCount;
}

export function parseLasHeader(buffer: ArrayBuffer): LasHeader {
  if (buffer.byteLength < 227) {
    throw new Error("The LAS/LAZ header is incomplete.");
  }
  const view = new DataView(buffer);
  if (
    view.getUint8(0) !== 0x4c ||
    view.getUint8(1) !== 0x41 ||
    view.getUint8(2) !== 0x53 ||
    view.getUint8(3) !== 0x46
  ) {
    throw new Error("The point cloud is not a LAS/LAZ file.");
  }

  const rawPointFormat = view.getUint8(104);
  const pointFormat = rawPointFormat & 0x3f;
  const pointRecordLength = view.getUint16(105, true);
  const pointsOffset = view.getUint32(96, true);
  const pointCount = safePointCount(view, buffer.byteLength);
  const scale = [
    view.getFloat64(131, true),
    view.getFloat64(139, true),
    view.getFloat64(147, true),
  ] as [number, number, number];
  const offset = [
    view.getFloat64(155, true),
    view.getFloat64(163, true),
    view.getFloat64(171, true),
  ] as [number, number, number];
  const maximum = [
    view.getFloat64(179, true),
    view.getFloat64(195, true),
    view.getFloat64(211, true),
  ] as [number, number, number];
  const minimum = [
    view.getFloat64(187, true),
    view.getFloat64(203, true),
    view.getFloat64(219, true),
  ] as [number, number, number];
  const colorOffset = COLOR_OFFSETS[pointFormat] ?? null;

  if (pointFormat > 10 || pointRecordLength < 12) {
    throw new Error(`Unsupported LAS point format ${pointFormat}.`);
  }
  if (
    !Number.isFinite(pointCount) ||
    pointCount < 0 ||
    !Number.isSafeInteger(pointCount)
  ) {
    throw new Error("The LAS/LAZ point count is invalid.");
  }
  if (
    pointsOffset < 227 ||
    pointsOffset > buffer.byteLength ||
    (colorOffset != null && colorOffset + 6 > pointRecordLength)
  ) {
    throw new Error("The LAS/LAZ point-record layout is invalid.");
  }
  if (
    [...scale, ...offset, ...minimum, ...maximum].some(
      (value) => !Number.isFinite(value),
    )
  ) {
    throw new Error("The LAS/LAZ coordinate metadata is invalid.");
  }

  return {
    bounds: { maximum, minimum },
    colorOffset,
    compressed: (rawPointFormat & 0xc0) !== 0,
    offset,
    pointCount,
    pointFormat,
    pointRecordLength,
    pointsOffset,
    scale,
  };
}

export function lasPointCount(buffer: ArrayBuffer) {
  try {
    return parseLasHeader(buffer).pointCount;
  } catch {
    return 0;
  }
}

export function lazSkipForBudget(buffer: ArrayBuffer, maxPoints = Infinity) {
  const pointCount = lasPointCount(buffer);
  if (!Number.isFinite(maxPoints) || maxPoints <= 0 || pointCount <= maxPoints) {
    return 1;
  }
  return Math.max(1, Math.ceil(pointCount / maxPoints));
}
