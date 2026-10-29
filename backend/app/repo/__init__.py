"""Repository / data-access layer (split into domain modules).

This package is a pure re-export façade over the per-domain modules; the
import surface is IDENTICAL to the old single-file ``app/repo.py``::

    from app import repo           # still works
    from app.repo import get_agent # still works
    repo._user_dict(u)             # private helpers stay importable

All reads/writes are async and go through the shared Prisma client
(app/db.get_prisma()). JSON blobs are stored as strings and (de)serialized in
these modules so the same code runs on SQLite and Postgres/Neon.
"""
from .common import _ts, _dump, _load_dict, _load_list
from .users import create_user, get_user_by_email, get_user, _user_dict
from .agents import (
    _agent_dict,
    list_agents,
    get_agent,
    create_agent,
    update_agent,
    delete_agent,
    set_agent_knowledge,
    append_agent_document,
)
from .calls import (
    _call_dict,
    list_calls,
    get_call,
    delete_call,
    create_call,
    update_call,
    count_active_calls,
    list_inprogress_rooms,
    count_live_calls,
    fail_stale_calls,
)
from .contacts import _contact_dict, create_contact_message, list_contact_messages
from .wallet import (
    get_wallet,
    recharge,
    credit,
    deduct,
    deduct_exact,
    has_spend_for_call,
    get_usage,
    cost_calc,
)
from .telephony import (
    _account_dict,
    _phone_dict,
    _purchase_dict,
    get_account_by_user,
    get_account,
    get_account_by_client,
    create_account,
    update_account,
    list_accounts,
    list_phone_numbers,
    get_phone_number,
    get_phone_by_number,
    create_phone_number,
    update_phone_number,
    delete_phone_number,
    list_agents_for_phone,
    find_inbound_agents_for_phone,
    create_purchase,
    get_purchase,
    get_purchase_by_idempotency,
    latest_purchase,
    list_purchases,
    update_purchase,
    get_telephony_config,
    create_telephony_config,
    update_telephony_config,
)

__all__ = [
    "_ts", "_dump", "_load_dict", "_load_list",
    "create_user", "get_user_by_email", "get_user", "_user_dict",
    "_agent_dict", "list_agents", "get_agent", "create_agent", "update_agent",
    "delete_agent", "set_agent_knowledge", "append_agent_document",
    "_call_dict", "list_calls", "get_call", "delete_call", "create_call",
    "update_call", "count_active_calls", "list_inprogress_rooms",
    "count_live_calls", "fail_stale_calls",
    "get_wallet", "recharge", "credit", "deduct", "deduct_exact",
    "has_spend_for_call", "get_usage",
    "cost_calc",
    "_contact_dict", "create_contact_message", "list_contact_messages",
    "_account_dict", "_phone_dict", "_purchase_dict",
    "get_account_by_user", "get_account", "get_account_by_client",
    "create_account", "update_account", "list_accounts",
    "list_phone_numbers", "get_phone_number", "get_phone_by_number",
    "create_phone_number", "update_phone_number", "delete_phone_number",
    "list_agents_for_phone",
    "find_inbound_agents_for_phone", "create_purchase", "get_purchase",
    "get_purchase_by_idempotency", "latest_purchase", "list_purchases",
    "update_purchase", "get_telephony_config", "create_telephony_config",
    "update_telephony_config",
]
