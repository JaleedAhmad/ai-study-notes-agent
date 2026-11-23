"""Identity checks for the existing trusted Streamlit backend.

UUID validation is not authentication. Only server-held session state supplies
the authenticated identity; repository owner arguments must agree with it.
"""

from uuid import UUID

import streamlit as st


def validate_user_id(value):
    if not isinstance(value, str) or not value:
        raise PermissionError("Authentication required.")
    try:
        identity = UUID(value)
    except ValueError:
        raise PermissionError("Authentication required.") from None
    if identity.int == 0:
        raise PermissionError("Authentication required.")
    return str(identity)


def current_user_id():
    state = getattr(st, "session_state", None)
    return validate_user_id(getattr(state, "user_id", None))


def require_authenticated_user(user_id):
    authenticated = current_user_id()
    if validate_user_id(user_id) != authenticated:
        raise PermissionError("Session unavailable.")
    return authenticated
