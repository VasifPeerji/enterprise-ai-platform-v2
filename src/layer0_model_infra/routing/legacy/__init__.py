"""Archived legacy routing components (the pre-kNN approach).

This subpackage holds the original Layer 3-5 routing pipeline that the
benchmark-driven kNN router replaced:

  fast_triage           - LLM intent / domain / complexity classification (Layer 3)
  complexity_classifier - the ~6.5KB-rubric 70B complexity scorer behind it
  uncertainty_estimator - query-surface (regex) heuristic uncertainty (Layer 4)
  bandit_router         - Thompson-sampling contextual bandit selection (Layer 5)
  query_analyzer        - an older standalone query-analysis helper (already unused)

None of these are wired into the live router anymore (see
``src/layer0_model_infra/router.py``); they are kept, intact and runnable, as a
record of the approaches evaluated before the kNN router was adopted, for the
project writeup, slide deck and thesis. Their configuration still lives in
``config/routing_config.py`` under the LEGACY section.
"""
