# GPU and sample acceptance checklist

The macOS development host can validate application logic and the rendered UI, but it cannot prove the target CUDA pipeline. Run this checklist on the Ubuntu RTX 3060 Ti host before treating the installation as production-ready.

## Automated checks

```bash
npm --prefix frontend ci
PYTHONPATH=services/api services/api/.venv/bin/python -m pytest -q services/api/tests
npm --prefix frontend run lint
npm --prefix frontend run test
npm --prefix frontend run build
VITE_PUBLIC_SHARE_BUILD=true npm --prefix frontend run build
MAPPER_ENV_FILE=.env ./scripts/check-config.sh
docker compose config --quiet
git diff --check
```

Both service tokens in `.env` must be different, non-placeholder values of at
least 32 characters, and `MAPPER_UID`/`MAPPER_GID` must match the account that
owns the retained data directory.

For a non-CUDA application smoke test, run `make demo`, complete first-user
setup, create a project, upload/resume files, inspect the live stages and logs,
and check `/api/health`. This proves the Docker/API/browser path only; it does
not satisfy any GPU or reconstruction acceptance item.

## GPU smoke

```bash
make gpu-smoke
docker compose exec nodeodm python3 /code/run.py --help
docker compose exec splat-worker python3 -c "import torch; print(torch.cuda.get_device_name(0)); print(torch.cuda.mem_get_info())"
```

Pass only if both worker containers see device 0 and the card reports approximately 8 GB VRAM.

## Supplied 34-photo dataset

Create a Standard project with all outputs selected and upload:

- `Sample Mapping/Images/` — 34 FC330 JPG images
- `Sample Mapping/Test Data.lchm` — provenance only

The intake summary must report:

- 34 images and 34 geotagged images
- FC330
- median relative altitude near 80 m
- 8 nadir frames and 26 oblique frames
- 33 ms rolling-shutter correction
- best-effort consumer-GPS accuracy

If these fields are blank, verify the grouped ExifTool keys directly before
processing:

```bash
exiftool -j -n -G "Sample Mapping/Images/DJI_0192.JPG"
```

Inspect NodeODM output and pass only if:

- CUDA SIFT is selected and used.
- OpenMVS reports GPU use instead of silently falling back.
- CPU/RAM-bound stages remain labeled as such; the UI must not imply full-pipeline CUDA.
- Orthomosaic, LAZ/EPT/COPC, OBJ/GLB/3D Tiles, DSM, DTM, PDF report, logs/raw outputs, and `all.zip` are present.
- `opensfm export_colmap --binary` is attempted from the packaged OpenSfM
  reconstruction. If the optional exporter fails, its exact output is logged
  and `ns-process-data odm` still completes from the authoritative ODM cameras.
- Nerfstudio's `ns-process-data odm` conversion succeeds without replacing ODM's calibrated Brown camera model with a weaker model.
- Regular Splatfacto stays within the 8 GB VRAM envelope.
- Splatfacto initializes on the internal worker network without DNS access by
  using the LPIPS/AlexNet weights baked into the image.
- PLY renders in Spark, SPZ compression succeeds, and `scene_transform.json` is retained.

Repeat with High only after Standard passes.

## Viewer and measurement checks

At 1440×900 and 1280×720:

1. Switch maps while one is processing.
2. Interrupt and resume an upload.
3. Cancel an active ODM task and verify the durable state.
4. Open orthomosaic, point cloud, 3D model, splat, elevation, report, and files.
   Confirm point-cloud 3D Tiles and EPT reveal coarse geometry before full
   detail, and that the LAS/LAZ 1.4 fallback remains responsive while its
   worker decodes a multi-million-point cloud. Confirm the 3D model prefers the
   browser-sized textured preview GLB, renders photographic color rather than a
   white material, displays a visual percentage bar while loading, fits the
   completed model into view, shows a preparing state while decoding, and
   retains textured 3D Tiles plus OBJ/MTL/JPEG fallbacks.
   In both the authenticated and public-share views, verify point-cloud orbit
   reaches a near-overhead view, stops at the ground horizon instead of
   crossing underneath the cloud, repeated wheel input keeps the same zoom step
   at near and far distances, and an equal pointer drag pans the same
   world-space distance at near and far zoom. Hold the scroll wheel and drag to
   confirm it pans without orbiting; normal wheel scrolling must still zoom.
   While EPT detail or an adaptive 3D Tiles pass is streaming, confirm the
   locked status appears and orbit, pan, and zoom input has no effect.
   Confirm navigation resumes when that loading pass reaches completion.
   While it streams, allow operator project polling to run (or rerender the
   public results view) and confirm progress never returns to coarse loading
   and previously decoded geometry remains visible.
5. Download every final format.
6. Compare raster CRS/bounds with `gdalinfo` or QGIS.
7. Compare distance, area, and DSM/DTM samples against QGIS. In both the
   authenticated and public-share viewers, confirm imperial is the first-visit
   default, the `ft`/`m` choice persists, distance totals and area side/center
   labels update live, Escape finishes a valid distance polyline, Escape
   cancels a one-point attempt without leaving Distance mode, Escape closes and
   finishes an area with at least three placed corners, and Escape cancels a
   one- or two-corner area attempt without leaving Area mode. Labels must remain
   fixed-size and decluttered when zoomed out. Confirm **Clear** removes every
   completed distance and area measurement plus any active sketch without
   leaving the selected measurement mode.
8. Force a splat failure and confirm ODM results remain available with a separate retry.
9. Restart each container during its owned stage and verify reconciliation.
10. Open the Advanced drawer and verify only the server allowlist appears;
    path, cluster, copy, rerun-stage, `ignore-gsd`, and resource-bypass options
    must be absent.
