import {
  AlertTriangle,
  Box,
  MoreVertical,
  Pencil,
  Play,
  RotateCcw,
  Settings2,
  Share2,
  Square,
  Trash2,
} from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { api } from "../lib/api";
import type { Project, ResultsProject, ShareStatus, SystemMetrics } from "../types";
import { ProcessingView } from "./ProcessingView";
import { ResultsView } from "./ResultsView";
import { ShareDialog } from "./ShareDialog";

interface Props {
  project?: Project;
  logs: string[];
  uploadProgress?: number;
  metrics?: SystemMetrics;
  folderName?: string;
  onChanged: () => Promise<void>;
  onResumeUploads: (project: Project, files: File[]) => Promise<void>;
  onRename: (project: Project) => void;
  onReprocess: (project: Project) => void;
}

export function Workspace({
  project,
  logs,
  uploadProgress,
  metrics,
  folderName,
  onChanged,
  onResumeUploads,
  onRename,
  onReprocess,
}: Props) {
  const [menu, setMenu] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [shareOpen, setShareOpen] = useState(false);
  const [shareStatus, setShareStatus] = useState<ShareStatus>();
  const resumeInput = useRef<HTMLInputElement>(null);
  const projectId = project?.id;
  const projectStatus = project?.status;

  useEffect(() => {
    let disposed = false;
    setShareOpen(false);
    setShareStatus(undefined);
    if (!projectId) return;
    void api
      .shareStatus(projectId)
      .then((status) => {
        if (!disposed) setShareStatus(status);
      })
      .catch(() => {
        if (!disposed) setShareStatus({ configured: false, share: null });
      });
    return () => {
      disposed = true;
    };
  }, [projectId, projectStatus]);

  if (!project) {
    return (
      <main className="workspace empty-workspace">
        <div>
          <Box size={44} strokeWidth={1.1} />
          <p className="eyebrow">LOCAL CUDA PIPELINE</p>
          <h1>Ready for a new aerial dataset</h1>
          <p>Create a map from the sidebar to upload imagery and begin reconstruction.</p>
        </div>
      </main>
    );
  }

  const currentProject = project;
  const isActive = ["queued", "processing", "splatting"].includes(project.status);
  const hasResults = ["completed", "partial"].includes(project.status);
  const canReprocess =
    ["completed", "partial", "failed", "canceled"].includes(project.status) &&
    project.uploads?.some(
      (upload) => upload.state === "complete" && ["image", "video"].includes(upload.kind),
    );
  const needsUploadRecovery =
    ["uploading", "failed", "canceled"].includes(project.status) &&
    uploadProgress === undefined &&
    (!project.uploads?.length || project.uploads.some((upload) => upload.state !== "complete"));

  async function action(callback: () => Promise<unknown>) {
    setBusy(true);
    setError("");
    try {
      await callback();
      await onChanged();
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Action failed");
    } finally {
      setBusy(false);
      setMenu(false);
    }
  }

  async function remove() {
    if (!window.confirm(`Permanently delete map “${currentProject.name}” and all retained data?`)) return;
    await action(() => api.deleteProject(currentProject));
  }

  return (
    <main className="workspace">
      <header className="workspace-header">
        <div className="workspace-title">
          <p className="eyebrow">{folderName?.toUpperCase() ?? "NO PROJECT"}</p>
          <div>
            <h1>{project.name}</h1>
            <span className="preset-badge">{project.preset.toUpperCase()}</span>
            {project.inspection.camera_model && (
              <span className="camera-badge">{project.inspection.camera_model}</span>
            )}
          </div>
        </div>
        <div className="workspace-actions">
          <input
            ref={resumeInput}
            hidden
            type="file"
            multiple
            accept=".jpg,.jpeg,.dng,.tif,.tiff,.mp4,.mov,.lrv,.ts,.srt,.lchm,.txt,.las,.laz"
            onChange={(event) => {
              const files = Array.from(event.target.files ?? []);
              event.target.value = "";
              if (files.length) void action(() => onResumeUploads(currentProject, files));
            }}
          />
          {needsUploadRecovery && (
            <button
              className="button primary"
              disabled={busy}
              onClick={() => resumeInput.current?.click()}
            >
              <Play size={14} /> Resume upload
            </button>
          )}
          {isActive && (
            <button className="button secondary danger-text" disabled={busy} onClick={() => action(() => api.cancelProject(project.id))}>
              <Square size={13} /> Cancel
            </button>
          )}
          {project.status === "partial" && (
            <button className="button primary" disabled={busy} onClick={() => action(() => api.retrySplat(project.id))}>
              <RotateCcw size={14} /> Retry splat
            </button>
          )}
          {["uploading", "failed", "canceled"].includes(project.status) &&
            !project.uploads?.some((upload) => upload.state === "uploading") &&
            project.uploads?.some((upload) => upload.state === "complete") && (
            <button className="button primary" disabled={busy} onClick={() => action(() => api.startProject(project.id))}>
              <Play size={14} /> Start processing
            </button>
          )}
          <div className="menu-wrap">
            <button className="icon-button" onClick={() => setMenu((value) => !value)} aria-label="Map actions">
              <MoreVertical size={17} />
            </button>
            {menu && (
              <div className="action-menu">
                <button
                  onClick={() => {
                    setMenu(false);
                    onRename(currentProject);
                  }}
                >
                  <Pencil size={14} /> Rename map
                </button>
                {canReprocess && (
                  <button
                    onClick={() => {
                      setMenu(false);
                      onReprocess(currentProject);
                    }}
                  >
                    <Settings2 size={14} /> Reprocess with different settings
                  </button>
                )}
                {shareStatus?.share && (
                  <button
                    onClick={() => {
                      setMenu(false);
                      setShareOpen(true);
                    }}
                  >
                    <Share2 size={14} /> Manage public share
                  </button>
                )}
                <button className="danger" onClick={remove}>
                  <Trash2 size={14} /> Delete map
                </button>
              </div>
            )}
          </div>
        </div>
      </header>
      {error && (
        <div className="workspace-error">
          <AlertTriangle size={15} /> {error}
        </div>
      )}
      {project.status === "partial" && (
        <div className="partial-banner">
          <AlertTriangle size={15} />
          <strong>ODM products completed successfully.</strong>
          <span>{project.error || "Only the Gaussian splat stage needs attention."}</span>
        </div>
      )}
      {hasResults ? (
        <ResultsView
          project={project as ResultsProject}
          onShare={
            shareStatus?.configured
              ? () => setShareOpen(true)
              : undefined
          }
        />
      ) : (
        <ProcessingView
          project={project}
          logLines={logs}
          uploadProgress={uploadProgress}
          metrics={metrics}
        />
      )}
      {shareOpen && shareStatus && (
        <ShareDialog
          project={project}
          status={shareStatus}
          onStatus={setShareStatus}
          onClose={() => setShareOpen(false)}
        />
      )}
    </main>
  );
}
