"""Ingest layer: normalize raw recorder output into the schema's ``Recording``.

Phase 1 ships only the desktop ingest — the desktop recorder already writes
the canonical shape, so ``from_dir`` is a thin loader. The browser extension
(Phase 2) will land here too, behind a uniform interface.
"""

from csrsb.ingest.desktop import load as load_desktop_recording

__all__ = ["load_desktop_recording"]
