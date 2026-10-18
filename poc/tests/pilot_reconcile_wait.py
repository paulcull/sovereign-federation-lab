"""Real SQL startup-wait regression; caller pauses the actual relay process."""
import os
from pathlib import Path
import sys
import threading
import time
import uuid

import psycopg

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from pilot_reconcile import wait_active
from deployment import enabled_store_ids
from seed import ENTITIES

dsn='postgresql://root@db-sg:26257/defaultdb?sslmode=disable'
assert os.environ.get('LAB_FOOTPRINT')=='mdm-compact'
if sys.argv[1:]==['--drain']:
    wait_active(dsn,40)
    print('PASS active relay drained before the actual process is paused')
    raise SystemExit(0)
assert not sys.argv[1:]
active=[entity['id'] for entity in ENTITIES.values() if entity['store_id'] in enabled_store_ids()]
with psycopg.connect(dsn) as connection:
    assert connection.execute("SELECT count(*) FROM sovereignty.outbox WHERE status IN ('queued','retry') AND destination_entity_id=ANY(%s)",(active,)).fetchone()[0]==0
    sid=connection.execute('SELECT id FROM sovereignty.scope ORDER BY id LIMIT 1').fetchone()[0]

old,new=str(uuid.uuid4()),str(uuid.uuid4())
errors=[]
def replacement():
    try:
        time.sleep(.1)
        # Same atomic retirement/renewal used after a committed receipt conflict.
        with psycopg.connect(dsn) as connection:
            connection.execute("UPDATE sovereignty.outbox SET status='superseded' WHERE id=%s",(old,))
            connection.execute('INSERT INTO sovereignty.outbox (id,scope_id,destination_entity_id,created_at) VALUES (%s,%s,%s,%s)',
                (new,sid,'LE-GB-02',time.time()))
    except Exception as error:errors.append(type(error).__name__)

thread=None
try:
    with psycopg.connect(dsn) as connection:
        connection.execute('INSERT INTO sovereignty.outbox (id,scope_id,destination_entity_id,created_at) VALUES (%s,%s,%s,%s)',
            (old,sid,'LE-GB-02',time.time()-10))
    thread=threading.Thread(target=replacement)
    thread.start()
    try:
        wait_active(dsn,1)
    except SystemExit:
        pass
    else:
        raise AssertionError('Startup falsely reported drained while a renewed active intent remained pending')
    thread.join()
    assert not errors,errors
    with psycopg.connect(dsn) as connection:
        assert connection.execute('SELECT status FROM sovereignty.outbox WHERE id=%s',(new,)).fetchone()[0]=='queued'
finally:
    if thread:thread.join()
    with psycopg.connect(dsn) as connection:
        connection.execute('DELETE FROM sovereignty.outbox WHERE id=ANY(%s)',([old,new],))
wait_active(dsn,1)
with psycopg.connect(dsn) as connection:
    assert connection.execute("SELECT count(*) FROM sovereignty.outbox WHERE destination_entity_id='LE-US-01' AND status IN ('queued','retry')").fetchone()[0]>=16
print('PASS real SQL replacement intent keeps startup pending; active drain succeeds without consuming suspended-US work')
