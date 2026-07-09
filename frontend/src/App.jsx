import { useEffect, useMemo, useState } from "react";
import { api } from "./api.js";
import { supabase } from "./lib/supabase.js";
import Auth from "./components/Auth.jsx";
import Header, { ALL_GAMEPLAY } from "./components/Header.jsx";
import NewJobPanel from "./components/NewJobPanel.jsx";
import RecordCards from "./components/RecordCards.jsx";
import SkillScores from "./components/SkillScores.jsx";
import BattleProfile from "./components/BattleProfile.jsx";
import CoachingFlags from "./components/CoachingFlags.jsx";
import { WinRateTable, CountTable } from "./components/StatTable.jsx";
import MatchesTable from "./components/MatchesTable.jsx";
import OpponentStrength from "./components/OpponentStrength.jsx";
import CoachChat from "./components/CoachChat.jsx";
import CareerProgress from "./components/CareerProgress.jsx";
import CoachSharing from "./components/CoachSharing.jsx";
import StudentRoster from "./components/StudentRoster.jsx";
import GameplayDateFilter from "./components/GameplayDateFilter.jsx";
import PeriodComparison from "./components/PeriodComparison.jsx";
import JobProgress from "./components/JobProgress.jsx";
import { formatRangeLabel } from "./lib/dateRange.js";

function toRows(table) {
  return Object.entries(table || {})
    .map(([label, v]) => ({ label, wins: v.wins, total: v.total, winPct: v.win_pct }))
    .sort((a, b) => b.total - a.total);
}

function computeTrend(matches) {
  const decided = matches
    .filter((m) => m.winner === "player" || m.winner === "opponent")
    .sort((a, b) => a.match - b.match);
  let wins = 0;
  return decided.map((m, i) => {
    if (m.winner === "player") wins += 1;
    return Math.round((wins / (i + 1)) * 1000) / 10;
  });
}

