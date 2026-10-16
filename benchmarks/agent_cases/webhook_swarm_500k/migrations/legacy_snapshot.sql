-- Existing installation snapshot. Upgrade code must preserve both rows and
-- their original identifiers, payload bytes, state, and creation timestamps.
INSERT INTO deliveries(id,tenant_id,event_id,payload_json,state,attempts,
                       next_attempt_at,endpoint_key,created_at)
VALUES
 (41,'north','evt-rotate','{"amount":7,"currency":"USD"}','delivered',1,NULL,'primary',1700000000),
 (42,'south','evt-south-9','{"amount":12,"currency":"EUR"}','queued',0,1700000120,'backup',1700000060);
