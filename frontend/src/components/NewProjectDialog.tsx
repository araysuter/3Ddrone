import { ChangeEvent, DragEvent, useEffect, useMemo, useRef, useState } from "react";
import {
  Box,
  ChevronDown,
  FileImage,
  Gauge,
  Layers3,
  Map as MapIcon,
  Mountain,
  RotateCcw,
  UploadCloud,
  X,
} from "lucide-react";
import { api } from "../lib/api";
import type { AdvancedOption, MapFolder, Project } from "../types";

interface Props {
  open: boolean;
  busy: boolean;
  mode?: "create" | "reprocess";
  initialProject?: Project;
  folders?: MapFolder[];
  defaultFolderId?: string | null;
  onClose: () => void;
  onSubmit: (payload: {
    name: string;
    preset: string;
    outputs: Record<string, boolean>;
    advanced: Record<string, unknown>;
    folder_id: string | null;
    files: File[];
  }) => Promise<void>;
}

const outputChoices = [
  ["orthomosaic", "Orthomosaic", MapIcon],
  ["point_cloud", "Point cloud", Layers3],
  ["mesh", "3D mesh", Box],
  ["dsm", "DSM", Mountain],
  ["dtm", "DTM", Mountain],
  ["report", "PDF report", FileImage],
  ["raw", "Raw outputs", Gauge],
  ["splat", "Gaussian splat", Box],
] as const;

const defaultOutputs = Object.fromEntries(outputChoices.map(([id]) => [id, true]));
const defaultAdvanced = { crop: 0 };

const presets = [
  {
    id: "standard",
    label: "Standard",
    detail: "5 cm requested · 15k splat steps",
    time: "Fastest",
  },
  {
    id: "high",
    label: "High",
    detail: "2.5 cm requested · 30k splat steps",
    time: "Recommended",
  },
  {
    id: "ultra",
    label: "Ultra",
    detail: "1 cm requested · 45k splat steps",
    time: "Slowest",
  },
] as const;

