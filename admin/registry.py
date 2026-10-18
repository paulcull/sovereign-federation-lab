"""Revisioned configuration and management receipts, independent of managed SQL."""
from contextlib import contextmanager
from copy import deepcopy
from dataclasses import dataclass
from datetime import datetime, timezone
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import tempfile
import uuid

# ISO 3166-1 alpha-2, including GB (UK is a display/region label).
COUNTRIES = frozenset('AD AE AF AG AI AL AM AO AQ AR AS AT AU AW AX AZ BA BB BD BE BF BG BH BI BJ BL BM BN BO BQ BR BS BT BV BW BY BZ CA CC CD CF CG CH CI CK CL CM CN CO CR CU CV CW CX CY CZ DE DJ DK DM DO DZ EC EE EG EH ER ES ET FI FJ FK FM FO FR GA GB GD GE GF GG GH GI GL GM GN GP GQ GR GS GT GU GW GY HK HM HN HR HT HU ID IE IL IM IN IO IQ IR IS IT JE JM JO JP KE KG KH KI KM KN KP KR KW KY KZ LA LB LC LI LK LR LS LT LU LV LY MA MC MD ME MF MG MH MK ML MM MN MO MP MQ MR MS MT MU MV MW MX MY MZ NA NC NE NF NG NI NL NO NP NR NU NZ OM PA PE PF PG PH PK PL PM PN PR PS PT PW PY QA RE RO RS RU RW SA SB SC SD SE SG SH SI SJ SK SL SM SN SO SR SS ST SV SX SY SZ TC TD TF TG TH TJ TK TL TM TN TO TR TT TV TW TZ UA UG UM US UY UZ VA VC VE VG VI VN VU WF WS YE YT ZA ZM ZW'.split())
BASELINE = {
    'STORE-SG-01': ('Singapore', 'SG', 'SG'),
    'STORE-GB-01': ('United Kingdom', 'GB', 'UK'),
    'STORE-US-01': ('United States', 'US', 'US'),
    'STORE-IN-01': ('India / Mumbai migration', 'IN', 'IN'),
}
STATES = {'enabled', 'suspended', 'unmanaged'}
MAX_BYTES = 2 * 1024 * 1024


class RegistryError(Exception):
    pass


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=True)


def text(value, limit=64):
    return isinstance(value, str) and 1 <= len(value) <= limit and value == value.strip() and value.isprintable()


def initial():
    return {'schema_version': 1, 'revision': 0, 'stores': [
        {'id': sid, 'name': name, 'country': country, 'desired_state': 'unmanaged',
         'node_count': 1, 'nodes': [{'id': sid + '-N01', 'desired_state': 'unmanaged'}]}
        for sid, (name, country, _) in BASELINE.items()],
        'observability': {'desired_state': 'unmanaged'}, 'history': []}


def validate(value):
    def require(condition):
        if not condition:
            raise RegistryError('Invalid administration state; restore a verified file. No reset was performed.')
    require(isinstance(value, dict) and set(value) == {'schema_version', 'revision', 'stores', 'observability', 'history'})
    require(type(value['schema_version']) is int and value['schema_version'] == 1)
    require(type(value['revision']) is int and value['revision'] >= 0)
    require(isinstance(value['stores'], list) and 4 <= len(value['stores']) <= 100)
    ids = set()
    for store in value['stores']:
        require(isinstance(store, dict) and set(store) == {'id', 'name', 'country', 'desired_state', 'node_count', 'nodes'})
        sid = store['id']
        require(isinstance(sid, str) and bool(re.fullmatch(r'STORE-[A-Z0-9]+(?:-[A-Z0-9]+)*', sid)) and len(sid) <= 48 and sid not in ids)
        ids.add(sid)
        require(text(store['name']) and isinstance(store['country'], str) and store['country'] in COUNTRIES
                and isinstance(store['desired_state'], str) and store['desired_state'] in STATES)
        if sid in BASELINE:
            require(store['country'] == BASELINE[sid][1])
        require(type(store['node_count']) is int and 1 <= store['node_count'] <= 9)
        require(isinstance(store['nodes'], list) and store['node_count'] <= len(store['nodes']) <= 9)
        for index, node in enumerate(store['nodes'], 1):
            expected = store['desired_state'] if index <= store['node_count'] else 'suspended'
            require(node == {'id': sid + '-N' + str(index).zfill(2), 'desired_state': expected})
    require(set(BASELINE) <= ids)
    require(value['observability'] in [{'desired_state': state} for state in STATES])
    require(isinstance(value['history'], list) and len(value['history']) == value['revision'])
    requests = set()
    for revision, item in enumerate(value['history'], 1):
        require(isinstance(item, dict) and set(item) == {'request_id', 'request_hash', 'revision', 'at', 'action', 'summary'})
        try:
            require(str(uuid.UUID(item['request_id'])) == item['request_id'])
            at = datetime.fromisoformat(item['at'])
            require(at.utcoffset() is not None and at.utcoffset().total_seconds() == 0)
        except (ValueError, TypeError, AttributeError):
            require(False)
        require(item['request_id'] not in requests and type(item['revision']) is int and item['revision'] == revision)
        requests.add(item['request_id'])
        require(isinstance(item['request_hash'], str) and bool(re.fullmatch(r'[0-9a-f]{64}', item['request_hash'])))
        require(isinstance(item['action'], str) and item['action'] in {'register_store', 'configure_store', 'observability'} and text(item['summary'], 180))
    return value


