import { ExternalLink, X } from "lucide-react";
import { useEffect, useState } from "react";
import { api } from "../lib/api";

export function AboutDialog({ open, onClose }: { open: boolean; onClose: () => void }) {
  const [about, setAbout] = useState<Awaited<ReturnType<typeof api.about>>>();

  useEffect(() => {
    if (open) api.about().then(setAbout).catch(() => undefined);
  }, [open]);

  if (!open) return null;
  return (
    <div className="modal-backdrop" onMouseDown={onClose}>
      <section
        className="about-modal"
        role="dialog"
        aria-modal="true"
        aria-labelledby="about-title"
        onMouseDown={(event) => event.stopPropagation()}
      >
        <header>
          <div>
            <p className="eyebrow">ABOUT & SOURCE</p>
            <h2 id="about-title">Local Aerial Mapper</h2>
          </div>
          <button className="icon-button" onClick={onClose} aria-label="Close">
            <X size={18} />
          </button>
        </header>
        <p>
          A private, single-user workstation built around the unmodified OpenDroneMap processing
          engine and a pinned, locally hardened NodeODM API, with a separate Nerfstudio/gsplat
          post-processing stage.
        </p>
        <dl>
          <div>
            <dt>License</dt>
            <dd>{about?.license ?? "AGPL-3.0-only"}</dd>
          </div>
          <div>
            <dt>OpenDroneMap</dt>
            <dd>{about?.engines.ODM ?? "3.6.0"}</dd>
          </div>
          <div>
            <dt>NodeODM</dt>
            <dd>{about?.engines.NodeODM ?? "2.2.3"}</dd>
          </div>
        </dl>
        <p className="warranty">{about?.warranty ?? "This software is provided without warranty."}</p>
        <a href={about?.source ?? "https://github.com/araysuter/3Ddrone"} target="_blank" rel="noreferrer">
          View complete source and third-party notices <ExternalLink size={13} />
        </a>
      </section>
    </div>
  );
}
