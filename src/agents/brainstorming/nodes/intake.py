"""Entry node: placeholder for future input normalization before the safety gate."""

from ..state import BrainstormingState


async def intake_node(state: BrainstormingState) -> dict:
    return {}
