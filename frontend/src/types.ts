export type ProjectStatus =
  | "uploading"
  | "queued"
  | "processing"
  | "splatting"
  | "completed"
  | "partial"
  | "failed"
  | "canceled";

export interface Inspection {
  images?: number;
  videos?: number;
  geotagged?: number;
  camera_model?: string;
  relative_altitude_median?: number;
  relative_altitude_range?: [number, number];
  nadir?: number;
  oblique?: number;
  megapixels?: number;
  rolling_shutter_ms?: number;
  accuracy?: {
    label: string;
    survey_grade: boolean;
    detail: string;
  };
  metadata_errors?: string[];
}

export interface Upload {
  id: string;
  filename: string;
  size: number;
  offset: number;
  sha256?: string;
  kind: string;
  state: string;
  error?: string;
}

export interface Artifact {
  id: string;
  category: string;
  label: string;
  path: string;
  viewer: string;
  size: number;
  content_type: string;
}

export interface Project {
  id: string;
  folder_id?: string | null;
  name: string;
  preset: "standard" | "high" | "ultra";
  status: ProjectStatus;
  stage: string;
  progress: number;
  outputs: Record<string, boolean>;
  advanced: Record<string, unknown>;
  inspection: Inspection;
  nodeodm_uuid?: string;
  splat_job_id?: string;
  error?: string;
  gcp_used: boolean;
  cancel_requested: boolean;
  created_at: string;
  updated_at: string;
  uploads?: Upload[];
  artifacts?: Artifact[];
}

export type ResultsProject = Pick<
  Project,
  "id" | "name" | "preset" | "outputs" | "inspection" | "gcp_used" | "artifacts"
> & {
  status: "completed" | "partial";
};

export interface PublicShareProject extends ResultsProject {
  folder_name?: string | null;
}

export interface ShareDetails {
  enabled: boolean;
  url: string;
  view_count: number;
  last_viewed_at?: string | null;
  last_published_at?: string | null;
  publish_error?: string | null;
}

export interface ShareStatus {
  configured: boolean;
  share?: ShareDetails | null;
}

export interface ProjectShareIssue {
  map_name: string;
  message: string;
}

export interface ProjectShareDetails {
  enabled: boolean;
  url: string;
  view_count: number;
  last_viewed_at?: string | null;
  last_published_at?: string | null;
  published_map_count: number;
  failed_map_count: number;
  publication_issues: ProjectShareIssue[];
}

export interface ProjectShareStatus {
  configured: boolean;
  share?: ProjectShareDetails | null;
}

export interface PublicProjectMapSummary {
  id: string;
  name: string;
  status: "completed" | "partial";
}

export interface PublicProjectShare {
  name: string;
  maps: PublicProjectMapSummary[];
}

export interface MapFolder {
  id: string;
  name: string;
  created_at: string;
  updated_at: string;
}

export interface Preset {
  label: string;
  description: string;
  odm: Record<string, unknown>;
  splat: Record<string, unknown>;
}

export interface AdvancedOption {
  name: string;
  type: "int" | "float" | "string" | "bool" | "enum";
  value: string;
  domain: string | string[];
  help: string;
}

export interface SystemMetrics {
  cpu_percent: number;
  logical_cores: number;
  ram_used_gb: number;
  ram_total_gb: number;
  disk_used_gb: number;
  disk_total_gb: number;
  gpu: {
    available: boolean;
    name?: string;
    utilization_percent?: number;
    memory_used_mb?: number;
    memory_total_mb?: number;
  };
}
