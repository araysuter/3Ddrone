import { ChangeEvent, DragEvent, useMemo, useRef, useState } from "react";
import {
  Box,
  ChevronDown,
  FileImage,
  Gauge,
  Layers3,
  Map as MapIcon,
  Mountain,
  UploadCloud,
  X,
} from "lucide-react";

interface Props {
  open: boolean;
  busy: boolean;
  onClose: () => void;
  onCreate: (payload: {
    name: string;
    preset: string;
    outputs: Record<string, boolean>;
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
];

export function NewProjectDialog({ open, busy, onClose, onCreate }: Props) {
  const [name, setName] = useState("");
  const [files, setFiles] = useState<File[]>([]);
  const [preset, setPreset] = useState("high");
  const [outputs, setOutputs] = useState<Record<string, boolean>>(
    Object.fromEntries(outputChoices.map(([id]) => [id, true])),
  );
  const [advanced, setAdvanced] = useState(false);
  const inputRef = useRef<HTMLInputElement>(null);
  const totalSize = useMemo(() => files.reduce((sum, file) => sum + file.size, 0), [files]);

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

  async function create() {
    if (!name.trim() || !files.length || busy) return;
    await onCreate({ name: name.trim(), preset, outputs, files });
    setName("");
    setFiles([]);
    setPreset("high");
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
            <p className="eyebrow">NEW DATASET</p>
            <h2 id="new-project-title">Create mapping project</h2>
          </div>
          <button className="icon-button" onClick={onClose} aria-label="Close">
            <X size={18} />
          </button>
        </header>
        <div className="modal-body">
          <label className="field-label">
            Project name
            <input
              autoFocus
              placeholder="e.g. Pioneer High School — July 23"
              value={name}
              onChange={(event) => setName(event.target.value)}
            />
          </label>
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
              accept=".jpg,.jpeg,.dng,.tif,.tiff,.mp4,.mov,.lchm,.txt,.geo,.las,.laz"
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
                    onChange={(event) =>
                      setOutputs((current) => ({ ...current, [id]: event.target.checked }))
                    }
                  />
                  <Icon size={15} />
                  {label}
                </label>
              ))}
            </div>
          </fieldset>
          <button className="advanced-toggle" onClick={() => setAdvanced((value) => !value)}>
            <ChevronDown className={advanced ? "rotated" : ""} size={15} />
            Advanced ODM options
          </button>
          {advanced && (
            <div className="advanced-note">
              Safe engine options become available after NodeODM reports its current metadata. Path,
              cluster, rerun-stage and resource-bypass flags are intentionally blocked.
            </div>
          )}
        </div>
        <footer className="modal-footer">
          <span>Files are retained locally until you confirm project deletion.</span>
          <div>
            <button className="button secondary" onClick={onClose}>
              Cancel
            </button>
            <button
              className="button primary"
              disabled={busy || !name.trim() || !files.length}
              onClick={create}
            >
              <UploadCloud size={15} />
              {busy ? "Starting upload…" : "Create & upload"}
            </button>
          </div>
        </footer>
      </section>
    </div>
  );
}
