import { useEffect, useState } from "react";
import { api } from "../api.js";
import { LOW_CONFIDENCE_THRESHOLD } from "../lib/confidence.js";

// Bookkeeping fields every event carries that aren't meaningful to hand-edit
// (either derived/internal, or already shown elsewhere in the row). Note
// "confidence" is deliberately NOT hidden anymore - it used to be filtered
// out entirely, which meant there was no quick way to tell a solid AI read
// from a shaky one without opening the raw events.json. It's now surfaced
// as its own badge (see confidenceBadge()) instead of a plain editable field.
const HIDDEN_FIELDS = new Set([
  "match", "timestamp", "confidence", "reference_frame",
  "corrected", "corrected_at", "corrected_by", "actor",
  "roster_conflict", "roster_conflict_species",
]);

// Below this, an event gets a visible "worth checking" flag - not because
// anything's necessarily wrong, but because it's the AI's own signal that
// this particular read is less certain than most. 0.9 was picked by looking
// at real extracted data: routine field_state reads come back at a full
// 1.0, while reads that involved some inference or a fuzzy species match
// (team_preview, pokemon_fainted) commonly land around 0.8 - including a
// real misread this threshold was tuned to actually catch (an opponent's
// Pokemon reported as "Charizard" while the event's own detail text said
// "Staraptor fainted", a genuine name-canonicalization mismatch).
function confidenceBadge(confidence) {
  if (typeof confidence !== "number") return null;
  const pct = Math.round(confidence * 100);
  let cls = "good";
  if (confidence < 0.7) cls = "bad";
  else if (confidence < LOW_CONFIDENCE_THRESHOLD) cls = "warn";
  return (
    <span className={`badge ${cls}`} title="How confident the AI was in this specific read">
      {pct}%
    </span>
  );
}

// Exported so BattleReplay.jsx can reuse the same blob-URL-loading-with-
// cleanup logic instead of duplicating it - the object-URL revoke-on-unmount
// behavior below is easy to get subtly wrong (a leaked blob URL per
// thumbnail shown), so one shared implementation is worth it.
export function EventThumb({ jobId, framePath, onEnlarge }) {
  const [src, setSrc] = useState(null);
  const [failed, setFailed] = useState(false);

  useEffect(() => {
    let objectUrl = null;
    let cancelled = false;
    setSrc(null);
    setFailed(false);
    api.frameBlobUrl(jobId, framePath)
      .then((url) => {
        if (cancelled) { URL.revokeObjectURL(url); return; }
        objectUrl = url;
        setSrc(url);
      })
      .catch(() => { if (!cancelled) setFailed(true); });
    // Revoke the object URL on unmount/change - otherwise every thumbnail
    // ever shown leaks memory for the rest of the tab's life.
    return () => {
      cancelled = true;
      if (objectUrl) URL.revokeObjectURL(objectUrl);
    };
  }, [jobId, framePath]);

  if (failed) return <div className="event-thumb missing">no image</div>;
  if (!src) return <div className="event-thumb loading">…</div>;
  return (
    <img
      className="event-thumb clickable"
      src={src}
      alt="reference frame the AI used for this event - click to enlarge"
      onClick={() => onEnlarge(src)}
    />
  );
}

// A larger, full-quality view of one reference frame - the small 96x54
// thumbnail is enough to orient at a glance, but genuinely judging whether
// the AI's read matches the screen (a health bar, on-screen text, which
// Pokemon is actually active) needs more than a postage stamp.
export function ImageLightbox({ src, onClose }) {
  return (
    <div className="modal-backdrop" onClick={onClose}>
      <div className="modal image-modal" onClick={(e) => e.stopPropagation()}>
        <div className="modal-header">
          <h3>Reference frame</h3>
          <button type="button" className="modal-close" onClick={onClose}>✕</button>
        </div>
        <img className="modal-image" src={src} alt="enlarged reference frame" />
      </div>
    </div>
  );
}

