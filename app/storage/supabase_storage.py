"""Upload transcript and consultation-note .txt files to Supabase Storage.

Requires SCRIBE_SUPABASE_URL and SCRIBE_SUPABASE_SERVICE_KEY to be set.
When either is absent the functions are silent no-ops so the app boots and
runs without Supabase configured (the same pattern used by the Supabase DB
backend).

Bucket: configured via SCRIBE_SUPABASE_STORAGE_BUCKET (default
``consultation-files``). Create it in the Supabase dashboard as a
*private* bucket before enabling; the service-role key bypasses its RLS.

File layout inside the bucket:
  transcripts/{session_id}.txt   — clean transcript (speaker-labelled plain text)
  notes/{session_id}.txt         — consultation note (Markdown)
"""
from __future__ import annotations

import logging
import threading
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from app.config import Settings

logger = logging.getLogger("svaani.storage")


def _upload(supabase_url: str, service_key: str, bucket: str, path: str, content: str) -> None:
    """Upload *content* to Supabase Storage at *bucket*/*path*.

    Uses the Storage REST API directly (no supabase-py dependency).
    Upserts — repeated calls overwrite the previous version.
    """
    import httpx  # already a project dependency

    url = f"{supabase_url.rstrip('/')}/storage/v1/object/{bucket}/{path}"
    headers = {
        "Authorization": f"Bearer {service_key}",
        "Content-Type": "text/plain; charset=utf-8",
        "x-upsert": "true",
    }
    try:
        r = httpx.put(url, content=content.encode("utf-8"), headers=headers, timeout=15)
        r.raise_for_status()
        logger.info("storage upload ok: %s/%s (%d bytes)", bucket, path, len(content))
    except Exception:  # noqa: BLE001
        logger.warning("storage upload failed: %s/%s", bucket, path, exc_info=True)


def upload_consultation_files(
    session_id: str,
    transcript_text: str,
    note_markdown: str,
    settings: "Settings",
    *,
    background: bool = True,
) -> None:
    """Upload transcript + note for *session_id* to Supabase Storage.

    Silently skips when Supabase Storage is not configured.
    When *background* is True (default) the uploads run in daemon threads so
    the API response is not blocked.
    """
    if not (settings.supabase_url and settings.supabase_service_key):
        return

    bucket = getattr(settings, "supabase_storage_bucket", "consultation-files")
    url = settings.supabase_url
    key = settings.supabase_service_key

    jobs = [
        (f"transcripts/{session_id}.txt", transcript_text),
        (f"notes/{session_id}.txt", note_markdown),
    ]

    if background:
        for path, content in jobs:
            t = threading.Thread(
                target=_upload, args=(url, key, bucket, path, content), daemon=True
            )
            t.start()
    else:
        for path, content in jobs:
            _upload(url, key, bucket, path, content)
