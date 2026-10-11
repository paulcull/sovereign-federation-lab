-- Synthetic PoC: business tables contain business data, not residency flags.

CREATE SCHEMA IF NOT EXISTS business;

CREATE SCHEMA IF NOT EXISTS sovereignty;

CREATE SCHEMA IF NOT EXISTS projection;

CREATE TABLE IF NOT EXISTS business.party (
  owner_entity_id STRING NOT NULL,
  id UUID NOT NULL,
  global_party_id UUID NOT NULL,
  party_type STRING NOT NULL,
  display_name STRING NOT NULL,
  PRIMARY KEY (owner_entity_id, id)
);

CREATE TABLE IF NOT EXISTS business.relationship (
  owner_entity_id STRING NOT NULL,
  id UUID NOT NULL,
  relationship_type STRING NOT NULL,
  status STRING NOT NULL,
  PRIMARY KEY (owner_entity_id, id)
);

CREATE TABLE IF NOT EXISTS business.party_relationship (
  owner_entity_id STRING NOT NULL,
  id UUID NOT NULL,
  party_id UUID NOT NULL,
  relationship_id UUID NOT NULL,
  role STRING NOT NULL,
  PRIMARY KEY (owner_entity_id, id),
  FOREIGN KEY (owner_entity_id, party_id) REFERENCES business.party (owner_entity_id, id),
  FOREIGN KEY (owner_entity_id, relationship_id) REFERENCES business.relationship (owner_entity_id, id)
);

CREATE TABLE IF NOT EXISTS business.product_holding (
  owner_entity_id STRING NOT NULL,
  id UUID NOT NULL,
  relationship_id UUID NOT NULL,
  product_type STRING NOT NULL,
  status STRING NOT NULL,
  currency STRING NOT NULL,
  balance DECIMAL(18,2),
  PRIMARY KEY (owner_entity_id, id),
  FOREIGN KEY (owner_entity_id, relationship_id) REFERENCES business.relationship (owner_entity_id, id)
);

CREATE TABLE IF NOT EXISTS business.contact_info (
  owner_entity_id STRING NOT NULL,
  id UUID NOT NULL,
  party_id UUID NOT NULL,
  channel STRING NOT NULL,
  value STRING NOT NULL,
  is_primary BOOL NOT NULL,
  PRIMARY KEY (owner_entity_id, id),
  FOREIGN KEY (owner_entity_id, party_id) REFERENCES business.party (owner_entity_id, id)
);

CREATE TABLE IF NOT EXISTS business.consent (
  owner_entity_id STRING NOT NULL,
  id UUID NOT NULL,
  party_id UUID NOT NULL,
  relationship_id UUID NOT NULL,
  purpose STRING NOT NULL,
  channel STRING NOT NULL,
  status STRING NOT NULL,
  PRIMARY KEY (owner_entity_id, id),
  FOREIGN KEY (owner_entity_id, party_id) REFERENCES business.party (owner_entity_id, id),
  FOREIGN KEY (owner_entity_id, relationship_id) REFERENCES business.relationship (owner_entity_id, id)
);

CREATE TABLE IF NOT EXISTS business.preference (
  owner_entity_id STRING NOT NULL,
  id UUID NOT NULL,
  party_id UUID NOT NULL,
  relationship_id UUID NOT NULL,
  channel STRING NOT NULL,
  language STRING NOT NULL,
  contact_window STRING NOT NULL,
  PRIMARY KEY (owner_entity_id, id),
  FOREIGN KEY (owner_entity_id, party_id) REFERENCES business.party (owner_entity_id, id),
  FOREIGN KEY (owner_entity_id, relationship_id) REFERENCES business.relationship (owner_entity_id, id)
);

CREATE TABLE IF NOT EXISTS business.contact_history (
  owner_entity_id STRING NOT NULL,
  id UUID NOT NULL,
  party_id UUID NOT NULL,
  relationship_id UUID NOT NULL,
  channel STRING NOT NULL,
  occurred_at FLOAT NOT NULL,
  summary STRING NOT NULL,
  agent_id STRING NOT NULL,
  PRIMARY KEY (owner_entity_id, id),
  FOREIGN KEY (owner_entity_id, party_id) REFERENCES business.party (owner_entity_id, id),
  FOREIGN KEY (owner_entity_id, relationship_id) REFERENCES business.relationship (owner_entity_id, id)
);

CREATE TABLE IF NOT EXISTS business.party_alternate_id (
  owner_entity_id STRING NOT NULL,
  id UUID NOT NULL,
  party_id UUID NOT NULL,
  scheme STRING NOT NULL,
  value STRING NOT NULL,
  PRIMARY KEY (owner_entity_id, id),
  FOREIGN KEY (owner_entity_id, party_id) REFERENCES business.party (owner_entity_id, id)
);

