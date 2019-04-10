from typing import List

from mentors import Shift, get_mentors_on_duty


def is_open(last_poller_json, mentors_on_duty: List[Shift]) -> bool:
    # JSON doesn't tell us anything about the sign, should never happen though
    if 'sign' not in last_poller_json:
        return len(mentors_on_duty) > 0

    # Never open when the door is not open
    if last_poller_json['sign']['door'] == 1:
        return False

    # Normal opne (follow shift schedule)
    if last_poller_json['sign']['switch']['one_on'] == 1:
        return len(mentors_on_duty) > 0

    # Force open
    if last_poller_json['sign']['switch']['two_on'] == 1:
        return True

    # Force closed
    return False
print(is_open({}, get_mentors_on_duty()))