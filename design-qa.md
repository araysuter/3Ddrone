# Measurement label design QA

## Evidence

- Source visual truth:
  - `/var/folders/wg/4c5ys1f50kg_hwllv6bpb4fc0000gn/T/TemporaryItems/NSIRD_screencaptureui_Y3QVWG/Screenshot 2026-07-26 at 11.38.42.png`
    (`378 × 218`, distance-tag reference).
  - `/var/folders/wg/4c5ys1f50kg_hwllv6bpb4fc0000gn/T/TemporaryItems/NSIRD_screencaptureui_iYMBJ1/Screenshot 2026-07-26 at 11.40.43.png`
    (`2220 × 1172`, coordinate-toolbar context).
- Browser-rendered implementation:
  - `/tmp/3ddrone-measurement-polyline-live.png` (`1440 × 900`).
  - `/tmp/3ddrone-measurement-distance-complete.png` (`1440 × 900`).
  - `/tmp/3ddrone-measurement-area-complete.png` (`1440 × 900`).
  - `/tmp/3ddrone-measurement-area-far-zoom.png` (`1440 × 900`).
  - `/tmp/3ddrone-measurement-public.png` (`1440 × 900`).
  - `/tmp/3ddrone-measurement-public-mobile.png` (`390 × 760`).
  - `/tmp/3ddrone-clear-before.png` (`1280 × 720`).
  - `/tmp/3ddrone-clear-after.png` (`1280 × 720`).
  - `/tmp/3ddrone-clear-mobile.png` (`390 × 760`).
  - `/tmp/3ddrone-area-escape-finished.png` (`1280 × 720`).
  - `/tmp/3ddrone-area-escape-cancelled.png` (`1280 × 720`).
  - `/tmp/3ddrone-public-share-measurement-ui.png` (`1280 × 720`).
  - `/tmp/3ddrone-public-share-measurements.png` (`1280 × 720`).
- Comparison artifacts:
  - `/tmp/3ddrone-distance-focused-comparison.png`.
  - `/tmp/3ddrone-full-view-comparison.jpg`.
- Browser: Codex in-app browser, CSS viewport `1440 × 900`, `1280 × 720`,
  and `390 × 760`, device scale factor `1`.
- Focused comparison normalization: the implementation label region was cropped
  and resized to the source tag's `378 × 218` pixel dimensions. The contextual
  full-view reference was proportionally scaled only for side-by-side review;
  shell dimensions were not treated as pixel-equivalent because the source is a
  cropped viewer rather than the full authenticated application.

## States and interactions tested

- Authenticated orthomosaic: live distance preview, three-point polyline,
  Escape completion, one-point Escape cancellation, retained Distance mode,
  imperial/metric conversion, preference after reload, live polygon labels,
  snapped polygon completion, far-zoom rendering, and clearing all completed
  measurements plus an active sketch without leaving the selected tool.
- Public share: authorization, imperial default, unit toggle, completed
  distance label, coordinate toolbar, and the same measurement controls.
  Escape closes a three-corner area without requiring a click on the starting
  point, cancels a one-corner area, and retains Area mode in both cases. A
  dedicated parity pass confirmed Inspect, Distance, Area, Clear, `ft`/`m`,
  fixed-size labels, and coordinate readout all render from the shared
  `MapViewer`.
- Responsive public share at `390 × 760`: toolbar remains horizontally
  scrollable, measurement modes and unit controls remain reachable, and the
  viewer/footer do not overlap.
- Console errors and warnings: none in the final private, public, or mobile
  passes.

## Fidelity review

- Fonts and typography: the label is a compact semibold monospace tag that
  matches the mapper's established technical UI. It is intentionally smaller
  than the enlarged reference crop so it remains unobtrusive at distant zoom.
- Spacing and layout rhythm: the unit control fits the existing segmented
  toolbar without changing its height; labels are centered on their geometry
  with consistent fixed-pixel padding.
- Colors and visual tokens: the blue line/vertices, near-black label surface,
  pale text, and muted border remain consistent with the existing dark mapper
  palette.
- Image quality and asset fidelity: no new raster assets were required. The
  repeating orthomosaic in QA captures is disposable fixture data and is not a
  production UI change.
- Copy and content: `ft` and `m` are compact and unambiguous; length, area,
  acres, miles, hectares, and kilometers use the agreed formatting.
- Icons and controls: existing Lucide mode icons are preserved; the unit toggle
  has pressed state and keyboard focus treatment.
- Responsiveness and accessibility: labels stay fixed in screen pixels,
  short/colliding side labels are eligible for suppression, the map is
  keyboard-focusable, and Escape behavior is scoped to an active Distance or
  Area sketch.

## Findings

- No actionable P0, P1, or P2 differences.
- P3: OpenLayers' native canvas text background has square rather than rounded
  corners. The dark padded tag, placement, contrast, and fixed sizing match the
  reference intent, and retaining the native style preserves reliable
  decluttering and live redraw performance.

## Comparison history

- Pass 1: no P0/P1/P2 design issues found. No visual fix iteration was
  required. The private and public implementations both matched the agreed
  placement, toolbar, units, and zoom behavior.

## Implementation checklist

- [x] Distance total is attached to the polyline.
- [x] Polygon side lengths and centered area are attached to the polygon.
- [x] Labels update live and remain after completion.
- [x] Coordinate toolbar remains active in every measurement mode.
- [x] Unit preference defaults to imperial, persists, and works in shared views.
- [x] Escape finishes or cancels Distance according to placed-point count.
- [x] Escape closes a valid Area or cancels it when fewer than three corners exist.
- [x] Clear removes all completed measurements and the active sketch.
- [x] Public shares expose the same measurement toolbar and interactions.
- [x] Desktop, far-zoom, public-share, and mobile states pass rendered QA.

final result: passed
