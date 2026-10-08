# 011. Redis also holds rate-limit counters

State: proposed (agreed in conversation, 2026-10-08)

## Context

Sign-in limits (5 failures in 15 minutes per account and per IP, SEC §3) and API throttles per user, organisation and IP (SEC §8) need counters shared by every web process. The architecture used Redis only as the Celery job broker.

## Options

1. Redis as a cache as well as the broker.
2. A PostgreSQL cache table.
3. In-process memory (only correct with one process).

## Decision

Use Redis through Django's built-in Redis cache backend in staging and production, on a separate database index from the job queue. Local development uses in-process memory, so no Redis is needed on a developer machine.

The cache holds only counters and flags keyed by IP address, email hash or organisation ID. It must never hold tenant records, document text, AI prompts or results. That rule keeps AI-04 (no shared caches across tenants) true.

## Revisit when

Rate-limit counters need to survive a Redis restart, or the cache starts holding anything other than counters.
