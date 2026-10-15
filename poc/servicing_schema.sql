-- Independent service schema. No business.*, sovereignty.* or mdm.* foreign keys.
-- All identifiers and customer associations remain in this service's SG store.
CREATE SCHEMA IF NOT EXISTS servicing;

CREATE TABLE IF NOT EXISTS servicing.case_record (
    owner_entity_id STRING NOT NULL,
    case_id UUID NOT NULL,
    mdm_owner_entity_id STRING NOT NULL,
    global_party_id UUID NOT NULL,
    relationship_scope_id UUID NOT NULL,
    category STRING NOT NULL CHECK (category IN ('CONTACT_REVIEW','DOCUMENT_REVIEW')),
    status STRING NOT NULL CHECK (status IN ('OPEN','CLOSED')),
    data_version INT8 NOT NULL CHECK (data_version > 0),
    PRIMARY KEY (owner_entity_id,case_id)
);
CREATE TABLE IF NOT EXISTS servicing.aggregate_version (
    service_id STRING NOT NULL, owner_entity_id STRING NOT NULL,
    aggregate_id UUID NOT NULL, data_version INT8 NOT NULL,
    PRIMARY KEY(service_id,owner_entity_id,aggregate_id)
);
CREATE TABLE IF NOT EXISTS servicing.state_outbox (
    event_id UUID PRIMARY KEY, service_id STRING NOT NULL, owner_entity_id STRING NOT NULL,
    aggregate_id UUID NOT NULL, data_version INT8 NOT NULL,
    intent_kind STRING NOT NULL CHECK (intent_kind = 'current_state'),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE(service_id,owner_entity_id,aggregate_id,data_version)
);
CREATE TABLE IF NOT EXISTS servicing.transition_event (
    event_id UUID PRIMARY KEY, service_id STRING NOT NULL, owner_entity_id STRING NOT NULL,
    aggregate_id UUID NOT NULL, data_version INT8 NOT NULL, operation STRING NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE(service_id,owner_entity_id,aggregate_id,data_version)
);
CREATE TABLE IF NOT EXISTS servicing.transaction_audit (
    event_id UUID PRIMARY KEY, service_id STRING NOT NULL, owner_entity_id STRING NOT NULL,
    aggregate_id UUID NOT NULL, data_version INT8 NOT NULL, actor_id STRING NOT NULL,
    request_id UUID NOT NULL, operation STRING NOT NULL, authority_observation JSONB NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE TABLE IF NOT EXISTS servicing.request_receipt (
    service_id STRING NOT NULL, owner_entity_id STRING NOT NULL, actor_id STRING NOT NULL,
    request_id UUID NOT NULL, request_hash STRING NOT NULL, result JSONB NOT NULL,
    PRIMARY KEY(service_id,owner_entity_id,actor_id,request_id)
);
CREATE TABLE IF NOT EXISTS servicing.delivery_receipt (
    service_id STRING NOT NULL, owner_entity_id STRING NOT NULL, aggregate_id UUID NOT NULL,
    destination_entity_id STRING NOT NULL, data_version INT8 NOT NULL,
    acknowledged_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY(service_id,owner_entity_id,aggregate_id,destination_entity_id)
);

CREATE USER IF NOT EXISTS sfl_servicing;
CREATE USER IF NOT EXISTS sfl_servicing_reader;
GRANT USAGE ON SCHEMA servicing TO sfl_servicing, sfl_servicing_reader;
GRANT SELECT,INSERT,UPDATE ON TABLE servicing.case_record,servicing.aggregate_version TO sfl_servicing;
GRANT SELECT,INSERT ON TABLE servicing.state_outbox,servicing.transition_event,
    servicing.transaction_audit,servicing.request_receipt TO sfl_servicing;
GRANT SELECT,INSERT,UPDATE ON TABLE servicing.delivery_receipt TO sfl_servicing;
GRANT SELECT ON TABLE servicing.case_record TO sfl_servicing_reader;
