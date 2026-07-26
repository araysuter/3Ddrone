import {
  AlertTriangle,
  Box,
  Check,
  Info,
  List,
  Map as MapIcon,
  X,
} from "lucide-react";
import {
  useEffect,
  useRef,
  useState,
  type RefObject,
} from "react";
import { AboutDialog } from "./components/AboutDialog";
import { ResultsView } from "./components/ResultsView";
import { publicApi } from "./lib/api";
import {
  parsePublicShareLocation,
  publicMapResourceBase,
  publicProjectMapPath,
  publicProjectMapResourceBase,
  type PublicShareLocation,
} from "./lib/publicShare";
import type {
  PublicProjectMapSummary,
  PublicProjectShare,
  PublicShareProject,
} from "./types";

type MapState =
  | { kind: "loading" }
  | { kind: "unavailable" }
  | { kind: "ready"; project: PublicShareProject };

type SelectedMapState =
  | { kind: "idle" }
  | { kind: "loading"; itemId: string }
  | { kind: "ready"; itemId: string; project: PublicShareProject };

export default function PublicApp() {
  const location = parsePublicShareLocation(window.location.pathname);
  if (!location) return <UnavailableView />;
  if (location.kind === "map") {
    return <PublicMapShare shareId={location.shareId} />;
  }
  return <PublicProjectShareView initialLocation={location} />;
}

