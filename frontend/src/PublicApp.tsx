import { AlertTriangle, Box } from "lucide-react";
import { useEffect, useState } from "react";
import { AboutDialog } from "./components/AboutDialog";
import { ResultsView } from "./components/ResultsView";
import { publicApi } from "./lib/api";
import { parsePublicShareLocation } from "./lib/publicShare";
import type { PublicShareProject } from "./types";

type PublicState =
  | { kind: "loading" }
  | { kind: "unavailable" }
  | { kind: "ready"; project: PublicShareProject };

export default function PublicApp() {
  const [state, setState] = useState<PublicState>({ kind: "loading" });
  const [aboutOpen, setAboutOpen] = useState(false);

  useEffect(() => {
    let disposed = false;
    const location = parsePublicShareLocation(window.location.pathname, window.location.hash);
    if (!location) {
      setState({ kind: "unavailable" });
      return;
    }
    void (async () => {
      try {
        if (location.secret) {
          await publicApi.authorize(location.shareId, location.secret);
          window.history.replaceState(null, "", window.location.pathname);
        }
        const project = await publicApi.getShare(location.shareId);
        if (!disposed) {
          setState({
            kind: "ready",
            project: { ...project, id: location.shareId },
          });
        }
      } catch {
        if (!disposed) setState({ kind: "unavailable" });
      }
    })();
    return () => {
      disposed = true;
    };
  }, []);

  if (state.kind === "loading") {
    return <div className="boot-screen">OPENING PUBLISHED MAP…</div>;
  }

  if (state.kind === "unavailable") {
    return (
      <main className="public-unavailable">
        <div className="public-brand-mark">
          <Box size={28} strokeWidth={1.25} />
          <span>LOCAL AERIAL MAPPER</span>
        </div>
        <section>
          <AlertTriangle size={32} strokeWidth={1.3} />
          <p className="eyebrow">PUBLIC MAP VIEW</p>
          <h1>A valid share link is required</h1>
          <p>
            This map link is missing, disabled, or no longer current. Ask the map owner for an
            active link.
          </p>
        </section>
      </main>
    );
  }

  return (
    <div className="public-shell">
      <header className="workspace-header public-header">
        <div className="workspace-title">
          <p className="eyebrow">
            {(state.project.folder_name || "NO PROJECT").toUpperCase()}
          </p>
          <div>
            <h1>{state.project.name}</h1>
            <span className="preset-badge">{state.project.preset.toUpperCase()}</span>
            {state.project.inspection.camera_model && (
              <span className="camera-badge">{state.project.inspection.camera_model}</span>
            )}
          </div>
        </div>
      </header>
      <ResultsView
        project={state.project}
        shared
        onAbout={() => setAboutOpen(true)}
      />
      <AboutDialog
        open={aboutOpen}
        publicView
        onClose={() => setAboutOpen(false)}
      />
    </div>
  );
}
