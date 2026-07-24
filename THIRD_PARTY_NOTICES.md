# Third-party notices

The complete source and license texts in this repository remain authoritative. This summary is provided for operator visibility.

| Component | Pinned version | License | Source or local notice |
|---|---:|---|---|
| OpenDroneMap | 3.6.0 | AGPLv3 | Root source, `LICENSE`, and `licenses/` |
| NodeODM | 2.2.3 | AGPLv3 | `vendor/nodeodm/` and `vendor/nodeodm/LICENSE` |
| Nerfstudio | 1.1.5 | Apache-2.0 | Installed in `services/splat/Dockerfile` |
| gsplat | Nerfstudio dependency | Apache-2.0 | Installed by Nerfstudio |
| Spark | 2.1.0 | MIT | Frontend dependency and pinned compressor checkout |
| React | 19.1.0 | MIT | `frontend/package-lock.json` |
| Vite | 6.3.5 | MIT | `frontend/package-lock.json` |
| Three.js | 0.180.0 | MIT | `frontend/package-lock.json` |
| OpenLayers | 10.6.1 | BSD-2-Clause | `frontend/package-lock.json` |
| FastAPI | 0.115.12 | MIT | `services/api/requirements.txt` |
| Rasterio | 1.4.3 | BSD-3-Clause | `services/api/requirements.txt` |

ODM’s transitive native dependencies and their licenses are enumerated under `licenses/` and in the original upstream history. Docker base images and Ubuntu/Debian packages retain their own notices inside the built images.

Gaussian training uses the Apache-licensed gsplat backend through Nerfstudio. This project does not embed or invoke the original restricted INRIA training implementation.
