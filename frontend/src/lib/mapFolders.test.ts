import { describe, expect, it } from "vitest";
import type { MapFolder, Project } from "../types";
import {
  NO_PROJECT_KEY,
  groupMapsByFolder,
  parseCollapsedFolderIds,
  serializeCollapsedFolderIds,
} from "./mapFolders";

function map(id: string, folderId: string | null, createdAt: string, status: Project["status"]) {
  return {
    id,
    folder_id: folderId,
    name: id,
    preset: "high",
    status,
    stage: "Complete",
    progress: 100,
    outputs: {},
    advanced: {},
    inspection: {},
    gcp_used: false,
    cancel_requested: false,
    created_at: createdAt,
    updated_at: createdAt,
  } satisfies Project;
}

function folder(id: string, name: string): MapFolder {
  return {
    id,
    name,
    created_at: "2026-01-01T00:00:00Z",
    updated_at: "2026-01-01T00:00:00Z",
  };
}

describe("map folder grouping", () => {
  it("groups maps by project regardless of processing status and keeps No Project last", () => {
    const groups = groupMapsByFolder(
      [folder("b", "Zeta"), folder("a", "Arbordale")],
      [
        map("new", "a", "2026-07-25T00:00:00Z", "processing"),
        map("old", "a", "2026-07-20T00:00:00Z", "completed"),
        map("orphan", "missing", "2026-07-24T00:00:00Z", "failed"),
      ],
    );

    expect(groups.map((group) => group.folder?.name ?? "No Project")).toEqual([
      "Arbordale",
      "Zeta",
      "No Project",
    ]);
    expect(groups[0].maps.map((item) => item.id)).toEqual(["new", "old"]);
    expect(groups.at(-1)?.key).toBe(NO_PROJECT_KEY);
    expect(groups.at(-1)?.maps.map((item) => item.id)).toEqual(["orphan"]);
  });

  it("round-trips collapse state and ignores invalid stored values", () => {
    const serialized = serializeCollapsedFolderIds(new Set(["b", NO_PROJECT_KEY, "a"]));
    expect([...parseCollapsedFolderIds(serialized)].sort()).toEqual([
      NO_PROJECT_KEY,
      "a",
      "b",
    ]);
    expect(parseCollapsedFolderIds("{broken").size).toBe(0);
    expect(parseCollapsedFolderIds('["valid",3,null]')).toEqual(new Set(["valid"]));
  });
});
