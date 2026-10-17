CREATE SCHEMA IF NOT EXISTS servicing_projection;
CREATE TABLE IF NOT EXISTS servicing_projection.case_state (
    owner_entity_id STRING NOT NULL, case_id UUID NOT NULL,
    destination_entity_id STRING NOT NULL, data_version INT8 NOT NULL,
    policy_revision INT8 NOT NULL, payload_hash STRING NOT NULL, row_data JSONB NOT NULL,
    PRIMARY KEY(owner_entity_id,case_id,destination_entity_id)
);
CREATE TABLE IF NOT EXISTS servicing_projection.inbox (
    owner_entity_id STRING NOT NULL, case_id UUID NOT NULL, destination_entity_id STRING NOT NULL,
    data_version INT8 NOT NULL, policy_revision INT8 NOT NULL, payload_hash STRING NOT NULL,
    received_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY(owner_entity_id,case_id,destination_entity_id,data_version,policy_revision,payload_hash)
);
CREATE TABLE IF NOT EXISTS servicing_projection.import_audit (
    owner_entity_id STRING NOT NULL, case_id UUID NOT NULL, destination_entity_id STRING NOT NULL,
    data_version INT8 NOT NULL, policy_revision INT8 NOT NULL, payload_hash STRING NOT NULL,
    imported_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY(owner_entity_id,case_id,destination_entity_id,data_version,policy_revision,payload_hash)
);
CREATE USER IF NOT EXISTS sfl_case_projection;
GRANT USAGE ON SCHEMA servicing_projection TO sfl_case_projection;
GRANT SELECT,INSERT,UPDATE ON TABLE servicing_projection.case_state TO sfl_case_projection;
GRANT SELECT,INSERT ON TABLE servicing_projection.inbox,servicing_projection.import_audit TO sfl_case_projection;
