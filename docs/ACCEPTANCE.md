# GPU and sample acceptance checklist

The macOS development host can validate application logic and the rendered UI, but it cannot prove the target CUDA pipeline. Run this checklist on the Ubuntu RTX 3060 Ti host before treating the installation as production-ready.

## Automated checks

```bash
PYTHONPATH=services/api services/api/.venv/bin/pytest -q services/api/tests
npm --prefix frontend run build
MAPPER_DATA_DIR=/tmp/mapper-config-check \
  NODEODM_TOKEN=test \
  MAPPER_INTERNAL_TOKEN=test-internal \
  docker compose config --quiet
```

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

Inspect NodeODM output and pass only if:

- CUDA SIFT is selected and used.
- OpenMVS reports GPU use instead of silently falling back.
- CPU/RAM-bound stages remain labeled as such; the UI must not imply full-pipeline CUDA.
- Orthomosaic, LAZ/EPT/COPC, OBJ/GLB/3D Tiles, DSM, DTM, PDF report, logs/raw outputs, and `all.zip` are present.
- `opensfm export_colmap --binary` succeeds from the packaged OpenSfM reconstruction.
- Regular Splatfacto stays within the 8 GB VRAM envelope.
- PLY renders in Spark, SPZ compression succeeds, and `scene_transform.json` is retained.

Repeat with High only after Standard passes.

## Viewer and measurement checks

At 1440×900 and 1280×720:

1. Switch projects while one is processing.
2. Interrupt and resume an upload.
3. Cancel an active ODM task and verify the durable state.
4. Open orthomosaic, point cloud, GLB, splat, elevation, report, and files.
5. Download every final format.
6. Compare raster CRS/bounds with `gdalinfo` or QGIS.
7. Compare distance, area, and DSM/DTM samples against QGIS.
8. Force a splat failure and confirm ODM results remain available with a separate retry.
9. Restart each container during its owned stage and verify reconciliation.

## Stop conditions

- If the sample fails in the unmodified official ODM 3.6.0 GPU baseline, diagnose capture quality or upstream compatibility before editing ODM.
- If ODM succeeds and COLMAP/splat fails, constrain changes to `services/splat/` and its data contract.
- If the pipeline succeeds but splat geometry is weak, collect a denser oblique reference capture before treating the viewer or trainer as defective.
