import {
  AlertTriangle,
  Check,
  CircleDot,
  Info,
  Map,
  MoreHorizontal,
  Plus,
  Radio,
  Settings,
} from "lucide-react";
import type { Project, ProjectStatus } from "../types";

interface Props {
  projects: Project[];
  selectedId?: string;
  onSelect: (id: string) => void;
  onNew: () => void;
  onAbout: () => void;
}

const groups: { label: string; statuses: ProjectStatus[] }[] = [
  { label: "PROCESSING", statuses: ["uploading", "queued", "processing", "splatting"] },
  { label: "COMPLETED", statuses: ["completed", "partial"] },
  { label: "ATTENTION", statuses: ["failed", "canceled"] },
];

function ProjectIcon({ status }: { status: ProjectStatus }) {
  if (status === "completed") return <Check size={13} />;
  if (status === "partial" || status === "failed") return <AlertTriangle size={13} />;
  if (status === "canceled") return <CircleDot size={13} />;
  return <Radio size={13} />;
}

export function Sidebar({ projects, selectedId, onSelect, onNew, onAbout }: Props) {
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
      <button className="button primary new-project-button" onClick={onNew}>
        <Plus size={15} />
        New project
      </button>
      <div className="project-groups">
        {groups.map((group) => {
          const items = projects.filter((project) => group.statuses.includes(project.status));
          if (!items.length) return null;
          return (
            <section className="project-group" key={group.label}>
              <h2>{group.label}</h2>
              {items.map((project) => (
                <button
                  className={`project-row ${selectedId === project.id ? "selected" : ""}`}
                  key={project.id}
                  onClick={() => onSelect(project.id)}
                >
                  <span className={`status-glyph ${project.status}`}>
                    <ProjectIcon status={project.status} />
                  </span>
                  <span className="project-row-copy">
                    <strong>{project.name}</strong>
                    <span>
                      {project.status === "completed"
                        ? "Completed"
                        : project.status === "partial"
                          ? "ODM complete"
                          : `${Math.round(project.progress)}% · ${project.stage}`}
                    </span>
                    {["uploading", "queued", "processing", "splatting"].includes(project.status) && (
                      <span className="sidebar-progress">
                        <i style={{ width: `${project.progress}%` }} />
                      </span>
                    )}
                  </span>
                  <MoreHorizontal className="row-more" size={15} />
                </button>
              ))}
            </section>
          );
        })}
        {!projects.length && (
          <div className="empty-sidebar">
            <CircleDot size={18} />
            <span>No mapping projects yet.</span>
          </div>
        )}
      </div>
      <footer className="sidebar-footer">
        <button onClick={onAbout}>
          <Info size={15} /> About & source
        </button>
        <button aria-label="Application settings">
          <Settings size={15} />
        </button>
      </footer>
    </aside>
  );
}
