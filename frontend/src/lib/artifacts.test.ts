import { describe, expect, it } from "vitest";
import type { Artifact } from "../types";
import {
  selectMeshArtifacts,
  selectPointCloudArtifact,
  selectPointCloudArtifacts,
  selectSplatArtifacts,
} from "./artifacts";
import {
  lasPointCount,
  lazSkipForBudget,
  parseLasHeader,
} from "./laz";

function artifact(
  label: string,
  viewer: string,
  category = "point_cloud",
): Artifact {
  return {
    id: label,
    category,
    label,
    path: `artifacts/${label}`,
    viewer,
    size: 1,
    content_type: "application/octet-stream",
  };
}

describe("selectPointCloudArtifact", () => {
  it("falls back to the downloadable LAZ produced by ODM", () => {
    const artifacts = [artifact("Point cloud LAZ", "download")];

    expect(selectPointCloudArtifact(artifacts)?.label).toBe("Point cloud LAZ");
  });

  it("prefers streamable 3D Tiles when available", () => {
    const artifacts = [
      artifact("Point cloud LAZ", "download"),
      artifact("OGC 3D Tiles point cloud", "tiles3d"),
    ];

    expect(selectPointCloudArtifact(artifacts)?.viewer).toBe("tiles3d");
  });

  it("uses progressive EPT before the monolithic LAZ fallback", () => {
    const laz = artifact("Point cloud LAZ", "download");
    const ept = artifact("EPT point cloud", "pointcloud");

    expect(selectPointCloudArtifacts([laz, ept])).toEqual({
      primary: ept,
      fallback: laz,
      downloadFallback: laz,
    });
  });
});

describe("LAS/LAZ metadata", () => {
  it("reads LAS 1.4 counts and derives a browser point-budget stride", () => {
    const buffer = new ArrayBuffer(375);
    const view = new DataView(buffer);
    for (const [index, byte] of [..."LASF"].entries()) {
      view.setUint8(index, byte.charCodeAt(0));
    }
    view.setUint8(24, 1);
    view.setUint8(25, 4);
    view.setUint32(96, 375, true);
    view.setUint8(104, 0x80 | 7);
    view.setUint16(105, 36, true);
    view.setBigUint64(247, 12_000_000n, true);
    view.setFloat64(131, 0.01, true);
    view.setFloat64(139, 0.01, true);
    view.setFloat64(147, 0.01, true);

    expect(lasPointCount(buffer)).toBe(12_000_000);
    expect(lazSkipForBudget(buffer, 6_000_000)).toBe(2);
    expect(parseLasHeader(buffer)).toMatchObject({
      colorOffset: 30,
      compressed: true,
      pointCount: 12_000_000,
      pointFormat: 7,
      pointRecordLength: 36,
      pointsOffset: 375,
    });
  });
});

describe("selectMeshArtifacts", () => {
  it("prefers progressive tiles and retains compact GLB as a fallback", () => {
    const obj = artifact("Textured terrain mesh OBJ", "mesh", "mesh");
    const glb = artifact("Textured terrain mesh GLB", "mesh", "mesh");
    const tiles = artifact("OGC 3D Tiles textured model", "tiles3d", "mesh");

    expect(selectMeshArtifacts([tiles, glb, obj])).toEqual({
      primary: tiles,
      fallback: glb,
      finalFallback: obj,
    });
  });

  it("uses GLB directly and only falls back to OBJ", () => {
    const glb = artifact("Textured mesh GLB", "mesh", "mesh");
    const obj = artifact("Textured mesh OBJ", "mesh", "mesh");

    expect(selectMeshArtifacts([obj, glb])).toEqual({
      primary: glb,
      fallback: obj,
      finalFallback: undefined,
    });
  });
});

describe("selectSplatArtifacts", () => {
  it("prefers compact SPZ and retains the Gaussian PLY as a fallback", () => {
    const spz = artifact("Gaussian splat SPZ", "splat", "splat");
    const ply = artifact("Gaussian splat PLY", "splat", "splat");

    expect(selectSplatArtifacts([ply, spz])).toEqual({
      primary: spz,
      fallback: ply,
    });
  });
});
