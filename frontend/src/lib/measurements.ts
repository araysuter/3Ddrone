import type { Coordinate } from "ol/coordinate.js";
import LineString from "ol/geom/LineString.js";
import Polygon from "ol/geom/Polygon.js";

export type MeasurementUnits = "imperial" | "metric";

export const MEASUREMENT_UNITS_STORAGE_KEY =
  "local-aerial-mapper:measurement-units:v1";

const FEET_PER_METER = 3.280_839_895;
const FEET_PER_MILE = 5_280;
const METERS_PER_MILE = 1_609.344;
const SQUARE_FEET_PER_SQUARE_METER = 10.763_910_417;
const SQUARE_FEET_PER_ACRE = 43_560;
const SQUARE_METERS_PER_ACRE = 4_046.856_422_4;

type StorageReader = Pick<Storage, "getItem">;
type StorageWriter = Pick<Storage, "setItem">;

export interface LineMeasurement {
  coordinate: Coordinate;
  meters: number;
}

export interface SegmentMeasurement extends LineMeasurement {
  mapLength: number;
}

export interface PolygonMeasurement {
  areaSquareMeters: number;
  coordinate: Coordinate;
  segments: SegmentMeasurement[];
}

export function readMeasurementUnits(storage?: StorageReader | null): MeasurementUnits {
  if (!storage) return "imperial";
  try {
    return storage.getItem(MEASUREMENT_UNITS_STORAGE_KEY) === "metric"
      ? "metric"
      : "imperial";
  } catch {
    return "imperial";
  }
}

export function writeMeasurementUnits(
  units: MeasurementUnits,
  storage?: StorageWriter | null,
) {
  if (!storage) return;
  try {
    storage.setItem(MEASUREMENT_UNITS_STORAGE_KEY, units);
  } catch {
    // The in-memory preference still works when browser storage is unavailable.
  }
}

export function formatLength(meters: number, units: MeasurementUnits) {
  const safeMeters = Math.abs(meters);
  if (units === "imperial") {
    const feet = safeMeters * FEET_PER_METER;
    return safeMeters >= METERS_PER_MILE
      ? `${(feet / FEET_PER_MILE).toFixed(3)} mi`
      : `${feet.toFixed(2)} ft`;
  }
  return safeMeters >= 1_000
    ? `${(safeMeters / 1_000).toFixed(3)} km`
    : `${safeMeters.toFixed(2)} m`;
}

export function formatArea(squareMeters: number, units: MeasurementUnits) {
  const safeSquareMeters = Math.abs(squareMeters);
  if (units === "imperial") {
    const squareFeet = safeSquareMeters * SQUARE_FEET_PER_SQUARE_METER;
    return safeSquareMeters >= SQUARE_METERS_PER_ACRE
      ? `${(squareFeet / SQUARE_FEET_PER_ACRE).toFixed(2)} ac`
      : `${squareFeet.toFixed(2)} ft²`;
  }
  return safeSquareMeters >= 10_000
    ? `${(safeSquareMeters / 10_000).toFixed(2)} ha`
    : `${safeSquareMeters.toFixed(2)} m²`;
}

export function measureLine(
  mapLine: LineString,
  projectLine: LineString,
  metersPerUnit: number,
): LineMeasurement | null {
  const meters = projectLine.getLength() * metersPerUnit;
  if (!Number.isFinite(meters) || meters <= 0) return null;
  return {
    coordinate: mapLine.getCoordinateAt(0.5),
    meters,
  };
}

export function measurePolygon(
  mapPolygon: Polygon,
  projectPolygon: Polygon,
  metersPerUnit: number,
): PolygonMeasurement | null {
  const mapRing = mapPolygon.getLinearRing(0)?.getCoordinates() ?? [];
  const projectRing = projectPolygon.getLinearRing(0)?.getCoordinates() ?? [];
  if (mapRing.length < 4 || projectRing.length < 4) return null;

  const segmentCount = Math.min(mapRing.length, projectRing.length) - 1;
  const segments: SegmentMeasurement[] = [];
  for (let index = 0; index < segmentCount; index += 1) {
    const mapStart = mapRing[index];
    const mapEnd = mapRing[index + 1];
    const projectStart = projectRing[index];
    const projectEnd = projectRing[index + 1];
    const mapLength = Math.hypot(mapEnd[0] - mapStart[0], mapEnd[1] - mapStart[1]);
    const meters =
      Math.hypot(
        projectEnd[0] - projectStart[0],
        projectEnd[1] - projectStart[1],
      ) * metersPerUnit;
    if (!Number.isFinite(meters) || meters <= 0) continue;
    segments.push({
      coordinate: [
        (mapStart[0] + mapEnd[0]) / 2,
        (mapStart[1] + mapEnd[1]) / 2,
      ],
      mapLength,
      meters,
    });
  }

  const areaSquareMeters =
    Math.abs(projectPolygon.getArea()) * metersPerUnit ** 2;
  if (!Number.isFinite(areaSquareMeters) || areaSquareMeters <= 0) return null;
  return {
    areaSquareMeters,
    coordinate: mapPolygon.getInteriorPoint().getCoordinates().slice(0, 2),
    segments,
  };
}

export function segmentCanFitLabel(
  mapLength: number,
  resolution: number,
  text: string,
) {
  if (!Number.isFinite(resolution) || resolution <= 0) return true;
  const estimatedLabelWidth = [...text].length * 6.6 + 12;
  return mapLength / resolution >= estimatedLabelWidth + 8;
}
