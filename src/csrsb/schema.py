"""Shared schema for recordings.

Both the desktop recorder and the browser extension emit events conforming to
``Recording``. The translator consumes only this shape — it never branches on
the recording surface.

The schema is intentionally wider than Phase 1 needs (drag, file upload,
clipboard, focus changes, etc.) so that adding the browser extension and
richer desktop capture in later phases doesn't require a schema migration.
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field

SCHEMA_VERSION = "1.0"

EventType = Literal[
    "click",
    "key",
    "input",
    "navigate",
    "scroll",
    "screenshot",
    "annotation",
    "wait",
    "drag",
    "drop",
    "file_upload",
    "clipboard",
    "focus_change",
    "tab_open",
    "tab_close",
    "tab_switch",
    "hover",
    "dom_settled",
    "network_idle",
    "screen_changed",
]

Surface = Literal["browser", "desktop"]


class SelectorAlternatives(BaseModel):
    """Ranked selector strategies for the same target element.

    Translator picks the most semantic one (testid > role+name > text >
    css > xpath) when describing a step.
    """

    model_config = ConfigDict(extra="ignore")

    css: Optional[str] = None
    xpath: Optional[str] = None
    aria: Optional[str] = None
    text: Optional[str] = None
    testid: Optional[str] = None
    role_name: Optional[str] = None


class ViewportBox(BaseModel):
    """Pixel rectangle of the target element within the screenshot."""

    model_config = ConfigDict(extra="ignore")

    x: int
    y: int
    w: int
    h: int


class Target(BaseModel):
    """The element or region being acted on."""

    model_config = ConfigDict(extra="ignore")

    selector_alternatives: SelectorAlternatives = Field(default_factory=SelectorAlternatives)
    frame_path: list[str] = Field(default_factory=list)
    shadow_path: list[str] = Field(default_factory=list)
    url: Optional[str] = None
    viewport_box: Optional[ViewportBox] = None
    accessible_name: Optional[str] = None
    window_title: Optional[str] = None
    app_name: Optional[str] = None


class Viewport(BaseModel):
    model_config = ConfigDict(extra="ignore")

    w: int
    h: int
    dpr: float = 1.0
    zoom: float = 1.0


class Event(BaseModel):
    """One recorded user action."""

    model_config = ConfigDict(extra="ignore")

    id: str
    ts_ms: int
    surface: Surface
    type: EventType
    target: Target = Field(default_factory=Target)
    value: Any = None
    screenshot_path: Optional[str] = None
    viewport: Optional[Viewport] = None
    redacted: bool = False
    notes: Optional[str] = None


class RecordingMetadata(BaseModel):
    model_config = ConfigDict(extra="ignore")

    os: Optional[str] = None
    browser: Optional[str] = None
    viewport: Optional[Viewport] = None
    user_intent_hint: Optional[str] = None


class Annotation(BaseModel):
    """A free-text note the user added during recording (e.g. via hotkey)."""

    model_config = ConfigDict(extra="ignore")

    ts_ms: int
    text: str


class Recording(BaseModel):
    """Top-level recording produced by a recorder, consumed by the translator."""

    model_config = ConfigDict(extra="ignore")

    version: str = SCHEMA_VERSION
    surface: Surface
    started_at: datetime
    ended_at: datetime
    metadata: RecordingMetadata = Field(default_factory=RecordingMetadata)
    events: list[Event] = Field(default_factory=list)
    notes: list[Annotation] = Field(default_factory=list)

    @classmethod
    def from_dir(cls, recording_dir: Path) -> "Recording":
        """Load a recording from ``<dir>/recording.json``."""
        path = Path(recording_dir) / "recording.json"
        return cls.model_validate_json(path.read_text(encoding="utf-8"))

    def write_to_dir(self, recording_dir: Path) -> Path:
        """Serialize to ``<dir>/recording.json``. Returns the file path."""
        recording_dir = Path(recording_dir)
        recording_dir.mkdir(parents=True, exist_ok=True)
        out = recording_dir / "recording.json"
        out.write_text(self.model_dump_json(indent=2, exclude_none=True), encoding="utf-8")
        return out


class Step(BaseModel):
    """One semantic step in the generated skill — produced by the translator
    from a contiguous run of events."""

    model_config = ConfigDict(extra="ignore")

    index: int
    title: str
    goal: str
    action: str
    expected_result: str
    fallback: Optional[str] = None
    screenshot_path: Optional[str] = None
    source_event_ids: list[str] = Field(default_factory=list)


class SkillDraft(BaseModel):
    """The output of the translator pipeline, ready to be written by the builder."""

    model_config = ConfigDict(extra="ignore")

    name: str
    description: str
    title: str
    when_to_use: list[str] = Field(default_factory=list)
    prerequisites: list[str] = Field(default_factory=list)
    inputs: list[str] = Field(default_factory=list)
    high_level_approach: str
    steps: list[Step]
    success_criteria: list[str] = Field(default_factory=list)
    failure_modes: list[str] = Field(default_factory=list)
    surface: Surface
