# Third-party notices

The complete source and license texts in this repository remain authoritative. This summary is provided for operator visibility.

| Component | Pinned version | License | Source or local notice |
|---|---:|---|---|
| OpenDroneMap | 3.6.0 | AGPLv3 | Root source, `LICENSE`, and `licenses/` |
| NodeODM | 2.2.3 | AGPLv3 | `vendor/nodeodm/` and `vendor/nodeodm/LICENSE` |
| Nerfstudio | 1.1.5 | Apache-2.0 | Installed in `services/splat/Dockerfile` |
| gsplat | commit `4d3a3b69` (1.4 series) | Apache-2.0 | Pinned and compiled in `services/splat/Dockerfile` |
| PyTorch | 2.4.1 | BSD-3-Clause | CUDA 12.4 wheel pinned in `services/splat/requirements.txt` |
| Spark | 2.1.0 / commit `f22236f9` | MIT | Frontend dependency and pinned compressor checkout |
| React | 19.1.0 | MIT | `frontend/package-lock.json` |
| Vite | 6.4.3 | MIT | `frontend/package-lock.json` |
| Three.js | 0.180.0 | MIT | `frontend/package-lock.json` |
| OpenLayers | 10.6.1 | BSD-2-Clause | `frontend/package-lock.json` |
| 3d-tiles-renderer | 0.4.27 | Apache-2.0 | `frontend/package-lock.json` |
| loaders.gl core/LAS | 4.4.3 | MIT | `frontend/package-lock.json` |
| math.gl types | 4.1.0 | MIT | `frontend/package-lock.json` |
| hash-wasm | 4.12.0 | MIT | `frontend/package-lock.json` |
| proj4 | 2.20.9 | MIT | `frontend/package-lock.json` |
| FastAPI | 0.139.2 | MIT | `services/api/requirements.txt` |
| Starlette | 1.3.1 | BSD-3-Clause | `services/api/requirements.txt` |
| Pillow | 12.3.0 | HPND | `services/api/requirements.txt` |
| Rasterio | 1.4.3 | BSD-3-Clause | `services/api/requirements.txt` |

ODM’s transitive native dependencies and their licenses are enumerated under `licenses/` and in the original upstream history. Docker base images and Ubuntu/Debian packages retain their own notices inside the built images.

Gaussian training uses the Apache-licensed gsplat backend through Nerfstudio. This project does not embed or invoke the original restricted INRIA training implementation.

## Compatibility security boundary

PyTorch 2.4.1 is retained because Nerfstudio 1.1.5, the pinned gsplat build, and
the target CUDA 12.4/RTX 3060 Ti profile must be validated as one stack. Current
dependency scanners report advisories against that older PyTorch release. The
splat worker is therefore internal-only, has no host port, accepts only
orchestrator-authenticated jobs, and resumes only checkpoints generated inside
the retained project directory. Do not import untrusted PyTorch checkpoints.
Upgrade this stack after the complete Standard and High GPU acceptance suite
passes on the target host.
