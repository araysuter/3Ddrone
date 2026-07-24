import { useEffect, useRef, useState } from "react";
import Map from "ol/Map";
import View from "ol/View";
import TileLayer from "ol/layer/Tile";
import VectorLayer from "ol/layer/Vector";
import XYZ from "ol/source/XYZ";
import VectorSource from "ol/source/Vector";
import Draw from "ol/interaction/Draw";
import { getArea, getLength } from "ol/sphere";
import { Fill, Stroke, Style } from "ol/style";
import { Crosshair, MousePointer2, Pentagon, Ruler } from "lucide-react";
import { api } from "../lib/api";

interface Props {
  projectId: string;
  layer: "orthomosaic" | "dsm" | "dtm";
}

export function MapViewer({ projectId, layer }: Props) {
  const target = useRef<HTMLDivElement>(null);
  const mapRef = useRef<Map | null>(null);
  const sourceRef = useRef(new VectorSource());
  const [tool, setTool] = useState<"inspect" | "distance" | "area">("inspect");
  const [readout, setReadout] = useState("Move across the map to inspect coordinates.");

  useEffect(() => {
    if (!target.current) return;
    const raster = new TileLayer({
      source: new XYZ({
        url: `/api/projects/${projectId}/tiles/${layer}/{z}/{x}/{y}.png`,
        crossOrigin: "use-credentials",
      }),
    });
    const measurements = new VectorLayer({
      source: sourceRef.current,
      style: new Style({
        stroke: new Stroke({ color: "#3b91ff", width: 2 }),
        fill: new Fill({ color: "rgba(59,145,255,.16)" }),
      }),
    });
    const map = new Map({
      target: target.current,
      layers: [raster, measurements],
      view: new View({ center: [0, 0], zoom: 2, minZoom: 0, maxZoom: 24 }),
      controls: [],
    });
    map.on("pointermove", (event) => {
      if (tool === "inspect") {
        setReadout(`${event.coordinate[0].toFixed(3)}, ${event.coordinate[1].toFixed(3)} · project CRS`);
      }
    });
    mapRef.current = map;
    return () => {
      map.setTarget(undefined);
      mapRef.current = null;
    };
  }, [projectId, layer]);

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
    draw.on("drawend", async (event) => {
      if (tool === "area") {
        const squareMeters = getArea(event.feature.getGeometry()!);
        setReadout(
          squareMeters > 10_000
            ? `${(squareMeters / 10_000).toFixed(2)} ha`
            : `${squareMeters.toFixed(2)} m²`,
        );
      } else {
        const meters = getLength(event.feature.getGeometry()!);
        setReadout(meters > 1000 ? `${(meters / 1000).toFixed(3)} km` : `${meters.toFixed(2)} m`);
      }
    });
    map.addInteraction(draw);
    return () => {
      map.removeInteraction(draw);
    };
  }, [tool]);

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
      <div className="map-empty-note">Local ODM tiles · No external basemap required</div>
    </div>
  );
}
