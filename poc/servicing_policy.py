"""Fail-closed OPA adapter for the independently owned case dataset."""
import httpx
from fastapi import HTTPException

FIELDS = {'case_id', 'status', 'category', 'data_version'}


def decide(url, action, principal, country):
    facts = dict(service_id='servicing-cases', owner_entity_id='LE-SG-01',
                 store_country=country, action=action,
                 principal={key: principal[key] for key in ('entity_id', 'processing_country', 'actions')})
    try:
        with httpx.Client(timeout=3, trust_env=False) as client:
            response = client.post(url.rstrip('/') + '/v1/data/servicing/decision', json={'input': facts})
            response.raise_for_status()
            result = response.json()['result']
        if (not isinstance(result, dict) or type(result.get('allow')) is not bool
                or type(result.get('revision')) is not int or result['revision'] < 1
                or not isinstance(result.get('fields'), list)
                or any(not isinstance(field, str) or field not in FIELDS for field in result['fields'])):
            raise ValueError('Invalid policy result')
    except (httpx.HTTPError, ValueError, KeyError, TypeError):
        raise HTTPException(503, 'Current service policy unavailable; fail closed')
    if result['allow'] is not True:
        raise HTTPException(403, 'Service policy denied')
    return result
