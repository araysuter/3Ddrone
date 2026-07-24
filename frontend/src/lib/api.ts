import type { AdvancedOption, Artifact, Project, SystemMetrics } from "../types";
import { createSHA256 } from "hash-wasm";

let csrfToken = "";

export class ApiError extends Error {
  status: number;

  constructor(status: number, message: string) {
    super(message);
    this.status = status;
  }
}

async function request<T>(path: string, init: RequestInit = {}): Promise<T> {
  const headers = new Headers(init.headers);
  if (init.body && !(init.body instanceof Blob) && !(init.body instanceof FormData)) {
    headers.set("Content-Type", "application/json");
  }
  if (csrfToken && !["GET", "HEAD"].includes(init.method ?? "GET")) {
    headers.set("X-CSRF-Token", csrfToken);
  }
  const response = await fetch(path, { ...init, headers, credentials: "include" });
  if (!response.ok) {
    let message = `${response.status} ${response.statusText}`;
    try {
      const payload = await response.json();
      message = payload.detail ?? payload.error ?? message;
    } catch {
      // Retain status text for non-JSON responses.
    }
    if (response.status === 401) {
      window.dispatchEvent(new Event("mapper:unauthorized"));
    }
    throw new ApiError(response.status, message);
  }
  if (response.status === 204) return undefined as T;
  return response.json() as Promise<T>;
}

export const api = {
  async setupStatus() {
    return request<{ required: boolean }>("/api/setup");
  },
  async setup(username: string, password: string) {
    const result = await request<{ csrf_token: string }>("/api/setup", {
      method: "POST",
      body: JSON.stringify({ username, password }),
    });
    csrfToken = result.csrf_token;
  },
  async session() {
    const result = await request<{ authenticated: boolean; csrf_token: string }>("/api/session");
    csrfToken = result.csrf_token;
    return result;
  },
  async login(username: string, password: string) {
    const result = await request<{ csrf_token: string }>("/api/login", {
      method: "POST",
      body: JSON.stringify({ username, password }),
    });
    csrfToken = result.csrf_token;
  },
  async logout() {
    await request("/api/logout", { method: "POST" });
    csrfToken = "";
  },
  listProjects: () => request<Project[]>("/api/projects"),
  getProject: (id: string) => request<Project>(`/api/projects/${id}`),
  createProject: (payload: {
    name: string;
    preset: string;
    outputs: Record<string, boolean>;
    advanced?: Record<string, unknown>;
  }) =>
    request<Project>("/api/projects", {
      method: "POST",
      body: JSON.stringify(payload),
    }),
  inspectProject: (id: string) =>
    request<Project["inspection"]>(`/api/projects/${id}/inspect`, { method: "POST" }),
  startProject: (id: string) =>
    request<Project>(`/api/projects/${id}/start`, { method: "POST" }),
  cancelProject: (id: string) =>
    request<Project>(`/api/projects/${id}/cancel`, { method: "POST" }),
  retrySplat: (id: string) =>
    request<Project>(`/api/projects/${id}/retry-splat`, { method: "POST" }),
  reprocessProject: (
    id: string,
    payload: {
      name: string;
      preset: string;
      outputs: Record<string, boolean>;
      advanced?: Record<string, unknown>;
    },
  ) =>
    request<Project>(`/api/projects/${id}/reprocess`, {
      method: "POST",
      body: JSON.stringify(payload),
    }),
  deleteProject: (project: Project) =>
    request<void>(`/api/projects/${project.id}`, {
      method: "DELETE",
      headers: { "X-Confirm-Project-Name": project.name },
    }),
  artifacts: (id: string) =>
    request<{ artifacts: Artifact[] }>(`/api/projects/${id}/artifacts`),
  system: () => request<SystemMetrics>("/api/system"),
  elevation: (id: string, layer: "dsm" | "dtm", x: number, y: number) =>
    request<{ elevation: number | null; crs: string }>(
      `/api/projects/${id}/elevation?layer=${layer}&x=${x}&y=${y}`,
    ),
  rasterMetadata: (id: string, layer: "orthomosaic" | "dsm" | "dtm") =>
    request<{
      layer: string;
      crs: string;
      crs_proj4: string;
      bounds: [number, number, number, number];
      bounds_3857: [number, number, number, number];
      min_zoom: number;
      max_zoom: number;
      tile_scheme: "tms";
      units: string;
    }>(`/api/projects/${id}/raster-metadata?layer=${layer}`),
  about: () =>
    request<{
      name: string;
      license: string;
      source: string;
      engines: Record<string, string>;
      warranty: string;
    }>("/api/about"),
  options: () => request<{ options: AdvancedOption[] }>("/api/options"),
};

const CHUNK_SIZE = 5 * 1024 * 1024;

async function sha256(file: File): Promise<string> {
  const hasher = await createSHA256();
  hasher.init();
  for (let offset = 0; offset < file.size; offset += CHUNK_SIZE) {
    const chunk = await file.slice(offset, Math.min(file.size, offset + CHUNK_SIZE)).arrayBuffer();
    hasher.update(new Uint8Array(chunk));
    if (offset > 0 && offset % (64 * 1024 * 1024) === 0) {
      await new Promise<void>((resolve) => window.setTimeout(resolve, 0));
    }
  }
  return hasher.digest("hex") as string;
}

