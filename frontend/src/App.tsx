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
  const [aboutOpen, setAboutOpen] = useState(false);
  const [creating, setCreating] = useState(false);
  const [logs, setLogs] = useState<Record<string, string[]>>({});
  const [uploadProgress, setUploadProgress] = useState<Record<string, number>>({});
  const [metrics, setMetrics] = useState<SystemMetrics>();

  const selected = useMemo(
    () => projects.find((project) => project.id === selectedId),
    [projects, selectedId],
  );

  const refresh = useCallback(async () => {
    const list = await api.listProjects();
    setProjects(list);
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
    files: File[];
  }) {
    setCreating(true);
    try {
      const project = await api.createProject(payload);
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
      await refresh();
    } finally {
      setCreating(false);
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
      />
      <Workspace
        project={selected}
        logs={selected ? logs[selected.id] ?? [] : []}
        uploadProgress={selected ? uploadProgress[selected.id] : undefined}
        metrics={metrics}
        onChanged={refresh}
      />
      <NewProjectDialog
        open={newProjectOpen}
        busy={creating}
        onClose={() => !creating && setNewProjectOpen(false)}
        onCreate={createProject}
      />
      <AboutDialog open={aboutOpen} onClose={() => setAboutOpen(false)} />
    </div>
  );
}