export function NewProjectDialog({
  open,
  busy,
  mode = "create",
  initialProject,
  folders = [],
  defaultFolderId = null,
  onClose,
  onSubmit,
}: Props) {
  const reprocessing = mode === "reprocess";
  const [name, setName] = useState(initialProject?.name ?? "");
  const [files, setFiles] = useState<File[]>([]);
  const [preset, setPreset] = useState(initialProject?.preset ?? "high");
  const [folderId, setFolderId] = useState(
    initialProject?.folder_id ?? defaultFolderId ?? "",
  );
  const [outputs, setOutputs] = useState<Record<string, boolean>>(
    () => ({ ...defaultOutputs, ...(initialProject?.outputs ?? {}) }),
  );
  const [advancedOpen, setAdvancedOpen] = useState(false);
  const [advancedOptions, setAdvancedOptions] = useState<AdvancedOption[]>();
  const [advancedValues, setAdvancedValues] = useState<Record<string, unknown>>(
    () => ({ ...defaultAdvanced, ...(initialProject?.advanced ?? {}) }),
  );
  const [advancedError, setAdvancedError] = useState("");
  const [error, setError] = useState("");
  const inputRef = useRef<HTMLInputElement>(null);
  const totalSize = useMemo(() => files.reduce((sum, file) => sum + file.size, 0), [files]);
  const retainedInputCount =
    initialProject?.uploads?.filter(
      (upload) => upload.state === "complete" && ["image", "video"].includes(upload.kind),
    ).length ?? 0;

  useEffect(() => {
    if (!open || !advancedOpen || advancedOptions) return;
    let disposed = false;
    setAdvancedError("");
    void api
      .options()
      .then((result) => {
        if (!disposed) setAdvancedOptions(result.options);
      })
      .catch((reason: unknown) => {
        if (!disposed) {
          setAdvancedError(
            reason instanceof Error ? reason.message : "ODM option metadata is unavailable",
          );
        }
      });
    return () => {
      disposed = true;
    };
  }, [open, advancedOpen, advancedOptions]);

  if (!open) return null;

  function addFiles(list: FileList | null) {
    if (!list) return;
    setFiles((current) => {
      const next = new Map(current.map((file) => [`${file.name}:${file.size}`, file]));
      for (const file of Array.from(list)) next.set(`${file.name}:${file.size}`, file);
      return [...next.values()];
    });
  }

  function drop(event: DragEvent) {
    event.preventDefault();
    addFiles(event.dataTransfer.files);
  }

  function setOutput(id: string, checked: boolean) {
    setOutputs((current) => {
      const next = { ...current, [id]: checked };
      if (id === "dtm" && checked) next.point_cloud = true;
      if (id === "splat" && checked) next.raw = true;
      if (id === "point_cloud" && !checked) next.dtm = false;
      if (id === "raw" && !checked) next.splat = false;
      return next;
    });
  }

  function enableAdvanced(option: AdvancedOption, enabled: boolean) {
    setAdvancedValues((current) => {
      const next = { ...current };
      if (!enabled) {
        delete next[option.name];
      } else if (option.type === "bool") {
        next[option.name] = true;
      } else if (option.type === "int") {
        const parsed = Number.parseInt(option.value, 10) || 0;
        next[option.name] = option.name === "max-concurrency" ? Math.max(1, parsed) : parsed;
      } else if (option.type === "float") {
        next[option.name] = Number.parseFloat(option.value) || 0;
      } else {
        next[option.name] = option.value;
      }
      return next;
    });
  }

  function setAdvancedValue(option: AdvancedOption, rawValue: string) {
    let value: unknown = rawValue;
    if (option.type === "int") value = Number.parseInt(rawValue, 10) || 0;
    if (option.type === "float") value = Number.parseFloat(rawValue) || 0;
    setAdvancedValues((current) => ({ ...current, [option.name]: value }));
  }

  async function submit() {
    if (
      !name.trim() ||
      (!reprocessing && !files.length) ||
      !Object.values(outputs).some(Boolean) ||
      busy
    ) {
      return;
    }
    setError("");
    try {
      await onSubmit({
        name: name.trim(),
        preset,
        outputs,
        advanced: advancedValues,
        folder_id: folderId || null,
        files,
      });
      if (!reprocessing) {
        setName("");
        setFiles([]);
        setPreset("high");
        setOutputs({ ...defaultOutputs });
        setAdvancedValues({ ...defaultAdvanced });
        setAdvancedOpen(false);
      }
    } catch (reason) {
      setError(
        reason instanceof Error
          ? reason.message
          : reprocessing
            ? "Map could not be reprocessed"
            : "Map could not be created",
      );
    }
  }

  return (
    <div className="modal-backdrop" role="presentation" onMouseDown={onClose}>
      <section
        className="new-project-modal"
        role="dialog"
        aria-modal="true"
        aria-labelledby="new-project-title"
        onMouseDown={(event) => event.stopPropagation()}
      >
        <header className="modal-header">
          <div>
            <p className="eyebrow">{reprocessing ? "REPROCESS MAP" : "NEW MAP"}</p>
            <h2 id="new-project-title">
              {reprocessing ? "Reprocess with different settings" : "Create aerial map"}
            </h2>
          </div>
          <button className="icon-button" onClick={onClose} aria-label="Close">
            <X size={18} />
          </button>
        </header>
        <div className="modal-body">
          <label className="field-label">
            Map name
            <input
              autoFocus
              placeholder="e.g. Pioneer High School — July 23"
              value={name}
              onChange={(event) => setName(event.target.value)}
            />
          </label>
          {!reprocessing && (
            <label className="field-label map-project-field">
              Project
              <select value={folderId} onChange={(event) => setFolderId(event.target.value)}>
                <option value="">No Project</option>
                {folders.map((folder) => (
                  <option value={folder.id} key={folder.id}>
                    {folder.name}
                  </option>
                ))}
              </select>
            </label>
          )}
          {reprocessing ? (
            <div className="reprocess-source-note">
              <RotateCcw size={18} />
              <div>
                <strong>Reusing {retainedInputCount} retained reconstruction files</strong>
                <span>
                  Existing artifacts stay on disk until the replacement ODM run is ready.
                </span>
              </div>
            </div>
          ) : (
            <>
              <div
                className="drop-zone"
                onClick={() => inputRef.current?.click()}
                onDragOver={(event) => event.preventDefault()}
                onDrop={drop}
              >
                <input
                  ref={inputRef}
                  hidden
                  type="file"
                  multiple
                  accept=".jpg,.jpeg,.dng,.tif,.tiff,.mp4,.mov,.lrv,.ts,.srt,.lchm,.txt,.las,.laz"
                  onChange={(event: ChangeEvent<HTMLInputElement>) => addFiles(event.target.files)}
                />
                <UploadCloud size={25} strokeWidth={1.5} />
                <strong>{files.length ? `${files.length} files ready` : "Drop source files here"}</strong>
                <span>
                  {files.length
                    ? `${(totalSize / 1024 / 1024).toFixed(1)} MB · Click to add more`
                    : "JPG, DNG, TIFF, video, GCP, GEO or Litchi mission"}
                </span>
              </div>
              {files.length > 0 && (
                <div className="file-preview-row">
                  <FileImage size={14} />
                  <span>{files.slice(0, 3).map((file) => file.name).join(", ")}</span>
                  {files.length > 3 && <em>+{files.length - 3} more</em>}
                  <button onClick={() => setFiles([])}>Clear</button>
                </div>
              )}
            </>
          )}
          <fieldset>
            <legend>Precision profile</legend>
            <div className="preset-grid">
              {presets.map((option) => (
                <button
                  type="button"
                  key={option.id}
                  className={`preset-choice ${preset === option.id ? "selected" : ""}`}
                  onClick={() => setPreset(option.id)}
                >
                  <span className="preset-radio" />
                  <strong>{option.label}</strong>
                  <small>{option.detail}</small>
                  <em>{option.time}</em>
                </button>
              ))}
            </div>
            <p className="field-note">
              Requested raster resolution is always capped by the source imagery’s estimated GSD.
            </p>
          </fieldset>
          <fieldset>
            <legend>Outputs</legend>
            <div className="output-grid">
              {outputChoices.map(([id, label, Icon]) => (
                <label className="output-choice" key={id}>
                  <input
                    type="checkbox"
                    checked={outputs[id]}
                    onChange={(event) => setOutput(id, event.target.checked)}
                  />
                  <Icon size={15} />
                  {label}
                </label>
              ))}
            </div>
          </fieldset>
          <button
            type="button"
            className="advanced-toggle"
            onClick={() => setAdvancedOpen((value) => !value)}
          >
            <ChevronDown className={advancedOpen ? "rotated" : ""} size={15} />
            Advanced ODM options
          </button>
          {advancedOpen && (
            <div className="advanced-panel">
              <p className="advanced-note">
                Only server-allowlisted options from this NodeODM engine are shown. Path, cluster,
                rerun-stage and resource-bypass flags are blocked.
                Edge cropping is disabled by default (`crop=0`).
              </p>
              {!advancedOptions && !advancedError && (
                <div className="advanced-status">Loading current ODM option metadata…</div>
              )}
              {advancedError && <div className="form-error">{advancedError}</div>}
              {advancedOptions?.map((option) => {
                const enabled = Object.hasOwn(advancedValues, option.name);
                const value = advancedValues[option.name];
                return (
                  <div className="advanced-option" key={option.name}>
                    <label>
                      <input
                        type="checkbox"
                        checked={enabled}
                        onChange={(event) => enableAdvanced(option, event.target.checked)}
                      />
                      <span>
                        <strong>{option.name}</strong>
                        <small>{option.help}</small>
                      </span>
                    </label>
                    {enabled && option.type !== "bool" && Array.isArray(option.domain) && (
                      <select
                        aria-label={`${option.name} value`}
                        value={String(value)}
                        onChange={(event) => setAdvancedValue(option, event.target.value)}
                      >
                        {option.domain.map((choice) => (
                          <option value={choice} key={choice}>
                            {choice}
                          </option>
                        ))}
                      </select>
                    )}
                    {enabled &&
                      option.type !== "bool" &&
                      !Array.isArray(option.domain) && (
                        <input
                          aria-label={`${option.name} value`}
                          type={option.type === "int" || option.type === "float" ? "number" : "text"}
                          step={option.type === "int" ? 1 : option.type === "float" ? "any" : undefined}
                          value={String(value)}
                          onChange={(event) => setAdvancedValue(option, event.target.value)}
                        />
                      )}
                    {enabled && option.name === "max-concurrency" && (
                      <em>Overrides the automatic RAM-safe limit. Increase only after monitoring memory.</em>
                    )}
                  </div>
                );
              })}
              {advancedOptions?.length === 0 && (
                <div className="advanced-status">
                  NodeODM is unavailable or reported no allowlisted options.
                </div>
              )}
            </div>
          )}
          {error && <div className="form-error">{error}</div>}
        </div>
        <footer className="modal-footer">
          <span>
            {reprocessing
              ? "Original uploads remain retained throughout reprocessing."
              : "Files are retained locally until you confirm map deletion."}
          </span>
          <div>
            <button className="button secondary" onClick={onClose}>
              Cancel
            </button>
            <button
              className="button primary"
              disabled={
                busy ||
                !name.trim() ||
                (!reprocessing && !files.length) ||
                !Object.values(outputs).some(Boolean)
              }
              onClick={submit}
            >
              {reprocessing ? <RotateCcw size={15} /> : <UploadCloud size={15} />}
              {busy
                ? reprocessing
                  ? "Queuing reprocess…"
                  : "Starting upload…"
                : reprocessing
                  ? "Reprocess map"
                  : "Create map & upload"}
            </button>
          </div>
        </footer>
      </section>
    </div>
  );
}
