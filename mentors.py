import os
import csv
from collections import namedtuple
from typing import List
import datetime
import pprint
import calendar
import requests


Shift = namedtuple('Shift', ['name', 'day_of_week', 'start', 'duration'])

SHIFTS_CSV_EXPORT_URL = os.environ['SHIFTS_CSV_EXPORT_URL']

CST: datetime.timezone = datetime.timezone(datetime.timedelta(hours=-5))
TIME_OF_DAY_FORMAT: str = '%I:%M:%S %p'
DURATION_FORMAT: str = '%H:%M:%S'
HOURS_FORMAT: str = '%I:%M %p'

mentors: List[Shift] = None
mentors_last_update: datetime.datetime = None
def get_shifts() -> List[Shift]:
    global mentors, mentors_last_update
    if mentors is None or (datetime.datetime.now() - mentors_last_update) > datetime.timedelta(minutes=15):
        res = requests.get(url=SHIFTS_CSV_EXPORT_URL)
        reader = csv.reader(res.content.decode('utf-8').splitlines())
        mentors = [Shift(*row[:4]) for row in reader if row[0] not in ('Name', '') and len(row) >= 4 and row[1] in calendar.day_name]
        mentors_last_update = datetime.datetime.now()

    return mentors


def get_mentors_on_duty() -> List[Shift]:
    now: datetime.datetime = datetime.datetime.now(tz=CST)
    current_day_of_week = now.strftime('%A')

    def is_mentor_on_duty(shift: Shift) -> bool:
        try:
            start = parse_start_str(shift.start, shift.day_of_week)
            end = start + parse_duration_str(shift.duration)
            return now >= start and now < end
        except Exception as e:
            print(f'Error while checking if {shift} on duty: {e}')
            return False

    return list(map(lambda mentor: mentor.name, filter(is_mentor_on_duty, get_shifts())))

Day = namedtuple('Day', ['day_of_week', 'hours'])
Hours = namedtuple('Hours', ['start', 'duration'])
def get_hours() -> List[Day]:
    shifts: List[Shift] = get_shifts().copy()

    shifts: List[Hours] = list(map(lambda shift: Hours(parse_start_str(shift.start, shift.day_of_week), parse_duration_str(shift.duration)), shifts))

    time_ranges: List[Hours] = []
    if len(shifts) > 0:
        time_ranges.append(shifts[-1])
        shifts.pop()
    
    while len(shifts) > 0:
        time_range = time_ranges[-1]
        time_range_end = time_range.start + time_range.duration
        def is_overlapping(shift: Hours) -> bool:
            return (time_range.start >= shift.start and time_range.start <= (shift.start + shift.duration)) \
                    or (time_range_end >= shift.start and time_range_end <= (shift.start + shift.duration)) \
                    or (time_range.start <= shift.start and time_range_end >= (shift.start + shift.duration))
        
        first_overlap: Hours = next(filter(is_overlapping, shifts), None)
        if first_overlap is not None:
            new_start = min(time_range.start, first_overlap.start)
            new_duration = max((time_range.start + time_range.duration), (first_overlap.start + first_overlap.duration)) - new_start
            shifts.remove(first_overlap)
            time_ranges[-1] = Hours(new_start, new_duration)
        else:
            time_ranges.append(shifts[-1])
            shifts.pop()
    
    cal: calendar.Calendar = calendar.Calendar(firstweekday=calendar.MONDAY)
    days: List[Day] = [Day(calendar.day_name[dow], list(sorted(filter(lambda hours: hours.start.weekday() == dow, time_ranges)))) for dow in cal.iterweekdays()]
    return [Day(day.day_of_week, list(map(format_hours, day.hours))) for day in days]

def format_hours(hours: Hours) -> str:
    return f'{hours.start.strftime(HOURS_FORMAT)} – {(hours.start + hours.duration).strftime(HOURS_FORMAT)}'


# start_str = '12:00:00 PM', day_of_week = 'Wednesday' -> 'Wednesday YEAR-MM-DD-YY 12:00 PM'
def parse_start_str(start_str: str, day_of_week: str) -> datetime.datetime:
    start_date: datetime.datetime = datetime.datetime.now(tz=CST)
    # Select the correct day of week
    if calendar.day_name[start_date.weekday()] != day_of_week:
        day_of_week_idx = list(calendar.day_name).index(day_of_week)
        day_diff: int = day_of_week_idx - start_date.weekday()
        # The day difference should move the date to the future, so add a week to make it positive
        if day_diff < 0:
            day_diff += 7
        start_date += datetime.timedelta(days=day_diff)
    # Parse start time
    start_time: datetime.time = datetime.datetime.strptime(start_str, TIME_OF_DAY_FORMAT).time()
    # Combine an upcoming day of the week with the shift + its start time
    return datetime.datetime.combine(start_date.date(), start_time, tzinfo=start_date.tzinfo)
    
# Adapted from https://stackoverflow.com/a/12352624 and only works for durations < 24hrs
# duration_str = '2:00:00' -> datetime.timedelta(hours=2)
def parse_duration_str(duration_str: str) -> datetime.timedelta:
    duration = datetime.datetime.strptime(duration_str, DURATION_FORMAT)
    return datetime.timedelta(hours=duration.hour, minutes=duration.minute, seconds=duration.second)

if __name__ == '__main__':
    pprint.pprint(get_shifts())
    pprint.pprint(get_hours())
