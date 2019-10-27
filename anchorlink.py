from typing import List, Dict, Tuple, Set, NamedTuple
import os
import csv
import warnings
import time
import shutil

import requests
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC

class Credentials(NamedTuple):
    '''Vanderbilt login pair'''
    username: str
    password: str

class Event(NamedTuple):
    '''https://anchorlink.vanderbilt.edu/actioncenter/organization/ORGANIZATION/events/calendar/details/ID'''
    organization: str
    id: str

PING_USERNAME_LOCATOR = (By.CSS_SELECTOR, '[name="pf.username"]')
PING_PASSWORD_LOCATOR = (By.CSS_SELECTOR, '[name="pf.pass"]')
PING_SIGN_ON_LOCATOR = (By.CSS_SELECTOR, 'a.ping-button')
PING_ERROR_LOCATOR = (By.CSS_SELECTOR, '.ping-error')

ANCHORLINK_LOCATOR = (By.CSS_SELECTOR, '[role="main"]')

LOGIN_EVENT_LOCATOR = (By.CSS_SELECTOR, ', '.join([ANCHORLINK_LOCATOR[1], PING_ERROR_LOCATOR[1]]))
RELOG_EVENT_LOCATOR = (By.CSS_SELECTOR, ', '.join([ANCHORLINK_LOCATOR[1], PING_USERNAME_LOCATOR[1]]))

SWIPE_CARD_ACCESS_CODE_FIELD_LOCATOR = (By.CSS_SELECTOR, 'div.form-control')
ACCESS_CODE_LOCATOR = (By.CSS_SELECTOR, '[name="AccessCode"]')
SWIPE_READY_LOCATOR = (By.CSS_SELECTOR, 'div.alert-info')
SWIPE_SUCCESS_LOCATOR = (By.CSS_SELECTOR, 'div.alert-success')
SWIPE_FAILURE_LOCATOR = (By.CSS_SELECTOR, 'div.alert-danger')
SWIPE_DONE_LOCATOR = (By.CSS_SELECTOR, ', '.join([SWIPE_SUCCESS_LOCATOR[1], SWIPE_FAILURE_LOCATOR[1]]))
CARD_DATA_LOCATOR = (By.CSS_SELECTOR, '[name="cardData"]')

EXPORT_COMPLETE_LOCATOR = (By.CSS_SELECTOR, 'div#flash')
MOST_RECENT_DOWNLOAD_BUTTON_LOCATOR = (By.CSS_SELECTOR, 'table > tbody > tr:first-child > td:last-child > a:first-child')

ATTENDANCE_REPORT_SKIP_N_FIRST_LINES = 6

class ReportLine(NamedTuple):
    '''From the 5th row of the exported report'''
    First_Name: str
    Last_Name: str
    Campus_Email: str
    Preferred_Email: str
    Attendance_Status: str
    Marked_By: str
    Marked_On: str
    Comments: str
    Card_ID_Number: str


ATTENDANCE_REPORT_FIELD_NAMES = ','.join(list(ReportLine.__annotations__.keys())).replace('_', ' ')

WAIT_TIME: int = 5


