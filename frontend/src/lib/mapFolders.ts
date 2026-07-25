import type { MapFolder, Project } from "../types";

export const NO_PROJECT_KEY = "__no_project__";
export const COLLAPSED_FOLDERS_STORAGE_KEY = "mapper-collapsed-folders:v1";

export interface MapFolderGroup {
  key: string;
  folder: MapFolder | null;
  maps: Project[];
}

export function groupMapsByFolder(folders: MapFolder[], maps: Project[]): MapFolderGroup[] {
  const sortedFolders = [...folders].sort(
    (left, right) =>
      left.name.localeCompare(right.name, undefined, { sensitivity: "base" }) ||
      left.id.localeCompare(right.id),
  );
  const sortedMaps = [...maps].sort(
    (left, right) =>
      Date.parse(right.created_at) - Date.parse(left.created_at) ||
      right.id.localeCompare(left.id),
  );
  const byFolder = new Map<string, Project[]>(
    sortedFolders.map((folder) => [folder.id, []]),
  );
  const unassigned: Project[] = [];
  for (const map of sortedMaps) {
    const target = map.folder_id ? byFolder.get(map.folder_id) : undefined;
    if (target) target.push(map);
    else unassigned.push(map);
  }
  return [
    ...sortedFolders.map((folder) => ({
      key: folder.id,
      folder,
      maps: byFolder.get(folder.id) ?? [],
    })),
    { key: NO_PROJECT_KEY, folder: null, maps: unassigned },
  ];
}

export function parseCollapsedFolderIds(raw: string | null): Set<string> {
  if (!raw) return new Set();
  try {
    const parsed: unknown = JSON.parse(raw);
    if (!Array.isArray(parsed)) return new Set();
    return new Set(parsed.filter((value): value is string => typeof value === "string"));
  } catch {
    return new Set();
  }
}

export function serializeCollapsedFolderIds(values: Set<string>): string {
  return JSON.stringify([...values].sort());
}
