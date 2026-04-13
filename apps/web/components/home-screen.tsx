import { CreateJobForm } from "@/components/create-job-form";
import { HistoryList } from "@/components/history-list";

export function HomeScreen() {
  return (
    <main className="shell">
      <div className="shell__inner">
        <section className="hero">
          <div className="panel hero__lead">
            <div className="hero__eyebrow">Image Platform</div>
            <h1>Photoreal image jobs with remote GPU execution.</h1>
            <p>
              FastAPI, Redis, Postgres, S3-compatible storage, and a RunPod-ready worker pipeline built around
              FLUX.1 Krea [dev].
            </p>
          </div>
          <div className="panel hero__stats">
            <div className="stat">
              <div className="label">Modes</div>
              <strong>Photoreal</strong>
              <div className="muted">Single-model FLUX generation tuned for realistic photography.</div>
            </div>
            <div className="stat">
              <div className="label">Recovery</div>
              <strong>Heartbeat leases</strong>
              <div className="muted">Stale running jobs are requeued or failed by a separate reaper.</div>
            </div>
            <div className="stat">
              <div className="label">Storage</div>
              <strong>S3-compatible</strong>
              <div className="muted">Real remote execution serves results through object storage from day one.</div>
            </div>
          </div>
        </section>

        <section className="main-grid">
          <div className="panel form-panel">
            <div className="section-title">
              <div>
                <h2>Create job</h2>
                <p className="section-subtitle">Prompt, negative prompt, ratio, seed, and optional prompt enhancement flag.</p>
              </div>
            </div>
            <CreateJobForm />
          </div>

          <div className="panel history-panel">
            <div className="section-title">
              <div>
                <h2>History</h2>
                <p className="section-subtitle">Queued, running, succeeded, and failed jobs with direct drill-down into each run.</p>
              </div>
            </div>
            <HistoryList />
          </div>
        </section>
      </div>
    </main>
  );
}
