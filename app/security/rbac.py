"""Role-based access control.

Minimal, dependency-injectable RBAC. In production the ``Principal`` comes from a
verified OIDC/JWT (e.g. Keycloak); here it is constructed from a header for the
scaffold. Every PHI-touching route should depend on a permission check.
"""
from __future__ import annotations

from enum import Enum

from pydantic import BaseModel


class Role(str, Enum):
    DOCTOR = "doctor"
    SCRIBE = "scribe"
    ADMIN = "admin"
    AUDITOR = "auditor"


class Permission(str, Enum):
    VIEW_TRANSCRIPT = "view_transcript"
    EDIT_NOTE = "edit_note"
    APPROVE_NOTE = "approve_note"
    FINALIZE_NOTE = "finalize_note"
    MANAGE_TEMPLATES = "manage_templates"
    EXPORT = "export"
    VIEW_AUDIT = "view_audit"


ROLE_PERMISSIONS: dict[Role, set[Permission]] = {
    # A clinician runs the whole workflow from one login: capture → review → edit →
    # approve → finalize/export, and authors their own note templates. Template
    # management is granted here (in addition to ADMIN) so a doctor never has to
    # switch roles just to build or save a template.
    Role.DOCTOR: {
        Permission.VIEW_TRANSCRIPT, Permission.EDIT_NOTE, Permission.APPROVE_NOTE,
        Permission.FINALIZE_NOTE, Permission.EXPORT, Permission.MANAGE_TEMPLATES,
    },
    Role.SCRIBE: {Permission.VIEW_TRANSCRIPT, Permission.EDIT_NOTE},
    Role.ADMIN: {Permission.MANAGE_TEMPLATES, Permission.VIEW_TRANSCRIPT, Permission.EXPORT},
    Role.AUDITOR: {Permission.VIEW_AUDIT, Permission.VIEW_TRANSCRIPT},
}


class Principal(BaseModel):
    id: str               # stable user id; in jwt mode this is the auth.users UUID
    role: Role
    email: str | None = None   # human identity (jwt mode); used for audit/display only


class AccessDenied(PermissionError):
    pass


def has_permission(principal: Principal, permission: Permission) -> bool:
    return permission in ROLE_PERMISSIONS.get(principal.role, set())


def require_permission(principal: Principal, permission: Permission) -> None:
    if not has_permission(principal, permission):
        raise AccessDenied(f"{principal.role.value} lacks {permission.value}")
