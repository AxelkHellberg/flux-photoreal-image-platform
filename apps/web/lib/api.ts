import {
  apiFetch,
  CreateImageRequest,
  ImageJob,
  ImageJobListResponse,
  RetryImageRequest,
} from "@image-platform/shared";

const API_BASE_URL = process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:8000";

export async function createImageJob(payload: CreateImageRequest): Promise<ImageJob> {
  return apiFetch<ImageJob>(API_BASE_URL, "/v1/images", {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export async function fetchImageJobs(cursor?: string): Promise<ImageJobListResponse> {
  const suffix = cursor ? `?cursor=${encodeURIComponent(cursor)}` : "";
  return apiFetch<ImageJobListResponse>(API_BASE_URL, `/v1/images${suffix}`);
}

export async function fetchImageJob(jobId: string): Promise<ImageJob> {
  return apiFetch<ImageJob>(API_BASE_URL, `/v1/images/${jobId}`);
}

export async function retryImageJob(jobId: string, payload: RetryImageRequest): Promise<ImageJob> {
  return apiFetch<ImageJob>(API_BASE_URL, `/v1/images/${jobId}/retry`, {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export function imageResultUrl(jobId: string): string {
  return `${API_BASE_URL}/v1/images/${jobId}/result`;
}
