import LineString from "ol/geom/LineString.js";
import Polygon from "ol/geom/Polygon.js";
import { describe, expect, it } from "vitest";
import {
  MEASUREMENT_UNITS_STORAGE_KEY,
  formatArea,
  formatLength,
  measureLine,
  measurePolygon,
  readMeasurementUnits,
  segmentCanFitLabel,
  writeMeasurementUnits,
} from "./measurements";

describe("measurement formatting", () => {
  it("formats imperial measurements with compact large-unit thresholds", () => {
    expect(formatLength(2.779_776, "imperial")).toBe("9.12 ft");
    expect(formatLength(1_609.344, "imperial")).toBe("1.000 mi");
    expect(formatArea(100, "imperial")).toBe("1076.39 ft²");
    expect(formatArea(4_046.856_422_4, "imperial")).toBe("1.00 ac");
  });

  it("retains the existing metric units and thresholds", () => {
    expect(formatLength(999.9, "metric")).toBe("999.90 m");
    expect(formatLength(1_000, "metric")).toBe("1.000 km");
    expect(formatArea(9_999.9, "metric")).toBe("9999.90 m²");
    expect(formatArea(10_000, "metric")).toBe("1.00 ha");
  });
});

describe("measurement geometry", () => {
  it("places a polyline total at the length-along-line midpoint", () => {
    const line = new LineString([
      [0, 0],
      [3, 0],
      [3, 4],
    ]);
    expect(measureLine(line, line.clone(), 1)).toEqual({
      coordinate: [3, 0.5],
      meters: 7,
    });
  });

  it("measures every polygon edge and places the area label inside", () => {
    const polygon = new Polygon([
      [
        [0, 0],
        [3, 0],
        [3, 4],
        [0, 4],
        [0, 0],
      ],
    ]);
    const measurement = measurePolygon(polygon, polygon.clone(), 1);

    expect(measurement?.areaSquareMeters).toBe(12);
    expect(measurement?.segments.map((segment) => segment.meters)).toEqual([
      3, 4, 3, 4,
    ]);
    expect(polygon.intersectsCoordinate(measurement!.coordinate)).toBe(true);
  });

  it("suppresses edge tags that cannot fit at the current resolution", () => {
    expect(segmentCanFitLabel(100, 1, "9.12 ft")).toBe(true);
    expect(segmentCanFitLabel(30, 1, "9.12 ft")).toBe(false);
    expect(segmentCanFitLabel(30, 0.25, "9.12 ft")).toBe(true);
  });
});

describe("measurement unit preference", () => {
  it("defaults safely to imperial and accepts only the stored metric value", () => {
    expect(readMeasurementUnits()).toBe("imperial");
    expect(readMeasurementUnits({ getItem: () => "metric" })).toBe("metric");
    expect(readMeasurementUnits({ getItem: () => "unexpected" })).toBe(
      "imperial",
    );
    expect(
      readMeasurementUnits({
        getItem: () => {
          throw new Error("storage unavailable");
        },
      }),
    ).toBe("imperial");
  });

  it("writes only the versioned unit value and tolerates storage failures", () => {
    const calls: Array<[string, string]> = [];
    writeMeasurementUnits("metric", {
      setItem: (key, value) => calls.push([key, value]),
    });
    expect(calls).toEqual([[MEASUREMENT_UNITS_STORAGE_KEY, "metric"]]);
    expect(() =>
      writeMeasurementUnits("imperial", {
        setItem: () => {
          throw new Error("storage unavailable");
        },
      }),
    ).not.toThrow();
  });
});
