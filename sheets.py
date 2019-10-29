import os
import re
from typing import List, Dict, Tuple
import json
import logging

from anchorlink import Attendance, ReportLine, Credentials, Event
from googleapiclient import discovery
from google.oauth2 import service_account

credentials = None

SPEARDSHEET_ID_REGEX = r'/spreadsheets/d/([a-zA-Z0-9-_]+)'
SHEET_ID_REGEX = r'[#&]gid=([0-9]+)'
VALUE_INPUT_OPTION = 'RAW'


class Sheet():
    def __init__(self, credentials: service_account.Credentials, spreadsheet_url: str, swipe_card_codes_column: str, prefix: str = ''):
        '''
        Uses Google Spreadsheets API v4 to update new card number entries by populating fields
        credentials: Google Service Account credentials
        spreadsheet_url: URL of the form https://docs.google.com/spreadsheets/d/spreadsheetId/edit#gid=sheetId
        swipe_card_codes_column: uppercase alphabetic column name
        prefix: string to prepend to column names being written to. i.e. if there is a First_Name field in the report, the update will only update a column named prefix + First_Name
        '''
        self.service = discovery.build('sheets', 'v4', credentials=credentials, cache_discovery=False)
        self.spreadsheet_id = next(re.finditer(SPEARDSHEET_ID_REGEX, spreadsheet_url), None).group(1)
        self.sheet_id = next(re.finditer(SHEET_ID_REGEX, spreadsheet_url), None).group(1)
        self.swipe_card_codes_column = swipe_card_codes_column
        assert self.swipe_card_codes_column.isalpha()
        assert self.swipe_card_codes_column.isupper()
        self.prefix = prefix
        self.last_batch_json = None

    # TODO: use a GDrive webhook. It's really messy right now and docs are unclear so I'll pass for now.
    # def register_webhook(self, address: str, resource_id: str, duration: datetime.timedelta, token: str = None):
    #     '''
    #     Creates a Google Drive Webhook for receiving push notifications when a sheet is changed
    #     '''
    #     self.gdrive = discover.build('drive', 'v3', credentials=credentials) # Build this in ctor
    #     self.gdrive.files().watch(fileId = self.spreadsheet_id, body={
    #         'kind': 'api#channel',
    #         'type': 'web_hook'
    #         'id': 'sheet',
    #         'token': token,
    #         'resourceId': resource_id,
    #         'resourceUri': f'https://www.googleapis.com/drive/v3/files/{resource_id}',
    #         'expiration' : int(round((datetime.datetime.now() + duration).time() * 1000))
    #     })
    def get_column_names(self) -> List[str]:
        '''Gets first row of spreadsheet, which is assumed to be column names. This is standard behavior of spreadsheets created through Google Forms.'''
        google_form_column_names: List[List[str]] = self.service.spreadsheets().values().get(spreadsheetId=self.spreadsheet_id, range='1:1', majorDimension='ROWS').execute().get('values', [])
        return google_form_column_names[0]

    def get_column_values(self, column_id: str) -> List[str]:
        '''Get cell values from a column.'''
        values = self.service.spreadsheets().values().get(spreadsheetId=self.spreadsheet_id, range=f'{column_id}:{column_id}', majorDimension='COLUMNS').execute().get('values', [])
        values = values[0][1:]
        return values

    def get_swipe_card_codes(self) -> List[str]:
        '''Gets cell values from the swipe card codes column. Strips whitespace and skips the first value (column name)'''
        swipe_card_codes = self.get_column_values(self.swipe_card_codes_column)
        return list(map(lambda code: code.strip(), swipe_card_codes))

    def is_column_valid(self, column_name: str) -> bool:
        '''Checks if a column name, barring the prefix, is one of the ReportLine fields'''
        if not column_name.startswith(self.prefix):
            return False
        if column_name.replace(self.prefix, '', 1) not in ReportLine._fields:
            return False
        return True

    def update(self, attendance: Attendance):
        swipe_card_codes = self.get_swipe_card_codes()
        if len(swipe_card_codes) == 0:
            return
        logging.info('Getting columns')
        column_names = self.get_column_names()

        filtered_column_names: List[Tuple[str, str]] = []

        for i, column_name in enumerate(column_names):
            if not self.is_column_valid(column_name):
                continue
            filtered_column_names.append((column_number_to_id(i + 1), column_name))
        if len(filtered_column_names) == 0:
            return

        logging.info('Uploading uniquified codes')
        attendance.upload(list(set(filter(lambda code: code.isdigit(), swipe_card_codes))))

        logging.info('Downloading report and getting a report line for each sheet row')
        report: List[ReportLine] = attendance.download()
        code_to_report: Dict[str, ReportLine] = {line.Card_ID_Number: line for line in report}
        report_rows: List[ReportLine] = [code_to_report.get(code, None) for code in swipe_card_codes]

        logging.info('Getting original column values')
        column_name_to_original_values: Dict[str, List[str]] = {}
        for column_id, column_name in filtered_column_names:
            values = self.get_column_values(column_id)[:len(report_rows)]
            # Fill with empty values if not as long as report_rows
            values += [''] * (len(report_rows) - len(values))

        data = []
        for column_id, column_name in filtered_column_names:
            values = column_name_to_original_values[column_name]
            for i, line in enumerate(report_rows):
                # Update cell values IFF a report exists
                if line is not None:
                    values[i] = getattr(line, column_name.replace(self.prefix, '', 1))
            data.append({
                "range": f'{column_id}2:{column_id}{len(report_rows)+1}',
                "majorDimension": "COLUMNS",
                "values": values
            })
        batch_body = {
            'value_input_option': VALUE_INPUT_OPTION,
            'data': data
        }

        batch_json = json.dumps(batch_body)
        if self.last_batch_json is None or self.last_batch_json != batch_json:
            logging.info('Posting updated cell values')
            self.service.spreadsheets().values().batchUpdate(spreadsheetId=self.spreadsheet_id, body=batch_body).execute()
            self.last_batch_json = batch_json

def column_number_to_id(n: int) -> str:
    '''Converts a one-indexed spreadsheet column number to column letter. Adapted from https://stackoverflow.com/a/48984697/2585333'''
    id = ''
    def divmod_excel(i: int) -> int:
        q, r = divmod(i, 26)
        if r == 0:
            return q - 1, r + 26
        return q, r

    while n > 0:
        n, r = divmod_excel(n)
        id = chr(ord('A') - 1 + r) + id
    return id


if __name__ == '__main__':
    logging.basicConfig(level=logging.INFO)
    attendance = Attendance(Credentials('puris', os.environ['PASS']), Event('designstudio', '5048888'))
    printee_sheet = Sheet(service_account.Credentials.from_service_account_file('credentials.json'), 'https://docs.google.com/spreadsheets/d/1tHCdRLZk4owYvN20t5A41__YDU-kBjw2Rw2E9y9SXhI/edit#gid=886233104', 'B', 'Printee_')
    printee_sheet.update(attendance)
    mentor_sheet = Sheet(service_account.Credentials.from_service_account_file('credentials.json'), 'https://docs.google.com/spreadsheets/d/1tHCdRLZk4owYvN20t5A41__YDU-kBjw2Rw2E9y9SXhI/edit#gid=886233104', 'F', 'Mentor_')
    mentor_sheet.update(attendance)
