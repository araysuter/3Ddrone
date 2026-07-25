import {
  AlertTriangle,
  Check,
  ChevronRight,
  CircleDot,
  Folder,
  FolderPlus,
  Info,
  LogOut,
  Map,
  MoreHorizontal,
  Pencil,
  Plus,
  Radio,
  Trash2,
} from "lucide-react";
import { DragEvent, useMemo, useState } from "react";
import {
  COLLAPSED_FOLDERS_STORAGE_KEY,
  groupMapsByFolder,
  NO_PROJECT_KEY,
  parseCollapsedFolderIds,
  serializeCollapsedFolderIds,
} from "../lib/mapFolders";
import type { MapFolder, Project, ProjectStatus } from "../types";

interface Props {
  maps: Project[];
  folders: MapFolder[];
  selectedId?: string;
  onSelect: (id: string) => void;
  onNewMap: () => void;
  onNewFolder: () => void;
  onRenameFolder: (folder: MapFolder) => void;
  onDeleteFolder: (folder: MapFolder) => Promise<void>;
  onMoveMap: (mapId: string, folderId: string | null) => Promise<void>;
  onAbout: () => void;
  onLogout: () => Promise<void>;
  uploadProgress: Record<string, number>;
}

const MAP_DRAG_TYPE = "application/x-aerial-map-id";

function ProjectIcon({ status }: { status: ProjectStatus }) {
  if (status === "completed") return <Check size={13} />;
  if (status === "partial" || status === "failed") return <AlertTriangle size={13} />;
  if (status === "canceled") return <CircleDot size={13} />;
  return <Radio size={13} />;
}

function initialCollapsedFolders() {
  try {
    return parseCollapsedFolderIds(localStorage.getItem(COLLAPSED_FOLDERS_STORAGE_KEY));
  } catch {
    return new Set<string>();
  }
}

