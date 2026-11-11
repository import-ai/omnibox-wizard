# Internal search snapshot API

The resource pagination engine calls two internal-only endpoints:

- POST /internal/api/v1/wizard/search/snapshot: query, namespace_id, user_id,
  optional resource_ids, recall_depth (1-400), timeout_ms (1-10000). It returns
  the full fixed-depth fused chunk union, recall_truncated, relevance_enabled,
  and a policy_signature. All enabled recall branches must succeed. It performs
  no model relevance judgment. Keep this route under the existing internal API
  network boundary; it does not replace Backend authorization.
- POST /internal/api/v1/wizard/search/judge: query, namespace_id, user_id,
  records (at most 32), recall_depth, policy_signature and timeout_ms. It returns
  ordered decisions (kept/rejected/pending) and the current policy signature.
  A changed signature returns no decisions so Backend invalidates the session.
  Foreign-namespace/user candidates are rejected. This endpoint never recalls
  candidates or embeds the query. Disabled/unconfigured relevance keeps inputs.

Candidate wire models are the existing IndexRecord/Chunk schemas. Backend must
serialize snake_case names again after restoring JSON-cached records. The shared
fixture in the Backend contract test is emitted from SnapshotResponse.

The checker gets a small soft-deadline margin within the hard request timeout so
it can return partial decisions. Cancellation still propagates. Failed or missing
judgments are pending, never assumed relevant.

The legacy /search endpoint and paginator remain for non-session callers. New
resource sessions use only the two endpoints above and keep all pagination state
in Backend. Both Wizard consumers must pin the same shared package SHA.
