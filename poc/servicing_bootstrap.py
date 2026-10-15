"""Explicit admin-only schema setup; the serving processes never receive root DSNs."""
import os
from pathlib import Path
import sys

import psycopg

if sys.argv[1:] not in (['source'], ['recipient']):
    raise SystemExit('Usage: servicing_bootstrap.py source|recipient (SERVICING_ADMIN_DSN required)')
name = 'servicing_schema.sql' if sys.argv[1] == 'source' else 'servicing_projection_schema.sql'
with psycopg.connect(os.environ['SERVICING_ADMIN_DSN'], autocommit=True) as connection:
    for statement in (Path(__file__).parent / name).read_text().split(';'):
        if statement.strip():
            connection.execute(statement)
print('PASS independent service schema and SQL privilege provisioning: ' + sys.argv[1])
