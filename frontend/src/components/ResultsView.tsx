import { lazy, Suspense, useEffect, useMemo, useState } from "react";
import {
  Box,
  CheckCircle2,
  Download,
  FileArchive,
  FileText,
  Layers3,
  Map,
  Mountain,
  Sparkles,
} from "lucide-react";
import type { Artifact, Project } from "../types";

const MapViewer = lazy(() =>
  import("../viewers/MapViewer").then((module) => ({ default: module.MapViewer })),
);
const ModelViewer = lazy(() =>
  import("../viewers/ModelViewer").then((module) => ({ default: module.ModelViewer })),
);
const SplatViewer = lazy(() =>
  import("../viewers/SplatViewer").then((module) => ({ default: module.SplatViewer })),
);
const TilesViewer = lazy(() =>
  import("../viewers/TilesViewer").then((module) => ({ default: module.TilesViewer })),
);

const tabs = [
  ["orthomosaic", "ORTHOMOSAIC", Map],
  ["point_cloud", "POINT CLOUD", Layers3],
  ["mesh", "3D MODEL", Box],
  ["splat", "GAUSSIAN SPLAT", Sparkles],
  ["elevation", "ELEVATION", Mountain],
  ["report", "REPORT", FileText],
  ["files", "FILES", FileArchive],
] as const;

function downloadUrl(project: Project, artifact: Artifact) {
  return `/api/projects/${project.id}/artifacts/${artifact.path}`;
}

function find(project: Project, category: string, labelPart?: string) {
  return project.artifacts?.find(
    (artifact) =>
      artifact.category === category &&
      (!labelPart || artifact.label.toLowerCase().includes(labelPart.toLowerCase())),
  );
}

export function ResultsView({ project }: { project: Project }) {
  const availableTabs = useMemo(
    () =>
      tabs.filter(([id]) => {
        if (id === "files") return true;
        if (id === "elevation") {
          return project.outputs.dsm !== false || project.outputs.dtm !== false;
        }
        return project.outputs[id] !== false;
      }),
    [project.outputs],
  );
  const [tab, setTab] = useState<string>(() => availableTabs[0]?.[0] ?? "files");
  const enabledElevationLayers = useMemo(
    () =>
      (["dsm", "dtm"] as const).filter((layer) => project.outputs[layer] !== false),
    [project.outputs],
  );
  const [elevation, setElevation] = useState<"dsm" | "dtm">(
    () => enabledElevationLayers[0] ?? "dsm",
  );
  const stats = useMemo(
    () => [
      ["IMAGES", `${project.inspection.images ?? "—"}`],
      ["CAMERA", project.inspection.camera_model || "—"],
      [
        "REL. ALTITUDE",
        project.inspection.relative_altitude_median != null
          ? `${project.inspection.relative_altitude_median} m`
          : "—",
      ],
      ["GEOREFERENCE", project.gcp_used ? "GCP-assisted" : "Consumer GPS"],
    ],
    [project],
  );

  useEffect(() => {
    if (!availableTabs.some(([id]) => id === tab)) {
      setTab(availableTabs[0]?.[0] ?? "files");
    }
  }, [availableTabs, tab]);

  useEffect(() => {
    if (!enabledElevationLayers.includes(elevation)) {
      setElevation(enabledElevationLayers[0] ?? "dsm");
    }
  }, [elevation, enabledElevationLayers]);

  return (
    <div className="results-view">
      <section className="result-summary">
        <div className="completion-badge">
          <CheckCircle2 size={17} />
          <strong>{project.status === "partial" ? "ODM COMPLETE" : "PROCESSING COMPLETE"}</strong>
          <span>{project.status === "partial" ? "Gaussian splat needs attention" : "All requested products are ready"}</span>
        </div>
        <div className="result-stats">
          {stats.map(([label, value]) => (
            <div key={label}>
              <span>{label}</span>
              <strong>{value}</strong>
            </div>
          ))}
        </div>
      </section>
      <nav className="result-tabs" aria-label="Project outputs">
        {availableTabs.map(([id, label, Icon]) => (
          <button className={tab === id ? "active" : ""} key={id} onClick={() => setTab(id)}>
            <Icon size={14} />
            {label}
          </button>
        ))}
      </nav>
      <section className="viewer-frame">
        <Suspense fallback={<div className="viewer-loading">LOADING VIEWER…</div>}>
          {tab === "orthomosaic" && <MapViewer projectId={project.id} layer="orthomosaic" />}
          {tab === "point_cloud" && (
            <ArtifactState
              project={project}
              artifact={
                find(project, "point_cloud", "Potree") ??
                find(project, "point_cloud", "3D Tiles")
              }
            >
              {(artifact) =>
                artifact.viewer === "tiles3d" ? (
                  <TilesViewer url={downloadUrl(project, artifact)} />
                ) : (
                  <iframe
                    className="artifact-iframe"
                    title="Potree point cloud"
                    src={downloadUrl(project, artifact)}
                  />
                )
              }
            </ArtifactState>
          )}
          {tab === "mesh" && (
            <ArtifactState
              project={project}
              artifact={find(project, "mesh", "GLB") ?? find(project, "mesh", "3D Tiles")}
            >
              {(artifact) =>
                artifact.viewer === "tiles3d" ? (
                  <TilesViewer url={downloadUrl(project, artifact)} />
                ) : (
                  <ModelViewer url={downloadUrl(project, artifact)} />
                )
              }
            </ArtifactState>
          )}
          {tab === "splat" && (
            <ArtifactState
              project={project}
              artifact={find(project, "splat", "SPZ") ?? find(project, "splat", "PLY")}
              partialText="ODM products are safe. Retry only the Gaussian splat stage."
            >
              {(artifact) => <SplatViewer url={downloadUrl(project, artifact)} />}
            </ArtifactState>
          )}
          {tab === "elevation" && (
            <div className="elevation-view">
              <div className="viewer-subtabs">
                {project.outputs.dsm !== false && (
                  <button className={elevation === "dsm" ? "active" : ""} onClick={() => setElevation("dsm")}>
                    DSM · SURFACE
                  </button>
                )}
                {project.outputs.dtm !== false && (
                  <button className={elevation === "dtm" ? "active" : ""} onClick={() => setElevation("dtm")}>
                    DTM · TERRAIN
                  </button>
                )}
              </div>
              <MapViewer projectId={project.id} layer={elevation} />
            </div>
          )}
          {tab === "report" && (
            <ArtifactState project={project} artifact={find(project, "report")}>
              {(artifact) => (
                <iframe
                  className="artifact-iframe report"
                  title="ODM quality report"
                  src={downloadUrl(project, artifact)}
                />
              )}
            </ArtifactState>
          )}
          {tab === "files" && <FileBrowser project={project} />}
        </Suspense>
      </section>
      <footer className="accuracy-footer">
        <span className="accuracy-dot" />
        <strong>{project.inspection.accuracy?.label ?? "Accuracy pending"}</strong>
        <span>
          {project.inspection.accuracy?.detail ??
            "Inspect the quality report before relying on measurements."}
        </span>
      </footer>
    </div>
  );
}

