import os
import re
from typing import List, Dict
import json

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
        Uses Google Spreadsheets API v4 to update new card number entries by adding
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
    
    def update(self, attendance: Attendance):
        swipe_card_codes = self.service.spreadsheets().values().get(spreadsheetId=self.spreadsheet_id, range=f'{self.swipe_card_codes_column}:{self.swipe_card_codes_column}', majorDimension='COLUMNS').execute().get('values', [])
        swipe_card_codes = swipe_card_codes[0][1:]
        if len(swipe_card_codes) == 0:
            return

        google_form_column_names: List[str] = self.service.spreadsheets().values().get(spreadsheetId=self.spreadsheet_id, range='1:1', majorDimension='ROWS').execute().get('values', [])
        google_form_column_names = google_form_column_names[0]
        
        google_form_filtered_column_names = []
        for i, column_name in enumerate(google_form_column_names):
            if not column_name.startswith(self.prefix):
                continue
            if column_name.replace(self.prefix, '', 1) not in ReportLine._fields:
                continue
            google_form_filtered_column_names.append((column_number_to_id(i + 1), column_name))
        if len(google_form_filtered_column_names) == 0:
            return

        attendance.upload(list(set(filter(lambda code: code.isdigit(), swipe_card_codes))))
        report: List[ReportLine] = attendance.download()
        code_to_report: Dict[str, ReportLine] = {line.Card_ID_Number: line for line in report}
        report_rows = [code_to_report[code] if code in code_to_report else None for code in swipe_card_codes]
        data = []
        for column_id, column_name in google_form_filtered_column_names:
            data.append({
                "range": f'{column_id}2:{column_id}{len(report_rows)+1}',
                "majorDimension": "COLUMNS",
                "values": [list(map(lambda line: getattr(line, column_name.replace(self.prefix, '', 1)) if line is not None else '', report_rows))]
            })
        batch_body = {
            'value_input_option': VALUE_INPUT_OPTION,
            'data': data
        }
        batch_json = json.dumps(batch_body)
        if self.last_batch_json is None or self.last_batch_json != batch_json:
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
    attendance = Attendance(Credentials('puris', os.environ['PASS']), Event('designstudio', '5048888'))
    printee_sheet = Sheet(service_account.Credentials.from_service_account_file('credentials.json'), 'https://docs.google.com/spreadsheets/d/1tHCdRLZk4owYvN20t5A41__YDU-kBjw2Rw2E9y9SXhI/edit#gid=886233104', 'B', 'Printee_')
    printee_sheet.update(attendance)
    mentor_sheet = Sheet(service_account.Credentials.from_service_account_file('credentials.json'), 'https://docs.google.com/spreadsheets/d/1tHCdRLZk4owYvN20t5A41__YDU-kBjw2Rw2E9y9SXhI/edit#gid=886233104', 'F', 'Mentor_')
    mentor_sheet.update(attendance)
