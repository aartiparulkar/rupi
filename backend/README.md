# Backend Structure

This backend follows a router-based FastAPI layout:

- app/: app initialization, config, dependencies
- routes/: admin, documents, and calculations APIs
- services/: fetchers, processors, LLM extraction, calculators
- models/: SQLAlchemy models and schema compatibility module
- config/: source and slab config
- scheduler.py: annual budget fetch scheduler
- tests/: basic unit/integration tests

