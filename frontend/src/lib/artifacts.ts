import type { Artifact } from "../types";

export function findArtifact(
  artifacts: Artifact[] | undefined,
  category: string,
  labelPart?: string,
) {
  return artifacts?.find(
    (artifact) =>
      artifact.category === category &&
      (!labelPart ||
        artifact.label.toLowerCase().includes(labelPart.toLowerCase())),
  );
}

export function selectPointCloudArtifact(artifacts: Artifact[] | undefined) {
  return (
    findArtifact(artifacts, "point_cloud", "3D Tiles") ??
    findArtifact(artifacts, "point_cloud", "Potree") ??
    findArtifact(artifacts, "point_cloud", "LAZ")
  );
}