@dataclass(frozen=True)
class Plan:
    base_revision: int
    action: str
    payload_json: str
    summary: str
    changes: tuple[str, ...]


def change(value, action, payload):
    value = deepcopy(value)
    if not isinstance(payload, dict):
        raise RegistryError('Invalid configuration request.')
    if action == 'register_store':
        if set(payload) != {'id', 'name', 'country', 'node_count'}:
            raise RegistryError('A store needs ID, name, country and logical node count only.')
        sid, name, country, count = (payload[k] for k in ('id', 'name', 'country', 'node_count'))
        if not isinstance(sid, str) or not re.fullmatch(r'STORE-[A-Z0-9]+(?:-[A-Z0-9]+)*', sid) or len(sid) > 48:
            raise RegistryError('Use a stable uppercase store ID, such as STORE-DE-01 (48 characters maximum).')
        if any(s['id'] == sid for s in value['stores']):
            raise RegistryError('That store ID is already registered.')
        if not text(name) or not isinstance(country, str) or country not in COUNTRIES:
            raise RegistryError('Use a printable name and valid ISO country, such as DE or GB.')
        store = {'id': sid, 'name': name, 'country': country, 'node_count': count,
                 'desired_state': 'enabled', 'nodes': []}
        value['stores'].append(store)
        summary = 'Registered logical store ' + sid
        changes = ('Register ' + sid + ' / ' + country, 'Create stable logical node identities',
                   'Backend unassigned; data placement unavailable')
    elif action == 'configure_store':
        if set(payload) != {'id', 'desired_state', 'node_count'}:
            raise RegistryError('A store configuration needs ID, desired state and logical node count only.')
        store = next((s for s in value['stores'] if s['id'] == payload['id']), None)
        if store is None:
            raise RegistryError('Store is not registered.')
        if not isinstance(payload['desired_state'], str) or payload['desired_state'] not in {'enabled', 'suspended'}:
            raise RegistryError('Choose enabled or suspended intent.')
        summary = 'Configured logical store ' + store['id']
        changes = (f"Desired state: {store['desired_state']} → {payload['desired_state']}",
                   f"Logical node count: {store['node_count']} → {payload['node_count']}",
                   'Excess node identities retained; physical nodes and data untouched')
        store['desired_state'], store['node_count'] = payload['desired_state'], payload['node_count']
    elif action == 'observability':
        if (set(payload) != {'desired_state'} or not isinstance(payload['desired_state'], str)
                or payload['desired_state'] not in {'enabled', 'suspended'}):
            raise RegistryError('Choose enabled or suspended observability intent.')
        summary = 'Saved observability intent: ' + payload['desired_state']
        changes = (f"Observability intent: {value['observability']['desired_state']} → {payload['desired_state']}",
                   'Collector / Loki / Grafana deployment adapter pending', 'Business SQL audit remains required')
        value['observability'] = dict(payload)
        store = None
    else:
        raise RegistryError('Unsupported configuration operation.')
    if action != 'observability':
        count = store['node_count']
        if type(count) is not int or not 1 <= count <= 9:
            raise RegistryError('Choose between 1 and 9 logical nodes.')
        for index in range(max(count, len(store['nodes']))):
            node = {'id': store['id'] + '-N' + str(index + 1).zfill(2),
                    'desired_state': store['desired_state'] if index < count else 'suspended'}
            if index < len(store['nodes']):
                store['nodes'][index] = node
            else:
                store['nodes'].append(node)
    if len(value['stores']) > 100:
        raise RegistryError('This local registry supports at most 100 stores.')
    return value, summary, changes


