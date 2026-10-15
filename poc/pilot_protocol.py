"""Versioned pilot import contract and durable source-placement read fence.

These checks complement current source/recipient policy admission. A placement
revision is not a distributed writer lease, and a receipt is not restore safety.
"""
import json
import uuid

from fastapi import HTTPException

import operational_core as core


PROTOCOL_VERSION = 1
VERSIONS = ('data_version', 'policy_generation', 'decision_revision',
            'placement_version', 'source_placement_version')


def validate_envelope(message):
    """Reject an incompatible or ambiguous graph before any local SQL mutation."""
    if not isinstance(message, dict) or type(message.get('protocol_version')) is not int or message['protocol_version'] != PROTOCOL_VERSION:
        raise HTTPException(422, 'Unsupported projection protocol')
    if any(type(message.get(name)) is not int or not 1 <= message[name] <= 2**63 - 1
           for name in VERSIONS):
        raise HTTPException(422, 'Invalid projection revision')
    for name in ('event_id', 'scope_id'):
        try:
            if str(uuid.UUID(message[name])) != message[name]:
                raise ValueError()
        except (KeyError, ValueError, TypeError, AttributeError):
            raise HTTPException(422, 'Invalid projection identity')
    if message.get('owner_entity_id') != core.SPEC['owner_entity_id'] or not isinstance(message.get('destination_entity_id'), str):
        raise HTTPException(422, 'Invalid projection owner or destination')
    if message.get('scope_kind') not in ('party', 'relationship') or not isinstance(message.get('policy'), dict):
        raise HTTPException(422, 'Invalid projection scope or policy')
    rows, facts = message.get('rows'), message.get('facts')
    if not isinstance(rows, list) or not isinstance(facts, list) or len(rows) > 50 or len(facts) != len(rows):
        raise HTTPException(422, 'Invalid bounded projection graph')
    try:
        encoded = json.dumps(message, separators=(',', ':'), allow_nan=False).encode()
    except (ValueError, TypeError):
        raise HTTPException(422, 'Invalid projection value')
    if len(encoded) > 32768:
        raise HTTPException(422, 'Projection graph exceeds 32 KiB')
    seen, counts = set(), {}
    for resource, fact in zip(rows, facts):
        if not isinstance(resource, dict) or not isinstance(fact, dict):
            raise HTTPException(422, 'Invalid projection resource')
        table, row = resource.get('table'), resource.get('row')
        if not isinstance(table, str):
            raise HTTPException(422, 'Invalid projection dataset')
        allowed = core.TABLES.get(table, {}).get(
            'global_fields' if message['scope_kind'] == 'party' else 'export_fields', [])
        if not allowed or not isinstance(row, dict) or set(row) - set(allowed) or not isinstance(row.get('id'), str):
            raise HTTPException(422, 'Invalid projection fields')
        try:
            uuid.UUID(row['id'])
        except ValueError:
            raise HTTPException(422, 'Invalid projection resource identity')
        key = (table, row['id'])
        if key in seen or fact.get('table') != table or fact.get('row') != row:
            raise HTTPException(422, 'Duplicate or inconsistent projection resource')
        seen.add(key)
        counts[table] = counts.get(table, 0) + 1
    supplied = message.get('row_counts')
    if not isinstance(supplied, dict) or any(type(v) is not int for v in supplied.values()) or supplied != counts:
        raise HTTPException(422, 'Projection row counts do not match')


def verify_projection_authority(connection, key, current):
    """A restored/legacy projection cannot invent a missing source revision."""
    expected = current.get('source_placement_version')
    if type(expected) is not int or expected < 1:
        raise HTTPException(409, 'Current source placement unavailable')
    row = connection.execute(
        'SELECT source_placement_version FROM sovereignty.manifest_authority '
        'WHERE owner_entity_id=%s AND scope_id=%s AND destination_entity_id=%s', key).fetchone()
    if row is None or row[0] != expected:
        raise HTTPException(409, 'Source placement requires current-authority reconciliation')