function storageGet(key: string) {
  try {
    return localStorage.getItem(key);
  } catch {
    return null;
  }
}

function storageSet(key: string, value: string) {
  try {
    localStorage.setItem(key, value);
  } catch {
    // Uploads still work when browser storage is disabled.
  }
}

function storageRemove(key: string) {
  try {
    localStorage.removeItem(key);
  } catch {
    // Nothing to recover when browser storage is disabled.
  }
}

async function uploadStatus(uploadId: string, fileSize: number) {
  let response: Response;
  try {
    response = await fetch(`/api/uploads/${uploadId}`, {
      method: "HEAD",
      credentials: "include",
    });
  } catch {
    throw new ApiError(0, "Upload recovery could not reach the server");
  }
  if (response.status === 401) {
    window.dispatchEvent(new Event("mapper:unauthorized"));
  }
  if (!response.ok) {
    throw new ApiError(response.status, "Upload recovery failed");
  }
  const offset = Number(response.headers.get("Upload-Offset") ?? 0);
  if (!Number.isFinite(offset) || offset < 0 || offset > fileSize) {
    throw new ApiError(409, "Server returned an invalid upload offset");
  }
  return { offset, state: response.headers.get("Upload-State") };
}

async function responseError(response: Response, fallback: string) {
  let message = fallback;
  try {
    const payload = await response.json();
    message = payload.detail ?? payload.error ?? fallback;
  } catch {
    // Retain the stable fallback when a proxy returns HTML or an empty body.
  }
  if (response.status === 401) {
    window.dispatchEvent(new Event("mapper:unauthorized"));
  }
  return new ApiError(response.status, message);
}

async function uploadFile(
  projectId: string,
  file: File,
  onProgress: (file: File, progress: number) => void,
): Promise<void> {
  const recoveryKey = `mapper-upload:${projectId}:${file.name}:${file.size}`;
  let uploadId = storageGet(recoveryKey);
  let offset = 0;
  if (uploadId) {
    try {
      const status = await uploadStatus(uploadId, file.size);
      offset = status.offset;
      if (status.state === "complete") {
        storageRemove(recoveryKey);
        onProgress(file, 1);
        return;
      } else if (status.state !== "uploading") {
        uploadId = null;
        offset = 0;
        storageRemove(recoveryKey);
      }
    } catch (reason) {
      if (reason instanceof ApiError && reason.status === 0) throw reason;
      uploadId = null;
      storageRemove(recoveryKey);
    }
  }
  if (!uploadId) {
    const initialized = await request<{ id: string; offset: number }>(
      `/api/projects/${projectId}/uploads`,
      {
        method: "POST",
        body: JSON.stringify({ filename: file.name, size: file.size }),
      },
    );
    uploadId = initialized.id;
    offset = initialized.offset;
    storageSet(recoveryKey, uploadId);
  }
  while (offset < file.size) {
    const chunk = file.slice(offset, Math.min(file.size, offset + CHUNK_SIZE));
    let response: Response | undefined;
    let recovered = false;
    for (let attempt = 0; attempt < 5; attempt += 1) {
      try {
        response = await fetch(`/api/uploads/${uploadId}`, {
          method: "PATCH",
          credentials: "include",
          headers: {
            "Content-Type": "application/offset+octet-stream",
            "Upload-Offset": String(offset),
            "X-CSRF-Token": csrfToken,
          },
          body: chunk,
        });
        if (response.ok || response.status === 409) break;
        if (response.status < 500 || response.status >= 600) break;
      } catch {
        try {
          const status = await uploadStatus(uploadId, file.size);
          if (status.offset !== offset) {
            offset = status.offset;
            onProgress(file, file.size === 0 ? 1 : offset / file.size);
            recovered = true;
            break;
          }
        } catch (reason) {
          if (reason instanceof ApiError && reason.status === 401) throw reason;
        }
      }
      await new Promise((resolve) => window.setTimeout(resolve, 500 * (attempt + 1)));
    }
    if (recovered) continue;
    if (!response) throw new ApiError(0, "Upload connection could not be restored");
    if (response.status === 409) {
      offset = (await uploadStatus(uploadId, file.size)).offset;
      continue;
    }
    if (!response.ok) {
      throw await responseError(response, "Upload failed");
    }
    offset = Number(response.headers.get("Upload-Offset"));
    if (!Number.isFinite(offset) || offset < 0 || offset > file.size) {
      throw new ApiError(409, "Server returned an invalid upload offset");
    }
    onProgress(file, offset / file.size);
  }
  await request(`/api/uploads/${uploadId}/complete`, {
    method: "POST",
    body: JSON.stringify({ sha256: await sha256(file) }),
  });
  storageRemove(recoveryKey);
}

export async function uploadFiles(
  projectId: string,
  files: File[],
  onProgress: (file: File, progress: number) => void,
): Promise<void> {
  const work = [...files];
  let firstError: unknown;
  const workers = Array.from({ length: Math.min(3, work.length) }, async () => {
    while (work.length) {
      const file = work.shift();
      if (!file) continue;
      try {
        await uploadFile(projectId, file, onProgress);
      } catch (reason) {
        firstError ??= reason;
      }
    }
  });
  await Promise.all(workers);
  if (firstError) throw firstError;
}
