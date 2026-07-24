import {
  AlertTriangle,
  Check,
  Circle,
  Cpu,
  Database,
  HardDrive,
  LoaderCircle,
  MemoryStick,
  Radio,
  Timer,
} from "lucide-react";
import { useEffect, useRef } from "react";
import type { Project, SystemMetrics } from "../types";

type Stage = readonly [label: string, threshold: number];

function outputEnabled(project: Project, output: string) {
  return project.outputs[output] !== false;
}

function stagesFor(project: Project): Stage[] {
  const stages: Stage[] = [
    ["Dataset validation", 12],
    ["Feature extraction", 18],
    ["Feature matching", 30],
    ["Camera reconstruction", 40],
    ["Dense reconstruction", 50],
  ];
  const rasterOutputs = (["dsm", "dtm", "orthomosaic"] as const).filter((output) =>
    outputEnabled(project, output),
  );
  if (outputEnabled(project, "mesh")) {
    stages.push(["Meshing and texturing", 65]);
  } else if (rasterOutputs.length) {
    // ODM still needs a terrain surface internally to create map products,
    // even when the user has disabled the exported 3D model.
    stages.push(["Terrain surface reconstruction", 65]);
  }
  if (
    ["orthomosaic", "point_cloud", "mesh", "dsm", "dtm"].some((output) =>
      outputEnabled(project, output),
    )
  ) {
    stages.push(["Georeferencing", 76]);
  }
  if (rasterOutputs.length) {
    const rasterLabel = rasterOutputs
      .map((output) => (output === "orthomosaic" ? "Orthomosaic" : output.toUpperCase()))
      .join(", ");
    stages.push([rasterLabel, 84]);
  }
  stages.push([
    outputEnabled(project, "report") ? "Report and packaging" : "Output packaging",
    92,
  ]);
  if (outputEnabled(project, "splat")) {
    stages.push(["Gaussian splat", 96]);
  }
  return stages;
}

interface Props {
  project: Project;
  logLines: string[];
  uploadProgress?: number;
  metrics?: SystemMetrics;
}

