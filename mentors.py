import os
import csv
from collections import namedtuple
from typing import List
import datetime
import pprint

import requests


Shift = namedtuple('Shift', ['name', 'day_of_week', 'start', 'duration'])

SHIFTS_CSV_EXPORT_URL = os.environ['SHIFTS_CSV_EXPORT_URL']

mentors: List[Shift] = None
mentors_last_update: datetime.datetime = None
def get_shifts() -> List[Shift]:
    global mentors, mentors_last_update
    if mentors is None or (datetime.datetime.now() - mentors_last_update) > datetime.timedelta(minutes=15):
        res = requests.get(url=SHIFTS_CSV_EXPORT_URL)
        reader = csv.reader(res.content.decode('utf-8').splitlines())
        mentors = [Shift(*row[:4]) for row in reader if row[0] not in ('Name', '')]
        mentors_last_update = datetime.datetime.now()

    return mentors


def get_mentors_on_duty() -> List[Shift]:
    now: datetime.datetime = datetime.datetime.now(tz=datetime.timezone(datetime.timedelta(hours=-5)))
    current_day_of_week = now.strftime('%A')

    def is_mentor_on_duty(shift: Shift) -> bool:
        try:
            if shift.day_of_week != current_day_of_week:
                return False
            start = datetime.datetime.combine(now.date(), datetime.datetime.strptime(shift.start, '%I:%M:%S %p').time(), tzinfo=now.tzinfo)
            # Adapted from https://stackoverflow.com/a/12352624 and only works for durations < 24hrs
            duration = datetime.datetime.strptime(shift.duration, '%H:%M:%S')
            duration = datetime.timedelta(hours=duration.hour, minutes=duration.minute, seconds=duration.second)
            end = start + duration
            return shift.day_of_week == current_day_of_week and now >= start and now < end
        except Exception as e:
            print(f'Error while checking if {shift} on duty: {e}')
            return False

    return list(map(lambda mentor: mentor.name, filter(is_mentor_on_duty, get_shifts())))

if __name__ == '__main__':
    pprint.pprint(get_shifts())
