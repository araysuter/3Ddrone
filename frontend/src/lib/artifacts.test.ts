import { describe, expect, it } from "vitest";
import type { Artifact } from "../types";
import { selectPointCloudArtifact } from "./artifacts";

function artifact(label: string, viewer: string): Artifact {
  return {
    id: label,
    category: "point_cloud",
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
