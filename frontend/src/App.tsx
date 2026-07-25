import { useCallback, useEffect, useMemo, useState } from "react";
import { api, ApiError, uploadFiles } from "./lib/api";
import type { MapFolder, Project, SystemMetrics } from "./types";
import { AboutDialog } from "./components/AboutDialog";
import { AuthScreen } from "./components/AuthScreen";
import { NewProjectDialog } from "./components/NewProjectDialog";
import { ProjectFolderDialog } from "./components/ProjectFolderDialog";
import { Sidebar } from "./components/Sidebar";
import { Workspace } from "./components/Workspace";

type AuthState = "loading" | "setup" | "login" | "ready";

export default function App() {
  const [auth, setAuth] = useState<AuthState>("loading");
  const [projects, setProjects] = useState<Project[]>([]);
  const [folders, setFolders] = useState<MapFolder[]>([]);
  const [selectedId, setSelectedId] = useState<string>();
  const [newMapOpen, setNewMapOpen] = useState(false);
  const [reprocessProjectId, setReprocessProjectId] = useState<string>();
  const [folderDialog, setFolderDialog] = useState<{
    mode: "create" | "rename";
    folder?: MapFolder;
  }>();
  const [aboutOpen, setAboutOpen] = useState(false);
  const [creating, setCreating] = useState(false);
  const [reprocessing, setReprocessing] = useState(false);
  const [savingFolder, setSavingFolder] = useState(false);
  const [logs, setLogs] = useState<Record<string, string[]>>({});
  const [uploadProgress, setUploadProgress] = useState<Record<string, number>>({});
  const [metrics, setMetrics] = useState<SystemMetrics>();

  const selected = useMemo(
    () => projects.find((project) => project.id === selectedId),
    [projects, selectedId],
  );
  const reprocessProject = useMemo(
    () => projects.find((project) => project.id === reprocessProjectId),
    [projects, reprocessProjectId],
  );
  const folderNames = useMemo(
    () => new Map(folders.map((folder) => [folder.id, folder.name])),
    [folders],
  );

  const refresh = useCallback(async () => {
    const [list, folderList] = await Promise.all([api.listProjects(), api.listFolders()]);
    setFolders(folderList);
    setProjects((current) =>
      list.map((project) => {
        const existing = current.find((candidate) => candidate.id === project.id);
        return existing ? { ...existing, ...project } : project;
      }),
    );
    setSelectedId((current) => current ?? list[0]?.id);
    if (selectedId) {
      try {
        const detail = await api.getProject(selectedId);
        setProjects((current) => current.map((project) => (project.id === detail.id ? detail : project)));
      } catch (reason) {
        if (reason instanceof ApiError && reason.status === 404) {
          setSelectedId(list[0]?.id);
        }
      }
    }
  }, [selectedId]);

  useEffect(() => {
    (async () => {
      const setup = await api.setupStatus();
      if (setup.required) {
        setAuth("setup");
        return;
      }
      try {
        await api.session();
        setAuth("ready");
      } catch {
        setAuth("login");
      }
    })().catch(() => setAuth("login"));
  }, []);

  useEffect(() => {
    const unauthorized = () => {
      setAuth("login");
      setProjects([]);
      setFolders([]);
      setSelectedId(undefined);
    };
    window.addEventListener("mapper:unauthorized", unauthorized);
    return () => window.removeEventListener("mapper:unauthorized", unauthorized);
  }, []);

  useEffect(() => {
    if (auth !== "ready") return;
    refresh().catch(console.error);
    api.system().then(setMetrics).catch(console.error);
    const interval = window.setInterval(() => {
      refresh().catch(console.error);
      api.system().then(setMetrics).catch(console.error);
    }, 5000);
    return () => window.clearInterval(interval);
  }, [auth, refresh]);

  useEffect(() => {
    if (!selectedId || auth !== "ready") return;
    const stream = new EventSource(`/api/projects/${selectedId}/events`);
    const addLog = (event: MessageEvent) => {
      const payload = JSON.parse(event.data);
      const lines = payload.lines ?? [];
      setLogs((current) => ({
        ...current,
        [selectedId]: [...(current[selectedId] ?? []), ...lines].slice(-500),
      }));
    };
    const changed = () => refresh().catch(console.error);
    stream.addEventListener("log", addLog);
    stream.addEventListener("splat", addLog);
    stream.addEventListener("state", changed);
    stream.addEventListener("progress", changed);
    stream.addEventListener("artifacts", changed);
    return () => stream.close();
  }, [selectedId, auth, refresh]);

  async function authenticated() {
    setAuth("ready");
    await refresh();
  }

  async function createProject(payload: {
    name: string;
    preset: string;
    outputs: Record<string, boolean>;
    advanced: Record<string, unknown>;
    folder_id: string | null;
    files: File[];
  }) {
    setCreating(true);
    let createdProject: Project | undefined;
    try {
      const project = await api.createProject({
        name: payload.name,
        preset: payload.preset,
        outputs: payload.outputs,
        advanced: payload.advanced,
        folder_id: payload.folder_id,
      });
      createdProject = project;
      setProjects((current) => [project, ...current]);
      setSelectedId(project.id);
      setNewMapOpen(false);
      const progressByFile = new Map<string, number>();
      await uploadFiles(project.id, payload.files, (file, progress) => {
        progressByFile.set(`${file.name}:${file.size}`, progress);
        const total = [...progressByFile.values()].reduce((sum, value) => sum + value, 0);
        setUploadProgress((current) => ({ ...current, [project.id]: total / payload.files.length }));
      });
      await api.inspectProject(project.id);
      await api.startProject(project.id);
      setUploadProgress((current) => {
        const next = { ...current };
        delete next[project.id];
        return next;
      });
      await refresh();
    } catch (reason) {
      const message = reason instanceof Error ? reason.message : "Upload failed";
      if (!createdProject) throw reason;
      const failedProjectId = createdProject.id;
      setUploadProgress((current) => {
        const next = { ...current };
        delete next[failedProjectId];
        return next;
      });
      setLogs((current) => ({
        ...current,
        [failedProjectId]: [
          ...(current[failedProjectId] ?? []),
          `[upload] ${message}`,
          "[upload] Use Resume upload in this project and re-select the original files.",
        ].slice(-500),
      }));
      await refresh().catch(() => undefined);
    } finally {
      setCreating(false);
    }
  }

  async function reprocessExistingProject(payload: {
    name: string;
    preset: string;
    outputs: Record<string, boolean>;
    advanced: Record<string, unknown>;
    folder_id: string | null;
  }) {
    if (!reprocessProject) return;
    setReprocessing(true);
    try {
      const updated = await api.reprocessProject(reprocessProject.id, {
        name: payload.name,
        preset: payload.preset,
        outputs: payload.outputs,
        advanced: payload.advanced,
      });
      setProjects((current) =>
        current.map((project) => (project.id === updated.id ? updated : project)),
      );
      setSelectedId(updated.id);
      setReprocessProjectId(undefined);
      await refresh();
    } finally {
      setReprocessing(false);
    }
  }

  async function logout() {
    try {
      await api.logout();
    } finally {
      setAuth("login");
      setProjects([]);
      setFolders([]);
      setSelectedId(undefined);
    }
  }

  async function resumeUploads(project: Project, files: File[]) {
    const completed = new Set(
      (project.uploads ?? [])
        .filter((upload) => upload.state === "complete")
        .map((upload) => `${upload.filename}:${upload.size}`),
    );
    const remaining = files.filter((file) => !completed.has(`${file.name}:${file.size}`));
    if (!remaining.length) throw new Error("Select at least one incomplete or rejected source file");
    const progressByFile = new Map<string, number>();
    try {
      await uploadFiles(project.id, remaining, (file, progress) => {
        progressByFile.set(`${file.name}:${file.size}`, progress);
        const total = [...progressByFile.values()].reduce((sum, value) => sum + value, 0);
        setUploadProgress((current) => ({ ...current, [project.id]: total / remaining.length }));
      });
      await api.inspectProject(project.id);
      await api.startProject(project.id);
      await refresh();
    } finally {
      setUploadProgress((current) => {
        const next = { ...current };
        delete next[project.id];
        return next;
      });
    }
  }

  async function saveFolder(name: string) {
    if (!folderDialog) return;
    setSavingFolder(true);
    try {
      const saved =
        folderDialog.mode === "rename" && folderDialog.folder
          ? await api.renameFolder(folderDialog.folder.id, name)
          : await api.createFolder(name);
      setFolders((current) => {
        const exists = current.some((folder) => folder.id === saved.id);
        return exists
          ? current.map((folder) => (folder.id === saved.id ? saved : folder))
          : [...current, saved];
      });
      setFolderDialog(undefined);
    } finally {
      setSavingFolder(false);
    }
  }

  async function deleteFolder(folder: MapFolder) {
    const count = projects.filter((project) => project.folder_id === folder.id).length;
    if (
      !window.confirm(
        `Delete project “${folder.name}”? ${count} map${count === 1 ? "" : "s"} will move to No Project. No map data will be deleted.`,
      )
    ) {
      return;
    }
    await api.deleteFolder(folder);
    setFolders((current) => current.filter((candidate) => candidate.id !== folder.id));
    setProjects((current) =>
      current.map((project) =>
        project.folder_id === folder.id ? { ...project, folder_id: null } : project,
      ),
    );
  }

  async function moveMap(mapId: string, folderId: string | null) {
    const previous = projects.find((project) => project.id === mapId);
    if (!previous) throw new Error("Map no longer exists");
    setProjects((current) =>
      current.map((project) =>
        project.id === mapId ? { ...project, folder_id: folderId } : project,
      ),
    );
    try {
      const updated = await api.assignProjectFolder(mapId, folderId);
      setProjects((current) =>
        current.map((project) => (project.id === mapId ? { ...project, ...updated } : project)),
      );
    } catch (reason) {
      setProjects((current) =>
        current.map((project) => (project.id === mapId ? previous : project)),
      );
      throw reason;
    }
  }

  if (auth === "loading") {
    return <div className="boot-screen">STARTING LOCAL MAPPER…</div>;
  }
  if (auth === "setup" || auth === "login") {
    return <AuthScreen setupRequired={auth === "setup"} onAuthenticated={authenticated} />;
  }

  return (
    <div className="app-shell">
      <Sidebar
        maps={projects}
        folders={folders}
        selectedId={selectedId}
        onSelect={setSelectedId}
        onNewMap={() => setNewMapOpen(true)}
        onNewFolder={() => setFolderDialog({ mode: "create" })}
        onRenameFolder={(folder) => setFolderDialog({ mode: "rename", folder })}
        onDeleteFolder={deleteFolder}
        onMoveMap={moveMap}
        onAbout={() => setAboutOpen(true)}
        onLogout={logout}
        uploadProgress={uploadProgress}
      />
      <Workspace
        project={selected}
        logs={selected ? logs[selected.id] ?? [] : []}
        uploadProgress={selected ? uploadProgress[selected.id] : undefined}
        metrics={metrics}
        folderName={selected?.folder_id ? folderNames.get(selected.folder_id) : undefined}
        onChanged={refresh}
        onResumeUploads={resumeUploads}
        onReprocess={(project) => setReprocessProjectId(project.id)}
      />
      {newMapOpen && (
        <NewProjectDialog
          open
          folders={folders}
          defaultFolderId={selected?.folder_id ?? null}
          busy={creating}
          onClose={() => !creating && setNewMapOpen(false)}
          onSubmit={createProject}
        />
      )}
      {reprocessProject && (
        <NewProjectDialog
          key={reprocessProject.id}
          open
          mode="reprocess"
          initialProject={reprocessProject}
          busy={reprocessing}
          onClose={() => !reprocessing && setReprocessProjectId(undefined)}
          onSubmit={reprocessExistingProject}
        />
      )}
      {folderDialog && (
        <ProjectFolderDialog
          key={`${folderDialog.mode}:${folderDialog.folder?.id ?? "new"}`}
          mode={folderDialog.mode}
          initialName={folderDialog.folder?.name}
          busy={savingFolder}
          onClose={() => !savingFolder && setFolderDialog(undefined)}
          onSubmit={saveFolder}
        />
      )}
      <AboutDialog open={aboutOpen} onClose={() => setAboutOpen(false)} />
    </div>
  );
}
