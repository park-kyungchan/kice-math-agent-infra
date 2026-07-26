# W6 contract — unblock the registry and provenance for ce.*
Split into two waves: W6a code-only, W6b database migration. W6b does not begin until W6a is green.

1. OBJECTIVE
   Register the six ce.* axes as governance metadata, mark the legacy taxonomy deprecated, and
   relax claim_provenance.axis so provenance can be recorded for a ce.* axis — all without
   altering the legacy Axis_N public output contract.

2. ARTIFACTS IT MAY MODIFY
   W6a: pipeline/query_engine/axis_registry.py, tests/test_axis_registry.py
   W6b: a new pipeline/migrate_db_ce_provenance.py, and storage/parsed_dataset.db via that script

3. ARTIFACTS IT MUST NOT TOUCH
   selective_fetcher.py, claim_provenance.py, validate_ssot_consistency.py, migrate_db_*.py
   (existing), generate_routing.py, ROUTING.md, MANIFEST.json, PROJECT_STATE.json, docs/*.
   Any need to change one of these is a contract breach: stop and report.

4. INTERFACES IT MUST PRESERVE  (survey evidence, 2026-07-26)
   AXIS_COLUMNS, AXIS_COLUMN_BY_DICT_KEY and DICT_KEY_BY_AXIS_COLUMN are consumed by
   selective_fetcher.py, claim_provenance.py, validate_ssot_consistency.py,
   migrate_db_axis_agnostic.py and generate_routing.py, and back the byte-for-byte legacy
   Axis_1..Axis_8 output contract. They MUST continue to contain exactly the eight legacy axes.
   The ce.* axes are therefore registered as a separate family and excluded from those three
   derived structures by construction.

5. DEFINITION OF DONE
   W6a: six ce.* axes registered; legacy axes marked deprecated except axis2_raw_parsing; the three
        legacy derived structures still contain exactly 8 entries; full test suite green.
   W6b: claim_provenance accepts a ce.* axis value and still rejects an unknown one; existing rows
        and constraints preserved; full test suite green.

6. CHECKS IT MUST RUN
   python -m unittest discover -s tests    (the CI runner; pytest is not installed)
   plus an explicit assertion that len(AXIS_COLUMNS) == 8 after the change.

7. RETRY LIMIT / APPROVAL
   Two attempts per wave. Touching any file in section 3 requires owner approval.
