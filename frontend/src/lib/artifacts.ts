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

export function selectMeshArtifacts(artifacts: Artifact[] | undefined) {
  const obj = findArtifact(artifacts, "mesh", "OBJ");
  const glb = findArtifact(artifacts, "mesh", "GLB");
  const tiles = findArtifact(artifacts, "mesh", "3D Tiles");
  return {
    primary: obj ?? glb ?? tiles,
    fallback: obj ? glb : undefined,
  };
}

export function selectSplatArtifacts(artifacts: Artifact[] | undefined) {
  const spz = findArtifact(artifacts, "splat", "SPZ");
  const ply = findArtifact(artifacts, "splat", "PLY");
  return {
    primary: spz ?? ply,
    fallback: spz ? ply : undefined,
  };
}
