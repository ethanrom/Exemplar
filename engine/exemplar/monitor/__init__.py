"""Online monitor: sub_type prune -> fast score -> escalate near tau -> fire/drop, with
witnesses, actions and a cost meter.

    mon = Monitor(perceive_fast=..., perceive_strong=..., on_firing=store.add_firing, on_event=sse.push,
                  actions=ActionRunner(slack_url=...))
    mon.deploy(DeployedRule(rule_id="r1", concept_id="c1", rule=rule, tau=cal.tau, delta=cal.delta))
    records = mon.process(EventInput(...))        # one FiringRecord per deployed rule
"""
from .actions import ActionContext, ActionRunner, chime_via_ring_client
from .cost import CostMeter, Prices
from .monitor import Monitor
from .stage0 import stage0_reason
from .types import DeployedRule, EventInput, FiringRecord

__all__ = ["ActionContext", "ActionRunner", "CostMeter", "DeployedRule", "EventInput", "FiringRecord", "Monitor",
           "Prices", "chime_via_ring_client", "stage0_reason"]