function EventRow({ jobId, event, onSaved }) {
  const [editing, setEditing] = useState(false);
  const [fields, setFields] = useState({});
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState(null);
  const [enlargedSrc, setEnlargedSrc] = useState(null);
  // Set right after a successful save, cleared on the next edit - lets the
  // "also fixed N other events" note (see save() below) survive the
  // onSaved() reload that replaces this row's own event prop, instead of
  // disappearing the instant the dashboard refetches.
  const [cascadeNote, setCascadeNote] = useState(null);

  const editableKeys = Object.keys(event).filter((k) => !HIDDEN_FIELDS.has(k) && k !== "__idx");
  // "detail" is still a normal editable field (correctable like any other -
  // sometimes the AI's own reasoning text is what's wrong, not just
  // "pokemon" or another data field), but it gets its own prominent block
  // when NOT editing rather than blending into the plain key/value list -
  // it's the closest thing to "why the AI concluded this" that already
  // exists in the data, so it shouldn't be easy to skim past.
  const otherKeys = editableKeys.filter((k) => k !== "detail");

  const confidence = typeof event.confidence === "number" ? event.confidence : null;
  const lowConfidence = confidence !== null && confidence < LOW_CONFIDENCE_THRESHOLD;
  // See analyze_matches.flag_roster_conflicts: much rarer and more actionable
  // than generic low confidence - the AI's raw read WAS a real, legal species,
  // just not one this match's roster read had identified. Confirmed via a
  // real human-review session against actual footage (a "Kingambit" case
  // where the on-screen text literally named it, yet it still got swapped
  // for a different Pokemon because the roster read missed it).
  const rosterConflict = event.roster_conflict === true;

  function startEdit() {
    const initial = {};
    editableKeys.forEach((k) => { initial[k] = event[k] ?? ""; });
    setFields(initial);
    setError(null);
    setCascadeNote(null);
    setEditing(true);
  }

  async function save() {
    setSaving(true);
    setError(null);
    // Only send fields that actually changed - the backend merges whatever
    // it gets into the existing event, so an untouched field is left alone
    // either way, but this keeps the audit-log "before/after" diff honest.
    const changed = {};
    editableKeys.forEach((k) => {
      if (String(fields[k] ?? "") !== String(event[k] ?? "")) changed[k] = fields[k];
    });
    if (!Object.keys(changed).length) {
      setEditing(false);
      setSaving(false);
      return;
    }
    try {
      const result = await api.correctEvent(jobId, event.__idx, changed);
      // Correcting `pokemon` cascades to every other event in this match on
      // the same side that had the same wrong name (see backend/
      // event_corrections.py) - surface that so it's obvious the fix wasn't
      // just cosmetic on this one row. onSaved() below reloads the whole
      // dashboard (Record/Report/Skill Scores all recompute from the now-
      // corrected events.json), so this note is the only visual confirmation
      // the cascade actually happened before this row's own props refresh.
      const n = (result.cascaded_indices || []).length;
      setCascadeNote(n > 0 ? `Also fixed ${n} other event${n === 1 ? "" : "s"} with the same misread Pokémon in this match.` : null);
      setEditing(false);
      onSaved();
    } catch (e) {
      setError(e.message);
    } finally {
      setSaving(false);
    }
  }

  return (
    <div className={`event-row ${event.corrected ? "corrected" : ""} ${rosterConflict ? "roster-conflict" : lowConfidence ? "low-confidence" : ""}`}>
      {event.reference_frame
        ? <EventThumb jobId={jobId} framePath={event.reference_frame} onEnlarge={setEnlargedSrc} />
        : <div className="event-thumb missing">no photo</div>}
      <div className="event-body">
        <div className="event-top">
          <span className="event-time">
            {typeof event.timestamp === "number" ? `${event.timestamp.toFixed(1)}s` : String(event.timestamp ?? "–")}
          </span>
          <span className="event-type">{event.event}</span>
          {confidenceBadge(confidence)}
          {rosterConflict ? (
            <span
              className="badge conflict"
              title={`The AI's raw on-screen read (${(event.roster_conflict_species || []).join(", ")}) IS a real, legal Pokemon in this format - it just wasn't in this match's identified roster, so it got swapped for a different species. Worth checking whether the roster read missed this Pokemon, rather than the AI having misread the screen.`}
            >
              ⚠ possible roster miss ({(event.roster_conflict_species || []).join(", ")})
            </span>
          ) : lowConfidence && (
            <span className="badge warn" title="Below 90% confidence - the AI itself flagged this read as less certain, worth a second look">
              ⚠ worth checking
            </span>
          )}
          {event.corrected && <span className="badge good" title="Manually corrected by a user">✓ corrected</span>}
        </div>

        {cascadeNote && <div className="cascade-note">{cascadeNote}</div>}

        {event.detail && (
          <div className="event-reasoning">
            <b>AI's reasoning:</b> {String(event.detail)}
          </div>
        )}

        {!editing && (
          <>
            <div className="event-detail">
              {otherKeys.map((k) => (
                <span key={k} className="event-field"><b>{k}:</b> {String(event[k] ?? "–")}</span>
              ))}
            </div>
            <button type="button" className="event-edit-btn" onClick={startEdit}>Correct this</button>
          </>
        )}

        {editing && (
          <div className="event-edit-form">
            {editableKeys.map((k) => (
              <label key={k} className="field small">
                <span>{k}</span>
                <input
                  value={fields[k] ?? ""}
                  onChange={(e) => setFields((f) => ({ ...f, [k]: e.target.value }))}
                />
              </label>
            ))}
            {error && <div className="banner">{error}</div>}
            <div className="event-edit-actions">
              <button type="button" onClick={() => setEditing(false)} disabled={saving}>Cancel</button>
              <button type="button" onClick={save} disabled={saving}>{saving ? "Saving…" : "Save"}</button>
            </div>
          </div>
        )}
      </div>

      {enlargedSrc && <ImageLightbox src={enlargedSrc} onClose={() => setEnlargedSrc(null)} />}
    </div>
  );
}

