import { describe, expect, it } from "vitest";
import type { Artifact } from "../types";
import { selectMeshArtifacts, selectPointCloudArtifact } from "./artifacts";

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
    const artifacts = [
      artifact("Point cloud LAZ", "download"),
      artifact("EPT point cloud", "pointcloud"),
    ];

    expect(selectPointCloudArtifact(artifacts)?.label).toBe("Point cloud LAZ");
  });

  it("prefers streamable 3D Tiles when available", () => {
    const artifacts = [
      artifact("Point cloud LAZ", "download"),
      artifact("OGC 3D Tiles point cloud", "tiles3d"),
    ];

    expect(selectPointCloudArtifact(artifacts)?.viewer).toBe("tiles3d");
  });
});

describe("selectMeshArtifacts", () => {
  it("prefers the textured OBJ and retains GLB as a fallback", () => {
    const obj = artifact("Textured terrain mesh OBJ", "mesh", "mesh");
    const glb = artifact("Textured terrain mesh GLB", "mesh", "mesh");
    const tiles = artifact("OGC 3D Tiles textured model", "tiles3d", "mesh");

    expect(selectMeshArtifacts([tiles, glb, obj])).toEqual({
      primary: obj,
      fallback: glb,
    });
  });

  it("uses GLB directly when no OBJ is available", () => {
    const glb = artifact("Textured mesh GLB", "mesh", "mesh");

    expect(selectMeshArtifacts([glb])).toEqual({
      primary: glb,
      fallback: undefined,
    });
  });
});