export function Sidebar({
  maps,
  folders,
  selectedId,
  onSelect,
  onNewMap,
  onNewFolder,
  onRenameFolder,
  onDeleteFolder,
  onMoveMap,
  onAbout,
  onLogout,
  uploadProgress,
}: Props) {
  const groups = useMemo(() => groupMapsByFolder(folders, maps), [folders, maps]);
  const [collapsed, setCollapsed] = useState<Set<string>>(initialCollapsedFolders);
  const [menuFolderId, setMenuFolderId] = useState<string>();
  const [draggingMapId, setDraggingMapId] = useState<string>();
  const [dropTarget, setDropTarget] = useState<string>();
  const [movingMapId, setMovingMapId] = useState<string>();
  const [error, setError] = useState("");

  function storeCollapsed(next: Set<string>) {
    setCollapsed(next);
    try {
      localStorage.setItem(
        COLLAPSED_FOLDERS_STORAGE_KEY,
        serializeCollapsedFolderIds(next),
      );
    } catch {
      // Folder toggles still work when browser storage is disabled.
    }
  }

  function toggleFolder(key: string) {
    const next = new Set(collapsed);
    if (next.has(key)) next.delete(key);
    else next.add(key);
    storeCollapsed(next);
  }

  async function dropMap(event: DragEvent, key: string, folderId: string | null) {
    event.preventDefault();
    const mapId = event.dataTransfer.getData(MAP_DRAG_TYPE) || draggingMapId;
    setDropTarget(undefined);
    setDraggingMapId(undefined);
    if (!mapId) return;
    const mapping = maps.find((candidate) => candidate.id === mapId);
    if (!mapping || (mapping.folder_id ?? null) === folderId) return;
    if (collapsed.has(key)) {
      const next = new Set(collapsed);
      next.delete(key);
      storeCollapsed(next);
    }
    setMovingMapId(mapId);
    setError("");
    try {
      await onMoveMap(mapId, folderId);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Map could not be moved");
    } finally {
      setMovingMapId(undefined);
    }
  }

  return (
    <aside className="sidebar">
      <header className="sidebar-header">
        <div className="brand-mark">
          <Map size={18} strokeWidth={1.7} />
        </div>
        <div>
          <strong>AERIAL MAPPER</strong>
          <span>LOCAL WORKSTATION</span>
        </div>
      </header>
      <div className="sidebar-create-actions">
        <button className="button primary new-map-button" onClick={onNewMap}>
          <Plus size={15} />
          New map
        </button>
        <button className="button secondary new-folder-button" onClick={onNewFolder}>
          <FolderPlus size={13} />
          New project
        </button>
      </div>
      <div className="map-folders">
        {error && (
          <div className="sidebar-error">
            <AlertTriangle size={13} />
            <span>{error}</span>
            <button onClick={() => setError("")} aria-label="Dismiss sidebar error">
              ×
            </button>
          </div>
        )}
        {groups.map((group) => {
          const isCollapsed = collapsed.has(group.key);
          const isNoProject = group.key === NO_PROJECT_KEY;
          const isDropTarget = dropTarget === group.key;
          return (
            <section
              className={`map-folder ${isDropTarget ? "drop-target" : ""}`}
              key={group.key}
              onDragOver={(event) => {
                if (!draggingMapId) return;
                event.preventDefault();
                event.dataTransfer.dropEffect = "move";
                setDropTarget(group.key);
              }}
              onDragLeave={(event) => {
                if (!event.currentTarget.contains(event.relatedTarget as Node)) {
                  setDropTarget((current) => (current === group.key ? undefined : current));
                }
              }}
              onDrop={(event) =>
                void dropMap(event, group.key, group.folder?.id ?? null)
              }
            >
              <div className="map-folder-header">
                <button
                  className="map-folder-toggle"
                  aria-expanded={!isCollapsed}
                  onClick={() => toggleFolder(group.key)}
                >
                  <ChevronRight
                    className={`folder-caret ${isCollapsed ? "" : "expanded"}`}
                    size={13}
                  />
                  <Folder size={13} />
                  <strong>{group.folder?.name ?? "No Project"}</strong>
                  <span>{group.maps.length}</span>
                </button>
                {group.folder && (
                  <div className="folder-menu-wrap">
                    <button
                      className="folder-menu-button"
                      aria-label={`Actions for ${group.folder.name}`}
                      onClick={() =>
                        setMenuFolderId((current) =>
                          current === group.folder?.id ? undefined : group.folder?.id,
                        )
                      }
                    >
                      <MoreHorizontal size={14} />
                    </button>
                    {menuFolderId === group.folder.id && (
                      <div className="folder-action-menu">
                        <button
                          onClick={() => {
                            setMenuFolderId(undefined);
                            onRenameFolder(group.folder!);
                          }}
                        >
                          <Pencil size={12} /> Rename
                        </button>
                        <button
                          className="danger"
                          onClick={() => {
                            setMenuFolderId(undefined);
                            void onDeleteFolder(group.folder!).catch((reason: unknown) =>
                              setError(
                                reason instanceof Error
                                  ? reason.message
                                  : "Project could not be deleted",
                              ),
                            );
                          }}
                        >
                          <Trash2 size={12} /> Delete
                        </button>
                      </div>
                    )}
                  </div>
                )}
              </div>
              {!isCollapsed && (
                <div className="map-folder-content">
                  {group.maps.map((mapping) => {
                    const displayedProgress =
                      mapping.status === "uploading" &&
                      uploadProgress[mapping.id] !== undefined
                        ? Math.round(uploadProgress[mapping.id] * 100)
                        : Math.round(mapping.progress);
                    const active = ["uploading", "queued", "processing", "splatting"].includes(
                      mapping.status,
                    );
                    return (
                      <button
                        className={`project-row ${selectedId === mapping.id ? "selected" : ""} ${
                          movingMapId === mapping.id ? "moving" : ""
                        }`}
                        key={mapping.id}
                        draggable
                        aria-grabbed={draggingMapId === mapping.id}
                        onClick={() => onSelect(mapping.id)}
                        onDragStart={(event) => {
                          event.dataTransfer.effectAllowed = "move";
                          event.dataTransfer.setData(MAP_DRAG_TYPE, mapping.id);
                          setDraggingMapId(mapping.id);
                          setError("");
                        }}
                        onDragEnd={() => {
                          setDraggingMapId(undefined);
                          setDropTarget(undefined);
                        }}
                      >
                        <span className={`status-glyph ${mapping.status}`}>
                          <ProjectIcon status={mapping.status} />
                        </span>
                        <span className="project-row-copy">
                          <strong>{mapping.name}</strong>
                          <span>
                            {mapping.status === "completed"
                              ? "Completed"
                              : mapping.status === "partial"
                                ? "ODM complete"
                                : `${displayedProgress}% · ${mapping.stage}`}
                          </span>
                          {active && (
                            <span className="sidebar-progress">
                              <i style={{ width: `${displayedProgress}%` }} />
                            </span>
                          )}
                        </span>
                      </button>
                    );
                  })}
                  {!group.maps.length && (
                    <div className="empty-folder">
                      {isNoProject ? "Drop maps here to unassign them" : "Drop maps into this project"}
                    </div>
                  )}
                </div>
              )}
            </section>
          );
        })}
      </div>
      <footer className="sidebar-footer">
        <button onClick={onAbout}>
          <Info size={15} /> About & source
        </button>
        <button aria-label="Sign out" onClick={() => void onLogout()}>
          <LogOut size={15} />
        </button>
      </footer>
    </aside>
  );
}
