import { Pencil, X } from "lucide-react";
import { FormEvent, useState } from "react";
import type { Project } from "../types";

interface Props {
  project: Project;
  busy: boolean;
  onClose: () => void;
  onSubmit: (name: string) => Promise<void>;
}

export function RenameMapDialog({ project, busy, onClose, onSubmit }: Props) {
  const [name, setName] = useState(project.name);
  const [error, setError] = useState("");

  async function submit(event: FormEvent) {
    event.preventDefault();
    if (!name.trim() || busy) return;
    setError("");
    try {
      await onSubmit(name.trim());
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Map could not be renamed");
    }
  }

  return (
    <div className="modal-backdrop" role="presentation" onMouseDown={onClose}>
      <form
        className="new-project-modal folder-dialog"
        role="dialog"
        aria-modal="true"
        aria-labelledby="rename-map-dialog-title"
        onMouseDown={(event) => event.stopPropagation()}
        onSubmit={submit}
      >
        <header className="modal-header">
          <div>
            <p className="eyebrow">RENAME MAP</p>
            <h2 id="rename-map-dialog-title">Rename map</h2>
          </div>
          <button className="icon-button" type="button" onClick={onClose} aria-label="Close">
            <X size={18} />
          </button>
        </header>
        <div className="modal-body">
          <label className="field-label">
            Map name
            <input
              autoFocus
              maxLength={120}
              placeholder="e.g. Arbordale ST — July 26"
              value={name}
              onChange={(event) => setName(event.target.value)}
            />
          </label>
          <p className="folder-dialog-note">
            Only the display name changes. Processing results and retained files stay in place.
          </p>
          {error && <div className="form-error">{error}</div>}
        </div>
        <footer className="modal-footer">
          <span>Project assignment and processing state are unchanged.</span>
          <div>
            <button className="button secondary" type="button" onClick={onClose}>
              Cancel
            </button>
            <button className="button primary" type="submit" disabled={busy || !name.trim()}>
              <Pencil size={14} />
              {busy ? "Saving…" : "Save name"}
            </button>
          </div>
        </footer>
      </form>
    </div>
  );
}
