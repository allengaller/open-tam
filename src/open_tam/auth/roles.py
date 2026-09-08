"""Role-based access control."""
from __future__ import annotations

from enum import Enum


class Role(str, Enum):
    ADMIN = "admin"
    OPERATOR = "operator"
    VIEWER = "viewer"


PERMISSIONS = {
    Role.ADMIN: {"read", "write", "investigate", "manage_users", "manage_skills"},
    Role.OPERATOR: {"read", "write", "investigate"},
    Role.VIEWER: {"read"},
}


def has_permission(role: str | Role, permission: str) -> bool:
    if isinstance(role, str):
        try:
            role = Role(role)
        except ValueError:
            return False
    return permission in PERMISSIONS.get(role, set())
