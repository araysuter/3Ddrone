# GPU and sample acceptance checklist

The macOS development host can validate application logic and the rendered UI, but it cannot prove the target CUDA pipeline. Run this checklist on the Ubuntu RTX 3060 Ti host before treating the installation as production-ready.

## Automated checks

```bash
npm --prefix frontend ci
PYTHONPATH=services/api services/api/.venv/bin/python -m pytest -q services/api/tests
npm --prefix frontend run lint
npm --prefix frontend run build
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

1. Switch projects while one is processing.
2. Interrupt and resume an upload.
3. Cancel an active ODM task and verify the durable state.
4. Open orthomosaic, point cloud, 3D model, splat, elevation, report, and files.
   Confirm the LAS/LAZ 1.4 fallback works when point-cloud 3D Tiles are not
   present, and that ODM's OBJ/MTL/JPEG model renders with its photographic
   texture. Also verify that the Draco-compressed GLB fallback opens.
5. Download every final format.
6. Compare raster CRS/bounds with `gdalinfo` or QGIS.
7. Compare distance, area, and DSM/DTM samples against QGIS.
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
13. Open a completed project's actions menu, choose **Reprocess with different
    settings**, change its preset and at least one output, and submit without
    selecting imagery again. Confirm the retained upload count is shown,
    NodeODM's effective options include `crop=0` unless Advanced overrides it,
    the new output selection is honored, and the prior local artifacts remain
    available until the replacement archive passes validation.

## Stop conditions

- If the sample fails in the unmodified official ODM 3.6.0 GPU baseline, diagnose capture quality or upstream compatibility before editing ODM.
- If ODM succeeds and COLMAP/splat fails, constrain changes to `services/splat/` and its data contract.
- If the pipeline succeeds but splat geometry is weak, collect a denser oblique reference capture before treating the viewer or trainer as defective.
