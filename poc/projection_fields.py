"""Persist exactly imported fields, preserving absent versus present-null values."""
from psycopg.types.json import Jsonb


def write_fields(connection,key,rows):
    connection.execute('DELETE FROM sovereignty.field_manifest WHERE owner_entity_id=%s '
        'AND scope_id=%s AND destination_entity_id=%s',key)
    for resource in rows:
        connection.execute('INSERT INTO sovereignty.field_manifest VALUES (%s,%s,%s,%s,%s,%s)',
            key+(resource['table'],resource['row']['id'],Jsonb(sorted(resource['row']))))
