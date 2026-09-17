# ADR-002: PostgreSQL + pgvector for Persistent Memory and State

## Status
Accepted

## Context
A personal AI agent must maintain long-term, durable persistence across reboots. This includes:
1. Sessions and chat messages.
2. Agent execution runs, step traces, and audit logs.
3. Pending and historical human approvals.
4. Cognitive memory partitioned across Working, Episodic, Semantic, Profile, and Project memory.
5. Semantic vector similarity search over accumulated knowledge without introducing an uncoordinated secondary database (e.g., Pinecone, Weaviate, Qdrant).

## Decision
We select **PostgreSQL 16** with the **pgvector** extension as the primary operational and memory database for AURA, accessed via **SQLAlchemy 2.x** (async mode) with **Alembic** migrations.

For automated testing and offline development environments, the persistence layer abstractly relies on SQLAlchemy 2.x async interfaces, allowing testing either against PostgreSQL or against an async SQLite (`aiosqlite`) test database with JSON-serialized embeddings.

Key tables:
- `sessions`: Conversation threads and global metadata.
- `messages`: Chronological dialogue events with role and content.
- `runs`: Discrete agent execution invocations with status and outputs.
- `run_events`: Detailed structured trace log per run.
- `approvals`: Human-in-the-loop pending/resolved approvals.
- `memories`: Memory units categorized by tier (episodic, semantic, profile, project) with vector embeddings.

## Consequences
### Positive
- **Single Source of Truth:** Relational data (sessions, approvals, runs) and vector data (semantic memory) reside in one unified ACID-compliant database.
- **Transactional Integrity:** A run, its events, and memory updates can be recorded transactionally.
- **Standard Tooling:** Standard backup, replication, migrations (Alembic), and local orchestration (Docker Compose).

### Negative / Trade-offs
- Local developer setup requires running a PostgreSQL container with `pgvector/pgvector:pg16` (mitigated by Docker Compose and SQLite fallback for lightweight test suites).