class Registry:
    def __init__(self, directory):
        self.directory = Path(directory)
        self.path = self.directory / 'state.json'

    @contextmanager
    def locked(self):
        try:
            self.directory.mkdir(mode=0o700, parents=True, exist_ok=True)
            if self.directory.is_symlink() or self.path.is_symlink():
                raise RegistryError('Administration state must not be a symbolic link.')
            fd = os.open(self.directory / '.lock', os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
            with os.fdopen(fd, 'a') as lock:
                fcntl.flock(lock, fcntl.LOCK_EX)
                yield
        except OSError:
            raise RegistryError('Administration state I/O failed; inspect local storage and retry the same request.') from None

    def _read(self):
        if not self.path.exists():
            self._write(initial())
        try:
            if self.path.stat().st_size > MAX_BYTES:
                raise RegistryError('Administration state exceeds the supported size; archive through a reviewed maintenance procedure.')
            def unique(pairs):
                result = {}
                for key, item in pairs:
                    if key in result:
                        raise RegistryError('Duplicate administration fields; no reset was performed.')
                    result[key] = item
                return result
            return validate(json.loads(self.path.read_text(), object_pairs_hook=unique))
        except (ValueError, TypeError, KeyError, UnicodeError):
            raise RegistryError('Administration state is corrupt; no reset was performed.') from None

    def _write(self, value):
        raw = (json.dumps(validate(value), indent=2) + '\n').encode()
        if len(raw) > MAX_BYTES:
            raise RegistryError('Administration state is full; no change was saved.')
        fd, name = tempfile.mkstemp(prefix='.state-', dir=self.directory)
        try:
            with os.fdopen(fd, 'wb') as stream:
                stream.write(raw)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(name, self.path)
            directory_fd = os.open(self.directory, os.O_RDONLY | os.O_DIRECTORY)
            try:
                os.fsync(directory_fd)
            finally:
                os.close(directory_fd)
        finally:
            if os.path.exists(name):
                os.unlink(name)

    def read(self):
        with self.locked():
            return self._read()

    def plan(self, action, payload):
        with self.locked():
            current = self._read()
            _, summary, changes = change(current, action, payload)
            return Plan(current['revision'], action, canonical(payload), summary, changes)

    def save(self, plan, request_id):
        try:
            request_id = str(uuid.UUID(request_id))
        except (ValueError, TypeError, AttributeError):
            raise RegistryError('A valid request UUID is required.') from None
        fingerprint = hashlib.sha256((plan.action + ':' + plan.payload_json).encode()).hexdigest()
        with self.locked():
            current = self._read()
            prior = next((r for r in current['history'] if r['request_id'] == request_id), None)
            if prior:
                if prior['request_hash'] != fingerprint:
                    raise RegistryError('Request UUID was already used for different input.')
                # Re-establish durability after a possibly failed directory fsync
                # before acknowledging an uncertain original commit as replayed.
                self._write(current)
                return {**prior, 'replayed': True}
            if current['revision'] != plan.base_revision:
                raise RegistryError('Configuration changed since review. Refresh and review again.')
            value, summary, _ = change(current, plan.action, json.loads(plan.payload_json))
            value['revision'] += 1
            receipt = {'request_id': request_id, 'request_hash': fingerprint, 'revision': value['revision'],
                       'at': datetime.now(timezone.utc).isoformat(), 'action': plan.action, 'summary': summary}
            value['history'].append(receipt)
            self._write(value)
            return {**receipt, 'replayed': False}
