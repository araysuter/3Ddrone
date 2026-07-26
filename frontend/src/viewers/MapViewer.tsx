import {
  useEffect,
  useRef,
  useState,
  type KeyboardEvent as ReactKeyboardEvent,
} from "react";
import type Feature from "ol/Feature.js";
import type ImageTile from "ol/ImageTile.js";
import Map from "ol/Map.js";
import View from "ol/View.js";
import Attribution from "ol/control/Attribution.js";
import TileLayer from "ol/layer/Tile.js";
import VectorLayer from "ol/layer/Vector.js";
import OSM from "ol/source/OSM.js";
import XYZ from "ol/source/XYZ.js";
import VectorSource from "ol/source/Vector.js";
import Draw from "ol/interaction/Draw.js";
import { get as getProjection, transform } from "ol/proj.js";
import { register } from "ol/proj/proj4.js";
import type { Coordinate } from "ol/coordinate.js";
import type Geometry from "ol/geom/Geometry.js";
import {
  Crosshair,
  Eraser,
  Layers,
  MousePointer2,
  Pentagon,
  Ruler,
} from "lucide-react";
import proj4 from "proj4";
import { resourceApi } from "../lib/api";
import {
  MEASUREMENT_DECLUTTER_GROUP,
  createMeasurementStyleFunction,
} from "../lib/mapMeasurementStyles";
import {
  canFinishMeasurementSketch,
  readMeasurementUnits,
  writeMeasurementUnits,
  type MeasurementUnits,
} from "../lib/measurements";

interface Props {
  resourceBase: string;
  layer: "orthomosaic" | "dsm" | "dtm";
}