function PublicMapShare({ shareId }: { shareId: string }) {
  const [state, setState] = useState<MapState>({ kind: "loading" });
  const [aboutOpen, setAboutOpen] = useState(false);

  useEffect(() => {
    let disposed = false;
    stripLocationHash();
    void publicApi
      .getMapShare(shareId)
      .then((project) => {
        if (!disposed) {
          setState({
            kind: "ready",
            project: { ...project, id: shareId },
          });
        }
      })
      .catch(() => {
        if (!disposed) setState({ kind: "unavailable" });
      });
    return () => {
      disposed = true;
    };
  }, [shareId]);

  if (state.kind === "loading") {
    return <div className="boot-screen">OPENING PUBLISHED MAP…</div>;
  }
  if (state.kind === "unavailable") return <UnavailableView />;

  return (
    <div className="public-shell">
      <PublicMapHeader
        eyebrow={state.project.folder_name || "NO PROJECT"}
        project={state.project}
      />
      <ResultsView
        project={state.project}
        publicResourceBase={publicMapResourceBase(shareId)}
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

function PublicProjectShareView({
  initialLocation,
}: {
  initialLocation: Extract<PublicShareLocation, { kind: "project" }>;
}) {
  const [route, setRoute] = useState(initialLocation);
  const [collection, setCollection] = useState<PublicProjectShare>();
  const [selected, setSelected] = useState<SelectedMapState>({ kind: "idle" });
  const [unavailable, setUnavailable] = useState(false);
  const [drawerOpen, setDrawerOpen] = useState(false);
  const [aboutOpen, setAboutOpen] = useState(false);
  const isPhone = usePhoneLayout();
  const mapsButtonRef = useRef<HTMLButtonElement>(null);
  const drawerRef = useRef<HTMLElement>(null);

  useEffect(() => {
    stripLocationHash();
    const handlePopState = () => {
      const next = parsePublicShareLocation(window.location.pathname);
      if (
        next?.kind === "project" &&
        next.shareId === initialLocation.shareId
      ) {
        setRoute(next);
        setUnavailable(false);
      } else {
        setUnavailable(true);
      }
    };
    window.addEventListener("popstate", handlePopState);
    return () => window.removeEventListener("popstate", handlePopState);
  }, [initialLocation.shareId]);

  useEffect(() => {
    let disposed = false;
    void publicApi
      .getProjectShare(initialLocation.shareId)
      .then((projectShare) => {
        if (!disposed) setCollection(projectShare);
      })
      .catch(() => {
        if (!disposed) setUnavailable(true);
      });
    return () => {
      disposed = true;
    };
  }, [initialLocation.shareId]);

  useEffect(() => {
    if (!collection || unavailable) return;
    if (!collection.maps.length) {
      setSelected({ kind: "idle" });
      return;
    }
    const itemId = route.itemId ?? collection.maps[0].id;
    if (!collection.maps.some((item) => item.id === itemId)) {
      setUnavailable(true);
      return;
    }
    if (!route.itemId) {
      const path = publicProjectMapPath(initialLocation.shareId, itemId);
      window.history.replaceState(null, "", path);
      setRoute({
        kind: "project",
        shareId: initialLocation.shareId,
        itemId,
      });
      return;
    }
    setSelected({ kind: "loading", itemId });
    let disposed = false;
    void publicApi
      .getProjectShareMap(initialLocation.shareId, itemId)
      .then((project) => {
        if (!disposed) {
          setSelected({
            kind: "ready",
            itemId,
            project: { ...project, id: itemId },
          });
        }
      })
      .catch(() => {
        if (!disposed) setUnavailable(true);
      });
    return () => {
      disposed = true;
    };
  }, [collection, initialLocation.shareId, route, unavailable]);

  useEffect(() => {
    if (!isPhone || !drawerOpen) return;
    const focusTarget =
      drawerRef.current?.querySelector<HTMLButtonElement>("[data-map-row]") ??
      drawerRef.current?.querySelector<HTMLButtonElement>(
        ".public-project-drawer-close",
      );
    focusTarget?.focus();
    const handleKeyDown = (event: KeyboardEvent) => {
      if (event.key !== "Escape") return;
      setDrawerOpen(false);
      mapsButtonRef.current?.focus();
    };
    window.addEventListener("keydown", handleKeyDown);
    return () => window.removeEventListener("keydown", handleKeyDown);
  }, [drawerOpen, isPhone]);

  if (unavailable) return <UnavailableView />;
  if (!collection) {
    return <div className="boot-screen">OPENING SHARED PROJECT…</div>;
  }

  function selectMap(item: PublicProjectMapSummary) {
    if (selected.kind === "ready" && selected.itemId === item.id) {
      setDrawerOpen(false);
      if (isPhone) {
        window.setTimeout(() => mapsButtonRef.current?.focus(), 0);
      }
      return;
    }
    const path = publicProjectMapPath(initialLocation.shareId, item.id);
    window.history.pushState(null, "", path);
    setRoute({
      kind: "project",
      shareId: initialLocation.shareId,
      itemId: item.id,
    });
    setDrawerOpen(false);
    if (isPhone) {
      window.setTimeout(() => mapsButtonRef.current?.focus(), 0);
    }
  }

  const selectedItemId =
    selected.kind === "idle" ? undefined : selected.itemId;

  return (
    <div className="public-project-shell">
      {isPhone && drawerOpen && (
        <button
          className="public-project-drawer-scrim"
          aria-label="Close maps drawer"
          onClick={() => {
            setDrawerOpen(false);
            mapsButtonRef.current?.focus();
          }}
        />
      )}
      <PublicProjectSidebar
        sidebarRef={drawerRef}
        collection={collection}
        selectedItemId={selectedItemId}
        drawerOpen={drawerOpen}
        isPhone={isPhone}
        onSelect={selectMap}
        onAbout={() => setAboutOpen(true)}
        onCloseDrawer={() => {
          setDrawerOpen(false);
          mapsButtonRef.current?.focus();
        }}
      />
      <main className="public-project-workspace">
        {collection.maps.length === 0 ? (
          <>
            <header className="workspace-header public-project-empty-header">
              <MobileMapsButton
                buttonRef={mapsButtonRef}
                open={drawerOpen}
                onClick={() => setDrawerOpen(true)}
              />
              <div className="workspace-title">
                <p className="eyebrow">SHARED PROJECT</p>
                <div>
                  <h1>{collection.name}</h1>
                </div>
              </div>
            </header>
            <section className="public-project-empty">
              <MapIcon size={42} strokeWidth={1.15} />
              <p className="eyebrow">SHARED PROJECT</p>
              <h1>No published maps yet</h1>
              <p>
                Eligible maps will appear here automatically after processing
                produces a usable result.
              </p>
            </section>
          </>
        ) : selected.kind === "ready" ? (
          <>
            <PublicMapHeader
              eyebrow={collection.name}
              project={selected.project}
              leading={
                <MobileMapsButton
                  buttonRef={mapsButtonRef}
                  open={drawerOpen}
                  onClick={() => setDrawerOpen(true)}
                />
              }
            />
            <ResultsView
              key={selected.itemId}
              project={selected.project}
              publicResourceBase={publicProjectMapResourceBase(
                initialLocation.shareId,
                selected.itemId,
              )}
            />
          </>
        ) : (
          <div className="boot-screen">OPENING PUBLISHED MAP…</div>
        )}
      </main>
      <AboutDialog
        open={aboutOpen}
        publicView
        onClose={() => setAboutOpen(false)}
      />
    </div>
  );
}

function PublicProjectSidebar({
  sidebarRef,
  collection,
  selectedItemId,
  drawerOpen,
  isPhone,
  onSelect,
  onAbout,
  onCloseDrawer,
}: {
  sidebarRef: RefObject<HTMLElement | null>;
  collection: PublicProjectShare;
  selectedItemId?: string;
  drawerOpen: boolean;
  isPhone: boolean;
  onSelect: (item: PublicProjectMapSummary) => void;
  onAbout: () => void;
  onCloseDrawer: () => void;
}) {
  return (
    <aside
      ref={sidebarRef}
      id="public-project-maps"
      className={`public-project-sidebar${drawerOpen ? " drawer-open" : ""}`}
      aria-label="Shared project maps"
      aria-hidden={isPhone && !drawerOpen}
      inert={isPhone && !drawerOpen}
      role={isPhone ? "dialog" : undefined}
      aria-modal={isPhone ? true : undefined}
    >
      <header className="sidebar-header">
        <div className="brand-mark">
          <MapIcon size={18} strokeWidth={1.7} />
        </div>
        <div>
          <strong>AERIAL MAPPER</strong>
          <span>SHARED PROJECT</span>
        </div>
        {isPhone && (
          <button
            className="public-project-drawer-close"
            onClick={onCloseDrawer}
            aria-label="Close maps drawer"
          >
            <X size={17} />
          </button>
        )}
      </header>
      <section className="public-project-summary">
        <p className="eyebrow">PROJECT</p>
        <h1>{collection.name}</h1>
        <span>
          {collection.maps.length} published{" "}
          {collection.maps.length === 1 ? "map" : "maps"}
        </span>
      </section>
      <nav className="public-project-map-list" aria-label="Published maps">
        {collection.maps.map((item) => (
          <button
            key={item.id}
            data-map-row
            className={selectedItemId === item.id ? "selected" : ""}
            aria-current={selectedItemId === item.id ? "page" : undefined}
            onClick={() => onSelect(item)}
          >
            <span className={`status-glyph ${item.status}`}>
              {item.status === "completed" ? (
                <Check size={13} />
              ) : (
                <AlertTriangle size={13} />
              )}
            </span>
            <span>
              <strong>{item.name}</strong>
              <small>
                {item.status === "partial" ? "Usable partial" : "Published"}
              </small>
            </span>
          </button>
        ))}
        {!collection.maps.length && (
          <p className="public-project-list-empty">No published maps</p>
        )}
      </nav>
      <footer className="sidebar-footer">
        <button onClick={onAbout}>
          <Info size={15} /> About &amp; source
        </button>
      </footer>
    </aside>
  );
}

function PublicMapHeader({
  eyebrow,
  project,
  leading,
}: {
  eyebrow: string;
  project: PublicShareProject;
  leading?: React.ReactNode;
}) {
  return (
    <header className="workspace-header public-header">
      {leading}
      <div className="workspace-title">
        <p className="eyebrow">{eyebrow.toUpperCase()}</p>
        <div>
          <h1>{project.name}</h1>
          <span className="preset-badge">{project.preset.toUpperCase()}</span>
          {project.inspection.camera_model && (
            <span className="camera-badge">
              {project.inspection.camera_model}
            </span>
          )}
        </div>
      </div>
    </header>
  );
}

function MobileMapsButton({
  buttonRef,
  open,
  onClick,
}: {
  buttonRef: RefObject<HTMLButtonElement | null>;
  open: boolean;
  onClick: () => void;
}) {
  return (
    <button
      ref={buttonRef}
      className="public-project-maps-button"
      aria-controls="public-project-maps"
      aria-expanded={open}
      onClick={onClick}
    >
      <List size={15} /> Maps
    </button>
  );
}

function UnavailableView() {
  return (
    <main className="public-unavailable">
      <div className="public-brand-mark">
        <Box size={28} strokeWidth={1.25} />
        <span>LOCAL AERIAL MAPPER</span>
      </div>
      <section>
        <AlertTriangle size={32} strokeWidth={1.3} />
        <p className="eyebrow">PUBLIC SHARED VIEW</p>
        <h1>A valid share link is required</h1>
        <p>
          This link is missing, disabled, or no longer current. Ask the map
          owner for an active link.
        </p>
      </section>
    </main>
  );
}

function usePhoneLayout() {
  const query = "(max-width: 600px)";
  const [matches, setMatches] = useState(() => window.matchMedia(query).matches);
  useEffect(() => {
    const media = window.matchMedia(query);
    const update = () => setMatches(media.matches);
    update();
    media.addEventListener("change", update);
    return () => media.removeEventListener("change", update);
  }, []);
  return matches;
}

function stripLocationHash() {
  if (window.location.hash) {
    window.history.replaceState(null, "", window.location.pathname);
  }
}
