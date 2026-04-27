# ABOUTME: Phase 4 Sprint 5 — pure tests for the LockableResource registry.
# ABOUTME: Confirms register / get / 422 on unknown / built-in equipment_record present.
from __future__ import annotations

import pytest
from fastapi import HTTPException

from services import lock_registry


def test_equipment_record_is_pre_registered():
    spec = lock_registry.get("equipment_record")
    assert spec.type == "equipment_record"
    assert spec.audit_prefix == "equipment_record.lock"
    assert spec.display_name == "equipment record"


def test_get_unknown_type_raises_422():
    with pytest.raises(HTTPException) as exc:
        lock_registry.get("definitely_not_a_resource")
    assert exc.value.status_code == 422
    assert "definitely_not_a_resource" in exc.value.detail


def test_register_idempotent_for_same_spec():
    # Same spec re-registered — no exception.
    lock_registry.register(lock_registry.EQUIPMENT_RECORD)


def test_register_rejects_mismatched_re_register():
    async def loader(_db, _id):  # noqa: ARG001
        return ""

    with pytest.raises(RuntimeError):
        lock_registry.register(
            lock_registry.LockableResource(
                type="equipment_record",
                display_name="other",
                audit_prefix="other",
                reference_loader=loader,
            )
        )


def test_all_types_includes_equipment_record():
    assert "equipment_record" in lock_registry.all_types()
