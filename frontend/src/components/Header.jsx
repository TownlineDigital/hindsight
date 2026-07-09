const TABS = [
  { id: "overview", label: "Overview" },
  { id: "progression", label: "Progression" },
  { id: "matches", label: "Matches" },
  { id: "opponents", label: "Opponent intel" },
  { id: "career", label: "Career" },
  { id: "coach", label: "Coach" },
  { id: "network", label: "Coaching Network" },
];

export default function Header({ jobs, jobId, onJobChange, onRefresh, tab, onTabChange, userEmail, onSignOut, onNewJob }) {
  return (
    <header>
      <div className="header-top">
        <div className="brand">
          <h1>VGC Coach</h1>
          <span className="sub">Pokémon Champions performance dashboard</span>
        </div>
        <div className="header-controls">
          <label className="sub" htmlFor="job-select">Job</label>
          <select id="job-select" value={jobId || ""} onChange={(e) => onJobChange(e.target.value)}>
            {!jobs.length && <option>(no jobs yet)</option>}
            {jobs.map((j) => (
              <option key={j.job_id} value={j.job_id}>{j.job_id} ({j.status})</option>
            ))}
          </select>
          <button onClick={onRefresh}>Refresh</button>
          <button className="accent" onClick={onNewJob}>+ New job</button>
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
