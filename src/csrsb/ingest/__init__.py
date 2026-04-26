"""Ingest layer: normalize raw recorder output into the schema's ``Recording``.

Phase 2 ships the desktop and browser ingest paths. Both run through
``normalize`` for shared timestamp/ID handling and emit ``Recording``s
indistinguishable to the translator.
"""

from csrsb.ingest.browser import from_payload as load_browser_payload
from csrsb.ingest.browser import from_zip as load_browser_zip
from csrsb.ingest.desktop import load as load_desktop_recording

__all__ = [
    "load_desktop_recording",
    "load_browser_payload",
    "load_browser_zip",
]