11. Check the browser console for errors and verify the two-column Outputs grid
    has complete borders at the narrower viewport.
12. Create a second Standard project with Gaussian splat, mesh, DTM, and report
    disabled. Confirm those stages/tabs never appear, the processing footer
    reads `ODM only`, NodeODM effective options contain `skip-3dmodel`,
    `skip-report`, and no `dtm`, and the selected-output archive contains none
    of those product families.
13. Open a completed map's actions menu, choose **Reprocess with different
    settings**, change its preset and at least one output, and submit without
    selecting imagery again. Confirm the retained upload count is shown,
    NodeODM's effective options include `crop=0` unless Advanced overrides it,
    the new output selection is honored, and the prior local artifacts remain
    available until the replacement archive passes validation.
14. Open any map's actions menu, choose **Rename map**, and save a new name.
    Confirm the sidebar, workspace title, and existing public-share header
    update while status, project assignment, uploads, and artifacts are unchanged.
15. Create an **Arbordale** project, drag a completed map into it, collapse and
    expand the project, and confirm the workspace eyebrow changes from
    **NO PROJECT** to **ARBORDALE**.
16. Open **New map** while the Arbordale map is selected and confirm the
    Project field defaults to Arbordale. Move the new map back to No Project and
    verify processing state is unchanged.
17. Rename Arbordale, then delete the nonempty project. Confirm its maps move
    to No Project and their retained source and artifact files remain intact.
    Repeat the sidebar checks at 1440×900 and 1280×720 with no console errors.
18. Enable the `sharing` profile, open Arbordale's completed map, and confirm
    **Share** is the rightmost results-toolbar action. Create a link and open it
    in a signed-out desktop browser and a phone-size viewport. Confirm the
    public header shows **ARBORDALE** above the map name, the first available
    output opens, and Files downloads work.
19. Confirm the public view has no processing-complete block, three-dot menu,
    upload, create, run, retry, reprocess, or delete control. Its four result
    statistics must fill the summary row. **About & source** must share the
    36px accuracy footer row and link to the deployed AGPL source.
20. Record the view count, reload once, and confirm it increments and updates
    Last viewed. Disable the link and confirm it fails generically. Re-enable
    it, then replace the public link and confirm the old UUID URL fails while
    the new URL succeeds. Open the new URL in a fresh signed-out browser and
    confirm it works without any prior share cookie.
21. Start reprocessing a shared map and confirm the public link retains the
    exact prior published result. Force an incomplete/failed run and confirm no
    technical error is exposed publicly. Complete a later run and confirm the
    link switches to the new snapshot.
22. From the public hostname, verify `/api/projects`, `/api/setup`,
    `/api/system`, and non-GET public methods return 404/403 while the private
    Tailscale operator remains functional. Repeat with browser console and
    network panels open and confirm share HTML/API/artifacts are `no-store`.
23. Open a named Project's three-dot menu and select **Share project**. Confirm
    **No Project** has no equivalent action. Create the link while the Project
    is empty and verify a signed-out browser shows **No published maps yet**.
24. Add two completed maps and one processing/failed map to the shared Project.
    Confirm the public sidebar is flat, contains only the two published maps,
    has no create controls, tree, menus, drag/drop, or logout, and labels the
    shell **AERIAL MAPPER / SHARED PROJECT**.
25. Open the Project base URL and confirm it replaces the address with the
    newest map's nested URL. Switch maps, reload, and use browser back/forward.
    At phone width, open the keyboard-accessible **Maps** drawer, select a map,
    and confirm the drawer closes.
26. Rename the Project and a published map, then move a map out and an eligible
    map in. Confirm public labels and membership update without changing the
    remaining snapshot files. Delete the named Project and confirm all
    collection and nested URLs fail generically.
27. Force one new Project-map publication to fail. Confirm other maps remain
    available, the failed new map stays hidden, and the owner dialog shows the
    failed count. Repair the artifact and use **Retry publishing**. Disable,
    re-enable, then replace the Project link; every old collection and nested
    URL must fail while the rotated link retains all published maps.
28. Confirm typed map and Project routes work while legacy `/share/{uuid}` and
    `/api/public/shares/{uuid}` return 404. Try one Project's item UUID beneath
    another Project's share UUID and confirm its metadata and artifacts return
    the generic unavailable response.
29. Open a fresh private orthomosaic with the network panel recording. Confirm
    **Basemap** is not pressed, the local-only dark background remains, OSM
    attribution is absent, and no request reaches `tile.openstreetmap.org`.
30. Enable **Basemap** and confirm OpenStreetMap renders beneath the transparent
    ODM boundary, the button reports its pressed state, visible attribution
    links to the OSM copyright page, and tile requests send only the mapper
    origin as their referrer. Disable it and confirm the dark background and
    attribution state return without changing the viewport or measurements.
31. Repeat the default-off and toggle checks in DSM, DTM, an individual public
    map share, and a map inside a public Project. Switching maps or raster tabs
    must reset the control off and must not carry the choice through browser
    storage.
32. Block the OSM tile hostname and confirm the viewer reports **Basemap
    unavailable · Local tiles remain** while local raster interaction and
    measurement tools continue working. At 1440×900, 1280×720, and 390×760,
    confirm the toolbar remains usable and horizontally scrollable, and the
    attribution never overlaps the status note.

## Stop conditions

- If the sample fails in the unmodified official ODM 3.6.0 GPU baseline, diagnose capture quality or upstream compatibility before editing ODM.
- If ODM succeeds and COLMAP/splat fails, constrain changes to `services/splat/` and its data contract.
- If the pipeline succeeds but splat geometry is weak, collect a denser oblique reference capture before treating the viewer or trainer as defective.
