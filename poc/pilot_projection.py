"""Approved wire envelope and the unchanged local projection transaction."""
import time
import uuid

from psycopg.types.json import Jsonb

import operational_core as core


def envelope(runtime, model, scope, destination, event_id, plan):
    approved = {(r['table'], r['row']['id']): r['row'] for r in plan['rows']}
    facts = [{**r, 'row': approved[(r['table'], r['row']['id'])]}
             for r in core.resources(model, scope) if (r['table'], r['row']['id']) in approved]
    # Other recipients, owner display names and withheld resources never cross.
    policy = scope['policy']
    recipient_policy = {k: policy[k] for k in ('owner_entity_id', 'allowed_countries',
                                                'denied_countries', 'purpose')}
    recipient_policy.update(allowed_entities=[destination], denied_entities=[destination]
                            if destination in policy['denied_entities'] else [],
                            grants={destination: policy['grants'][destination]}
                            if destination in policy['grants'] else {})
    rows = sorted(plan['rows'], key=lambda r: (r['table'], r['row']['id']))
    facts = sorted(facts, key=lambda r: (r['table'], r['row']['id']))
    return dict(event_id=str(event_id), owner_entity_id=scope['owner_entity_id'], scope_id=scope['id'],
                destination_entity_id=destination, scope_kind=scope['scope_kind'],
                data_version=scope['data_version'], policy_generation=scope['policy_generation'],
                decision_revision=scope['decision_revision'],
                placement_version=runtime.entities[destination]['placement_version'],
                policy=recipient_policy, rows=rows, facts=facts,
                row_counts={k: v for k, v in plan['row_counts'].items() if v})


def apply_projection(connection, message):
    key = (message['owner_entity_id'], message['scope_id'], message['destination_entity_id'])
    if connection.execute('SELECT event_id FROM sovereignty.inbox WHERE event_id=%s',
                          (message['event_id'],)).fetchone():
        return 'duplicate'
    prior = connection.execute('SELECT data_version,policy_generation,decision_revision '
        'FROM sovereignty.manifest WHERE owner_entity_id=%s AND scope_id=%s AND destination_entity_id=%s', key).fetchone()
    versions = tuple(message[k] for k in ('data_version', 'policy_generation', 'decision_revision'))
    if prior and any(old > new for old, new in zip(prior, versions)):
        raise ValueError('Stale business manifest fenced')
    for table in reversed(core.ORDER):
        connection.execute(f'DELETE FROM projection.{table} WHERE owner_entity_id=%s '
                           'AND scope_id=%s AND destination_entity_id=%s', key)
    for table in core.ORDER:
        for resource in (r for r in message['rows'] if r['table'] == table):
            columns = ['owner_entity_id', 'scope_id', 'destination_entity_id'] + list(resource['row'])
            connection.execute(f"INSERT INTO projection.{table} ({','.join(columns)}) "
                               f"VALUES ({','.join(['%s'] * len(columns))})",
                               list(key) + list(resource['row'].values()))
    connection.execute('UPSERT INTO sovereignty.manifest VALUES (%s,%s,%s,%s,%s,%s,%s,%s)',
                       key + versions + (message['placement_version'], Jsonb(message['row_counts'])))
    connection.execute('INSERT INTO sovereignty.inbox VALUES (%s,%s)', (message['event_id'], time.time()))
    status = 'replicated' if message['rows'] else 'purged'
    event = dict(id=str(uuid.uuid4()), time=time.time(), record_id=message['scope_id'],
                 owner_entity_id=message['owner_entity_id'], destination_entity_id=message['destination_entity_id'],
                 status=status, dataset='party_relationship_graph', source_receipt=False)
    connection.execute('INSERT INTO sovereignty.audit VALUES (%s,%s,%s)',
                       (event['id'], event['time'], Jsonb(event)))
    return status
