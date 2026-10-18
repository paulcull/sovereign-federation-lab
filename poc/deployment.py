"""Explicit lab footprints; an inactive store is never remapped or emulated."""
import os
import json
from pathlib import Path

_CATALOG=json.loads((Path(__file__).resolve().parents[1]/'shared/catalog.json').read_text())


def footprint():
    value = os.getenv('LAB_FOOTPRINT', 'full')
    if value not in ('full', 'mdm-compact'):
        raise RuntimeError('Unknown lab footprint')
    return value


def active_regions():
    return ('SG', 'UK') if footprint() == 'mdm-compact' else ('SG', 'UK', 'US', 'IN')


def enabled_store_ids():
    return {store['id'] for store in _CATALOG['stores'] if store['region'] in active_regions()}


def description():
    compact = footprint() == 'mdm-compact'
    return dict(footprint=footprint(), active_regions=list(active_regions()),
                suspended_regions=['US', 'IN'] if compact else [],
                telemetry='suspended' if compact else 'configured',
                full_lab=not compact)
