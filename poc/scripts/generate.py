#!/usr/bin/env python3
"""Dependency-free workload stub. Extend scenarios in seed.py; never use real PII."""
import argparse, json, time, urllib.request
p=argparse.ArgumentParser(description=__doc__)
p.add_argument('--url',default='http://localhost:8000')
p.add_argument('--count',type=int,default=3,help='Records per batch, 1–100')
p.add_argument('--scenario',default='mixed')
p.add_argument('--batches',type=int,default=1)
p.add_argument('--interval',type=float,default=2)
a=p.parse_args()
if not 1<=a.count<=100 or a.batches<1 or a.interval<0:p.error('Invalid count, batches or interval')
for i in range(a.batches):
 req=urllib.request.Request(a.url.rstrip('/')+'/api/generate',data=json.dumps({'count':a.count,'scenario':a.scenario}).encode(),headers={'Content-Type':'application/json'},method='POST')
 with urllib.request.urlopen(req,timeout=60) as response: result=json.load(response)
 print(json.dumps({'batch':i+1,'created':[{'id':d['id'],'owner_entity_id':d['owner_entity_id'],'scenario':d['scenario']} for d in result['created']]}),flush=True)
 if i<a.batches-1:time.sleep(a.interval)
