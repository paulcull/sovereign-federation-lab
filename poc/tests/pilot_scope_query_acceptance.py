"""Read-only bounded graph queries against actual CockroachDB and source OPA.

The connection wrapper records executed SQL; every statement still reaches the
real database. Full-model reads appear only as the reference implementation here.
"""
import json
import os
import re
from pathlib import Path
import sys
import threading
import uuid
from types import SimpleNamespace

import httpx
from fastapi import HTTPException
from opentelemetry import trace
import psycopg

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'poc'))
import operational_core as core
from operational import OperationalRuntime, SCOPE_POLICY_FACT_INDEXES, scope_policy_fact_query
from seed import ENTITIES, STORE_INFO


class RecordingConnection:
    def __init__(self, connection):
        self.connection = connection
        self.statements = []

    def execute(self, statement, parameters=()):
        self.statements.append((statement, parameters))
        return self.connection.execute(statement, parameters)

    def pipeline(self):
        return self.connection.pipeline()


def canonical(resources):
    return sorted(resources, key=lambda row: (row['table'], row['row']['id']))


def constrained_uuids(span_lines):
    """Decode UUID key spans rendered as Go-quoted raw bytes by CockroachDB.

    Typed UUID[] parameters produce byte-key spans while scalar string
    parameters can be printed as UUID text. Compare complete decoded values,
    never just an index name or an owner-only prefix.
    """
    found=set()
    escapes={'a':7,'b':8,'f':12,'n':10,'r':13,'t':9,'v':11,'\\':92,'"':34}
    for token in re.findall(r'"(?:[^"\\]|\\.)*"', '\n'.join(span_lines)):
        value=bytearray();position=1
        while position<len(token)-1:
            character=token[position];position+=1
            if character!='\\':
                value.extend(character.encode('utf-8'));continue
            escape=token[position];position+=1
            if escape=='x':
                value.append(int(token[position:position+2],16));position+=2
            elif escape in ('u','U'):
                width=4 if escape=='u' else 8
                value.extend(chr(int(token[position:position+width],16)).encode('utf-8'));position+=width
            elif escape in escapes:
                value.append(escapes[escape])
            else:
                raise AssertionError('Unsupported CockroachDB key escape')
        if len(value)==16:
            found.add(str(uuid.UUID(bytes=bytes(value))))
        else:
            try:found.add(str(uuid.UUID(bytes(value).decode('ascii'))))
            except (ValueError,UnicodeDecodeError):pass
    return found

def check_fact_plans(connection,checks):
    for table,field,multiple,values in checks:
        statement=scope_policy_fact_query(table,field,multiple=multiple)
        subject_parameter=[uuid.UUID(value) for value in values] if multiple else values[0]
        parameters=(core.SPEC['owner_entity_id'],subject_parameter,513)
        explanation='\n'.join(row[0] for row in connection.execute('EXPLAIN (VERBOSE) '+statement,parameters))
        span_lines=[line for line in explanation.splitlines() if 'spans:' in line or 'constraint:' in line]
        observed_values=constrained_uuids(span_lines)
        assert set(values) <= observed_values, explanation
        assert table+'@'+SCOPE_POLICY_FACT_INDEXES[(table,field)] in explanation, explanation
        assert 'FULL SCAN' not in explanation, explanation
        # Execute the exact hinted statement as well as explaining it. A hint
        # which only prevents planning/execution is not a working scope query.
        connection.execute(statement,parameters).fetchall()

