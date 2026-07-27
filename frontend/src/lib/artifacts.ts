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

export function selectPointCloudArtifacts(artifacts: Artifact[] | undefined) {
  const tiles = findArtifact(artifacts, "point_cloud", "3D Tiles");
  const ept = findArtifact(artifacts, "point_cloud", "EPT");
  const potree = findArtifact(artifacts, "point_cloud", "Potree");
  const laz = findArtifact(artifacts, "point_cloud", "LAZ");
  return {
    primary: tiles ?? ept ?? potree ?? laz,
    fallback: tiles ? (ept ?? potree ?? laz) : ept ? laz : undefined,
    downloadFallback: ept ? laz : undefined,
  };
}

export function selectPointCloudArtifact(artifacts: Artifact[] | undefined) {
  return selectPointCloudArtifacts(artifacts).primary;
}

export function selectMeshArtifacts(artifacts: Artifact[] | undefined) {
  const obj = findArtifact(artifacts, "mesh", "OBJ");
  const glb = findArtifact(artifacts, "mesh", "GLB");
  const tiles = findArtifact(artifacts, "mesh", "3D Tiles");
  return {
    primary: glb ?? tiles ?? obj,
    fallback: glb ? obj : tiles ? obj : undefined,
    finalFallback: undefined,
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