function ArtifactState({
  project,
  artifact,
  partialText,
  children,
}: {
  project: Project;
  artifact?: Artifact;
  partialText?: string;
  children: (artifact: Artifact) => React.ReactNode;
}) {
  if (artifact) return children(artifact);
  return (
    <div className="artifact-empty">
      <FileArchive size={34} strokeWidth={1.25} />
      <strong>This output is not available</strong>
      <span>{project.status === "partial" ? partialText : "It may have been disabled for this project."}</span>
    </div>
  );
}

function FileBrowser({ project }: { project: Project }) {
  const artifacts = project.artifacts ?? [];
  return (
    <div className="file-browser">
      <header>
        <div>
          <p className="eyebrow">ALLOWLISTED OUTPUTS</p>
          <h3>Project artifacts</h3>
        </div>
        <span>{artifacts.length} downloadable files</span>
      </header>
      <div className="file-list">
        {artifacts.map((artifact) => (
          <a href={downloadUrl(project, artifact)} key={artifact.id} download>
            <FileArchive size={15} />
            <span>
              <strong>{artifact.label}</strong>
              <small>{artifact.path}</small>
            </span>
            <em>{formatBytes(artifact.size)}</em>
            <Download size={14} />
          </a>
        ))}
        {!artifacts.length && <div className="file-list-empty">No discovered artifacts yet.</div>}
      </div>
    </div>
  );
}

function formatBytes(value: number) {
  if (value > 1024 ** 3) return `${(value / 1024 ** 3).toFixed(1)} GB`;
  if (value > 1024 ** 2) return `${(value / 1024 ** 2).toFixed(1)} MB`;
  if (value > 1024) return `${(value / 1024).toFixed(1)} KB`;
  return `${value} B`;
}
