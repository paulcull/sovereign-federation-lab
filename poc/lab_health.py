"""Separate liveness and dependency readiness. Never substitute a database."""
import os
from concurrent.futures import ThreadPoolExecutor
import httpx,psycopg
from deployment import active_regions, description
from fastapi import APIRouter
from fastapi.responses import JSONResponse

def check_region(region):
    result={'region':region,'database':False,'policy':False}
    try:
        with psycopg.connect(os.environ['DB_'+region],connect_timeout=2) as c:
            result['database']='CockroachDB' in c.execute('SELECT version()').fetchone()[0]
    except Exception:pass
    try:
        url=os.environ.get('OPA_'+region,os.environ.get('MIGRATION_OPA_IN_URL',''))
        response=httpx.post(url+'/v1/data/bank/migration/allow',json={'input':{'operation':'register','country':'IN'}},timeout=2,trust_env=False)
        result['policy']=response.status_code==200 and response.json().get('result') is True
    except Exception:pass
    return result


def dependency_status():
    with ThreadPoolExecutor(max_workers=4) as pool:checks=list(pool.map(check_region,active_regions()))
    return {'status':'ready' if all(x['database'] and x['policy'] for x in checks) else 'not-ready',
            'database':'cockroach','stores':checks,**description()}


def router():
    r=APIRouter(prefix='/api/health')
    @r.get('/live')
    def live():return {'status':'alive','database':'cockroach','edition':9}
    @r.get('/ready')
    def ready():
        result=dependency_status()
        return JSONResponse(result,status_code=200 if result['status']=='ready' else 503)
    return r
