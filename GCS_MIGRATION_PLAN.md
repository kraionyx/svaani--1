# Implementation Plan: Cloud Storage Audio Buffering

This plan details the migration from holding 100MB+ audio files in RAM (via `/tmp` tempfiles) to streaming them directly to a Google Cloud Storage (GCS) bucket.

## Why this works (The "Recheck")

I re-checked the `sarvam.py` code. The Sarvam SDK explicitly requires a local file path (`job.upload_files([in_path])`) to perform Batch Diarization. 

You might ask: *"If Sarvam needs a local file, don't we still need RAM?"*
Yes, but only for **5 seconds**, not **1 hour**! 

*   **Current state:** We hold 20 files in RAM simultaneously for the *entire hour* the doctors are speaking (2.3 GB RAM constant usage).
*   **New state:** We stream the audio to the bucket. When a doctor hits "Stop", we download their file from the bucket to a tempfile, upload it to Sarvam, and instantly delete it. This takes ~5 seconds. Your server's RAM stays completely empty 99% of the time, and only briefly spikes by 115MB when someone clicks Stop. 

This guarantees massive cost savings on Cloud Run RAM and provides HIPAA-compliant backup storage.

---

## Proposed Changes

### 1. `app/config.py`
Add configuration variables for the cloud storage bucket.
- Add `gcs_bucket_name: str | None = None` to `Settings`.

### 2. `app/storage/gcs.py` (New Module)
Create a new module to handle bucket streaming.
- Implement an `AudioStreamer` class.
- Use `blob.open("wb")` from the `google-cloud-storage` library. This provides a file-like object that automatically handles multipart chunked uploads in the background as we write to it, meaning we don't have to manage complex 5MB buffers manually.
- Add a `download_to_temp` method that fetches the file from the bucket into a local `tempfile` when the session is over.

### 3. `app/audio/ws.py`
Refactor the WebSocket loop to stream to the bucket instead of a local tempfile.
- On "start": Initialize `AudioStreamer` to the GCS bucket.
- On "bytes" frame: `streamer.write(chunk)` instead of `audio_temp.write(chunk)`. (The live Sarvam streaming path remains unchanged and instant).
- On "stop": Call `streamer.close()`. 
- Before calling `_diarize()`: Call `streamer.download_to_temp()` to get the file, pass that short-lived tempfile to Sarvam, and ensure the tempfile is immediately deleted in a `finally` block.

### 4. `app/stt/sarvam.py`
Minor tweaks to ensure it gracefully handles the short-lived tempfile path passed from `ws.py`.
- Ensure `transcribe_for_session` and `transcribe_diarized` properly accept the file path and do not attempt to hold it in memory.

---

## Verification Plan

### Automated Tests
- Run `pytest` to ensure no existing logic is broken.
- Mock the GCS bucket during tests or use a local file-backed `AudioStreamer` for local development.

### Manual Verification
- Start an audio recording in the web UI.
- Verify the `app/audio/ws.py` writes chunks to the GCS bucket (check the GCP Console).
- Stop the recording.
- Verify that the Batch Diarization successfully downloads the file, uploads it to Sarvam, processes the accurate transcript, and deletes the local tempfile.