def main():
    dsn = os.getenv('DB_SG', 'postgresql://root@db-sg:26257/defaultdb?sslmode=disable')
    with httpx.Client(timeout=3, trust_env=False) as http:
        source = SimpleNamespace(id='STORE-SG-01', http=http,
            opa=os.getenv('OPA_SG', 'http://opa-sg:8181'))
        runtime = OperationalRuntime({'STORE-SG-01':source}, ENTITIES, STORE_INFO,
            threading.RLock(), {}, trace.get_tracer('pilot.scope.query.acceptance'))
        with psycopg.connect(dsn, connect_timeout=2) as connection:
            assert 'CockroachDB' in connection.execute('SELECT version()').fetchone()[0]
            full = runtime.load(connection)
            seeds = {scope['id'] for scope in core.SPEC['scopes']}
            selected = [scope for scope in full['scopes'] if scope['id'] in seeds]
            selected += [scope for scope in full['scopes'] if scope['id'] not in seeds][-4:]
            assert len(selected) >= 4
            comparisons = 0
            for scope in selected:
                observed = RecordingConnection(connection)
                scoped = runtime.load_scope(observed, scope['id'])
                assert [item['id'] for item in scoped['scopes']] == [scope['id']]
                assert all(binding['scope_id'] == scope['id'] for binding in scoped['bindings'])
                assert canonical(core.resources(scoped, scoped['scopes'][0])) == canonical(core.resources(full, scope))
                for statement, parameters in observed.statements:
                    if 'FROM business.' not in statement:
                        continue
                    assert 'WHERE owner_entity_id=%s' in statement
                    assert 'id=ANY(%s)' in statement or 'LIMIT %s' in statement
                for entity in ('LE-GB-02', 'LE-US-01'):
                    expected = runtime.plan(full, scope, entity)
                    actual = runtime.plan(scoped, scoped['scopes'][0], entity)
                    assert canonical(expected['rows']) == canonical(actual['rows'])
                    assert expected['row_counts'] == actual['row_counts']
                    comparisons += 1
            # The party minimum has a separate, unbound classification fact.
            party = next(scope for scope in selected if scope['scope_kind'] == 'party'
                         and scope['primary_party_id'] == core.SPEC['scopes'][0]['primary_party_id'])
            scoped = runtime.load_scope(connection, party['id'])
            assert scoped['rows']['classification']
            assert all(binding['resource_type'] != 'classification' for binding in scoped['bindings'])
            for row in scoped['rows']['classification']:
                if row['party_id'] == party['primary_party_id']:
                    row['level'] = 'RESTRICTED'
            assert core.resources(scoped, scoped['scopes'][0])[0]['sensitivity'] == 'RESTRICTED'
            try:
                runtime.load_scope(connection, party['id'], max_resources=0)
            except HTTPException as error:
                assert error.status_code == 422
            else:
                raise AssertionError('Bounded query silently truncated an oversized scope')
            # Check the real optimiser chooses bounded spans for the graph roots.
            for statement, parameters in (
                ('SELECT doc FROM sovereignty.scope WHERE owner_entity_id=%s AND id=%s',
                 (core.SPEC['owner_entity_id'], party['id'])),
                ('SELECT resource_id FROM sovereignty.binding WHERE owner_entity_id=%s AND scope_id=%s',
                 (core.SPEC['owner_entity_id'], party['id'])),
                ('SELECT id FROM business.party WHERE owner_entity_id=%s AND id=ANY(%s)',
                 (core.SPEC['owner_entity_id'], [party['primary_party_id']]))):
                explanation = '\n'.join(row[0] for row in connection.execute('EXPLAIN ' + statement, parameters))
                assert 'FULL SCAN' not in explanation, explanation
                assert 'spans:' in explanation or 'constraint:' in explanation, explanation
            # The scalar consent path must use its subject-qualified span too.
            # A LIMIT above an owner-only scan is not a bounded point query.
            relationship=next(scope for scope in selected if scope['scope_kind']=='relationship')
            checks=[('consent','relationship_id',False,[relationship['relationship_id']])]
            # Exercise the loader's exact array predicates with one and two
            # subjects, including its UUID[] adaptation and ORDER BY + LIMIT.
            # The shared builder keeps these EXPLAINs identical to runtime SQL.
            # Run on both the fresh CI seed and accumulated acceptance data;
            # do not add rows or alter statistics to influence index selection.
            for subject_table,field in (('party','party_id'),('relationship','relationship_id'),
                                       ('product_holding','holding_id')):
                subjects=sorted({row['id'] for row in full['rows'][subject_table]})[:2]
                assert len(subjects)==2, 'Expected two real synthetic subjects for the plan regression'
                checks.extend(('classification',field,True,subjects[:count]) for count in (1,2))
            check_fact_plans(connection,checks)
        # Sparse/empty peer business tables exercise the small-table optimiser
        # choices that a populated owner alone misses. These remain real tables;
        # the test never changes fixtures or statistics to obtain a desired plan.
        for store in ('UK','US'):
            peer_dsn=os.getenv('DB_'+store,'postgresql://root@db-'+store.lower()+':26257/defaultdb?sslmode=disable')
            with psycopg.connect(peer_dsn,connect_timeout=2) as connection:
                assert 'CockroachDB' in connection.execute('SELECT version()').fetchone()[0]
                check_fact_plans(connection,checks)
    print('PASS bounded CockroachDB scope/binding/business queries, unbound policy facts, '
          f'explicit oversize rejection, {comparisons} full/scoped actual OPA plan comparisons, '
          'and exact subject spans/execution on SG/UK/US')


if __name__ == '__main__':
    main()
