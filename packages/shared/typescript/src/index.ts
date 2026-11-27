export type JobStatus = "queued" | "running" | "succeeded" | "failed";
export type GenerationMode = "photoreal";
export type AspectRatioPreset = "1:1" | "16:9" | "9:16" | "4:5" | "3:2";
export type SeedStrategy = "same" | "new";

export interface CreateImageRequest {
  prompt: string;
  negative_prompt?: string;
  aspect_ratio: AspectRatioPreset;
  mode: GenerationMode;
  seed?: number;
  auto_enhance_prompt?: boolean;
  input_image_base64?: string;
  input_image_mime_type?: string;
  input_image_strength?: number;
}

export interface RetryImageRequest {
  seed_strategy: SeedStrategy;
}

export interface ImageJob {
  id: string;
  status: JobStatus;
  prompt_original: string;
  prompt_final: string;
  negative_prompt: string;
  aspect_ratio: AspectRatioPreset;
  width: number;
  height: number;
  mode: GenerationMode;
  seed: number;
  auto_enhance_prompt: boolean;
  progress_percent: number;
  progress_stage: string;
  generation_params: Record<string, unknown>;
  result_url: string | null;
  storage_bucket: string | null;
  storage_key: string | null;
  mime_type: string | null;
  heartbeat_at: string | null;
  attempt_count: number;
  max_attempts: number;
  worker_id: string | null;
  error_code: string | null;
  error_message: string | null;
  retried_from_job_id: string | null;
  created_at: string;
  started_at: string | null;
  finished_at: string | null;
  updated_at: string;
}

export interface ImageJobListResponse {
  items: ImageJob[];
  next_cursor: string | null;
}

export async function apiFetch<T>(baseUrl: string, path: string, init?: RequestInit): Promise<T> {
  const headers = new Headers(init?.headers);
  if (!headers.has("Content-Type")) {
    headers.set("Content-Type", "application/json");
  }

  const response = await fetch(`${baseUrl}${path}`, {
    ...init,
    headers,
    cache: "no-store",
  });

  if (!response.ok) {
    const detail = await response.text();
    throw new Error(detail || `Request failed with status ${response.status}`);
  }

  return response.json() as Promise<T>;
}

export function isTerminalStatus(status: JobStatus): boolean {
  return status === "succeeded" || status === "failed";
}
