import {
  AlertTriangle,
  Copy,
  Eye,
  Link2,
  RefreshCw,
  RotateCcw,
  ShieldOff,
  X,
} from "lucide-react";
import { useEffect, useState } from "react";
import { api } from "../lib/api";
import type { MapFolder, ProjectShareStatus } from "../types";

export function ProjectShareDialog({
  folder,
  onClose,
}: {
  folder: MapFolder;
  onClose: () => void;
}) {
  const [status, setStatus] = useState<ProjectShareStatus>();
  const [busy, setBusy] = useState(false);
  const [copied, setCopied] = useState(false);
  const [error, setError] = useState("");
  const share = status?.share;

  useEffect(() => {
    let disposed = false;
    void api
      .projectShareStatus(folder.id)
      .then((current) => {
        if (!disposed) setStatus(current);
      })
      .catch((reason: unknown) => {
        if (!disposed) {
          setError(
            reason instanceof Error
              ? reason.message
              : "Project share settings could not be loaded",
          );
        }
      });
    return () => {
      disposed = true;
    };
  }, [folder.id]);

  async function update(action: () => Promise<ProjectShareStatus>) {
    setBusy(true);
    setError("");
    try {
      setStatus(await action());
    } catch (reason) {
      setError(
        reason instanceof Error
          ? reason.message
          : "Project share settings could not be changed",
      );
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
    if (
      !window.confirm(
        "Disable this public project link? Every map URL inside it will immediately stop working.",
      )
    ) {
      return;
    }
    void update(() => api.disableProjectShare(folder.id));
  }

  function regenerate() {
    if (
      !window.confirm(
        "Replace this public project link? The collection and every map URL inside the current link will immediately stop working, and view statistics will reset.",
      )
    ) {
      return;
    }
    void update(() => api.regenerateProjectShare(folder.id));
  }

  return (
    <div className="modal-backdrop" role="presentation" onMouseDown={onClose}>
      <section
        className="share-modal project-share-modal"
        role="dialog"
        aria-modal="true"
        aria-labelledby="project-share-dialog-title"
        onMouseDown={(event) => event.stopPropagation()}
      >
        <header>
          <div>
            <p className="eyebrow">PUBLIC PROJECT LINK</p>
            <h2 id="project-share-dialog-title">Share “{folder.name}”</h2>
          </div>
          <button
            className="icon-button"
            onClick={onClose}
            aria-label="Close project share dialog"
          >
            <X size={18} />
          </button>
        </header>

        <div className="share-warning">
          <AlertTriangle size={17} />
          <div>
            <strong>
              Anyone with this public link can view every published map in this
              project.
            </strong>
            <span>
              Completed and usable partial maps appear automatically. Recipients
              can use viewers and download published files, but cannot create,
              process, move, rename, or delete anything.
            </span>
          </div>
        </div>

        {!status && !error && (
          <div className="share-create">
            <Link2 size={30} strokeWidth={1.35} />
            <p>Loading project sharing settings…</p>
          </div>
        )}

        {status && !status.configured && (
          <div className="share-create">
            <AlertTriangle size={30} strokeWidth={1.35} />
            <p>Public sharing is not configured on this workstation.</p>
          </div>
        )}

        {status?.configured && !share && (
          <div className="share-create">
            <Link2 size={30} strokeWidth={1.35} />
            <p>
              Create one stable link for this project. Empty projects are
              allowed, and eligible maps will appear automatically.
            </p>
            <button
              className="button primary"
              disabled={busy}
              onClick={() =>
                void update(() => api.enableProjectShare(folder.id))
              }
            >
              <Link2 size={14} />{" "}
              {busy ? "Publishing…" : "Create public project link"}
            </button>
          </div>
        )}

        {share && (
          <>
            <div className="share-link-block">
              <label htmlFor="project-share-url">
                {share.enabled ? "ACTIVE PUBLIC LINK" : "DISABLED LINK"}
              </label>
              <div>
                <input
                  id="project-share-url"
                  readOnly
                  value={share.url}
                />
                <button
                  className="button secondary"
                  onClick={() => void copyLink()}
                >
                  <Copy size={14} /> {copied ? "Copied" : "Copy"}
                </button>
              </div>
              {!share.enabled && (
                <button
                  className="button primary"
                  disabled={busy}
                  onClick={() =>
                    void update(() => api.enableProjectShare(folder.id))
                  }
                >
                  <Link2 size={14} /> Re-enable link
                </button>
              )}
            </div>

            <dl className="share-metrics project-share-metrics">
              <div>
                <dt>
                  <Eye size={13} /> Page views
                </dt>
                <dd>{share.view_count.toLocaleString()}</dd>
              </div>
              <div>
                <dt>Published maps</dt>
                <dd>{share.published_map_count.toLocaleString()}</dd>
              </div>
              <div>
                <dt>Failed maps</dt>
                <dd>{share.failed_map_count.toLocaleString()}</dd>
              </div>
              <div>
                <dt>Last viewed</dt>
                <dd>{formatDate(share.last_viewed_at)}</dd>
              </div>
              <div>
                <dt>Last publication</dt>
                <dd>{formatDate(share.last_published_at)}</dd>
              </div>
            </dl>

            {share.publication_issues.length > 0 && (
              <div className="project-share-issues">
                <p className="eyebrow">PUBLICATION ATTENTION</p>
                {share.publication_issues.map((issue) => (
                  <div key={`${issue.map_name}:${issue.message}`}>
                    <AlertTriangle size={14} />
                    <span>
                      <strong>{issue.map_name}</strong>
                      {issue.message}
                    </span>
                  </div>
                ))}
              </div>
            )}

            <div className="share-controls project-share-controls">
              {share.failed_map_count > 0 && (
                <button
                  className="button secondary"
                  disabled={busy}
                  onClick={() =>
                    void update(() => api.retryProjectShare(folder.id))
                  }
                >
                  <RotateCcw size={14} /> Retry publishing
                </button>
              )}
              <button
                className="button secondary"
                disabled={busy}
                onClick={regenerate}
              >
                <RefreshCw size={14} /> Replace public link
              </button>
              {share.enabled && (
                <button
                  className="button secondary danger-text"
                  disabled={busy}
                  onClick={disable}
                >
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
