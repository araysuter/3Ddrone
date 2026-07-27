import { lazy, Suspense, useEffect, useMemo, useState } from "react";
import {
  Box,
  CheckCircle2,
  Download,
  FileArchive,
  FileText,
  Info,
  Layers3,
  Map,
  Mountain,
  Share2,
  Sparkles,
} from "lucide-react";
import {
  findArtifact,
  selectMeshArtifacts,
  selectPointCloudArtifacts,
  selectSplatArtifacts,
} from "../lib/artifacts";
import { artifactResourcePath } from "../lib/publicShare";
import type { Artifact, ResultsProject } from "../types";

const loadMapViewer = () =>
  import("../viewers/MapViewer").then((module) => ({
    default: module.MapViewer,
  }));
const loadModelViewer = () =>
  import("../viewers/ModelViewer").then((module) => ({
    default: module.ModelViewer,
  }));
const loadPointCloudViewer = () =>
  import("../viewers/PointCloudViewer").then((module) => ({
    default: module.PointCloudViewer,
  }));
const loadEptPointCloudViewer = () =>
  import("../viewers/EptPointCloudViewer").then((module) => ({
    default: module.EptPointCloudViewer,
  }));
const loadSplatViewer = () =>
  import("../viewers/SplatViewer").then((module) => ({
    default: module.SplatViewer,
  }));
const loadTilesViewer = () =>
  import("../viewers/TilesViewer").then((module) => ({
    default: module.TilesViewer,
  }));

const MapViewer = lazy(loadMapViewer);
const ModelViewer = lazy(loadModelViewer);
const PointCloudViewer = lazy(loadPointCloudViewer);
const EptPointCloudViewer = lazy(loadEptPointCloudViewer);
const SplatViewer = lazy(loadSplatViewer);
const TilesViewer = lazy(loadTilesViewer);

const tabs = [
  ["orthomosaic", "ORTHOMOSAIC", Map],
  ["point_cloud", "POINT CLOUD", Layers3],
  ["mesh", "3D MODEL", Box],
  ["splat", "GAUSSIAN SPLAT", Sparkles],
  ["elevation", "ELEVATION", Mountain],
  ["report", "REPORT", FileText],
  ["files", "FILES", FileArchive],
] as const;

function artifactResourceUrl(
  project: ResultsProject,
  artifact: Artifact,
  publicResourceBase?: string,
) {
  const base = publicResourceBase ?? `/api/projects/${project.id}`;
  return artifactResourcePath(base, artifact.path);
}

function find(project: ResultsProject, category: string, labelPart?: string) {
  return findArtifact(project.artifacts, category, labelPart);
}

function renderPointCloudArtifact(
  project: ResultsProject,
  artifact: Artifact,
  publicResourceBase?: string,
  fallback?: Artifact,
  finalFallback?: Artifact,
) {
  const artifactUrl = artifactResourceUrl(
    project,
    artifact,
    publicResourceBase,
  );
  if (artifact.viewer === "tiles3d") {
    return (
      <TilesViewer
        allowAboveGroundOrbit
        fallback={
          fallback
            ? renderPointCloudArtifact(
                project,
                fallback,
                publicResourceBase,
                finalFallback,
              )
            : undefined
        }
        loadingLabel="POINT CLOUD"
        url={artifactUrl}
      />
    );
  }
  if (artifact.label.toLowerCase().includes("ept")) {
    return (
      <EptPointCloudViewer
        fallbackUrl={
          fallback
            ? artifactResourceUrl(project, fallback, publicResourceBase)
            : undefined
        }
        url={artifactUrl}
      />
    );
  }
  if (artifact.label.toLowerCase().includes("laz")) {
    return <PointCloudViewer url={artifactUrl} />;
  }
  return (
    <iframe
      className="artifact-iframe"
      title="Potree point cloud"
      src={artifactUrl}
    />
  );
}

function renderMeshArtifact(
  project: ResultsProject,
  artifact: Artifact,
  publicResourceBase?: string,
  fallback?: Artifact,
  finalFallback?: Artifact,
) {
  if (artifact.viewer === "tiles3d") {
    return (
      <TilesViewer
        fallback={
          fallback ? (
            <ModelViewer
              url={artifactResourceUrl(project, fallback, publicResourceBase)}
              fallbackUrl={
                finalFallback
                  ? artifactResourceUrl(
                      project,
                      finalFallback,
                      publicResourceBase,
                    )
                  : undefined
              }
            />
          ) : undefined
        }
        loadingLabel="3D MODEL"
        url={artifactResourceUrl(project, artifact, publicResourceBase)}
      />
    );
  }
  return (
    <ModelViewer
      url={artifactResourceUrl(project, artifact, publicResourceBase)}
      fallbackUrl={
        fallback
          ? artifactResourceUrl(project, fallback, publicResourceBase)
          : undefined
      }
    />
  );
}

