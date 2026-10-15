"""/rules/*: get, patch (deploy / retire / actions), backtest."""
from __future__ import annotations

from typing import Any, Literal

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from .. import rules_logic
from ..errors import NotFound
from ..serialize import rule_summary
from ..state import AppState
from .deps import get_state

router = APIRouter(tags=["rules"])

Action = Literal["ui", "webhook_out", "slack", "chime"]


class RulePatch(BaseModel):
    status: Literal["candidate", "selected", "deployed", "retired"] | None = None
    actions: list[Action] | None = None


def _rule(st: AppState, rule_id: str):
    r = st.store.rules.get(rule_id)
    if r is None:
        raise NotFound(f"rule {rule_id}")
    return r


@router.get("/rules/{rule_id}")
def get_rule(rule_id: str, st: AppState = Depends(get_state)) -> dict[str, Any]:
    return rule_summary(_rule(st, rule_id))


@router.patch("/rules/{rule_id}")
def update_rule(rule_id: str, body: RulePatch, st: AppState = Depends(get_state)) -> dict[str, Any]:
    """`status: deployed` registers the rule with the monitor (503 until E is merged); `retired` undeploys it."""
    row = _rule(st, rule_id)
    deploying = body.status == "deployed" and row.status != "deployed"
    if deploying:
        st.services.calibrate                       # fail with 503 before anything is written
        st.services.monitor_cls
        st.services.deployed_rule_cls
    if body.actions is not None:
        st.store.rules.set_actions(rule_id, body.actions or ["ui"])
    if deploying:
        rules_logic.set_deployed(st, _rule(st, rule_id))
    elif body.status is not None and body.status != row.status:
        if row.status == "deployed":
            st.undeploy_rule(rule_id)
        st.store.rules.update(rule_id, status=body.status)
    elif body.actions is not None and row.status == "deployed" and st.monitor_if_ready() is not None:
        st.deploy_rule(_rule(st, rule_id))          # same rule, new action set
    return rule_summary(_rule(st, rule_id))


@router.get("/rules/{rule_id}/backtest")
def backtest_rule(rule_id: str, st: AppState = Depends(get_state)) -> dict[str, Any]:
    """Score every traced clip; calibration (tau, delta, recall CI) from `random` labels only."""
    return rules_logic.backtest(st, _rule(st, rule_id))
