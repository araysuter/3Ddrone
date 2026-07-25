import { useEffect, useRef, useState } from "react";
import Map from "ol/Map.js";
import View from "ol/View.js";
import TileLayer from "ol/layer/Tile.js";
import VectorLayer from "ol/layer/Vector.js";
import XYZ from "ol/source/XYZ.js";
import VectorSource from "ol/source/Vector.js";
import Draw from "ol/interaction/Draw.js";
import { Fill, Stroke, Style } from "ol/style.js";
import { get as getProjection, transform } from "ol/proj.js";
import { register } from "ol/proj/proj4.js";
import type { Coordinate } from "ol/coordinate.js";
import type { LineString, Polygon } from "ol/geom.js";
import { Crosshair, MousePointer2, Pentagon, Ruler } from "lucide-react";
import proj4 from "proj4";
import { api, publicApi } from "../lib/api";

interface Props {
  projectId: string;
  layer: "orthomosaic" | "dsm" | "dtm";
  publicShare?: boolean;
}

export function MapViewer({ projectId, layer, publicShare = false }: Props) {
  const target = useRef<HTMLDivElement>(null);
  const mapRef = useRef<Map | null>(null);
  const sourceRef = useRef(new VectorSource());
  const [tool, setTool] = useState<"inspect" | "distance" | "area">("inspect");
  const toolRef = useRef(tool);
  const projectProjectionRef = useRef("EPSG:3857");
  const metersPerUnitRef = useRef(1);
  const crsLabelRef = useRef("project CRS");
  const [mapReady, setMapReady] = useState(0);
  const [readout, setReadout] = useState("Loading raster metadata…");
  const [error, setError] = useState("");

  useEffect(() => {
    toolRef.current = tool;
  }, [tool]);

  useEffect(() => {
    let disposed = false;
    let map: Map | null = null;
    sourceRef.current.clear();
    setError("");
    setReadout("Loading raster metadata…");
    const dataApi = publicShare ? publicApi : api;
    const basePath = publicShare
      ? `/api/public/shares/${projectId}`
      : `/api/projects/${projectId}`;
    void dataApi
      .rasterMetadata(projectId, layer)
      .then((metadata) => {
        if (disposed || !target.current) return;
        const projectionCode = `MAPPER:${projectId}:${layer}`;
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
        const raster = new TileLayer({
          source: new XYZ({
            url: `${basePath}/tiles/${layer}/{z}/{x}/{-y}.png`,
            crossOrigin: "use-credentials",
            minZoom: metadata.min_zoom,
            maxZoom: metadata.max_zoom,
            wrapX: false,
          }),
        });
        const measurements = new VectorLayer({
          source: sourceRef.current,
          style: new Style({
            stroke: new Stroke({ color: "#3b91ff", width: 2 }),
            fill: new Fill({ color: "rgba(59,145,255,.16)" }),
          }),
        });
        map = new Map({
          target: target.current,
          layers: [raster, measurements],
          view: new View({
            center: [0, 0],
            zoom: metadata.min_zoom,
            minZoom: Math.max(0, metadata.min_zoom - 2),
            maxZoom: metadata.max_zoom + 2,
          }),
          controls: [],
        });
        map.getView().fit(metadata.bounds_3857, {
          padding: [28, 28, 28, 28],
          maxZoom: metadata.max_zoom,
        });
        map.on("pointermove", (event) => {
          if (toolRef.current === "inspect") {
            const coordinate = toProjectCoordinate(event.coordinate);
            setReadout(
              `${coordinate[0].toFixed(3)}, ${coordinate[1].toFixed(3)} · ${crsLabelRef.current}`,
            );
          }
        });
        map.on("singleclick", (event) => {
          if (toolRef.current !== "inspect" || layer === "orthomosaic") return;
          const coordinate = toProjectCoordinate(event.coordinate);
          setReadout(
            `${coordinate[0].toFixed(3)}, ${coordinate[1].toFixed(3)} · sampling ${layer.toUpperCase()}…`,
          );
          void dataApi
            .elevation(projectId, layer, coordinate[0], coordinate[1])
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
        mapRef.current = map;
        setReadout(`Raster ready · ${metadata.crs}`);
        setMapReady((value) => value + 1);
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

    return () => {
      disposed = true;
      if (map) {
        map.setTarget(undefined);
        map.dispose();
      }
      mapRef.current = null;
    };
  }, [projectId, layer, publicShare]);

  useEffect(() => {
    const map = mapRef.current;
    if (!map) return;
    const interactions = map
      .getInteractions()
      .getArray()
      .filter((interaction) => interaction instanceof Draw);
    interactions.forEach((interaction) => map.removeInteraction(interaction));
    if (tool === "inspect") return;
    const draw = new Draw({ source: sourceRef.current, type: tool === "area" ? "Polygon" : "LineString" });
    draw.on("drawend", (event) => {
      const geometry = event.feature
        .getGeometry()!
        .clone()
        .transform("EPSG:3857", projectProjectionRef.current);
      const metersPerUnit = metersPerUnitRef.current;
      if (tool === "area") {
        const squareMeters = Math.abs((geometry as Polygon).getArea()) * metersPerUnit ** 2;
        setReadout(
          squareMeters > 10_000
            ? `${(squareMeters / 10_000).toFixed(2)} ha · ${crsLabelRef.current}`
            : `${squareMeters.toFixed(2)} m² · ${crsLabelRef.current}`,
        );
      } else {
        const meters = (geometry as LineString).getLength() * metersPerUnit;
        setReadout(
          meters > 1000
            ? `${(meters / 1000).toFixed(3)} km · ${crsLabelRef.current}`
            : `${meters.toFixed(2)} m · ${crsLabelRef.current}`,
        );
      }
    });
    map.addInteraction(draw);
    return () => {
      map.removeInteraction(draw);
    };
  }, [tool, mapReady]);

  return (
    <div className="map-viewer">
      <div className="viewer-toolbar">
        <button className={tool === "inspect" ? "active" : ""} onClick={() => setTool("inspect")}>
          <MousePointer2 size={14} /> Inspect
        </button>
        <button className={tool === "distance" ? "active" : ""} onClick={() => setTool("distance")}>
          <Ruler size={14} /> Distance
        </button>
        <button className={tool === "area" ? "active" : ""} onClick={() => setTool("area")}>
          <Pentagon size={14} /> Area
        </button>
        <span>
          <Crosshair size={13} /> {readout}
        </span>
      </div>
      <div className="ol-map" ref={target} />
      <div className="map-empty-note">
        {error || "Local ODM TMS tiles · No external basemap required"}
      </div>
    </div>
  );
}
