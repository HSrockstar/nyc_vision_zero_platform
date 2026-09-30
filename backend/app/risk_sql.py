"""M4只连接事故、地点、当前归属和一对一伤亡，不连接人员/车辆/原因。"""

BASE = """
  SELECT c.collision_id,c.location_id,l.geom IS NOT NULL AS geocoded,
    CASE WHEN a.match_status IN ('AUTO_MATCHED','MANUAL_CONFIRMED')
      AND i.status='CONFIRMED' AND i.is_active THEN i.intersection_id END AS intersection_id,
    s.persons_injured,s.persons_killed,s.pedestrians_injured,s.pedestrians_killed,
    s.cyclists_injured,s.cyclists_killed,
    s.persons_injured IS NULL OR s.persons_killed IS NULL
      OR s.pedestrians_injured IS NULL OR s.pedestrians_killed IS NULL
      OR s.cyclists_injured IS NULL OR s.cyclists_killed IS NULL AS incomplete
  FROM public.collision c JOIN public.location l USING(location_id)
    LEFT JOIN public.location_assignment a USING(location_id)
    LEFT JOIN public.intersection i ON i.intersection_id=a.intersection_id
    LEFT JOIN public.casualty_stat s USING(collision_id)
  WHERE c.crash_date >= :start AND c.crash_date < :end
"""

AGGREGATES = "WITH base AS (" + BASE + """ )
  SELECT intersection_id,count(*) AS collision_count,
    coalesce(sum(persons_injured),0) AS injured_count,
    coalesce(sum(persons_killed),0) AS killed_count,
    coalesce(sum(coalesce(pedestrians_injured,0)::bigint+coalesce(pedestrians_killed,0)::bigint
      +coalesce(cyclists_injured,0)::bigint+coalesce(cyclists_killed,0)::bigint),0)::bigint AS vulnerable_road_user_count,
    count(*) FILTER (WHERE incomplete) AS incomplete_casualty_collision_count
  FROM base WHERE intersection_id IS NOT NULL GROUP BY intersection_id ORDER BY intersection_id
"""

COVERAGE = "WITH base AS (" + BASE + """ )
  SELECT count(*) AS total,count(*) FILTER (WHERE geocoded) AS geocoded,
    count(*) FILTER (WHERE NOT geocoded) AS missing_coordinates,
    count(*) FILTER (WHERE intersection_id IS NOT NULL) AS included,
    count(*) FILTER (WHERE intersection_id IS NULL) AS unmatched,
    count(*) FILTER (WHERE intersection_id IS NOT NULL AND incomplete) AS incomplete_included,
    count(DISTINCT intersection_id) AS profiled_intersections
  FROM base
"""

MAPPING = """
  SELECT a.location_id,a.intersection_id,a.match_status,a.match_method,a.algorithm_version,
    a.distance_m,a.version,a.evidence,i.intersection_code,i.street_a,i.street_b,i.borough_id,
    i.version AS intersection_version,i.confirmation_note,i.confirmed_at,
    ST_X(i.center_geom) AS longitude,ST_Y(i.center_geom) AS latitude
  FROM public.location_assignment a JOIN public.intersection i USING(intersection_id)
  WHERE a.match_status IN ('AUTO_MATCHED','MANUAL_CONFIRMED') AND i.status='CONFIRMED' AND i.is_active
    AND EXISTS (SELECT 1 FROM public.collision c WHERE c.location_id=a.location_id
      AND c.crash_date >= :start AND c.crash_date < :end)
  ORDER BY a.location_id
"""
