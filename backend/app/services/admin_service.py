"""Super Admin service façade.

Split by responsibility (behavior unchanged; original public import surface):

* ``admin_shared.py``       — timestamps, config invalidation, audit-log write/read.
* ``admin_users.py``        — user list/detail, role changes, disable, wallet adjust.
* ``admin_catalog_ops.py``  — provider CRUD + catalog-model CRUD.
* ``admin_billing.py``      — billing configuration get/update.
* ``admin_analytics.py``    — stats overview + per-call usage rows.

This module re-exports everything, so imports keep working unchanged::

    from app.services import admin_service
    admin_service.list_users(...)
"""
from .admin_shared import (
    _now,
    _invalidate,
    audit,
    _sanitize_detail,
    list_audit_logs,
    _audit_dict,
)
from .admin_users import (
    _user_public,
    list_users,
    set_user_role,
    set_user_disabled,
    user_detail,
    admin_add_wallet,
)
from .admin_catalog_ops import (
    _provider_public,
    list_providers,
    create_provider,
    update_provider,
    delete_provider,
    _model_public,
    list_models,
    get_model,
    create_model,
    update_model,
    delete_model,
)
from .admin_billing import (
    get_billing,
    update_billing,
)
from .admin_analytics import (
    stats_overview,
    usage_rows,
    _load,
)

__all__ = [
    "_now", "_invalidate", "audit", "_sanitize_detail", "list_audit_logs", "_audit_dict",
    "_user_public", "list_users", "set_user_role", "set_user_disabled",
    "user_detail", "admin_add_wallet",
    "_provider_public", "list_providers", "create_provider", "update_provider",
    "delete_provider", "_model_public", "list_models", "get_model", "create_model",
    "update_model", "delete_model",
    "get_billing", "update_billing",
    "stats_overview", "usage_rows", "_load",
]