// Renders one match's events (filtered from the job's full flat events list)
// with a reference-frame thumbnail per event and an inline correction form -
// see backend's GET /jobs/{id}/frame/{path} and PATCH /jobs/{id}/events/{index}.
// `__idx` (the position in the FULL events array, not this filtered list) is
// what the PATCH endpoint's {index} actually addresses, so it's attached
// before filtering rather than recomputed from the filtered list's own order.
export default function MatchEvents({ jobId, events, matchNumber, onCorrected }) {
  const matchEvents = (events || [])
    .map((e, i) => ({ ...e, __idx: i }))
    .filter((e) => e.match === matchNumber)
    .sort((a, b) => (a.timestamp ?? 0) - (b.timestamp ?? 0));

  if (!matchEvents.length) {
    return <div className="empty">No events recorded for this match.</div>;
  }

  // team_preview used to just blend into the flat chronological list (it
  // sorts first, since its timestamp is 30s before the match "starts") with
  // no visual distinction from any other event - easy to scroll past without
  // recognizing it as THE team preview. It's still rendered with the exact
  // same EventRow (same correction form, same fields) - just pulled out and
  // given its own labeled section so the full roster/brought/lead read is
  // easy to find and doesn't look like just another event in the pile.
  const teamPreview = matchEvents.find((e) => e.event === "team_preview");
  const otherEvents = matchEvents.filter((e) => e.event !== "team_preview");

  return (
    <div className="match-events">
      {teamPreview && (
        <div className="team-preview-section">
          <h4 className="team-preview-heading">Team Preview</h4>
          <EventRow jobId={jobId} event={teamPreview} onSaved={onCorrected} />
        </div>
      )}
      {otherEvents.map((e) => (
        <EventRow key={e.__idx} jobId={jobId} event={e} onSaved={onCorrected} />
      ))}
    </div>
  );
}