CREATE TABLE IF NOT EXISTS business.relationship_alternate_id (
  owner_entity_id STRING NOT NULL,
  id UUID NOT NULL,
  relationship_id UUID NOT NULL,
  scheme STRING NOT NULL,
  value STRING NOT NULL,
  PRIMARY KEY (owner_entity_id, id),
  FOREIGN KEY (owner_entity_id, relationship_id) REFERENCES business.relationship (owner_entity_id, id)
);

CREATE TABLE IF NOT EXISTS business.holding_alternate_id (
  owner_entity_id STRING NOT NULL,
  id UUID NOT NULL,
  holding_id UUID NOT NULL,
  scheme STRING NOT NULL,
  value STRING NOT NULL,
  PRIMARY KEY (owner_entity_id, id),
  FOREIGN KEY (owner_entity_id, holding_id) REFERENCES business.product_holding (owner_entity_id, id)
);

CREATE TABLE IF NOT EXISTS business.classification (
  owner_entity_id STRING NOT NULL,
  id UUID NOT NULL,
  subject_type STRING NOT NULL,
  party_id UUID,
  relationship_id UUID,
  holding_id UUID,
  code STRING NOT NULL,
  level STRING NOT NULL,
  PRIMARY KEY (owner_entity_id, id),
  FOREIGN KEY (owner_entity_id, party_id) REFERENCES business.party (owner_entity_id, id),
  FOREIGN KEY (owner_entity_id, relationship_id) REFERENCES business.relationship (owner_entity_id, id),
  FOREIGN KEY (owner_entity_id, holding_id) REFERENCES business.product_holding (owner_entity_id, id),
  CHECK ((subject_type='party' AND party_id IS NOT NULL AND relationship_id IS NULL AND holding_id IS NULL) OR (subject_type='relationship' AND relationship_id IS NOT NULL AND party_id IS NULL AND holding_id IS NULL) OR (subject_type='holding' AND holding_id IS NOT NULL AND party_id IS NULL AND relationship_id IS NULL))
);

CREATE TABLE IF NOT EXISTS projection.party (
  owner_entity_id STRING NOT NULL,
  scope_id UUID NOT NULL,
  destination_entity_id STRING NOT NULL,
  id UUID NOT NULL,
  global_party_id UUID,
  party_type STRING,
  display_name STRING,
  PRIMARY KEY (owner_entity_id, scope_id, destination_entity_id, id)
);

CREATE TABLE IF NOT EXISTS projection.relationship (
  owner_entity_id STRING NOT NULL,
  scope_id UUID NOT NULL,
  destination_entity_id STRING NOT NULL,
  id UUID NOT NULL,
  relationship_type STRING,
  status STRING,
  PRIMARY KEY (owner_entity_id, scope_id, destination_entity_id, id)
);

CREATE TABLE IF NOT EXISTS projection.party_relationship (
  owner_entity_id STRING NOT NULL,
  scope_id UUID NOT NULL,
  destination_entity_id STRING NOT NULL,
  id UUID NOT NULL,
  party_id UUID NOT NULL,
  relationship_id UUID NOT NULL,
  role STRING,
  PRIMARY KEY (owner_entity_id, scope_id, destination_entity_id, id),
  FOREIGN KEY (owner_entity_id, scope_id, destination_entity_id, party_id) REFERENCES projection.party (owner_entity_id, scope_id, destination_entity_id, id),
  FOREIGN KEY (owner_entity_id, scope_id, destination_entity_id, relationship_id) REFERENCES projection.relationship (owner_entity_id, scope_id, destination_entity_id, id)
);

CREATE TABLE IF NOT EXISTS projection.product_holding (
  owner_entity_id STRING NOT NULL,
  scope_id UUID NOT NULL,
  destination_entity_id STRING NOT NULL,
  id UUID NOT NULL,
  relationship_id UUID NOT NULL,
  product_type STRING,
  status STRING,
  currency STRING,
  balance DECIMAL(18,2),
  PRIMARY KEY (owner_entity_id, scope_id, destination_entity_id, id),
  FOREIGN KEY (owner_entity_id, scope_id, destination_entity_id, relationship_id) REFERENCES projection.relationship (owner_entity_id, scope_id, destination_entity_id, id)
);

CREATE TABLE IF NOT EXISTS projection.contact_info (
  owner_entity_id STRING NOT NULL,
  scope_id UUID NOT NULL,
  destination_entity_id STRING NOT NULL,
  id UUID NOT NULL,
  party_id UUID NOT NULL,
  channel STRING,
  value STRING,
  is_primary BOOL,
  PRIMARY KEY (owner_entity_id, scope_id, destination_entity_id, id),
  FOREIGN KEY (owner_entity_id, scope_id, destination_entity_id, party_id) REFERENCES projection.party (owner_entity_id, scope_id, destination_entity_id, id)
);