export function ProcessingView({ project, logLines, uploadProgress, metrics }: Props) {
  const logRef = useRef<HTMLDivElement>(null);
  const stages = stagesFor(project);
  const shownProgress =
    project.status === "uploading" && uploadProgress !== undefined
      ? Math.round(uploadProgress * 100)
      : Math.round(project.progress);
  const processingStage =
    project.status === "processing" || project.status === "splatting"
      ? stages.findIndex(([, threshold]) => project.progress < threshold)
      : -1;
  const failureContext = [project.stage, project.error, ...logLines.slice(-100)]
    .join("\n")
    .toLowerCase();
  let failedStage =
    project.status === "failed"
      ? stages.findIndex(([label]) => project.stage.toLowerCase().includes(label.toLowerCase()))
      : -1;
  if (
    failedStage < 0 &&
    project.status === "failed" &&
    ["mesh", "reconstructmesh", "screened_poisson"].some((marker) =>
      failureContext.includes(marker),
    )
  ) {
    failedStage = stages.findIndex(
      ([label]) => label.includes("Meshing") || label.includes("Terrain surface"),
    );
  }
  if (failedStage < 0 && project.status === "failed") {
    failedStage = stages.findIndex(([, threshold]) => project.progress < threshold);
    if (failedStage < 0) failedStage = stages.length - 1;
  }
  const completedStages = stages.filter(
    ([, threshold], index) =>
      project.progress >= threshold && (failedStage < 0 || index < failedStage),
  ).length;
  const activeStage = failedStage >= 0 ? failedStage : processingStage;
  const elapsed = (() => {
    const seconds = Math.max(0, (Date.now() - new Date(project.created_at).getTime()) / 1000);
    if (seconds < 60) return `${Math.round(seconds)}s`;
    return `${Math.floor(seconds / 60)}m ${Math.round(seconds % 60)}s`;
  })();

  useEffect(() => {
    logRef.current?.scrollTo({ top: logRef.current.scrollHeight });
  }, [logLines]);

  return (
    <div className="processing-view">
      <section className="progress-summary">
        <div className="progress-title-row">
          <div>
            <span className={`live-dot ${project.status}`} />
            <strong>{project.status === "uploading" ? "UPLOADING SOURCE DATA" : "PROCESSING DATASET"}</strong>
            <span className="stage-copy">— {project.stage}</span>
          </div>
          <strong className="progress-number">{shownProgress}%</strong>
        </div>
        <div className="hero-progress">
          <i style={{ width: `${shownProgress}%` }} />
        </div>
        <div className="progress-meta">
          <span>
            <Timer size={13} /> Elapsed {elapsed}
          </span>
          <span>
            {outputEnabled(project, "splat")
              ? "Single GPU pipeline · ODM → Splatfacto"
              : "Single GPU pipeline · ODM only"}
          </span>
        </div>
      </section>
      <div className="processing-grid">
        <section className="stage-panel">
          <header className="panel-header">
            <strong>PIPELINE</strong>
            <span>{completedStages}/{stages.length}</span>
          </header>
          <div className="stage-list">
            {stages.map(([label, threshold], index) => {
              const done =
                project.progress >= threshold && (failedStage < 0 || index < failedStage);
              const active = index === activeStage;
              const failed = index === failedStage;
              return (
                <div
                  className={`stage-row ${done ? "done" : ""} ${active ? "active" : ""} ${failed ? "failed" : ""}`}
                  key={label}
                >
                  <span className="stage-icon">
                    {done ? (
                      <Check size={13} />
                    ) : failed ? (
                      <AlertTriangle size={13} />
                    ) : active ? (
                      <LoaderCircle className="spin" size={13} />
                    ) : (
                      <Circle size={11} />
                    )}
                  </span>
                  <span>
                    <strong>{label}</strong>
                    <small>
                      {done ? "Complete" : failed ? "Failed" : active ? "In progress" : "Waiting"}
                    </small>
                  </span>
                  {active && !failed && <em>{Math.round(project.progress)}%</em>}
                </div>
              );
            })}
          </div>
        </section>
        <section className="log-panel">
          <header className="panel-header">
            <strong>LIVE PROCESSING LOG</strong>
            <span className="streaming">
              <Radio size={12} /> STREAMING
            </span>
          </header>
          <div className="log-scroller" ref={logRef}>
            {logLines.length ? (
              logLines.map((line, index) => (
                <div className="log-line" key={`${index}-${line}`}>
                  <span>{String(index + 1).padStart(3, "0")}</span>
                  <code>{line}</code>
                </div>
              ))
            ) : (
              <>
                <div className="log-line">
                  <span>001</span>
                  <code>Project created. Waiting for validated source files.</code>
                </div>
                <div className="log-line dim">
                  <span>002</span>
                  <code>Durable progress will continue here when processing begins.</code>
                </div>
              </>
            )}
          </div>
        </section>
      </div>
      <footer className="resource-strip">
        <div>
          <Cpu size={14} />
          <span>GPU</span>
          <strong>{metrics?.gpu.available ? metrics.gpu.name : "Not detected"}</strong>
          <i><b style={{ width: `${metrics?.gpu.utilization_percent ?? 0}%` }} /></i>
        </div>
        <div>
          <MemoryStick size={14} />
          <span>VRAM</span>
          <strong>
            {metrics?.gpu.available
              ? `${((metrics.gpu.memory_used_mb ?? 0) / 1024).toFixed(1)} / ${((metrics.gpu.memory_total_mb ?? 0) / 1024).toFixed(1)} GB`
              : "Unavailable"}
          </strong>
          <i>
            <b
              style={{
                width: `${metrics?.gpu.memory_total_mb ? ((metrics.gpu.memory_used_mb ?? 0) / metrics.gpu.memory_total_mb) * 100 : 0}%`,
              }}
            />
          </i>
        </div>
        <div>
          <Database size={14} />
          <span>RAM</span>
          <strong>{metrics ? `${metrics.ram_used_gb} / ${metrics.ram_total_gb} GB` : "Reading…"}</strong>
          <i><b style={{ width: `${metrics ? (metrics.ram_used_gb / metrics.ram_total_gb) * 100 : 0}%` }} /></i>
        </div>
        <div>
          <HardDrive size={14} />
          <span>STORAGE</span>
          <strong>{metrics ? `${metrics.disk_used_gb} / ${metrics.disk_total_gb} GB` : "Reading…"}</strong>
          <i><b style={{ width: `${metrics ? (metrics.disk_used_gb / metrics.disk_total_gb) * 100 : 0}%` }} /></i>
        </div>
      </footer>
    </div>
  );
}
