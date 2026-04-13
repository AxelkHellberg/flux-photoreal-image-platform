"use client";

import { ImageJob, isTerminalStatus } from "@image-platform/shared";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { startTransition, useCallback, useEffect, useState } from "react";

import { fetchImageJob, imageResultUrl, retryImageJob } from "@/lib/api";

function formatDate(value: string | null) {
  if (!value) return "-";
  return new Intl.DateTimeFormat(undefined, {
    dateStyle: "medium",
    timeStyle: "short",
  }).format(new Date(value));
}

export function JobDetailScreen({ jobId }: { jobId: string }) {
  const router = useRouter();
  const [job, setJob] = useState<ImageJob | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [isRetrying, setIsRetrying] = useState<"same" | "new" | null>(null);

  const refreshJob = useCallback(async () => {
    try {
      const response = await fetchImageJob(jobId);
      setJob(response);
      setError(null);
    } catch (refreshError) {
      setError(refreshError instanceof Error ? refreshError.message : "Unable to load job details.");
    }
  }, [jobId]);

  useEffect(() => {
    void refreshJob();
  }, [refreshJob]);

  useEffect(() => {
    if (!job || isTerminalStatus(job.status)) {
      return;
    }

    const timer = window.setInterval(() => {
      void refreshJob();
    }, 3000);

    return () => window.clearInterval(timer);
  }, [job, refreshJob]);

  async function triggerRetry(seedStrategy: "same" | "new") {
    setIsRetrying(seedStrategy);
    try {
      const nextJob = await retryImageJob(jobId, { seed_strategy: seedStrategy });
      startTransition(() => router.push(`/images/${nextJob.id}`));
    } catch (retryError) {
      setError(retryError instanceof Error ? retryError.message : "Unable to retry the job.");
    } finally {
      setIsRetrying(null);
    }
  }

  return (
    <main className="shell">
      <div className="shell__inner detail-panel panel">
        <div className="section-title detail-header">
          <div>
            <div className="hero__eyebrow">Job detail</div>
            <h1>{job?.prompt_original ?? "Loading job..."}</h1>
            <p className="section-subtitle">Track progress, download the result, or retry with the same or a fresh seed.</p>
          </div>
          <Link href="/" className="button button--secondary">
            Back to queue
          </Link>
        </div>

        {error ? <div className="error">{error}</div> : null}

        {!job ? (
          <div className="muted">Loading job...</div>
        ) : (
          <div className="detail-layout">
            <div className="detail-meta">
              <div className="detail-image">
                {job.status === "succeeded" ? (
                  <img src={imageResultUrl(job.id)} alt={job.prompt_original} />
                ) : (
                  <div style={{ padding: 24 }}>
                    <div className="badge" data-status={job.status}>
                      {job.status}
                    </div>
                    <div style={{ marginTop: 16 }} className="progress">
                      <span style={{ width: `${job.progress_percent}%` }} />
                    </div>
                    <p className="muted">{job.progress_stage}</p>
                  </div>
                )}
              </div>

              <div className="toolbar">
                <button className="button button--secondary" type="button" onClick={() => void refreshJob()}>
                  Refresh
                </button>
                <button className="button button--secondary" type="button" disabled={Boolean(isRetrying)} onClick={() => void triggerRetry("same")}>
                  {isRetrying === "same" ? "Retrying..." : "Retry same seed"}
                </button>
                <button className="button button--secondary" type="button" disabled={Boolean(isRetrying)} onClick={() => void triggerRetry("new")}>
                  {isRetrying === "new" ? "Retrying..." : "Retry new seed"}
                </button>
                {job.status === "succeeded" ? (
                  <a className="button" href={imageResultUrl(job.id)} download>
                    Download image
                  </a>
                ) : null}
              </div>

              {job.error_message ? <div className="error">{job.error_message}</div> : null}
            </div>

            <div className="detail-meta">
              <div className="badge" data-status={job.status}>
                {job.status}
              </div>
              <div className="meta-grid">
                <div className="meta-card">
                  <div className="label">Mode</div>
                  <strong>{job.mode}</strong>
                </div>
                <div className="meta-card">
                  <div className="label">Aspect ratio</div>
                  <strong>{job.aspect_ratio}</strong>
                </div>
                <div className="meta-card">
                  <div className="label">Seed</div>
                  <strong className="mono">{job.seed}</strong>
                </div>
                <div className="meta-card">
                  <div className="label">Attempts</div>
                  <strong>{job.attempt_count} / {job.max_attempts}</strong>
                </div>
                <div className="meta-card">
                  <div className="label">Created</div>
                  <strong>{formatDate(job.created_at)}</strong>
                </div>
                <div className="meta-card">
                  <div className="label">Heartbeat</div>
                  <strong>{formatDate(job.heartbeat_at)}</strong>
                </div>
              </div>

              <div className="meta-card">
                <div className="label">Prompt used</div>
                <strong>{job.prompt_final}</strong>
              </div>

              <div className="meta-card">
                <div className="label">Negative prompt</div>
                <strong>{job.negative_prompt || "-"}</strong>
              </div>

              <div className="meta-card">
                <div className="label">Generation params</div>
                <pre className="mono" style={{ whiteSpace: "pre-wrap", margin: 0 }}>{JSON.stringify(job.generation_params, null, 2)}</pre>
              </div>
            </div>
          </div>
        )}
      </div>
    </main>
  );
}
