import os
import csv
from collections import namedtuple
from typing import List, Set, OrderedDict, Dict
import datetime
import pprint
import calendar
import logging
import re

import requests

Shift = namedtuple('Shift', ['name', 'day_of_week', 'start', 'duration'])

SHIFTS_CSV_EXPORT_URL = os.environ['SHIFTS_CSV_EXPORT_URL']

CST: datetime.timezone = datetime.timezone(datetime.timedelta(hours=-5))
TIME_OF_DAY_FORMAT: str = '%I:%M:%S %p'
DURATION_REGEX = re.compile(r'(?P<hours>\d+):(?P<minutes>\d+):(?P<seconds>\d+)')


def get_mentors_on_duty() -> List[str]:
    """
    Finds the on duty shifts and returns the associated mentor names
    Returns a list because sets are not serializable to JSON
    """
    now: datetime.datetime = datetime.datetime.now(tz=CST)

    def get_name(shift: Shift) -> str:
        return shift.name

    def is_mentor_on_duty(shift: Shift) -> bool:
        return now >= shift.start and now < (shift.start + shift.duration)

    return list(map(get_name, filter(is_mentor_on_duty, get_shifts())))

Day = namedtuple('Day', ['day_of_week', 'hours'])

# Linux-only space-padding from POSIX standard https://stackoverflow.com/questions/10807164/python-time-formatting-different-in-windows
TIME_RANGE_FORMAT: str = '%_I:%M %p'
class TimeRange(namedtuple('Hours', ['start', 'duration'])):
    def __str__(self):
        """String representation of a time-range as '2:00 PM - 4:00 PM'"""
        return f'{self.start.strftime(TIME_RANGE_FORMAT)} – {(self.start + self.duration).strftime(TIME_RANGE_FORMAT)}'

    def __lt__(self, other: 'Hours') -> bool:
        """Used for sorting, datetime-first"""
        return self.start < other.start or self.duration < other.duration


def get_hours() -> List[Day]:
    """
    Computes open hours by day of week for the website
    Time Range Algorithm:
    1. pick a shift
        a. find another shift that overlaps with it
        b. merge them by taking the minimum start time and maximum end time
        c. repeat a. and b. until no overlaps remain
    2. repeat 1. until no shifts remain
    """

    shifts: Set[Shift] = get_shifts().copy()

    time_ranges: List[TimeRange] = []
    if len(shifts) > 0:
        shift = shifts.pop()
        time_ranges.append(TimeRange(shift.start, shift.duration))
    
    while len(shifts) > 0:
        time_range: TimeRange = time_ranges[-1]
        time_range_end: datetime.datetime = time_range.start + time_range.duration
        def is_overlapping(shift: Shift) -> bool:
            """
            Determines whether a shift overlaps with a time range.
            Cases:
            1. Time range start is in-between shift start and shift end
            2. Time range end is in-between shift start and shift end
            3. Time range contains the entire shift
            """
            return (time_range.start >= shift.start and time_range.start <= (shift.start + shift.duration)) \
                    or (time_range_end >= shift.start and time_range_end <= (shift.start + shift.duration)) \
                    or (time_range.start <= shift.start and time_range_end >= (shift.start + shift.duration))
        
        first_overlap: Shift = next(filter(is_overlapping, shifts), None)
        if first_overlap is not None:
            new_start: datetime.datetime = min(time_range.start, first_overlap.start)
            new_end: datetime.datetime = max((time_range.start + time_range.duration), (first_overlap.start + first_overlap.duration))
            new_duration: datetime.datetime = new_end - new_start
            shifts.remove(first_overlap)
            time_ranges[-1] = TimeRange(new_start, new_duration)
        else:
            shift = shifts.pop()
            time_ranges.append(TimeRange(shift.start, shift.duration))

    def get_hours_for_day_of_week(dow: int) -> List[str]:
        """Finds time-ranges for this day of the week, sorts, and converts them to strings"""
        return list(map(str, sorted(filter(lambda time_range: time_range.start.weekday() == dow, time_ranges))))

    cal: calendar.Calendar = calendar.Calendar(firstweekday=calendar.MONDAY)
    return [Day(calendar.day_name[dow], get_hours_for_day_of_week(dow)) for dow in cal.iterweekdays()]


mentors: Set[Shift] = None
mentors_last_update: datetime.datetime = None
def get_shifts() -> Set[Shift]:
    """Gets shifts in CSV format from Google Sheets, parses them, and returns them as a list"""

    def is_valid(row: List[str]) -> bool:
        """
        Checks row validity before parsing
        row = ['FirstName L', 'Wednesday', '2:00 PM', '2:00:00']
        """
        # Don't need to validate time formats -- if parsing fails, then the shift will be ignored later on
        return len(row) >= 4 and row[0] not in ['Name', '']

    global mentors, mentors_last_update
    if mentors is None or (datetime.datetime.now() - mentors_last_update) > datetime.timedelta(minutes=15):
        res = requests.get(url=SHIFTS_CSV_EXPORT_URL)
        reader = csv.reader(res.content.decode('utf-8').splitlines())
        mentors = {parse_shift(Shift(*row[:4])) for row in reader if is_valid(row)}
        mentors.discard(None)
        mentors_last_update = datetime.datetime.now()

    return mentors


def parse_shift(shift: Shift) -> Shift:
    """
    Parses date and time-related fields to the python types
    """
    shift_dict: OrderedDict[str, str] = shift._asdict()
    try:
        if type(shift.duration) is str:
            shift_dict['duration'] = parse_duration_str(shift.duration)
        if type(shift.start) is str:
            shift_dict['start'] = parse_start_str(shift.start, shift.day_of_week)
        return Shift(**shift_dict)
    except (TypeError, ValueError, IndexError) as e:
        logging.warning(f'Exception while parsing shift {shift}: {e}')
        return None


def parse_start_str(start_str: str, day_of_week: str) -> datetime.datetime:
    """
    Parses the start time and combines it with a date that is today or a day of week in the near future
    start_str = '12:00:00 PM', day_of_week = 'Wednesday' -> 'Wednesday YEAR-MM-DD-YY 12:00:00 PM'
    """
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
    # Combine an upcoming date (that has the correct day of week) with the shift start time
    return datetime.datetime.combine(start_date.date(), start_time, tzinfo=start_date.tzinfo)
    

def parse_duration_str(duration_str: str) -> datetime.timedelta:
    """
    Parses durations using a regex
    Adapted from https://stackoverflow.com/a/12352624 and only works for durations < 24hrs
    duration_str = '2:00:00' -> datetime.timedelta(hours=2)
    """
    groups: Dict[str, str] = DURATION_REGEX.match(duration_str).groupdict()
    duration: Dict[str,int] = {key: int(value) for key, value in groups.items()}
    return datetime.timedelta(**duration)

if __name__ == '__main__':
    pprint.pprint(get_hours())
    pprint.pprint(get_shifts())
    pprint.pprint(get_mentors_on_duty())
