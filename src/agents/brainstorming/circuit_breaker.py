"""Iteration guard for the assistant <-> tools <-> critique loop.

The reference repo's circuit_breaker.py is Postgres-backed and guards
cross-session conversation-compaction failures. This agent's loop is
per-turn and in-process, so the equivalent guard is just a state counter
checked against state["max_iterations"] -- no persistence needed.
"""

from .state import BrainstormingState


def check_iteration_limit(state: BrainstormingState) -> bool:
    """Return True if the loop should stop because it hit max_iterations."""
    return state["iteration"] >= state["max_iterations"]


def increment_iteration(state: BrainstormingState) -> dict:
    """Partial state update incrementing the iteration counter."""
    return {"iteration": state["iteration"] + 1}
