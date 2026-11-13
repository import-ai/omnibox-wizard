# Internal search snapshot API

The resource pagination engine calls one internal-only endpoint:

- POST /internal/api/v1/wizard/search/snapshot: query, namespace_id, user_id,
  optional resource_ids, recall_depth (1-400), timeout_ms (1-10000). It returns
  the full fixed-depth fused chunk union as records and recall_truncated. All
  enabled recall branches must succeed. It performs no model relevance judgment.
  Keep this route under the existing internal API network boundary; it does not
  replace Backend authorization.

Candidate wire models are the existing IndexRecord/Chunk schemas. Backend must
serialize snake_case names again after restoring JSON-cached records. The shared
fixture in the Backend contract test is emitted from SnapshotResponse.

Cancellation propagates from the caller's deadline. New resource sessions use
only this endpoint and keep all pagination state in Backend. Both Wizard
consumers must pin the same shared package SHA.
