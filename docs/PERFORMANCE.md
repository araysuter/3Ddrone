# Pipeline performance and profiling

The mapper should optimize elapsed time and output quality, not try to hold
every meter at 100%. OpenDroneMap is a sequence of GPU, parallel CPU, serial
CPU, memory-bound, and storage-bound programs. It is normal for one processor
to be idle while another stage owns the critical path.

## Acceleration already in use

- CUDA PopSift extracts SIFT features when the project log says
  `Using GPU for extracting SIFT features`.
- CUDA OpenMVS estimates dense depth maps when the log enables a CUDA device.
- Nerfstudio Splatfacto and gsplat train the optional Gaussian splat on CUDA.
- OpenSfM feature matching and camera reconstruction, Poisson meshing,
  point-cloud filtering/classification, DSM/DTM generation, orthophoto
  rendering, GDAL/PDAL derivatives, tiles, reports, and ZIP packaging are
  CPU-only or I/O-bound in the pinned stack.

Moving those CPU stages to CUDA would mean replacing their algorithms and
validating different output geometry, not switching an existing build flag.

## Mapper scheduling

New runs use two thread budgets:

- `sfm-max-concurrency` is calculated from image megapixels and available RAM,
  with 10 GB retained for Ubuntu and mapper services.
- `max-concurrency` uses every logical CPU core for later processing stages.

This avoids the former behavior where the conservative OpenSfM memory limit
also throttled meshing, elevation, raster, and export work. Setting Advanced
`max-concurrency` below the automatic value caps both budgets.

Splatfacto still performs 15,000, 30,000, or 45,000 training iterations for
Standard, High, or Ultra. Periodic validation-image and all-image evaluation
passes are disabled because they only feed TensorBoard metrics that the mapper
does not display; checkpoints and final PLY/SPZ exports are unchanged.

## Observe a real run

Run these in separate terminals on the Ubuntu host:

```bash
watch -n 1 'docker stats --no-stream nodeodm splat-worker'
```

```bash
nvidia-smi dmon -s pucm -d 1
```

The project log must contain the mapper line with `cpu-threads` and
`sfm-threads`, followed later by both:

```text
Using GPU for extracting SIFT features
nvidia-smi detected
```

After completion, download the raw `benchmark.txt` or inspect it beneath the
retained project artifacts. It records elapsed seconds for every ODM stage.
Compare the same dataset, outputs, and preset before and after a scheduling
change; CPU or GPU percentage alone is not a throughput benchmark.

For a meaningful acceptance comparison, record:

- total NodeODM processing time;
- each `benchmark.txt` stage time;
- Splatfacto start/end time and iteration rate;
- peak system RAM and GPU VRAM;
- whether GPU SIFT or OpenMVS fell back to CPU;
- the ODM quality report and visual output checks.

Stop and restore a lower Advanced `max-concurrency` if the kernel reports an
out-of-memory kill, swap activity remains sustained, or the mapper's 10 GB host
reserve is exhausted.
