"use client";

import { ImageJob, isTerminalStatus } from "@image-platform/shared";
import Link from "next/link";
import { useCallback, useEffect, useState } from "react";

import { fetchImageJobs, imageResultUrl } from "@/lib/api";

function formatDate(value: string) {
  return new Intl.DateTimeFormat(undefined, {
    dateStyle: "medium",
    timeStyle: "short",
  }).format(new Date(value));
}

export function HistoryList() {
  const [jobs, setJobs] = useState<ImageJob[]>([]);
  const [nextCursor, setNextCursor] = useState<string | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  const [isLoadingMore, setIsLoadingMore] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const loadJobs = useCallback(async (cursor?: string) => {
    try {
      if (cursor) {
        setIsLoadingMore(true);
      } else {
        setIsLoading(true);
      }
      const response = await fetchImageJobs(cursor);
      setJobs((current) => (cursor ? [...current, ...response.items] : response.items));
      setNextCursor(response.next_cursor);
      setError(null);
    } catch (loadError) {
      setError(loadError instanceof Error ? loadError.message : "Unable to load jobs.");
    } finally {
      setIsLoading(false);
      setIsLoadingMore(false);
    }
  }, []);

  useEffect(() => {
    void loadJobs();
  }, [loadJobs]);

  return (
    <div className="history-list">
      {error ? <div className="error">{error}</div> : null}
      {isLoading ? <div className="muted">Loading history...</div> : null}
      {!isLoading && jobs.length === 0 ? <div className="muted">No generation jobs yet.</div> : null}

      {jobs.map((job) => (
        <Link href={`/images/${job.id}`} key={job.id} className="job-card">
          <div className="job-card__thumb">
            {job.status === "succeeded" ? (
              <img src={imageResultUrl(job.id)} alt={job.prompt_original} />
            ) : (
              <div style={{ padding: 18 }}>
                <div className="badge" data-status={job.status}>
                  {job.status}
                </div>
              </div>
            )}
          </div>
          <div className="job-card__meta">
            <div className="badge" data-status={job.status}>
              {job.status}
            </div>
            <h3>{job.prompt_original}</h3>
            <div className="muted">{job.mode} · {job.aspect_ratio} · seed {job.seed}</div>
            <div className="muted mono">{formatDate(job.created_at)}</div>
            {!isTerminalStatus(job.status) ? (
              <>
                <div className="progress">
                  <span style={{ width: `${job.progress_percent}%` }} />
                </div>
                <div className="muted">{job.progress_stage}</div>
              </>
            ) : null}
            {job.error_message ? <div className="error">{job.error_message}</div> : null}
          </div>
        </Link>
      ))}

      {nextCursor ? (
        <button
          className="button button--secondary"
          type="button"
          disabled={isLoadingMore}
          onClick={() => void loadJobs(nextCursor)}
        >
          {isLoadingMore ? "Loading more..." : "Load more"}
        </button>
      ) : null}
    </div>
  );
}
