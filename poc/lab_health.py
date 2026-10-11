"""Separate liveness and dependency readiness. Never substitute a database."""
import os
from concurrent.futures import ThreadPoolExecutor
import httpx,psycopg
from fastapi import APIRouter
from fastapi.responses import JSONResponse

def router():
    r=APIRouter(prefix='/api/health')
    @r.get('/live')
    def live():return {'status':'alive','database':'cockroach','edition':9}
    @r.get('/ready')
    def ready():
        def check(region):
            result={'region':region,'database':False,'policy':False}
            try:
                with psycopg.connect(os.environ['DB_'+region],connect_timeout=2) as c:
                    value=c.execute('SELECT version()').fetchone()[0]
                    result['database']='CockroachDB' in value
            except Exception:pass
            try:
                url=os.environ.get('OPA_'+region,os.environ.get('MIGRATION_OPA_IN_URL',''))
                response=httpx.post(url+'/v1/data/bank/migration/allow',json={'input':{'operation':'register','country':'IN'}},timeout=2,trust_env=False)
                result['policy']=response.status_code==200 and response.json().get('result') is True
            except Exception:pass
            return result
        with ThreadPoolExecutor(max_workers=4) as pool:checks=list(pool.map(check,['SG','UK','US','IN']))
        ok=all(x['database'] and x['policy'] for x in checks)
        return JSONResponse({'status':'ready' if ok else 'not-ready','database':'cockroach','stores':checks},status_code=200 if ok else 503)
    return r
