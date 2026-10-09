"""Service layer: dynamic configuration, credentials, catalog, admin.

These modules sit between the API/admin routers and the repository layer so
that FastAPI handlers, the LiveKit worker and the billing engine all resolve
configuration through ONE code path (services → config_store snapshot → DB,
falling back to code defaults in app/catalog.py + app/llm_catalog.py).

Importing this package never touches the database or LiveKit.
"""
