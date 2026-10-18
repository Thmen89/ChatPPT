"""The settings page reads and writes ``chatppt.toml`` here (flat upstream key names)."""

from typing import Any

from fastapi import APIRouter, Body, HTTPException

from chatppt.config_store import can_change_keys, save_ui_values, ui_values

API_V1_CONFIG_ROUTER = APIRouter(prefix="/api/v1/config", tags=["Config"])


def _require_unlocked() -> None:
    if not can_change_keys():
        raise HTTPException(status_code=403, detail="Settings are locked (CAN_CHANGE_KEYS=false)")


@API_V1_CONFIG_ROUTER.get("", response_model=dict[str, Any])
def get_config() -> dict[str, Any]:
    _require_unlocked()
    return ui_values()


@API_V1_CONFIG_ROUTER.put("", response_model=dict[str, Any])
def put_config(values: dict[str, Any] = Body(...)) -> dict[str, Any]:
    _require_unlocked()
    return ui_values(save_ui_values(values))
