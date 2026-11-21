# Production Roadmap

Honest baseline: the app already has async ingestion, idempotency, multi-tenancy, caching, rate limiting, human-in-the-loop
retraining and a tool-calling copilot, validated on PostgreSQL + Redis + Celery. What separates it from production is
mostly **reliability, security, observability, ML rigor and delivery**, listed below in priority order
(impact for the effort, roughly 1-2 days each).

| #   | Upgrade                                                                                                                                                                                | What it adds                                                | Why it matters                                                                  |
| --- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ----------------------------------------------------------- | ------------------------------------------------------------------------------- |
| 1   | **CI with GitHub Actions** (pytest + lint + `docker build`, Postgres/Redis service containers)                                                                                         | Every push is tested automatically; real build badge        | Proves the project stays green; the biggest credibility jump for the least work |
| 2   | **Alembic migrations** (replace `create_all`)                                                                                                                                          | Versioned, reversible schema changes                        | Schema evolution without data loss                                              |
| 3   | **Real auth + RBAC**: hashed API keys or JWT, admin / analyst / viewer roles, secrets from env                                                                                         | Replaces the plain demo keys; role checks on review/retrain | Security is the first thing a reviewer asks about                               |
| 4   | **Observability**: structured JSON logs with request IDs, Prometheus `/metrics`, liveness/readiness endpoints                                                                          | Latency, error rates, queue depth, job duration             | You can't run what you can't see                                                |
| 5   | **Load test + published numbers** (Locust or k6): p50/p95/p99, throughput, cache hit-rate                                                                                              | Measured performance report in `docs/`                      | Same measure-before/after approach as the URL shortener                         |
| 6   | **ML rigor**: MLflow experiment tracking + model registry, probability calibration, evaluation on a _harder, public_ procurement dataset, TF-IDF vs embeddings comparison, drift check | Honest metrics beyond synthetic data                        | Addresses the biggest weakness (synthetic data)                                 |
| 7   | **Tenant isolation in the database**: PostgreSQL row-level security                                                                                                                    | Defense in depth beyond app-level filtering                 | Real multi-tenant safety                                                        |
| 8   | **Deployment**: hosted API + managed Postgres/Redis (free tiers), HTTPS, health checks                                                                                                 | A live URL                                                  | "Deployed" is a different category from "runs locally"                          |
| 9   | **RAG over procurement policy documents** (pgvector)                                                                                                                                   | Copilot answers policy questions with citations             | Extends the copilot beyond analytics tools                                      |
| 10  | **Frontend upgrade** (Next.js) and SSO                                                                                                                                                 | Product-grade UI                                            | Optional polish                                                                 |

## Definition of "production-style" for this project

Items **1-5 done** (tested in CI, migrated schema, authenticated roles, observable, load-tested with published numbers)
plus **6** for ML credibility. Items 7-10 are bonus.

## Not goals (avoid over-engineering)

Kubernetes, Kafka, microservices. A well-tested modular monolith with a queue is the right size for this problem.
