from typing import List

from mentors import Shift


def is_open(last_poller_json, mentors_on_duty: List[Shift]) -> bool:
    # Never open when the door is not open
    if last_poller_json['sign']['door'] == 0:
        return False

    # Normal opne (follow shift schedule)
    if last_poller_json['sign']['one_on'] == 1:
        return len(mentors_on_duty) > 0

    # Force open
    if last_poller_json['sign']['two_on'] == 1:
        return True

    # Force closed
    return False