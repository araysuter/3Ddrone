import type { Artifact, Project, SystemMetrics } from "../types";

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
  about: () =>
    request<{
      name: string;
      license: string;
      source: string;
      engines: Record<string, string>;
      warranty: string;
    }>("/api/about"),
};

const CHUNK_SIZE = 5 * 1024 * 1024;

async function sha256(file: File): Promise<string> {
  const hash = await crypto.subtle.digest("SHA-256", await file.arrayBuffer());
  return [...new Uint8Array(hash)].map((value) => value.toString(16).padStart(2, "0")).join("");
}

async function uploadFile(
  projectId: string,
  file: File,
  onProgress: (file: File, progress: number) => void,
): Promise<void> {
  const recoveryKey = `mapper-upload:${projectId}:${file.name}:${file.size}`;
  let uploadId = localStorage.getItem(recoveryKey);
  let offset = 0;
  if (uploadId) {
    const status = await fetch(`/api/uploads/${uploadId}`, {
      method: "HEAD",
      credentials: "include",
    });
    if (status.ok) {
      offset = Number(status.headers.get("Upload-Offset") ?? 0);
      if (status.headers.get("Upload-State") === "complete") {
        localStorage.removeItem(recoveryKey);
        onProgress(file, 1);
        return;
      }
    } else {
      uploadId = null;
      localStorage.removeItem(recoveryKey);
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
    localStorage.setItem(recoveryKey, uploadId);
  }
  while (offset < file.size) {
    const chunk = file.slice(offset, Math.min(file.size, offset + CHUNK_SIZE));
    let response: Response | undefined;
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
      } catch {
        // Re-query the durable server offset after a short connection loss.
      }
      await new Promise((resolve) => window.setTimeout(resolve, 500 * (attempt + 1)));
    }
    if (!response) throw new ApiError(0, "Upload connection could not be restored");
    if (response.status === 409) {
      const recovered = await fetch(`/api/uploads/${uploadId}`, {
        method: "HEAD",
        credentials: "include",
      });
      if (!recovered.ok) throw new ApiError(recovered.status, "Upload recovery failed");
      offset = Number(recovered.headers.get("Upload-Offset") ?? 0);
      continue;
    }
    if (!response.ok) {
      throw new ApiError(response.status, (await response.json()).detail ?? "Upload failed");
    }
    offset = Number(response.headers.get("Upload-Offset"));
    onProgress(file, offset / file.size);
  }
  await request(`/api/uploads/${uploadId}/complete`, {
    method: "POST",
    body: JSON.stringify({ sha256: await sha256(file) }),
  });
  localStorage.removeItem(recoveryKey);
}

export async function uploadFiles(
  projectId: string,
  files: File[],
  onProgress: (file: File, progress: number) => void,
): Promise<void> {
  const work = [...files];
  const workers = Array.from({ length: Math.min(3, work.length) }, async () => {
    while (work.length) {
      const file = work.shift();
      if (file) await uploadFile(projectId, file, onProgress);
    }
  });
  await Promise.all(workers);
}
