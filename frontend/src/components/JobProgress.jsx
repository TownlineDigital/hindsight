import { useEffect, useRef, useState } from "react";
import { api } from "../api.js";

// Shown while a Gameplay upload is queued/running (App.jsx's `loading` +
// `jobProgress` state) - added 2026-07-09, direct user request: "is there a
// way to add some kind of visual component to the progress bar? maybe the
// bar slowly fills up and previews the frames being analyzed as it loads?"
//
// Two real, honest signals drive this (nothing here is faked/simulated):
//   1. jobProgress.step_index/total_steps - which of the ~8 pipeline steps
//      (get_video, compose_schema, structure_pass, analyze_matches, ...)
//      is currently running. Coarse: analyze_matches is by far the longest
//      step and this alone would leave the bar sitting still for most of a
//      job's runtime.
//   2. GET /jobs/{id}/latest-frame, polled every 2.5s - whichever frame
//      image was most recently written to disk (see backend/job_files.
//      latest_frame_path). structure_pass.py and analyze_matches.py both
//      write frames to disk continuously as they work, even though they run
//      as blocking subprocesses with no in-process progress callback (see
//      pipeline._run's docstring) - polling "what's newest on disk" is a
//      genuine live signal of real work happening, not a fake animation.
//
// The bar's fill % combines both: a base position from step_index (the 8
// coarse steps divide the bar into 8 blocks), plus a small "creep" within
// the CURRENT block that nudges forward every time a genuinely NEW frame
// appears - capped well short of the next block's boundary, so it never
// overtakes step_index's own jump to the next step. This is what makes the
// bar visibly "slowly fill up" during the long analyze_matches step instead
// of sitting frozen at one number for minutes, while still being driven by
// real activity rather than a canned animation.
export default function JobProgress({ jobId, jobProgress }) {
  const [frameUrl, setFrameUrl] = useState(null);
  const [creep, setCreep] = useState(0);
  const lastPathRef = useRef(null);
  const urlRef = useRef(null);
  const lastStepRef = useRef(null);

  useEffect(() => {
    if (!jobId) return undefined;
    let cancelled = false;
    let timer = null;

    async function poll() {
      try {
        const { path } = await api.latestFrame(jobId);
        if (cancelled) return;
        if (path && path !== lastPathRef.current) {
          lastPathRef.current = path;
          setCreep((c) => c + 1);
          const url = await api.frameBlobUrl(jobId, path);
          if (cancelled) {
            URL.revokeObjectURL(url);
            return;
          }
          if (urlRef.current) URL.revokeObjectURL(urlRef.current);
          urlRef.current = url;
          setFrameUrl(url);
        }
      } catch {
        // A failed poll just means no preview update this tick - the loading
        // banner itself already has its own error handling elsewhere; this
        // is a nice-to-have, not worth surfacing its own error banner for.
      } finally {
        if (!cancelled) timer = setTimeout(poll, 2500);
      }
    }
    poll();

    return () => {
      cancelled = true;
      if (timer) clearTimeout(timer);
      if (urlRef.current) URL.revokeObjectURL(urlRef.current);
    };
  }, [jobId]);

  // Reset the within-step creep whenever the pipeline actually advances to a
  // new named step - otherwise the creep from a long analyze_matches run
  // would carry over and make the NEXT step start already part-full.
  const stepIndex = jobProgress?.step_index ?? 0;
  useEffect(() => {
    if (lastStepRef.current !== stepIndex) {
      lastStepRef.current = stepIndex;
      setCreep(0);
    }
  }, [stepIndex]);

  const totalSteps = jobProgress?.total_steps || 1;
  const stepSpan = 100 / totalSteps;
  const stepBase = stepIndex * stepSpan;
  // Each new frame nudges the bar ~6% of one step's width, capped at 80% of
  // the way into the current step - leaves visible headroom so the jump to
  // the NEXT step (driven by real step_index, not this creep) always reads
  // as forward progress rather than the bar appearing to reverse.
  const creepPct = Math.min(stepSpan * 0.8, creep * stepSpan * 0.06);
  const pct = jobProgress ? Math.min(99, Math.round(stepBase + creepPct)) : 0;

  return (
    <div className="card job-progress">
      <div className="job-progress-top">
        <span className="job-progress-label">
          {jobProgress
            ? `${jobProgress.step} (step ${stepIndex + 1}/${totalSteps})…`
            : "Loading…"}
        </span>
        <span className="job-progress-pct">{pct}%</span>
      </div>
      <div className="job-progress-track">
        <div className="job-progress-fill" style={{ width: `${pct}%` }} />
      </div>
      {frameUrl && (
        <div className="job-progress-preview">
          <img src={frameUrl} alt="Frame currently being analyzed" />
          <div className="job-progress-preview-caption">Currently analyzing this frame…</div>
        </div>
      )}
    </div>
  );
}
