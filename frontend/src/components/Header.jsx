const TABS = [
  { id: "overview", label: "Overview" },
  { id: "progression", label: "Progression" },
  { id: "matches", label: "Matches" },
  { id: "opponents", label: "Opponent intel" },
  { id: "career", label: "Career" },
  { id: "coach", label: "Coach" },
  { id: "network", label: "Coaching Network" },
];

// Sentinel value for the "combined" option in the Gameplay dropdown - not a
// real job_id (real ones are 12-char uuid hex from backend/jobs.create_job),
// so it can never collide with an actual job. Selecting it means "show me
// everything combined" (matches, opponent intel, win-rate/matchup breakdowns
// merged across every completed Gameplay upload) instead of one upload's data
// - see App.jsx's openJob/loadCombined for how this is handled.
export const ALL_GAMEPLAY = "__all__";

export default function Header({ jobs, jobId, onJobChange, onRefresh, tab, onTabChange, userEmail, onSignOut, onNewJob }) {
  return (
    <header>
      <div className="header-top">
        <div className="brand">
          <h1>VGC Coach</h1>
          <span className="sub">Pokémon Champions performance dashboard</span>
        </div>
        <div className="header-controls">
          <label className="sub" htmlFor="job-select">Gameplay</label>
          <select id="job-select" value={jobId || ""} onChange={(e) => onJobChange(e.target.value)}>
            {!jobs.length && <option>(no gameplay yet)</option>}
            {!!jobs.length && <option value={ALL_GAMEPLAY}>All Gameplay (Combined)</option>}
            {jobs.map((j) => (
              <option key={j.job_id} value={j.job_id}>{j.name || j.job_id} ({j.status})</option>
            ))}
          </select>
          <button onClick={onRefresh}>Refresh</button>
          <button className="accent" onClick={onNewJob}>+ New Gameplay</button>
          {userEmail && (
            <>
              <span className="sub user-email">{userEmail}</span>
              <button onClick={onSignOut}>Sign out</button>
            </>
          )}
        </div>
      </div>
      <nav className="tabs">
        {TABS.map((t) => (
          <button
            key={t.id}
            className={`tab ${tab === t.id ? "active" : ""}`}
            onClick={() => onTabChange(t.id)}
          >
            {t.label}
          </button>
        ))}
      </nav>
    </header>
  );
}
