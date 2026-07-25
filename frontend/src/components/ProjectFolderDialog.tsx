import { FolderPlus, Pencil, X } from "lucide-react";
import { FormEvent, useState } from "react";

interface Props {
  mode: "create" | "rename";
  initialName?: string;
  busy: boolean;
  onClose: () => void;
  onSubmit: (name: string) => Promise<void>;
}

export function ProjectFolderDialog({
  mode,
  initialName = "",
  busy,
  onClose,
  onSubmit,
}: Props) {
  const [name, setName] = useState(initialName);
  const [error, setError] = useState("");
  const creating = mode === "create";

  async function submit(event: FormEvent) {
    event.preventDefault();
    if (!name.trim() || busy) return;
    setError("");
    try {
      await onSubmit(name.trim());
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Project could not be saved");
    }
  }

  return (
    <div className="modal-backdrop" role="presentation" onMouseDown={onClose}>
      <form
        className="new-project-modal folder-dialog"
        role="dialog"
        aria-modal="true"
        aria-labelledby="folder-dialog-title"
        onMouseDown={(event) => event.stopPropagation()}
        onSubmit={submit}
      >
        <header className="modal-header">
          <div>
            <p className="eyebrow">{creating ? "NEW PROJECT" : "RENAME PROJECT"}</p>
            <h2 id="folder-dialog-title">
              {creating ? "Create a map project" : "Rename project"}
            </h2>
          </div>
          <button className="icon-button" type="button" onClick={onClose} aria-label="Close">
            <X size={18} />
          </button>
        </header>
        <div className="modal-body">
          <label className="field-label">
            Project name
            <input
              autoFocus
              maxLength={120}
              placeholder="e.g. Arbordale Street"
              value={name}
              onChange={(event) => setName(event.target.value)}
            />
          </label>
          <p className="folder-dialog-note">
            Projects organize recurring maps. They do not move or duplicate mapping data.
          </p>
          {error && <div className="form-error">{error}</div>}
        </div>
        <footer className="modal-footer">
          <span>Maps can be moved between projects at any time.</span>
          <div>
            <button className="button secondary" type="button" onClick={onClose}>
              Cancel
            </button>
            <button className="button primary" type="submit" disabled={busy || !name.trim()}>
              {creating ? <FolderPlus size={15} /> : <Pencil size={14} />}
              {busy ? "Saving…" : creating ? "Create project" : "Save name"}
            </button>
          </div>
        </footer>
      </form>
    </div>
  );
}