export function ResultsView({
  project,
  publicResourceBase,
  onShare,
  onAbout,
}: {
  project: ResultsProject;
  publicResourceBase?: string;
  onShare?: () => void;
  onAbout?: () => void;
}) {
  const shared = Boolean(publicResourceBase);
  const resourceBase = publicResourceBase ?? `/api/projects/${project.id}`;
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
  const meshArtifacts = selectMeshArtifacts(project.artifacts);
  const pointCloudArtifacts = selectPointCloudArtifacts(project.artifacts);
  const splatArtifacts = selectSplatArtifacts(project.artifacts);
  const preloadViewer = (tabId: string) => {
    if (typeof window === "undefined") return;
    if (tabId === "orthomosaic" || tabId === "elevation") {
      void loadMapViewer();
    } else if (tabId === "point_cloud") {
      const primary = pointCloudArtifacts.primary;
      if (primary?.viewer === "tiles3d") void loadTilesViewer();
      else if (primary?.label.toLowerCase().includes("ept")) {
        void loadEptPointCloudViewer();
      } else if (primary?.label.toLowerCase().includes("laz")) {
        void loadPointCloudViewer();
      }
    } else if (tabId === "mesh") {
      if (meshArtifacts.primary?.viewer === "tiles3d") void loadTilesViewer();
      else void loadModelViewer();
    } else if (tabId === "splat") {
      void loadSplatViewer();
    }
  };
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
      <section className={`result-summary${shared ? " shared-summary" : ""}`}>
        {!shared && <div className="completion-badge">
          <CheckCircle2 size={17} />
          <strong>{project.status === "partial" ? "ODM COMPLETE" : "PROCESSING COMPLETE"}</strong>
          <span>{project.status === "partial" ? "Gaussian splat needs attention" : "All requested products are ready"}</span>
        </div>}
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
          <button
            className={tab === id ? "active" : ""}
            key={id}
            onClick={() => setTab(id)}
            onFocus={() => preloadViewer(id)}
            onMouseEnter={() => preloadViewer(id)}
          >
            <Icon size={14} />
            {label}
          </button>
        ))}
        {!shared && onShare && (
          <button className="share-tab-button" onClick={onShare}>
            <Share2 size={14} />
            SHARE
          </button>
        )}
      </nav>
      <section className="viewer-frame">
        <Suspense fallback={<div className="viewer-loading">LOADING VIEWER…</div>}>
          {tab === "orthomosaic" && (
            <MapViewer resourceBase={resourceBase} layer="orthomosaic" />
          )}
          {tab === "point_cloud" && (
            <ArtifactState
              project={project}
              artifact={pointCloudArtifacts.primary}
              shared={shared}
            >
              {(artifact) =>
                renderPointCloudArtifact(
                  project,
                  artifact,
                  publicResourceBase,
                  pointCloudArtifacts.fallback,
                  pointCloudArtifacts.downloadFallback,
                )
              }
            </ArtifactState>
          )}
          {tab === "mesh" && (
            <ArtifactState
              project={project}
              artifact={meshArtifacts.primary}
              shared={shared}
            >
              {(artifact) =>
                renderMeshArtifact(
                  project,
                  artifact,
                  publicResourceBase,
                  meshArtifacts.fallback,
                  meshArtifacts.finalFallback,
                )
              }
            </ArtifactState>
          )}
          {tab === "splat" && (
            <ArtifactState
              project={project}
              artifact={splatArtifacts.primary}
              partialText="ODM products are safe. Retry only the Gaussian splat stage."
              shared={shared}
            >
              {(artifact) => (
                <SplatViewer
                  url={artifactResourceUrl(
                    project,
                    artifact,
                    publicResourceBase,
                  )}
                  fallbackUrl={
                    splatArtifacts.fallback
                      ? artifactResourceUrl(
                          project,
                          splatArtifacts.fallback,
                          publicResourceBase,
                        )
                      : undefined
                  }
                />
              )}
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
              <MapViewer resourceBase={resourceBase} layer={elevation} />
            </div>
          )}
          {tab === "report" && (
            <ArtifactState project={project} artifact={find(project, "report")} shared={shared}>
              {(artifact) => (
                <iframe
                  className="artifact-iframe report"
                  title="ODM quality report"
                  src={artifactResourceUrl(
                    project,
                    artifact,
                    publicResourceBase,
                  )}
                />
              )}
            </ArtifactState>
          )}
          {tab === "files" && (
            <FileBrowser
              project={project}
              publicResourceBase={publicResourceBase}
            />
          )}
        </Suspense>
      </section>
      <footer className="accuracy-footer">
        <span className="accuracy-dot" />
        <strong>{project.inspection.accuracy?.label ?? "Accuracy pending"}</strong>
        <span>
          {project.inspection.accuracy?.detail ??
            "Inspect the quality report before relying on measurements."}
        </span>
        {shared && onAbout && (
          <button className="public-about-button" onClick={onAbout}>
            <Info size={13} /> About &amp; source
          </button>
        )}
      </footer>
    </div>
  );
}

function ArtifactState({
  project,
  artifact,
  partialText,
  shared,
  children,
}: {
  project: ResultsProject;
  artifact?: Artifact;
  partialText?: string;
  shared?: boolean;
  children: (artifact: Artifact) => React.ReactNode;
}) {
  if (artifact) return children(artifact);
  return (
    <div className="artifact-empty">
      <FileArchive size={34} strokeWidth={1.25} />
      <strong>This output is not available</strong>
      <span>
        {shared
          ? "This published view does not include that output."
          : project.status === "partial"
            ? partialText
            : "It may have been disabled for this project."}
      </span>
    </div>
  );
}

function FileBrowser({
  project,
  publicResourceBase,
}: {
  project: ResultsProject;
  publicResourceBase?: string;
}) {
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
          <a
            href={artifactResourceUrl(project, artifact, publicResourceBase)}
            key={artifact.id}
            download
          >
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