CREATE TABLE IF NOT EXISTS projection.consent (
  owner_entity_id STRING NOT NULL,
  scope_id UUID NOT NULL,
  destination_entity_id STRING NOT NULL,
  id UUID NOT NULL,
  party_id UUID NOT NULL,
  relationship_id UUID NOT NULL,
  purpose STRING,
  channel STRING,
  status STRING,
  PRIMARY KEY (owner_entity_id, scope_id, destination_entity_id, id),
  FOREIGN KEY (owner_entity_id, scope_id, destination_entity_id, party_id) REFERENCES projection.party (owner_entity_id, scope_id, destination_entity_id, id),
  FOREIGN KEY (owner_entity_id, scope_id, destination_entity_id, relationship_id) REFERENCES projection.relationship (owner_entity_id, scope_id, destination_entity_id, id)
);

CREATE TABLE IF NOT EXISTS projection.preference (
  owner_entity_id STRING NOT NULL,
  scope_id UUID NOT NULL,
  destination_entity_id STRING NOT NULL,
  id UUID NOT NULL,
  party_id UUID NOT NULL,
  relationship_id UUID NOT NULL,
  channel STRING,
  language STRING,
  contact_window STRING,
  PRIMARY KEY (owner_entity_id, scope_id, destination_entity_id, id),
  FOREIGN KEY (owner_entity_id, scope_id, destination_entity_id, party_id) REFERENCES projection.party (owner_entity_id, scope_id, destination_entity_id, id),
  FOREIGN KEY (owner_entity_id, scope_id, destination_entity_id, relationship_id) REFERENCES projection.relationship (owner_entity_id, scope_id, destination_entity_id, id)
);

CREATE TABLE IF NOT EXISTS projection.contact_history (
  owner_entity_id STRING NOT NULL,
  scope_id UUID NOT NULL,
  destination_entity_id STRING NOT NULL,
  id UUID NOT NULL,
  party_id UUID NOT NULL,
  relationship_id UUID NOT NULL,
  channel STRING,
  occurred_at FLOAT,
  summary STRING,
  agent_id STRING,
  PRIMARY KEY (owner_entity_id, scope_id, destination_entity_id, id),
  FOREIGN KEY (owner_entity_id, scope_id, destination_entity_id, party_id) REFERENCES projection.party (owner_entity_id, scope_id, destination_entity_id, id),
  FOREIGN KEY (owner_entity_id, scope_id, destination_entity_id, relationship_id) REFERENCES projection.relationship (owner_entity_id, scope_id, destination_entity_id, id)
);

CREATE TABLE IF NOT EXISTS projection.party_alternate_id (
  owner_entity_id STRING NOT NULL,
  scope_id UUID NOT NULL,
  destination_entity_id STRING NOT NULL,
  id UUID NOT NULL,
  party_id UUID NOT NULL,
  scheme STRING,
  value STRING,
  PRIMARY KEY (owner_entity_id, scope_id, destination_entity_id, id),
  FOREIGN KEY (owner_entity_id, scope_id, destination_entity_id, party_id) REFERENCES projection.party (owner_entity_id, scope_id, destination_entity_id, id)
);

CREATE TABLE IF NOT EXISTS projection.relationship_alternate_id (
  owner_entity_id STRING NOT NULL,
  scope_id UUID NOT NULL,
  destination_entity_id STRING NOT NULL,
  id UUID NOT NULL,
  relationship_id UUID NOT NULL,
  scheme STRING,
  value STRING,
  PRIMARY KEY (owner_entity_id, scope_id, destination_entity_id, id),
  FOREIGN KEY (owner_entity_id, scope_id, destination_entity_id, relationship_id) REFERENCES projection.relationship (owner_entity_id, scope_id, destination_entity_id, id)
);

CREATE TABLE IF NOT EXISTS projection.holding_alternate_id (
  owner_entity_id STRING NOT NULL,
  scope_id UUID NOT NULL,
  destination_entity_id STRING NOT NULL,
  id UUID NOT NULL,
  holding_id UUID NOT NULL,
  scheme STRING,
  value STRING,
  PRIMARY KEY (owner_entity_id, scope_id, destination_entity_id, id),
  FOREIGN KEY (owner_entity_id, scope_id, destination_entity_id, holding_id) REFERENCES projection.product_holding (owner_entity_id, scope_id, destination_entity_id, id)
);

