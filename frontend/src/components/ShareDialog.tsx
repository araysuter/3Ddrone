import {
  AlertTriangle,
  Copy,
  Eye,
  Link2,
  RefreshCw,
  ShieldOff,
  X,
} from "lucide-react";
import { useEffect, useState } from "react";
import { api } from "../lib/api";
import type { Project, ShareStatus } from "../types";

export function ShareDialog({
  project,
  status,
  onStatus,
  onClose,
}: {
  project: Project;
  status: ShareStatus;
  onStatus: (status: ShareStatus) => void;
  onClose: () => void;
}) {
  const [busy, setBusy] = useState(false);
  const [copied, setCopied] = useState(false);
  const [error, setError] = useState("");
  const share = status.share;

  useEffect(() => {
    let disposed = false;
    void api
      .shareStatus(project.id)
      .then((current) => {
        if (!disposed) onStatus(current);
      })
      .catch(() => undefined);
    return () => {
      disposed = true;
    };
  }, [onStatus, project.id]);

  async function update(action: () => Promise<ShareStatus>) {
    setBusy(true);
    setError("");
    try {
      onStatus(await action());
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Share settings could not be changed");
    } finally {
      setBusy(false);
    }
  }

  async function copyLink() {
    if (!share?.url) return;
    await navigator.clipboard.writeText(share.url);
    setCopied(true);
    window.setTimeout(() => setCopied(false), 1800);
  }

  function disable() {
    if (!window.confirm("Disable this public link? Anyone using it will immediately lose access.")) {
      return;
    }
    void update(() => api.disableShare(project.id));
  }

  function regenerate() {
    if (
      !window.confirm(
        "Generate a new public link? The current link will immediately stop working and view statistics will reset.",
      )
    ) {
      return;
    }
    void update(() => api.regenerateShare(project.id));
  }

  return (
    <div className="modal-backdrop" role="presentation" onMouseDown={onClose}>
      <section
        className="share-modal"
        role="dialog"
        aria-modal="true"
        aria-labelledby="share-dialog-title"
        onMouseDown={(event) => event.stopPropagation()}
      >
        <header>
          <div>
            <p className="eyebrow">PUBLIC MAP LINK</p>
            <h2 id="share-dialog-title">Share “{project.name}”</h2>
          </div>
          <button className="icon-button" onClick={onClose} aria-label="Close share dialog">
            <X size={18} />
          </button>
        </header>

        <div className="share-warning">
          <AlertTriangle size={17} />
          <div>
            <strong>Anyone with this public link can view and download the published map.</strong>
            <span>
              This includes all available outputs and files. They cannot create maps, start scans,
              reprocess, or access the private operator interface.
            </span>
          </div>
        </div>

        {!share && (
          <div className="share-create">
            <Link2 size={30} strokeWidth={1.35} />
            <p>Create one stable link for this map. It has no automatic expiration.</p>
            <button
              className="button primary"
              disabled={busy}
              onClick={() => void update(() => api.enableShare(project.id))}
            >
              <Link2 size={14} /> {busy ? "Publishing…" : "Create public link"}
            </button>
          </div>
        )}

        {share && (
          <>
            <div className="share-link-block">
              <label htmlFor="share-url">{share.enabled ? "ACTIVE PUBLIC LINK" : "DISABLED LINK"}</label>
              <div>
                <input id="share-url" readOnly value={share.url} />
                <button className="button secondary" onClick={() => void copyLink()}>
                  <Copy size={14} /> {copied ? "Copied" : "Copy"}
                </button>
              </div>
              {!share.enabled && (
                <button
                  className="button primary"
                  disabled={busy}
                  onClick={() => void update(() => api.enableShare(project.id))}
                >
                  <Link2 size={14} /> Re-enable link
                </button>
              )}
            </div>
            <dl className="share-metrics">
              <div>
                <dt><Eye size={13} /> Page views</dt>
                <dd>{share.view_count.toLocaleString()}</dd>
              </div>
              <div>
                <dt>Last viewed</dt>
                <dd>{formatDate(share.last_viewed_at)}</dd>
              </div>
              <div>
                <dt>Published result</dt>
                <dd>{formatDate(share.last_published_at)}</dd>
              </div>
            </dl>
            {share.publish_error && (
              <p className="share-publish-note">
                The existing public result is still available. Its replacement could not be
                published after the latest run.
              </p>
            )}
            <div className="share-controls">
              <button className="button secondary" disabled={busy} onClick={regenerate}>
                <RefreshCw size={14} /> Replace public link
              </button>
              {share.enabled && (
                <button className="button secondary danger-text" disabled={busy} onClick={disable}>
                  <ShieldOff size={14} /> Disable link
                </button>
              )}
            </div>
          </>
        )}
        {error && <p className="form-error">{error}</p>}
      </section>
    </div>
  );
}

function formatDate(value?: string | null) {
  if (!value) return "Never";
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? "Unknown" : date.toLocaleString();
}