class Attendance():
    def __init__(self, credentials: Credentials, event: Event, debug: bool = False, driver = None):
        self.credentials = credentials
        self.event = event
        self.debug = debug
        self.driver = driver
        self.logged_in = False
        self.previously_uploaded = set()
        self.last_download = None
        if self.driver is None:
            # Headless mode
            opts = webdriver.ChromeOptions()
            if not debug:
                opts.add_argument('--headless')
                opts.add_argument('--disable-gpu')
                opts.add_argument('--no-sandbox')
                opts.add_argument('--disable-dev-shm-usage')
                opts.binary_location = shutil.which('chromium-browser').replace('/bin/', '/lib/chromium-browser/', 1)
            self.driver = webdriver.Chrome(options=opts)
            # No implicit waiting -- all waits must be EXPLICIT
            self.driver.implicitly_wait(0)


    def __del__(self):
        # Quit doesn't work in __del__ for Chrome
        self.driver.close()

    def is_login_valid(self) -> bool:
        if not self.logged_in:
            return False
        self.driver.get("https://anchorlink.vanderbilt.edu/account/login?returnUrl=/")
        WebDriverWait(self.driver, WAIT_TIME).until(EC.visibility_of_element_located(RELOG_EVENT_LOCATOR))
        self.logged_in = len(self.driver.find_elements(*ANCHORLINK_LOCATOR)) > 0
        return self.logged_in

    def login(self):
        """Logs in via Vanderbilt Ping SSO or raises an exception if credentials aren't valid"""
        if self.is_login_valid():
            return
        self.driver.get("https://anchorlink.vanderbilt.edu/account/login?returnUrl=/")
        WebDriverWait(self.driver, WAIT_TIME).until(EC.visibility_of_element_located(PING_USERNAME_LOCATOR))
        self.driver.find_element(*PING_USERNAME_LOCATOR).send_keys(self.credentials.username)
        self.driver.find_element(*PING_PASSWORD_LOCATOR).send_keys(self.credentials.password)
        self.driver.find_element(*PING_SIGN_ON_LOCATOR).click()

        WebDriverWait(self.driver, WAIT_TIME).until(EC.visibility_of_element_located(LOGIN_EVENT_LOCATOR))
        if len(self.driver.find_elements(*PING_ERROR_LOCATOR)) > 0:
            raise PermissionError(f'Could not log in: "{self.driver.find_element(*PING_ERROR_LOCATOR).text}"')
        self.logged_in = True


    def raw_upload(self, swiped_card_codes: List[str]) -> List[bool]:
        """Uploads swipe card codes to event attendance and returns an equally-sized list of whether each upload succeeded"""
        self.login()

        def get_access_code() -> str:
            """Gets access code from track attendance page"""
            self.driver.get(f"https://anchorlink.vanderbilt.edu/actioncenter/organization/{self.event.organization}/events/events/trackattendance/{self.event.id}")
            WebDriverWait(self.driver, WAIT_TIME).until(EC.visibility_of_element_located(SWIPE_CARD_ACCESS_CODE_FIELD_LOCATOR))
            form_control = self.driver.find_element(*SWIPE_CARD_ACCESS_CODE_FIELD_LOCATOR)
            return form_control.text

        access_code = get_access_code()
        if access_code is None:
            return [False] * len(swiped_card_codes)

        self.driver.get("https://anchorlink.vanderbilt.edu/swipe")
        access_code_element = self.driver.find_element(*ACCESS_CODE_LOCATOR)
        access_code_element.send_keys(access_code)
        access_code_element.submit()
        WebDriverWait(self.driver, WAIT_TIME).until(EC.visibility_of_element_located(SWIPE_READY_LOCATOR))

        def submit_card(code: str) -> bool:
            card_data_element = self.driver.find_element(*CARD_DATA_LOCATOR)
            card_data_element.send_keys(code)
            card_data_element.submit()
            WebDriverWait(self.driver, WAIT_TIME).until(EC.visibility_of_any_elements_located(SWIPE_DONE_LOCATOR))
            if len(self.driver.find_elements(*SWIPE_SUCCESS_LOCATOR)) > 0:
                return True
            if len(self.driver.find_elements(*SWIPE_FAILURE_LOCATOR)) > 0:
                return False
            warnings.warn("Could not find swipe success or failure element, assuming success", RuntimeWarning)
            return True

        # Invalidate last download
        self.last_download = None
        return list(map(submit_card, swiped_card_codes))


    def download(self) -> List[ReportLine]:
        """Exports and downloads attendance report. Caches card codes to avoid duplicate uploads."""
        if self.last_download is not None:
            return self.last_download
        self.login()

        # Export attendance
        self.driver.get(f"https://anchorlink.vanderbilt.edu/actioncenter/organization/{self.event.organization}/events/events/exporteventattendance?eventId={self.event.id}")
        WebDriverWait(self.driver, WAIT_TIME).until(EC.visibility_of_element_located(EXPORT_COMPLETE_LOCATOR))

        # Get download URL from user's My Downloads page. Assumes that the newest report is the correct one.
        self.driver.get("https://anchorlink.vanderbilt.edu/actioncenter/downloads")
        WebDriverWait(self.driver, WAIT_TIME).until(EC.visibility_of_element_located(MOST_RECENT_DOWNLOAD_BUTTON_LOCATOR))
        # First table, table body, first row, last column, first link
        download_url = self.driver.find_element(*MOST_RECENT_DOWNLOAD_BUTTON_LOCATOR)

        # requests is used here because clicking the link in Selenium would trigger a browser download
        session = requests.Session()
        for c in self.driver.get_cookies():
            session.cookies.set(c['name'], c['value'])
        download = session.get(download_url.get_attribute('href'))

        # Parse download as UTF-8 CSV skipping the first 5 lines 
        download_lines = download.content.decode('utf-8').splitlines()
        if download_lines[ATTENDANCE_REPORT_SKIP_N_FIRST_LINES-1] != ATTENDANCE_REPORT_FIELD_NAMES:
            warnings.warn(f"Report fields do not match: {download_lines[ATTENDANCE_REPORT_SKIP_N_FIRST_LINES-1]} != {ATTENDANCE_REPORT_FIELD_NAMES}", RuntimeWarning)
        reader = csv.reader(download_lines[ATTENDANCE_REPORT_SKIP_N_FIRST_LINES:])

        report = list(map(lambda line: ReportLine(*line), reader))
        for line in report:
            self.previously_uploaded.add(line.Card_ID_Number)
        self.last_download = report
        return report


    def upload(self, swiped_card_codes: List[str]) -> List[bool]:
        """Uploads swipe card codes to event attendance and returns an equally-sized list of whether each upload succeeded. Checks last download and previous upload success to avoid duplicate uploads."""
        filtered_swipe_card_codes = []
        filtered_swipe_card_codes_indices = []
        for i, code in enumerate(swiped_card_codes):
            # Upload new codes and unique only
            if code not in self.previously_uploaded and code not in swiped_card_codes[:i]:
                filtered_swipe_card_codes.append(code)
                filtered_swipe_card_codes_indices.append(i)

        successes = [True] * len(swiped_card_codes)
        if len(filtered_swipe_card_codes) == 0:
            return successes

        uploaded_successes = self.raw_upload(filtered_swipe_card_codes)
        for i, code, succ in zip(filtered_swipe_card_codes_indices, filtered_swipe_card_codes, uploaded_successes):
            if not succ:
                # Because they were uploaded uniquely, there might be some missed failures
                for j, other_code in enumerate(swiped_card_codes[i:]):
                    if other_code == code:
                        successes[j] = False
            else:
                self.previously_uploaded.add(code)

        return successes


if __name__ == '__main__':
    attendance = Attendance(Credentials('puris', os.environ['VANDERBILT_PASSWORD']), Event('designstudio', '5048888'), debug=True)
    # These are not real card numbers
    print(attendance.upload(['796000210', '796000210', '796000210']))
    print(attendance.download())
