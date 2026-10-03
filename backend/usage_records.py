"""Immutable per-run accounting, including both sides of a fallback."""

# New reports retain each primary/fallback segment. Legacy rows remain visible, without guessing their login or effort.
RUNS = """(SELECT t.id,t.bot,t.started,t.finished,t.task_id,s.input_tokens,s.cached_tokens,s.output_tokens,
 s.model,s.provider,s.est_cost_usd,s.billing,s.runtime,s.harness,s.effort,s.profile
 FROM turns t JOIN turn_usage_segments s ON s.turn_id=t.id
 UNION ALL SELECT t.id,t.bot,t.started,t.finished,t.task_id,t.input_tokens,t.cached_tokens,t.output_tokens,
 t.model,t.provider,t.est_cost_usd,t.billing,NULL,NULL,NULL,NULL FROM turns t
 WHERE NOT EXISTS (SELECT 1 FROM turn_usage_segments s WHERE s.turn_id=t.id))"""
