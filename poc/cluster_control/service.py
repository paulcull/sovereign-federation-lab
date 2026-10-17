# SPDX-License-Identifier: MIT
"""Real CockroachDB inventory and regional, durable synthetic recovery jobs.

Only server-registered targets and fixed SQL operations are accepted. No Docker
socket, arbitrary SQL, customer rows, credentials or raw exception text enter the
operator interface or application logs. This adapter is for the trusted loopback
lab; regional identity, TLS and external backup storage remain production work.
"""
import hashlib
import json
import math
import os
import re
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from typing import Literal
from urllib.parse import urlsplit

import httpx
import psycopg
from fastapi import APIRouter, HTTPException, Request
from psycopg.types.json import Jsonb
from pydantic import BaseModel, ConfigDict

TARGETS = {
    "sg": {"name": "Singapore", "city": "Singapore", "country": "SG", "env": "SG"},
    "uk": {"name": "United Kingdom", "city": "London", "country": "GB", "env": "UK"},
    "us": {"name": "United States", "city": "New York", "country": "US", "env": "US"},
    "in": {"name": "India", "city": "Mumbai", "country": "IN", "env": "IN"},
}
KINDS = {"health_check": "Cluster health check", "recovery_rehearsal": "Recovery rehearsal"}
STEPS = {
    "health_check": ["Connect to CockroachDB", "Inspect nodes and ranges", "Verify country locality"],
    "recovery_rehearsal": ["Check database health", "Create synthetic canary", "Back up with CockroachDB", "Restore and compare", "Remove temporary databases"],
}
CANARY = [(1, "synthetic-control-canary"), (2, "regional-recovery-proof"), (3, "no-customer-payload")]


class Operation(BaseModel):
    model_config = ConfigDict(extra="forbid")
    kind: Literal["health_check", "recovery_rehearsal"]
    request_id: uuid.UUID
    confirmation: str = ""