export function MapViewer({ resourceBase, layer }: Props) {
  const target = useRef<HTMLDivElement>(null);
  const mapRef = useRef<Map | null>(null);
  const basemapLayerRef = useRef<TileLayer<OSM> | null>(null);
  const sourceRef = useRef(new VectorSource());
  const drawRef = useRef<Draw | null>(null);
  const activeSketchRef = useRef<Feature<Geometry> | null>(null);
  const [tool, setTool] = useState<"inspect" | "distance" | "area">("inspect");
  const toolRef = useRef(tool);
  const [basemapEnabled, setBasemapEnabled] = useState(false);
  const [basemapError, setBasemapError] = useState(false);
  const [viewerReady, setViewerReady] = useState(false);
  const [units, setUnits] = useState<MeasurementUnits>(() => {
    try {
      return readMeasurementUnits(window.localStorage);
    } catch {
      return "imperial";
    }
  });
  const unitsRef = useRef(units);
  const projectProjectionRef = useRef("EPSG:3857");
  const metersPerUnitRef = useRef(1);
  const crsLabelRef = useRef("project CRS");
  const [mapReady, setMapReady] = useState(0);
  const [readout, setReadout] = useState("Loading raster metadata…");
  const [error, setError] = useState("");
  const [hasMeasurements, setHasMeasurements] = useState(false);

  useEffect(() => {
    toolRef.current = tool;
  }, [tool]);

  useEffect(() => {
    unitsRef.current = units;
    try {
      writeMeasurementUnits(units, window.localStorage);
    } catch {
      // The current-page toggle still works when browser storage is unavailable.
    }
    sourceRef.current.changed();
    mapRef.current?.render();
    drawRef.current?.getOverlay().changed();
  }, [units]);

  useEffect(() => {
    let disposed = false;
    let map: Map | null = null;
    sourceRef.current.clear();
    basemapLayerRef.current = null;
    setHasMeasurements(false);
    setBasemapEnabled(false);
    setBasemapError(false);
    setViewerReady(false);
    setError("");
    setReadout("Loading raster metadata…");
    void resourceApi
      .rasterMetadata(resourceBase, layer)
      .then((metadata) => {
        if (disposed || !target.current) return;
        const projectionCode = `MAPPER:${resourceBase.replace(/[^a-z0-9]/gi, "_")}:${layer}`;
        if (metadata.crs_proj4) {
          proj4.defs(projectionCode, metadata.crs_proj4);
          register(proj4);
          projectProjectionRef.current = projectionCode;
        } else {
          projectProjectionRef.current = metadata.crs;
        }
        const projectProjection = getProjection(projectProjectionRef.current);
        metersPerUnitRef.current = projectProjection?.getMetersPerUnit() ?? 1;
        crsLabelRef.current = metadata.crs;
        const basemapSource = new OSM({
          crossOrigin: "anonymous",
          tileLoadFunction: (tile, src) => {
            const image = (tile as ImageTile).getImage() as HTMLImageElement;
            image.referrerPolicy = "origin";
            image.src = src;
          },
          wrapX: false,
        });
        basemapSource.on("tileloadend", () => {
          if (!disposed) setBasemapError(false);
        });
        basemapSource.on("tileloaderror", () => {
          if (!disposed) setBasemapError(true);
        });
        const basemap = new TileLayer({
          source: basemapSource,
          visible: false,
          preload: 0,
        });
        const raster = new TileLayer({
          source: new XYZ({
            url: `${resourceBase}/tiles/${layer}/{z}/{x}/{-y}.png`,
            crossOrigin: "use-credentials",
            minZoom: metadata.min_zoom,
            maxZoom: metadata.max_zoom,
            wrapX: false,
          }),
        });
        const measurements = new VectorLayer({
          source: sourceRef.current,
          style: createMeasurementStyleFunction({
            getMetersPerUnit: () => metersPerUnitRef.current,
            getProjectProjection: () => projectProjectionRef.current,
            getUnits: () => unitsRef.current,
          }),
          declutter: MEASUREMENT_DECLUTTER_GROUP,
        });
        map = new Map({
          target: target.current,
          layers: [basemap, raster, measurements],
          view: new View({
            center: [0, 0],
            zoom: metadata.min_zoom,
            minZoom: Math.max(0, metadata.min_zoom - 2),
            maxZoom: metadata.max_zoom + 2,
          }),
          controls: [new Attribution({ collapsible: false })],
        });
        map.getView().fit(metadata.bounds_3857, {
          padding: [28, 28, 28, 28],
          maxZoom: metadata.max_zoom,
        });
        map.on("pointermove", (event) => {
          setReadout(formatProjectCoordinate(event.coordinate));
        });
        map.on("singleclick", (event) => {
          if (toolRef.current !== "inspect" || layer === "orthomosaic") return;
          const coordinate = toProjectCoordinate(event.coordinate);
          setReadout(
            `${coordinate[0].toFixed(3)}, ${coordinate[1].toFixed(3)} · sampling ${layer.toUpperCase()}…`,
          );
          void resourceApi
            .elevation(resourceBase, layer, coordinate[0], coordinate[1])
            .then((sample) => {
              const elevation =
                sample.elevation == null ? "No elevation data" : `${sample.elevation.toFixed(3)} m`;
              setReadout(
                `${coordinate[0].toFixed(3)}, ${coordinate[1].toFixed(3)} · ${elevation} · ${sample.crs}`,
              );
            })
            .catch((reason: unknown) => {
              setReadout(reason instanceof Error ? reason.message : "Elevation sample failed");
            });
        });
        basemapLayerRef.current = basemap;
        mapRef.current = map;
        const center = map.getView().getCenter();
        setReadout(
          center ? formatProjectCoordinate(center) : `Raster ready · ${metadata.crs}`,
        );
        setMapReady((value) => value + 1);
        setViewerReady(true);
      })
      .catch((reason: unknown) => {
        if (!disposed) {
          setError(reason instanceof Error ? reason.message : "Raster metadata could not be loaded");
          setReadout("Raster is unavailable");
        }
      });

    function toProjectCoordinate(coordinate: Coordinate) {
      return transform(coordinate, "EPSG:3857", projectProjectionRef.current);
    }

    function formatProjectCoordinate(coordinate: Coordinate) {
      const projectCoordinate = toProjectCoordinate(coordinate);
      return `${projectCoordinate[0].toFixed(3)}, ${projectCoordinate[1].toFixed(3)} · ${crsLabelRef.current}`;
    }

    return () => {
      disposed = true;
      if (map) {
        map.setTarget(undefined);
        map.dispose();
      }
      mapRef.current = null;
      basemapLayerRef.current = null;
    };
  }, [resourceBase, layer]);

  useEffect(() => {
    const map = mapRef.current;
    if (!map) return;
    const interactions = map
      .getInteractions()
      .getArray()
      .filter((interaction) => interaction instanceof Draw);
    interactions.forEach((interaction) => map.removeInteraction(interaction));
    drawRef.current = null;
    activeSketchRef.current = null;
    if (tool === "inspect") return;

    const draw = new Draw({
      source: sourceRef.current,
      type: tool === "area" ? "Polygon" : "LineString",
      snapTolerance: 12,
      style: createMeasurementStyleFunction(
        {
          getMetersPerUnit: () => metersPerUnitRef.current,
          getProjectProjection: () => projectProjectionRef.current,
          getUnits: () => unitsRef.current,
        },
        tool,
      ),
    });
    draw.getOverlay().setDeclutter(MEASUREMENT_DECLUTTER_GROUP);
    draw.on("drawstart", (event) => {
      activeSketchRef.current = event.feature;
      setHasMeasurements(true);
    });
    draw.on("drawend", (event) => {
      activeSketchRef.current = null;
      setHasMeasurements(true);
      event.feature.changed();
    });
    draw.on("drawabort", () => {
      activeSketchRef.current = null;
      setHasMeasurements(sourceRef.current.getFeatures().length > 0);
    });
    drawRef.current = draw;
    map.addInteraction(draw);
    return () => {
      draw.abortDrawing();
      map.removeInteraction(draw);
      if (drawRef.current === draw) drawRef.current = null;
      activeSketchRef.current = null;
    };
  }, [tool, mapReady]);

  function handleMapKeyDown(event: ReactKeyboardEvent<HTMLDivElement>) {
    const activeTool = toolRef.current;
    if (event.key !== "Escape" || activeTool === "inspect") return;
    const draw = drawRef.current;
    const activeSketch = activeSketchRef.current;
    const geometry = activeSketch?.getGeometry();
    if (!draw || !geometry) return;

    if (canFinishMeasurementSketch(activeTool, geometry)) {
      draw.finishDrawing();
    } else {
      draw.abortDrawing();
    }
    event.preventDefault();
    event.stopPropagation();
  }

  function handleClearMeasurements() {
    drawRef.current?.abortDrawing();
    activeSketchRef.current = null;
    sourceRef.current.clear();
    setHasMeasurements(false);
    mapRef.current?.render();
  }

  function handleBasemapToggle() {
    const nextEnabled = !basemapEnabled;
    basemapLayerRef.current?.setVisible(nextEnabled);
    setBasemapEnabled(nextEnabled);
    setBasemapError(false);
  }

  const mapStatus = error
    ? error
    : basemapEnabled
      ? basemapError
        ? "Basemap unavailable · Local tiles remain"
        : "OpenStreetMap basemap on"
      : "Local ODM tiles · Basemap off";

  return (
    <div className="map-viewer">
      <div className="viewer-toolbar">
        <button
          type="button"
          className={tool === "inspect" ? "active" : ""}
          onClick={() => setTool("inspect")}
        >
          <MousePointer2 size={14} /> Inspect
        </button>
        <button
          type="button"
          className={tool === "distance" ? "active" : ""}
          onClick={() => setTool("distance")}
        >
          <Ruler size={14} /> Distance
        </button>
        <button
          type="button"
          className={tool === "area" ? "active" : ""}
          onClick={() => setTool("area")}
        >
          <Pentagon size={14} /> Area
        </button>
        <button
          type="button"
          className="viewer-clear-button"
          disabled={!hasMeasurements}
          title="Clear all measurements"
          onClick={handleClearMeasurements}
        >
          <Eraser size={14} /> Clear
        </button>
        <button
          type="button"
          className={basemapEnabled ? "active" : ""}
          aria-pressed={basemapEnabled}
          disabled={!viewerReady}
          title={
            basemapEnabled
              ? "Hide the OpenStreetMap basemap"
              : "Show the OpenStreetMap basemap (uses internet)"
          }
          onClick={handleBasemapToggle}
        >
          <Layers size={14} /> Basemap
        </button>
        <div className="viewer-unit-toggle" role="group" aria-label="Measurement units">
          <button
            type="button"
            className={units === "imperial" ? "active" : ""}
            aria-pressed={units === "imperial"}
            onClick={() => setUnits("imperial")}
          >
            ft
          </button>
          <button
            type="button"
            className={units === "metric" ? "active" : ""}
            aria-pressed={units === "metric"}
            onClick={() => setUnits("metric")}
          >
            m
          </button>
        </div>
        <span>
          <Crosshair size={13} /> {readout}
        </span>
      </div>
      <div
        className="ol-map"
        ref={target}
        tabIndex={0}
        aria-label="Aerial map viewer"
        onPointerDown={(event) => event.currentTarget.focus({ preventScroll: true })}
        onKeyDown={handleMapKeyDown}
      />
      <div className="map-empty-note">{mapStatus}</div>
    </div>
  );
}
