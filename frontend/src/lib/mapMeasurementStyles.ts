import type { FeatureLike } from "ol/Feature.js";
import LineString from "ol/geom/LineString.js";
import MultiPoint from "ol/geom/MultiPoint.js";
import Point from "ol/geom/Point.js";
import Polygon from "ol/geom/Polygon.js";
import {
  Circle as CircleStyle,
  Fill,
  Stroke,
  Style,
  Text,
} from "ol/style.js";
import type { StyleFunction } from "ol/style/Style.js";
import {
  formatArea,
  formatLength,
  measureLine,
  measurePolygon,
  segmentCanFitLabel,
  type MeasurementUnits,
} from "./measurements";

export const MEASUREMENT_DECLUTTER_GROUP = "measurement-labels";

type MeasurementStyleMode = "area" | "auto" | "distance";

interface MeasurementStyleContext {
  getMetersPerUnit: () => number;
  getProjectProjection: () => string;
  getUnits: () => MeasurementUnits;
}

const lineStroke = new Stroke({
  color: "#2f8cff",
  lineCap: "round",
  lineJoin: "round",
  width: 2.25,
});

const geometryStyle = new Style({
  stroke: lineStroke,
  fill: new Fill({ color: "rgba(47,140,255,.16)" }),
  zIndex: 1,
});

const areaSketchLineStyle = new Style({
  stroke: lineStroke,
  zIndex: 1,
});

const vertexImage = new CircleStyle({
  radius: 3.5,
  fill: new Fill({ color: "#2f8cff" }),
  stroke: new Stroke({ color: "#102a43", width: 1.25 }),
  declutterMode: "none",
});

const cursorStyle = new Style({
  image: vertexImage,
  zIndex: 4,
});

function vertexStyle(coordinates: CoordinateArray) {
  return new Style({
    geometry: new MultiPoint(coordinates),
    image: vertexImage,
    zIndex: 4,
  });
}

type CoordinateArray = number[][];

function labelStyle(
  coordinate: number[],
  text: string,
  priority: "edge" | "summary",
) {
  return new Style({
    geometry: new Point(coordinate),
    text: new Text({
      text,
      font: '600 11px "SFMono-Regular", Consolas, "Liberation Mono", monospace',
      fill: new Fill({ color: "#f4f8fb" }),
      backgroundFill: new Fill({ color: "rgba(5,9,13,.94)" }),
      backgroundStroke: new Stroke({ color: "#1f3445", width: 1 }),
      padding: [3, 5, 3, 5],
      offsetY: -1,
      overflow: true,
      declutterMode: "declutter",
    }),
    zIndex: priority === "summary" ? 20 : 10,
  });
}

function lineStyles(
  line: LineString,
  context: MeasurementStyleContext,
): Style[] {
  const projectLine = line
    .clone()
    .transform("EPSG:3857", context.getProjectProjection());
  const measurement = measureLine(
    line,
    projectLine,
    context.getMetersPerUnit(),
  );
  const styles = [geometryStyle, vertexStyle(line.getCoordinates())];
  if (measurement) {
    styles.push(
      labelStyle(
        measurement.coordinate,
        formatLength(measurement.meters, context.getUnits()),
        "summary",
      ),
    );
  }
  return styles;
}

function polygonStyles(
  polygon: Polygon,
  resolution: number,
  context: MeasurementStyleContext,
): Style[] {
  const projectPolygon = polygon
    .clone()
    .transform("EPSG:3857", context.getProjectProjection());
  const measurement = measurePolygon(
    polygon,
    projectPolygon,
    context.getMetersPerUnit(),
  );
  const ring = polygon.getLinearRing(0)?.getCoordinates() ?? [];
  const styles = [
    geometryStyle,
    vertexStyle(ring.length > 1 ? ring.slice(0, -1) : ring),
  ];
  if (!measurement) return styles;

  for (const segment of measurement.segments) {
    const text = formatLength(segment.meters, context.getUnits());
    if (segmentCanFitLabel(segment.mapLength, resolution, text)) {
      styles.push(labelStyle(segment.coordinate, text, "edge"));
    }
  }
  styles.push(
    labelStyle(
      measurement.coordinate,
      formatArea(measurement.areaSquareMeters, context.getUnits()),
      "summary",
    ),
  );
  return styles;
}

export function createMeasurementStyleFunction(
  context: MeasurementStyleContext,
  mode: MeasurementStyleMode = "auto",
): StyleFunction {
  return (feature: FeatureLike, resolution: number) => {
    const geometry = feature.getGeometry();
    if (geometry instanceof Point) return cursorStyle;
    if (geometry instanceof Polygon) {
      return polygonStyles(geometry, resolution, context);
    }
    if (geometry instanceof LineString) {
      return mode === "area"
        ? [areaSketchLineStyle]
        : lineStyles(geometry, context);
    }
    return [];
  };
}