CREATE TABLE IF NOT EXISTS projection.classification (
  owner_entity_id STRING NOT NULL,
  scope_id UUID NOT NULL,
  destination_entity_id STRING NOT NULL,
  id UUID NOT NULL,
  subject_type STRING NOT NULL,
  party_id UUID,
  relationship_id UUID,
  holding_id UUID,
  code STRING,
  level STRING,
  PRIMARY KEY (owner_entity_id, scope_id, destination_entity_id, id),
  FOREIGN KEY (owner_entity_id, scope_id, destination_entity_id, party_id) REFERENCES projection.party (owner_entity_id, scope_id, destination_entity_id, id),
  FOREIGN KEY (owner_entity_id, scope_id, destination_entity_id, relationship_id) REFERENCES projection.relationship (owner_entity_id, scope_id, destination_entity_id, id),
  FOREIGN KEY (owner_entity_id, scope_id, destination_entity_id, holding_id) REFERENCES projection.product_holding (owner_entity_id, scope_id, destination_entity_id, id),
  CHECK ((subject_type='party' AND party_id IS NOT NULL AND relationship_id IS NULL AND holding_id IS NULL) OR (subject_type='relationship' AND relationship_id IS NOT NULL AND party_id IS NULL AND holding_id IS NULL) OR (subject_type='holding' AND holding_id IS NOT NULL AND party_id IS NULL AND relationship_id IS NULL))
);

CREATE TABLE IF NOT EXISTS sovereignty.scope (
 id UUID PRIMARY KEY, owner_entity_id STRING NOT NULL, relationship_id UUID NULL,
 data_version INT NOT NULL, policy_generation INT NOT NULL, decision_revision INT NOT NULL, doc JSONB NOT NULL,
 root_type STRING NOT NULL, root_id UUID NOT NULL, primary_party_id UUID NOT NULL,
 UNIQUE(owner_entity_id,id), UNIQUE(owner_entity_id,root_type,root_id),
 CHECK ((root_type = 'party' AND relationship_id IS NULL AND root_id = primary_party_id)
 OR (root_type = 'relationship' AND relationship_id IS NOT NULL AND root_id = relationship_id)),
 FOREIGN KEY(owner_entity_id,relationship_id) REFERENCES business.relationship(owner_entity_id,id),
 FOREIGN KEY(owner_entity_id,primary_party_id) REFERENCES business.party(owner_entity_id,id)
);

CREATE TABLE IF NOT EXISTS sovereignty.resource_rule (owner_entity_id STRING NOT NULL, resource_type STRING NOT NULL, resource_id UUID NOT NULL, rule JSONB NOT NULL, PRIMARY KEY(owner_entity_id,resource_type,resource_id));

CREATE TABLE IF NOT EXISTS sovereignty.binding (owner_entity_id STRING NOT NULL, scope_id UUID NOT NULL, resource_type STRING NOT NULL, resource_id UUID NOT NULL, PRIMARY KEY(owner_entity_id,scope_id,resource_type,resource_id), FOREIGN KEY(owner_entity_id,scope_id) REFERENCES sovereignty.scope(owner_entity_id,id), FOREIGN KEY(owner_entity_id,resource_type,resource_id) REFERENCES sovereignty.resource_rule(owner_entity_id,resource_type,resource_id));

CREATE TABLE IF NOT EXISTS sovereignty.outbox (id UUID PRIMARY KEY, scope_id UUID NOT NULL, destination_entity_id STRING NOT NULL, status STRING NOT NULL DEFAULT 'queued', attempts INT NOT NULL DEFAULT 0, reason STRING NOT NULL DEFAULT '', created_at FLOAT NOT NULL);

CREATE TABLE IF NOT EXISTS sovereignty.audit (id UUID PRIMARY KEY, ts FLOAT NOT NULL, doc JSONB NOT NULL);

CREATE TABLE IF NOT EXISTS sovereignty.command_receipt (owner_entity_id STRING NOT NULL, request_id UUID NOT NULL, request_hash STRING NOT NULL, result JSONB NOT NULL, PRIMARY KEY(owner_entity_id,request_id));

CREATE TABLE IF NOT EXISTS sovereignty.inbox (event_id UUID PRIMARY KEY, received_at FLOAT NOT NULL);

CREATE TABLE IF NOT EXISTS sovereignty.manifest (owner_entity_id STRING NOT NULL, scope_id UUID NOT NULL, destination_entity_id STRING NOT NULL, data_version INT NOT NULL, policy_generation INT NOT NULL, decision_revision INT NOT NULL, placement_version INT NOT NULL, row_counts JSONB NOT NULL, PRIMARY KEY(owner_entity_id,scope_id,destination_entity_id));

CREATE TABLE IF NOT EXISTS sovereignty.table_rule (owner_entity_id STRING NOT NULL, resource_type STRING NOT NULL, rule JSONB NOT NULL, PRIMARY KEY(owner_entity_id,resource_type));
