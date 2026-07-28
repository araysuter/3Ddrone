export interface EptMetadata {
  bounds: [number, number, number, number, number, number];
  boundsConforming?: [number, number, number, number, number, number];
  dataType: string;
  hierarchyType: string;
  points: number;
}

export interface EptNode {
  key: string;
  pointCount: number;
}

export function eptDepth(key: string) {
  const depth = Number.parseInt(key.split("-", 1)[0] ?? "", 10);
  return Number.isFinite(depth) ? depth : Number.MAX_SAFE_INTEGER;
}

export function selectEptNodes(
  hierarchy: Record<string, number>,
  pointBudget: number,
) {
  const nodes = Object.entries(hierarchy)
    .filter((entry): entry is [string, number] => entry[1] > 0)
    .map(([key, pointCount]) => ({ key, pointCount }))
    .sort((left, right) => {
      const depthDifference = eptDepth(left.key) - eptDepth(right.key);
      return depthDifference || left.key.localeCompare(right.key);
    });
  if (nodes.length === 0) return [];

  const selected: EptNode[] = [];
  let selectedPoints = 0;
  for (let index = 0; index < nodes.length; ) {
    const depth = eptDepth(nodes[index].key);
    let end = index;
    let levelPoints = 0;
    while (end < nodes.length && eptDepth(nodes[end].key) === depth) {
      levelPoints += nodes[end].pointCount;
      end += 1;
    }
    const level = nodes.slice(index, end);
    // EPT levels cover the scene in spatial tiles. Loading only part of a
    // level creates abrupt density seams at the selected tile boundaries.
    if (selected.length > 0 && selectedPoints + levelPoints > pointBudget) break;
    selected.push(...level);
    selectedPoints += levelPoints;
    index = end;
  }
  return selected;
}

export function eptSceneFrame(metadata: EptMetadata) {
  const bounds = metadata.boundsConforming ?? metadata.bounds;
  if (
    bounds.length !== 6 ||
    bounds.some((value) => !Number.isFinite(value))
  ) {
    throw new Error("EPT metadata contains invalid bounds.");
  }
  const [minimumX, minimumY, minimumZ, maximumX, maximumY, maximumZ] =
    bounds;
  const width = Math.max(0, maximumX - minimumX);
  const depth = Math.max(0, maximumY - minimumY);
  const height = Math.max(0, maximumZ - minimumZ);
  return {
    origin: [
      minimumX + width / 2,
      minimumY + depth / 2,
      minimumZ,
    ] as [number, number, number],
    radius: Math.max(
      Math.hypot(width / 2, height, depth / 2),
      0.000001,
    ),
  };
}
