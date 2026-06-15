"""Operational data layer (reviews, admin queue, improvement pipeline, versioning,
documents, edit history, feature flags).

In-memory by default so the app and tests run with no database; the same interface
is satisfied by a Supabase-backed implementation (tables in ``supabase/schema.sql``)
when ``SCRIBE_STORE_BACKEND=supabase``. Clinical PHI is NOT kept here — it lives in
the encrypted session store. This layer holds the quality/ops metadata around the
scribe.
"""