class ClusterControl:
    def __init__(self):
        self.stop = threading.Event()
        self.threads = []
        self.pending_updates = {}

    def target(self, key):
        if key not in TARGETS:
            raise HTTPException(404, "Unknown registered cluster")
        return TARGETS[key]

    def connect(self, key, *, long=False):
        env = self.target(key)["env"]
        dsn = os.environ.get("DB_" + env)
        if not dsn:
            raise RuntimeError("Registered cluster is not configured")
        return psycopg.connect(dsn, connect_timeout=2, autocommit=True,
                               options="-c statement_timeout=" + ("60000" if long else "4000"))

    def initialize(self, key):
        # Schema backfills need a longer budget than bounded observation queries.
        with self.connect(key, long=True) as c:
            c.execute("CREATE SCHEMA IF NOT EXISTS cluster_control")
            c.execute("""CREATE TABLE IF NOT EXISTS cluster_control.jobs (
                id UUID PRIMARY KEY, request_id UUID UNIQUE NOT NULL,
                kind STRING NOT NULL, state STRING NOT NULL, created_at FLOAT NOT NULL,
                updated_at FLOAT NOT NULL, steps JSONB NOT NULL, result JSONB NOT NULL,
                error_code STRING NOT NULL DEFAULT '', actor STRING NOT NULL DEFAULT 'development-operator',
                INDEX jobs_recovery_status (kind,state,updated_at DESC),
                INDEX jobs_queue (state,created_at), INDEX jobs_history (created_at DESC))""")
            c.execute("""CREATE TABLE IF NOT EXISTS cluster_control.events (
                id UUID PRIMARY KEY, job_id UUID NOT NULL, ts FLOAT NOT NULL,
                state STRING NOT NULL, step INT NOT NULL)""")
            c.execute("CREATE TABLE IF NOT EXISTS cluster_control.guard (id INT PRIMARY KEY, revision INT NOT NULL)")
            c.execute("INSERT INTO cluster_control.guard VALUES (1, 0) ON CONFLICT (id) DO NOTHING")
            # An interrupted mutation is not silently replayed after a restart.
        self.interrupt_running(key, "coordinator_restarted")

    def interrupt_running(self, key, error):
        """Called only when this region's single worker has no executing task."""
        with self.connect(key) as c, c.transaction():
            rows = c.execute("UPDATE cluster_control.jobs SET state='interrupted', error_code=%s, updated_at=%s WHERE state='running' RETURNING id,steps", (error, time.time())).fetchall()
            for job, steps in rows:
                for step in steps:
                    if step["state"] == "running":
                        step["state"] = "interrupted"
                c.execute("UPDATE cluster_control.jobs SET steps=%s WHERE id=%s", (Jsonb(steps), job))
                c.execute("INSERT INTO cluster_control.events VALUES (%s,%s,%s,'interrupted',-1)", (uuid.uuid4(), job, time.time()))

    def start(self):
        self.stop.clear()
        self.threads = [threading.Thread(target=self.worker, args=(key,), daemon=True) for key in TARGETS]
        for thread in self.threads:
            thread.start()

    def shutdown(self):
        self.stop.set()
        for thread in self.threads:
            thread.join(timeout=2)

    def snapshot(self, key):
        target = self.target(key)
        out = {"id": key, **{k: target[k] for k in ("name", "city", "country")},
               "observed_at": time.time(), "status": "unreachable", "sql": False,
               "nodes": [], "databases": [], "version": None, "cluster_id": None,
               "topology": "single-node development", "ha": False,
               "business_backup_configured": False}
        started = time.monotonic()
        try:
            with self.connect(key) as c:
                identity = c.execute("SELECT crdb_internal.cluster_id()::STRING, version()").fetchone()
                if "CockroachDB" not in identity[1]:
                    return out
                out.update(sql=True, cluster_id=identity[0], version=re.search(r"v\d+\.\d+\.\d+", identity[1])[0],
                           cluster_version=c.execute("SHOW CLUSTER SETTING version").fetchone()[0])
                out["databases"] = [{"name": row[0], "kind": "system" if row[0] in ("system", "postgres") else "application"}
                                    for row in c.execute("SHOW DATABASES").fetchall() if not row[0].startswith("sfl_canary_")]
            out["sql_latency_ms"] = round((time.monotonic() - started) * 1000, 1)
            response = httpx.get("http://db-" + key + ":8080/_status/nodes", timeout=3, trust_env=False)
            response.raise_for_status()
            body = response.json()
            if not isinstance(body.get("nodes"), list) or not body["nodes"]:
                raise ValueError("Node inventory missing")
            for node in body["nodes"]:
                desc, metrics = node["desc"], node.get("metrics", {})
                stores = [s.get("metrics", {}) for s in node.get("storeStatuses", [])]
                required = ("ranges", "ranges.unavailable", "ranges.underreplicated", "capacity", "capacity.used", "capacity.available")
                if not stores or any(not isinstance(s.get(name), (float, int)) or isinstance(s.get(name), bool)
                                     or not math.isfinite(s[name]) or s[name] < 0 for s in stores for name in required):
                    raise ValueError("Store metrics incomplete")
                total = lambda name: sum(s.get(name, 0) for s in stores)
                live = body.get("livenessByNodeId", {}).get(str(desc["nodeId"]))
                out["nodes"].append({"id": desc["nodeId"], "status": "live" if live == 3 else "not-live",
                    "version": desc.get("buildTag"), "locality": {t["key"]: t["value"] for t in desc.get("locality", {}).get("tiers", [])},
                    "ranges": total("ranges"), "unavailable_ranges": total("ranges.unavailable"),
                    "under_replicated_ranges": total("ranges.underreplicated"),
                    "storage_used_bytes": total("capacity.used"), "disk_available_bytes": total("capacity.available"), "disk_capacity_bytes": total("capacity"),
                    "cpu_percent": round(metrics.get("sys.cpu.combined.percent-normalized", 0) * 100, 1),
                    "memory_bytes": metrics.get("sys.rss", 0), "sql_connections": metrics.get("sql.conns", 0)})
            nodes = out["nodes"]
            out["status"] = "healthy" if nodes and all(n["status"] == "live" and n["unavailable_ranges"] == 0 for n in nodes) else "attention"
            out["locality_matches"] = bool(nodes) and all(n["locality"].get("country") == target["country"] for n in nodes)
            if not out["locality_matches"]:
                out["status"] = "attention"
        except Exception:
            out["status"] = "partial" if out["sql"] else "unreachable"
        out["recovery_ready"] = out["status"] == "healthy" and bool(out["nodes"]) and all(
            n["disk_available_bytes"] >= max(n["disk_capacity_bytes"] * .08, 512 * 1024 * 1024) for n in out["nodes"])
        return out

    def history(self, key):
        self.target(key)
        try:
            with self.connect(key) as c:
                rows = c.execute("SELECT id,kind,state,created_at,updated_at,steps,result,error_code,actor FROM cluster_control.jobs ORDER BY created_at DESC LIMIT 30").fetchall()
                latest = c.execute("SELECT id,kind,state,created_at,updated_at,steps,result,error_code,actor FROM cluster_control.jobs WHERE kind='recovery_rehearsal' AND state='succeeded' ORDER BY updated_at DESC LIMIT 1").fetchone()
            return {"available": True, "jobs": [self.job_dict(key, row) for row in rows],
                    "latest_recovery": self.job_dict(key, latest) if latest else None}
        except Exception:
            return {"available": False, "jobs": [], "latest_recovery": None}

    @staticmethod
    def job_dict(key, row):
        return dict(zip(["id", "kind", "state", "created_at", "updated_at", "steps", "result", "error_code", "actor"],
                        [str(row[0]), *row[1:]]), cluster=key)

    def enqueue(self, key, body):
        for attempt in range(3):
            try:
                return self._enqueue(key, body)
            except psycopg.errors.SerializationFailure:
                if attempt == 2:
                    raise HTTPException(503, "Operation journal busy; retry with the same request identifier") from None
                time.sleep(.03 * (attempt + 1))

    def _enqueue(self, key, body):
        self.target(key)
        if body.kind == "recovery_rehearsal" and body.confirmation != key:
            raise HTTPException(422, "Confirm the selected cluster before the recovery rehearsal")
        try:
            with self.connect(key) as c, c.transaction():
                c.execute("SELECT revision FROM cluster_control.guard WHERE id=1 FOR UPDATE").fetchone()
                old = c.execute("SELECT id,kind FROM cluster_control.jobs WHERE request_id=%s", (body.request_id,)).fetchone()
                if old:
                    if old[1] != body.kind:
                        raise HTTPException(409, "Request identifier was already used for a different operation")
                    return {"id": str(old[0]), "replayed": True}
                pending = c.execute("SELECT count(*) FROM cluster_control.jobs WHERE kind=%s AND state IN ('queued','running')", (body.kind,)).fetchone()[0]
                uncertain = c.execute("SELECT count(*) FROM cluster_control.jobs WHERE kind='recovery_rehearsal' AND state='interrupted'").fetchone()[0]
                if pending or (body.kind == "recovery_rehearsal" and uncertain):
                    raise HTTPException(409, "An operation is active or an interrupted recovery requires inspection")
                job, now = uuid.uuid4(), time.time()
                steps = [{"label": label, "state": "pending"} for label in STEPS[body.kind]]
                c.execute("INSERT INTO cluster_control.jobs (id,request_id,kind,state,created_at,updated_at,steps,result) VALUES (%s,%s,%s,'queued',%s,%s,%s,%s)",
                          (job, body.request_id, body.kind, now, now, Jsonb(steps), Jsonb({})))
                c.execute("INSERT INTO cluster_control.events VALUES (%s,%s,%s,'queued',-1)", (uuid.uuid4(), job, now))
                c.execute("UPDATE cluster_control.guard SET revision=revision+1 WHERE id=1")
            return {"id": str(job), "replayed": False}
        except HTTPException:
            raise
        except psycopg.errors.SerializationFailure:
            raise
        except Exception:
            raise HTTPException(503, "Operation acceptance is uncertain; retry with the same request identifier") from None

    def update(self, key, job, state, steps, result=None, error="", step=-1):
        with self.connect(key) as c, c.transaction():
            c.execute("UPDATE cluster_control.jobs SET state=%s,updated_at=%s,steps=%s,result=%s,error_code=%s WHERE id=%s",
                      (state, time.time(), Jsonb(steps), Jsonb(result or {}), error, job))
            c.execute("INSERT INTO cluster_control.events VALUES (%s,%s,%s,%s,%s)", (uuid.uuid4(), job, time.time(), state, step))

    def worker(self, key):
        initialized = False
        while not self.stop.is_set():
            try:
                if not initialized:
                    self.initialize(key)
                    initialized = True
                # Persist any known native receipts before reconciling or taking
                # another job. Retrying the journal never replays native SQL.
                self.flush_pending_update(key)
                # Reconcile a lost final journal write once SQL recovers. Never
                # leave Running forever or replay an uncertain database mutation.
                self.interrupt_running(key, "execution_state_uncertain")
                with self.connect(key) as c:
                    row = c.execute("""UPDATE cluster_control.jobs SET state='running',updated_at=%s
                        WHERE id=(SELECT id FROM cluster_control.jobs WHERE state='queued' ORDER BY created_at LIMIT 1)
                        AND state='queued' RETURNING id,kind,steps""", (time.time(),)).fetchone()
                if row:
                    self.execute(key, *row)
            except Exception:
                # Retain journal state on database failure; never log SQL/DSNs.
                pass
            self.stop.wait(1)

    def flush_pending_update(self, key):
        pending = self.pending_updates.get(key)
        if pending is not None:
            self.update(key, **pending)
            del self.pending_updates[key]

    def execute(self, key, job, kind, steps):
        source = "sfl_canary_" + job.hex
        restored = source + "_restore"
        mutation_started = False
        error_code = ""
        try:
            result = {}
            for index, _ in enumerate(steps):
                if self.stop.is_set():
                    raise RuntimeError("Interrupted")
                steps[index]["state"] = "running"
                self.update(key, job, "running", steps, result, step=index)
                if kind == "health_check":
                    snap = self.snapshot(key)
                    result = {"sql": snap["sql"],
                              "live_nodes": sum(n["status"] == "live" for n in snap["nodes"]),
                              "locality_matches": snap.get("locality_matches", False), "ha": False}
                    checks = [snap["sql"], snap["status"] == "healthy", result["locality_matches"]]
                    if not checks[index] or (index == len(steps) - 1 and not all(checks)):
                        raise RuntimeError("Check failed")
                    if index == len(steps) - 1:
                        result["summary"] = "SQL, live nodes, available ranges and country labels verified. Single-node topology has no failover."
                elif index == 0:
                    snap = self.snapshot(key)
                    if snap["status"] != "healthy" or not snap.get("locality_matches"):
                        raise RuntimeError("Preflight failed")
                    if not snap.get("recovery_ready"):
                        error_code = "insufficient_disk_headroom"
                        raise RuntimeError("Insufficient disk headroom")
                elif index == 1:
                    mutation_started = True
                    with self.connect(key, long=True) as c:
                        c.execute(psycopg.sql.SQL("CREATE DATABASE {}").format(psycopg.sql.Identifier(source)))
                        c.execute(psycopg.sql.SQL("CREATE TABLE {}.public.canary (id INT PRIMARY KEY, value STRING NOT NULL)").format(psycopg.sql.Identifier(source)))
                        c.cursor().executemany(psycopg.sql.SQL("INSERT INTO {}.public.canary VALUES (%s,%s)").format(psycopg.sql.Identifier(source)), CANARY)
                elif index == 2:
                    with self.connect(key, long=True) as c:
                        native = c.execute(psycopg.sql.SQL("BACKUP DATABASE {} INTO %s").format(psycopg.sql.Identifier(source)),
                                           ("nodelocal://1/cluster-control/" + job.hex,)).fetchone()
                        result["backup_job_id"] = str(native[0])
                elif index == 3:
                    with self.connect(key, long=True) as c:
                        native = c.execute(psycopg.sql.SQL("RESTORE DATABASE {} FROM LATEST IN %s WITH new_db_name = %s").format(psycopg.sql.Identifier(source)),
                                           ("nodelocal://1/cluster-control/" + job.hex, restored)).fetchone()
                        result["restore_job_id"] = str(native[0])
                        actual = c.execute(psycopg.sql.SQL("SELECT id,value FROM {}.public.canary ORDER BY id").format(psycopg.sql.Identifier(restored))).fetchall()
                        if actual != CANARY:
                            raise RuntimeError("Restored contents differ")
                        result = {**result, "restore_job_id": str(native[0]), "verified_rows": len(actual), "digest": hashlib.sha256(json.dumps(actual).encode()).hexdigest(),
                                  "backup_scope": "synthetic_canary", "storage": "same_cluster_node_local",
                                  "business_backup": False, "summary": "Native BACKUP and RESTORE verified three synthetic rows. Business backup and off-host disaster recovery remain unconfigured."}
                elif index == 4:
                    with self.connect(key, long=True) as c:
                        for database in (restored, source):
                            c.execute(psycopg.sql.SQL("DROP DATABASE {} CASCADE").format(psycopg.sql.Identifier(database)))
                steps[index]["state"] = "succeeded"
                self.update(key, job, "running", steps, result, step=index)
            self.update(key, job, "succeeded", steps, result)
        except Exception:
            terminal = "interrupted" if kind == "recovery_rehearsal" and mutation_started else "failed"
            for step in steps:
                if step["state"] == "running":
                    step["state"] = terminal
            # Leave failed canary artifacts for inspection, never delete on guesswork.
            pending = {"job": job, "state": terminal, "steps": deepcopy(steps), "result": deepcopy(result),
                       "error": error_code or ("operation_requires_inspection" if terminal == "interrupted" else "operation_failed_inspect_cluster")}
            try:
                self.update(key, **pending)
            except Exception:
                # Keep known receipts while this process survives the SQL outage.
                # A process loss still requires native-job/artifact inspection.
                self.pending_updates[key] = pending

    def environment(self):
        targets = [("Policy · " + t["name"], "http://opa-" + k + ":8181/health") for k, t in TARGETS.items()]
        targets += [("Grafana", "http://grafana:3000/api/health"), ("Loki", "http://loki:3100/ready")]
        def check(item):
            name, url = item
            try:
                r = httpx.get(url, timeout=3, trust_env=False)
                return {"name": name, "status": "healthy" if r.status_code == 200 else "unavailable"}
            except Exception:
                return {"name": name, "status": "unavailable"}
        with ThreadPoolExecutor(max_workers=6) as pool:
            services = list(pool.map(check, targets))
        return {"name": "Federation development lab", "deployment": "Docker Compose", "host_count": 1,
                "geography_attested": False, "services": services, "observed_at": time.time()}

    def router(self):
        router = APIRouter(prefix="/api/cluster-control", tags=["Cluster control"])

        @router.get("/clusters")
        def clusters():
            with ThreadPoolExecutor(max_workers=4) as pool:
                snapshots = list(pool.map(self.snapshot, TARGETS))
            return {"mode": "live", "observed_at": time.time(), "clusters": snapshots,
                    "boundary": "Four independent database clusters on one development host; geography labels are not physical residency evidence."}

        @router.get("/clusters/{key}/operations")
        def history(key: str):
            return self.history(key)

        @router.post("/clusters/{key}/operations", status_code=202)
        def operate(key: str, body: Operation, request: Request):
            if request.headers.get("x-lab-control") != "1":
                raise HTTPException(403, "Same-origin control header required")
            origin = request.headers.get("origin")
            if origin and (urlsplit(origin).netloc != request.headers.get("host") or urlsplit(origin).scheme != request.url.scheme):
                raise HTTPException(403, "Cross-origin control operations are forbidden")
            if request.headers.get("sec-fetch-site") in ("cross-site", "same-site"):
                raise HTTPException(403, "Same-origin control operation required")
            return self.enqueue(key, body)

        @router.get("/environment")
        def environment():
            return self.environment()

        return router