export default function App() {
  // undefined = still checking with the backend, true = real sign-in
  // required, false = local dev mode (no Supabase configured server-side -
  // see backend/auth.py). Checked FIRST so we never show a sign-in screen
  // there's no way to complete, or wire up a Supabase listener that would
  // crash if the frontend's own env vars aren't set either.
  const [accountsRequired, setAccountsRequired] = useState(undefined);

  // undefined = still checking for an existing session, null = signed out,
  // an object = signed in. Only meaningful when accountsRequired === true.
  const [session, setSession] = useState(undefined);

  const [jobs, setJobs] = useState([]);
  const [jobId, setJobId] = useState(null);
  const [tab, setTab] = useState("overview");
  // Which half of the "Coaching Network" tab is showing - being coached
  // (share your own stats) vs being a coach (manage students). One account
  // can do both (see backend/coaching.py's docstring), so this is just a
  // view toggle, not a role setting.
  const [networkView, setNetworkView] = useState("share");
  const [data, setData] = useState(null);
  const [error, setError] = useState(null);
  const [loading, setLoading] = useState(true);
  const [showNewJob, setShowNewJob] = useState(false);
  // Set while a just-created job is still queued/running - lets the loading
  // banner show real progress ("compose_schema, step 2/8") instead of a bare
  // "Loading…", and is what the poll loop below checks to know when to stop.
  const [jobProgress, setJobProgress] = useState(null);

  // Career tab data - aggregated across EVERY completed job on this account
  // (see backend/career.py), not just the currently-selected job. Loaded
  // lazily the first time the tab is opened rather than on every dashboard
  // load, since most visits only look at one job at a time.
  const [careerData, setCareerData] = useState(null);
  const [careerLoading, setCareerLoading] = useState(false);
  const [careerError, setCareerError] = useState(null);

  // Date-range filter + period-comparison state for the combined "All
  // Gameplay" view (added 2026-07-09) - see GameplayDateFilter.jsx and
  // lib/dateRange.js for the {since, until} range shape. dateRange always
  // narrows the currently-loaded combined `data`; compareRange (when
  // non-null) is a SECOND window fetched separately into compareData, for
  // PeriodComparison.jsx's side-by-side stat cards in the Overview tab. Both
  // only ever apply while isCombined - a single job has no "date range" to
  // narrow, since it's already just the one Gameplay upload.
  const [dateRange, setDateRange] = useState({ since: null, until: null });
  const [compareRange, setCompareRange] = useState(null);
  const [compareData, setCompareData] = useState(null);
  const [compareLoading, setCompareLoading] = useState(false);
  const [compareError, setCompareError] = useState(null);

  async function loadJobs() {
    const list = await api.listJobs();
    list.sort((a, b) => (a.job_id > b.job_id ? 1 : -1));
    setJobs(list);
    if (!list.length) return null;
    // Default to the combined "All Gameplay" view rather than just the most
    // recent upload, as long as there's at least one completed job to
    // combine (career.merge_user_events only ever includes done jobs) - a
    // brand new account with only a still-processing job falls back to the
    // old "show me that job's progress" behavior instead, since there's
    // nothing yet to combine.
    const hasCompleted = list.some((j) => j.status === "done");
    const preferredId = hasCompleted
      ? ALL_GAMEPLAY
      : (list.find((j) => j.job_id === "demo") || list[0]).job_id;
    // Return the list alongside the pick, not just its id - the caller needs
    // the FRESH list (not React's possibly-still-stale `jobs` state right
    // after this setJobs() call) to correctly decide poll-vs-load below.
    return { list, preferredId };
  }

  async function loadDashboard(id) {
    if (!id) return;
    setError(null);
    setLoading(true);
    try {
      const [record, report, matches, opponentStrength, skillScores, events, battleProfile] = await Promise.all([
        api.record(id), api.report(id), api.matchesSummary(id), api.opponentStrength(id),
        api.skillScores(id), api.events(id), api.battleProfile(id),
      ]);
      setData({ record, report, matches, opponentStrength, skillScores, events, battleProfile });
    } catch (e) {
      setError(e.message);
      setData(null);
    } finally {
      setLoading(false);
    }
  }

  // The "All Gameplay (Combined)" view - same data shape as loadDashboard()
  // above (so every tab that reads `data` works unmodified), but sourced
  // from the /career/* endpoints, which merge every completed job's events
  // together (see backend/career.py's merge_user_events). Never needs
  // polling: merge_user_events only ever looks at jobs that are already
  // "done", so there's nothing here that could still be "running."
  async function loadCombinedDashboard(range) {
    setError(null);
    setLoading(true);
    try {
      const [record, report, matches, opponentStrength, skillScores, events, battleProfile] = await Promise.all([
        api.careerRecord(range), api.careerReport(range), api.careerMatches(range), api.careerOpponentStrength(range),
        api.careerSkillScores(range), api.careerEvents(range), api.careerBattleProfile(range),
      ]);
      setData({ record, report, matches, opponentStrength, skillScores, events, battleProfile });
    } catch (e) {
      setError(e.message);
      setData(null);
    } finally {
      setLoading(false);
    }
  }

  // Fetches Period B (compareRange) for PeriodComparison.jsx - only the two
  // pieces its stat cards actually need (record for win rate/wins-losses,
  // skillScores for the four skill scores + overall), not the full dashboard
  // shape loadCombinedDashboard() builds. Clears compareData back to null
  // when comparison is turned off (compareRange === null) rather than
  // leaving stale Period B numbers on screen.
  async function loadCompareData(range) {
    if (!range) {
      setCompareData(null);
      setCompareError(null);
      return;
    }
    setCompareError(null);
    setCompareLoading(true);
    try {
      const [record, skillScores] = await Promise.all([
        api.careerRecord(range), api.careerSkillScores(range),
      ]);
      setCompareData({ record, skillScores });
    } catch (e) {
      setCompareError(e.message);
      setCompareData(null);
    } finally {
      setCompareLoading(false);
    }
  }

  async function loadCareer() {
    setCareerError(null);
    setCareerLoading(true);
    try {
      const [record, report, skillScores, trend] = await Promise.all([
        api.careerRecord(), api.careerReport(), api.careerSkillScores(), api.careerSkillScoresTrend(),
      ]);
      setCareerData({ record, report, skillScores, trend });
    } catch (e) {
      setCareerError(e.message);
      setCareerData(null);
    } finally {
      setCareerLoading(false);
    }
  }

  // Called once a new job's created (NewJobPanel) or once an existing
  // queued/running job's picked from the dropdown - polls GET /jobs/{id}
  // every few seconds until it's done or failed, then loads the real
  // dashboard data (or surfaces the failure).
  async function pollJob(id) {
    try {
      const status = await api.jobStatus(id);
      // Clear any error left over from a PREVIOUSLY viewed job before acting
      // on this poll tick. Root cause of a real bug (2026-07-09): switching
      // the Gameplay dropdown from a failed job to a still-running one and
      // hitting Refresh correctly called this function with the right job
      // id (confirmed via network tab - the GET /jobs/{id} calls were all
      // hitting the NEW job and returning 200), but the OLD job's error
      // banner never disappeared, because the render below is gated on
      // `!error` (`{!error && loading && ...}`) and nothing on this path
      // ever reset `error` back to null - only loadDashboard/
      // loadCombinedDashboard and this function's own "done"/"failed"
      // branches did. So a stale "events.json not ready yet (job status:
      // failed...)" banner from the last job you looked at would just sit
      // there forever, silently blocking the progress bar from ever
      // showing up even though polling was working correctly underneath it.
      setError(null);
      if (status.status === "done") {
        setJobProgress(null);
        await loadDashboard(id);
        const list = await api.listJobs();
        list.sort((a, b) => (a.job_id > b.job_id ? 1 : -1));
        setJobs(list);
      } else if (status.status === "failed") {
        setJobProgress(null);
        setLoading(false);
        setError(`Job failed: ${status.error || "unknown error"}`);
      } else {
        setJobProgress(status);
        setTimeout(() => pollJob(id), 3000);
      }
    } catch (e) {
      setJobProgress(null);
      setLoading(false);
      setError(e.message);
    }
  }

  async function handleJobCreated(newJobId) {
    setShowNewJob(false);
    setError(null);
    setLoading(true);
    setJobId(newJobId);
    const list = await api.listJobs();
    list.sort((a, b) => (a.job_id > b.job_id ? 1 : -1));
    setJobs(list);
    pollJob(newJobId);
  }

  // The one place that decides "is this job still processing, or can we
  // safely fetch its analytics?" - reused by handleJobChange, the header's
  // refresh button, AND the initial-mount effect below, since all three
  // used to independently (and inconsistently) make this same decision.
  // Loading a queued/running job's dashboard data directly used to throw a
  // hard "events.json not ready yet" error instead of just polling - most
  // visible on a fresh account with no "done" job yet to prefer, where the
  // very first job (still running) becomes the initial pick. `list`
  // defaults to the current `jobs` state, but callers that just fetched a
  // fresh list themselves (loadJobs) should pass it explicitly rather than
  // rely on that state having already re-rendered.
  function openJob(id, list) {
    setJobId(id);
    if (id === ALL_GAMEPLAY) {
      loadCombinedDashboard(dateRange);
      if (compareRange) loadCompareData(compareRange);
      return;
    }
    const job = (list || jobs).find((j) => j.job_id === id);
    if (job && (job.status === "queued" || job.status === "running")) {
      // Clear immediately (not just inside pollJob) so switching from a
      // failed job straight to a running one never even flashes the old
      // error banner while the first status fetch is in flight.
      setError(null);
      setLoading(true);
      pollJob(id);
    } else {
      loadDashboard(id);
    }
  }

  function handleJobChange(id) {
    openJob(id);
  }

  // Step 1: ask the backend whether real accounts are required at all. Fails
  // open to local mode (rather than getting stuck on "Checking...") if even
  // this call can't reach the API, since a broken auth check shouldn't be
  // the reason the whole app refuses to render.
  useEffect(() => {
    api.authStatus()
      .then((r) => setAccountsRequired(!!r.accounts_required))
      .catch(() => setAccountsRequired(false));
  }, []);

  // Step 2: only wire up Supabase's session listener when accounts are
  // actually required - skipping this entirely in local dev mode is what
  // avoids ever touching a possibly-unconfigured `supabase` client.
  useEffect(() => {
    if (accountsRequired !== true || !supabase) return;
    supabase.auth.getSession().then(({ data }) => setSession(data.session));
    const { data: listener } = supabase.auth.onAuthStateChange((_event, newSession) => {
      setSession(newSession);
    });
    return () => listener.subscription.unsubscribe();
  }, [accountsRequired]);

  // "Ready" = either local dev mode (no sign-in needed), or accounts are
  // required AND we have a real session. Only then do the job list / dashboard
  // calls, which would otherwise 401.
  const ready = accountsRequired === false || (accountsRequired === true && !!session);
  useEffect(() => {
    if (!ready) return;
    (async () => {
      try {
        const result = await loadJobs();
        if (!result) { setLoading(false); return; }
        openJob(result.preferredId, result.list);
      } catch (e) {
        setError(`Couldn't reach the API: ${e.message}. Is uvicorn running?`);
        setLoading(false);
      }
    })();
  }, [ready]);

  // Load career data the first time the Career tab is opened (not on every
  // dashboard load - most visits only look at one job). Cheap to recompute
  // (see backend/career.py's docstring), so no invalidation logic needed;
  // this just avoids the wasted call on every other tab.
  useEffect(() => {
    if (ready && tab === "career" && !careerData && !careerLoading) {
      loadCareer();
    }
  }, [ready, tab]);

  // Is the Gameplay dropdown currently set to "All Gameplay (Combined)"? A
  // handful of child components (event correction, the coach's "this job"
  // scope) need to know this, since they depend on jobId being a REAL job -
  // see MatchesTable/MatchSummary's own comments on why correcting an event
  // computed against career.merge_user_events' merged array can't safely be
  // routed back to any single job's events.json. Declared here (rather than
  // just before use, below) so the two date-range effects that follow can
  // reference it.
  const isCombined = jobId === ALL_GAMEPLAY;

  // Refetch the combined dashboard whenever the date-range filter changes,
  // while already on "All Gameplay (Combined)" - openJob() handles the
  // initial load when the dropdown FIRST switches to combined, so this only
  // needs to fire on later range edits. Skipped entirely on a single-job
  // view: dateRange has no meaning there.
  useEffect(() => {
    if (ready && isCombined) loadCombinedDashboard(dateRange);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [dateRange]);

  // Fetch (or clear) Period B whenever the comparison range changes, while
  // in combined mode. Mirrors the dateRange effect above.
  useEffect(() => {
    if (ready && isCombined) loadCompareData(compareRange);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [compareRange]);

  const trend = useMemo(() => (data ? computeTrend(data.matches) : []), [data]);

  if (accountsRequired === undefined) {
    return <div className="banner info" style={{ margin: 24 }}>Checking…</div>;
  }
  if (accountsRequired === true && session === undefined) {
    return <div className="banner info" style={{ margin: 24 }}>Checking session…</div>;
  }
  if (accountsRequired === true && !session) {
    return <Auth />;
  }

  return (
    <div className="app">
      <Header
        jobs={jobs} jobId={jobId}
        onJobChange={handleJobChange}
        onRefresh={() => (tab === "career" ? loadCareer() : openJob(jobId))}
        tab={tab}
        onTabChange={(nextTab) => { setTab(nextTab); api.track("tab_viewed", { tab: nextTab }); }}
        userEmail={accountsRequired ? session.user?.email : null}
        onSignOut={accountsRequired ? () => supabase.auth.signOut() : undefined}
        onNewJob={() => { setShowNewJob(true); api.track("new_job_panel_opened"); }}
      />
      {showNewJob && (
        <NewJobPanel onClose={() => setShowNewJob(false)} onJobCreated={handleJobCreated} />
      )}
      <main>
        {error && <div className="banner">{error}</div>}
        {!error && loading && jobProgress && (
          <JobProgress jobId={jobId} jobProgress={jobProgress} />
        )}
        {!error && loading && !jobProgress && <div className="banner info">Loading…</div>}
        {!error && !loading && !data && <div className="banner">No Gameplay yet. Click "+ New Gameplay" above, or run seed_demo_job.py.</div>}

        {!error && data && isCombined &&
          (tab === "overview" || tab === "progression" || tab === "matches" || tab === "opponents") && (
          <GameplayDateFilter
            range={dateRange}
            onRangeChange={setDateRange}
            compareRange={compareRange}
            onCompareRangeChange={setCompareRange}
          />
        )}

        {!error && data && (
          <>
            {tab === "overview" && (
              <div className="tab-panel">
                <section>
                  <RecordCards record={data.record} report={data.report} trend={trend} />
                </section>
                {isCombined && compareRange && (
                  <section>
                    {compareError && <div className="banner">{compareError}</div>}
                    {!compareError && compareLoading && <div className="banner info">Loading comparison period…</div>}
                    {!compareError && !compareLoading && compareData && (
                      <PeriodComparison
                        periodALabel={formatRangeLabel(dateRange)}
                        periodBLabel={formatRangeLabel(compareRange)}
                        periodAData={{ record: data.record, skillScores: data.skillScores }}
                        periodBData={compareData}
                      />
                    )}
                  </section>
                )}
                <section>
                  <h2>Coaching flags</h2>
                  <CoachingFlags flags={data.report.flags} />
                </section>
              </div>
            )}

            {tab === "progression" && (
              <div className="tab-panel">
                <section>
                  <h2>Skill scores</h2>
                  <SkillScores data={data.skillScores} />
                </section>
                <section>
                  <h2>Overall battle profile</h2>
                  <BattleProfile data={data.battleProfile} />
                </section>
                <section>
                  <div className="two-col">
                    <WinRateTable title="Win rate by lead" rows={toRows(data.record.by_lead)} />
                    <WinRateTable title="Win rate by bring" rows={toRows(data.record.by_bring)} />
                  </div>
                </section>
                <section>
                  <div className="two-col">
                    <WinRateTable
                      title="Toughest matchups"
                      rows={data.report.toughest_matchups.map((m) => ({ label: m.pokemon, wins: m.wins, total: m.total, winPct: m.win_pct }))}
                    />
                    <CountTable
                      title="Most used Pokémon"
                      rows={data.report.most_used_pokemon.map(([label, count]) => ({ label, count }))}
                    />
                  </div>
                </section>
              </div>
            )}

            {tab === "matches" && (
              <div className="tab-panel">
                <section>
                  <MatchesTable
                    matches={data.matches}
                    events={data.events}
                    jobId={jobId}
                    isCombined={isCombined}
                    onCorrected={() => (isCombined ? loadCombinedDashboard(dateRange) : loadDashboard(jobId))}
                  />
                </section>
              </div>
            )}

            {tab === "opponents" && (
              <div className="tab-panel">
                <section>
                  <OpponentStrength data={data.opponentStrength} />
                </section>
              </div>
            )}

            {tab === "career" && (
              <>
                {careerError && <div className="banner">{careerError}</div>}
                {!careerError && careerLoading && <div className="banner info">Loading career data…</div>}
                {!careerError && !careerLoading && <CareerProgress data={careerData} />}
              </>
            )}

            {tab === "coach" && (
              <div className="tab-panel">
                <section>
                  <CoachChat jobId={isCombined ? null : jobId} forceCareer={isCombined} />
                </section>
              </div>
            )}

            {tab === "network" && (
              <div className="tab-panel">
                <div className="tabs-inline small" style={{ marginBottom: 4 }}>
                  <button
                    className={`tab-inline ${networkView === "share" ? "active" : ""}`}
                    onClick={() => { setNetworkView("share"); api.track("network_view_toggled", { view: "share" }); }}
                  >
                    Share your stats
                  </button>
                  <button
                    className={`tab-inline ${networkView === "students" ? "active" : ""}`}
                    onClick={() => { setNetworkView("students"); api.track("network_view_toggled", { view: "students" }); }}
                  >
                    Your students
                  </button>
                </div>
                {networkView === "share" ? <CoachSharing /> : <StudentRoster />}
              </div>
            )}
          </>
        )}
      </main>
    </div>
  );
}
