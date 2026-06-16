"""Offline evaluation harness for the scribe (Goal 9).

Runs candidate prompts / pipeline changes over a versioned golden dataset and scores
clinical-attribution / extraction / risk accuracy, WITHOUT touching production. Used by the
human-gated improvement pipeline and by the regression test suite.
"""
