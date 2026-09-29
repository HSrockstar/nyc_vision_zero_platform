CREATE VIEW public.v_collision_base AS
SELECT c.*, l.borough_id, l.on_street_name, l.cross_street_name, l.off_street_name,
       ST_X(l.geom) AS longitude, ST_Y(l.geom) AS latitude,
       s.persons_injured, s.persons_killed, s.pedestrians_injured, s.pedestrians_killed,
       s.cyclists_injured, s.cyclists_killed, s.motorists_injured, s.motorists_killed
FROM public.collision c JOIN public.location l USING (location_id)
JOIN public.casualty_stat s USING (collision_id);

CREATE VIEW public.v_risk_profile AS
WITH scored AS (
    SELECT p.*, r.period_start, r.period_end, r.rule_id, r.input_revision,
           rule.rule_name, rule.version_no AS rule_version, rule.threshold_medium, rule.threshold_high,
           i.intersection_code, i.street_a, i.street_b,
           CASE WHEN p.incomplete_casualty_collision_count > 0 THEN NULL ELSE
               p.collision_count * rule.weight_collision + p.injured_count * rule.weight_injured
               + p.killed_count * rule.weight_killed + p.vulnerable_road_user_count * rule.weight_vru
           END AS score,
           r.input_revision IS DISTINCT FROM d.revision AS is_stale
    FROM public.risk_profile p JOIN public.risk_run r USING (run_id)
    JOIN public.risk_rule rule USING (rule_id)
    JOIN public.intersection i USING (intersection_id)
    CROSS JOIN public.dataset_state d
    WHERE r.status = 'SUCCEEDED' AND d.state_id = 1
)
SELECT scored.*, CASE WHEN score IS NULL THEN 'UNKNOWN'
    WHEN score >= threshold_high THEN 'HIGH'
    WHEN score >= threshold_medium THEN 'MEDIUM' ELSE 'LOW' END AS risk_level
FROM scored;

CREATE VIEW public.v_governance_task AS
SELECT t.*, p.intersection_id, p.run_id, i.intersection_code,
       u.display_name AS creator_name, assignee.display_name AS assignee_name
FROM public.governance_task t JOIN public.risk_profile p USING (profile_id)
JOIN public.intersection i USING (intersection_id)
JOIN public.app_user u ON u.user_id = t.created_by
LEFT JOIN public.app_user assignee ON assignee.user_id = t.assignee_id
WHERE t.deleted_at IS NULL;
