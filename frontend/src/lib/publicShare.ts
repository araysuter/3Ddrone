const UUID_PATTERN =
  "([0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12})";
const MAP_ROUTE = new RegExp(`^/share/maps/${UUID_PATTERN}/?$`, "i");
const PROJECT_ROUTE = new RegExp(
  `^/share/projects/${UUID_PATTERN}(?:/maps/${UUID_PATTERN})?/?$`,
  "i",
);

export type PublicShareLocation =
  | { kind: "map"; shareId: string }
  | { kind: "project"; shareId: string; itemId?: string };

export function parsePublicShareLocation(
  pathname: string,
): PublicShareLocation | null {
  const mapMatch = pathname.match(MAP_ROUTE);
  if (mapMatch) {
    return { kind: "map", shareId: mapMatch[1].toLowerCase() };
  }
  const projectMatch = pathname.match(PROJECT_ROUTE);
  if (projectMatch) {
    return {
      kind: "project",
      shareId: projectMatch[1].toLowerCase(),
      itemId: projectMatch[2]?.toLowerCase(),
    };
  }
  return null;
}

export function publicProjectMapPath(shareId: string, itemId: string) {
  return `/share/projects/${shareId}/maps/${itemId}`;
}

export function publicMapResourceBase(shareId: string) {
  return `/api/public/map-shares/${shareId}`;
}

export function publicProjectMapResourceBase(
  shareId: string,
  itemId: string,
) {
  return `/api/public/project-shares/${shareId}/maps/${itemId}`;
}

export function artifactResourcePath(
  resourceBase: string,
  artifactPath: string,
) {
  return `${resourceBase}/artifacts/${artifactPath}`;
}
