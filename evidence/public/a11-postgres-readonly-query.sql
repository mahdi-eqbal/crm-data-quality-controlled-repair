BEGIN ISOLATION LEVEL REPEATABLE READ READ ONLY;
WITH state AS (
    SELECT o.event_id,
           COALESCE(string_agg(j.event_kind, ' + ' ORDER BY j.event_kind), 'pending') AS journal
    FROM crm_make_observation_outbox o
    LEFT JOIN crm_make_observation_delivery_events j USING (event_id)
    GROUP BY o.event_id
)
SELECT journal, COUNT(*) AS events FROM state GROUP BY journal ORDER BY journal;

SELECT e.http_status, d.decision_kind,
       e.evidence_sha256 = d.evidence_digest AS evidence_digest_matches
FROM crm_a11_recovery_evidence e
JOIN crm_a11_recovery_decisions d USING (event_id);
ROLLBACK;
