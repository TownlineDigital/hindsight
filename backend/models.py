"""
Pydantic request/response shapes for the API.

Kept deliberately small: most endpoints just pass through JSON that the
pipeline scripts already produce (events.json, matches.csv), so those don't
need their own models - a plain list/dict response is enough.
"""

from typing import Optional, Literal
from pydantic import BaseModel


class JobStatus(BaseModel):
    job_id: str
    status: Literal["queued", "running", "done", "failed"]
    step: str
    step_index: int
    total_steps: int
    matches_found: Optional[int] = None
    cost_estimate_usd: Optional[float] = None
    error: Optional[str] = None
    video: Optional[str] = None
    game: str
    mode: str
    regulation: Optional[str] = None
    source_type: Optional[str] = None


class CoachQuestion(BaseModel):
    question: str


class CoachAnswer(BaseModel):
    answer: str


class EventCorrection(BaseModel):
    """Body for PATCH /jobs/{id}/events/{index} - `fields` is a freeform dict
    merged into the existing event (only the keys you pass get overwritten,
    e.g. {"pokemon": "Charizard"} to fix a misread species). Events are
    themselves freeform dicts (see ARCHITECTURE_HANDOFF.md section 4), so
    this deliberately doesn't try to enumerate every possible field."""
    fields: dict


# -------------------------------------------------------- coach sharing -----
# See backend/coaching.py's module docstring for the full feature writeup
# (privacy model, what a coach can/can't see, why label/coach_label are two
# separate fields).

class ShareLinkCreate(BaseModel):
    label: Optional[str] = None
    expires_in_days: Optional[int] = None   # None = never expires, player's own choice


class RedeemShareLink(BaseModel):
    token: str


class RenameStudent(BaseModel):
    label: str


class NoteCreate(BaseModel):
    text: str
    category: Optional[str] = None   # freeform, e.g. "general" | "coaching_plan" | "skill_focus"


class NoteUpdate(BaseModel):
    text: Optional[str] = None
    category: Optional[str] = None


# ---------------------------------------------------------- telemetry -----
# See backend/audit.py's module docstring - this feeds the SAME internal
# audit log the action-level events (job_created, coach_question_asked,
# share_link_created, ...) already write to, just for frontend-only signals
# (tab views, UI interactions) that don't otherwise correspond to a backend
# call.

class ClientEvent(BaseModel):
    """Body for POST /telemetry/event. `payload` is a freeform dict (mirrors
    audit.record()'s own freeform design) so a new kind of frontend event to
    track never needs a model change - just a new event_type string and
    whatever fields make sense for it."""
    event_type: str
    payload: dict = {}
