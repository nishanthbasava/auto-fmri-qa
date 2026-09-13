"""Database layer: users, review decisions, and the audit log.

The pipeline's compute output stays in runs/<run>/state.json (that is the
artifact of a run). What people DO with it -- who reviewed what, when, and what
they decided -- is the app's system of record and lives here. SQLite by default
(zero setup, used by tests and single-user dev); Postgres in the lab and cloud
deployments via DATABASE_URL.
"""
