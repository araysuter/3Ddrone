import { useCallback, useEffect, useMemo, useState } from "react";
import { api, ApiError, uploadFiles } from "./lib/api";
import type { Project, SystemMetrics } from "./types";
import { AboutDialog } from "./components/AboutDialog";
import { AuthScreen } from "./components/AuthScreen";
import { NewProjectDialog } from "./components/NewProjectDialog";
import { Sidebar } from "./components/Sidebar";
import { Workspace } from "./components/Workspace";

type AuthState = "loading" | "setup" | "login" | "ready";

export default function App() {
  const [auth, setAuth] = useState<AuthState>("loading");
  const [projects, setProjects] = useState<Project[]>([]);
  const [selectedId, setSelectedId] = useState<string>();
  const [newProjectOpen, setNewProjectOpen] = useState(false);
  const [reprocessProjectId, setReprocessProjectId] = useState<string>();
  const [aboutOpen, setAboutOpen] = useState(false);
  const [creating, setCreating] = useState(false);
  const [reprocessing, setReprocessing] = useState(false);
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

  const refresh = useCallback(async () => {
    const list = await api.listProjects();
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
      });
      createdProject = project;
      setProjects((current) => [project, ...current]);
      setSelectedId(project.id);
      setNewProjectOpen(false);
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
  }) {
    if (!reprocessProject) return;
    setReprocessing(true);
    try {
      const updated = await api.reprocessProject(reprocessProject.id, payload);
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

  if (auth === "loading") {
    return <div className="boot-screen">STARTING LOCAL MAPPER…</div>;
  }
  if (auth === "setup" || auth === "login") {
    return <AuthScreen setupRequired={auth === "setup"} onAuthenticated={authenticated} />;
  }

  return (
    <div className="app-shell">
      <Sidebar
        projects={projects}
        selectedId={selectedId}
        onSelect={setSelectedId}
        onNew={() => setNewProjectOpen(true)}
        onAbout={() => setAboutOpen(true)}
        onLogout={logout}
        uploadProgress={uploadProgress}
      />
      <Workspace
        project={selected}
        logs={selected ? logs[selected.id] ?? [] : []}
        uploadProgress={selected ? uploadProgress[selected.id] : undefined}
        metrics={metrics}
        onChanged={refresh}
        onResumeUploads={resumeUploads}
        onReprocess={(project) => setReprocessProjectId(project.id)}
      />
      <NewProjectDialog
        open={newProjectOpen}
        busy={creating}
        onClose={() => !creating && setNewProjectOpen(false)}
        onSubmit={createProject}
      />
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
      <AboutDialog open={aboutOpen} onClose={() => setAboutOpen(false)} />
    </div>
  );
}
