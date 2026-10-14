"""Shared timestamp meaning, not a new source grant or freshness relaxation."""

EVIDENCE_DATE_INSTRUCTIONS = """
Date roles: collected_at = data collection, not user activity, cohort start, payment or
SQL storage; report_created_at = report generation; created_at = its object's creation;
fresh_until = cache deadline, not an observed event. None establishes coverage or SQL-save time.
Use explicit source observation periods/cutoffs, else keep observation dates/coverage
unknown even if collected_at is present and recent. Label collected_at as collection,
never observation or report-save time. Do not invent dates, relax freshness or
grant another source read.
"""
