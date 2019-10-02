from typing import List, Dict
from enum import Enum, auto

from mentors import Shift, get_mentors_on_duty


class OpenType(Enum):
    CLOSED = auto()
    OPEN = auto()
    FORCE_OPEN = auto()
    FORCE_CLOSE = auto()


def is_open(poller_json: Dict, mentors_on_duty: List[Shift]) -> OpenType:
    """Runs decision logic for whether the sign should say open"""
    # JSON doesn't tell us anything about the sign, should never happen though
    if 'sign' not in poller_json:
        return OpenType.OPEN if len(mentors_on_duty) > 0 else OpenType.CLOSED

    # Never open when the door is not open
    if poller_json['sign']['door'] == 1:
        return OpenType.CLOSED

    # Normal open (follow shift schedule)
    if poller_json['sign']['switch']['one_on'] == 1:
        return OpenType.OPEN if len(mentors_on_duty) > 0 else OpenType.CLOSED

    # Force open
    if poller_json['sign']['switch']['two_on'] == 1:
        return OpenType.FORCE_OPEN

    # Force closed
    return OpenType.FORCE_CLOSE
