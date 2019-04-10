from typing import List
from enum import Enum, auto

from mentors import Shift, get_mentors_on_duty


class OpenType(Enum):
    CLOSED = auto()
    OPEN = auto()
    FORCE_OPEN = auto()


def is_open(last_poller_json, mentors_on_duty: List[Shift]) -> OpenType:
    # JSON doesn't tell us anything about the sign, should never happen though
    if 'sign' not in last_poller_json:
        return OpenType.OPEN if len(mentors_on_duty) > 0 else OpenType.CLOSED

    # Never open when the door is not open
    if last_poller_json['sign']['door'] == 1:
        return OpenType.FORCE_OPEN

    # Normal open (follow shift schedule)
    if last_poller_json['sign']['switch']['one_on'] == 1:
        return OpenType.OPEN if len(mentors_on_duty) > 0 else OpenType.CLOSED

    # Force open
    if last_poller_json['sign']['switch']['two_on'] == 1:
        return OpenType.FORCE_OPEN

    # Force closed
    return OpenType.CLOSED
