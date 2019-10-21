import os
from typing import Set, List, Dict
import secrets
import logging
import http
import json
import ssl
import time
from datetime import datetime, timedelta
from enum import Enum, auto
from collections import defaultdict

import requests
from flask import Flask
from flask_sockets import Sockets
import gevent
from geventwebsocket.websocket import WebSocket
from google.oauth2 import service_account

from mentors import get_mentors_on_duty, get_hours
from sign import is_open, OpenType
from weather import get_weather
from anchorlink import Attendance, Credentials, Event
from sheets import Sheet

LOGGING_FORMAT: str = '[%(asctime)s] %(levelname)s: %(message)s'
CLIENT_JOINALL_TIMEOUT_SECONDS: float = 5.0
CLIENT_KEEPALIVE_SECONDS: float = 50.0
POLLER_JSON_TIMEOUT_SECONDS: float = 30.0
SHEET_UPDATE_PERIOD: float = 15.0

app = Flask(__name__)
app.config['SECRET_KEY'] = os.urandom(24)
sockets = Sockets(app)

logging.basicConfig(level=logging.INFO, format=LOGGING_FORMAT)

X_API_KEY: str = os.environ['X_API_KEY']


class ClientType(Enum):
    POLLER = 'poller'
    PRINTERS = 'printers'
    SIGN = 'sign'
    HOURS = 'hours'


# Last-value caching of the poller pi computed update
last_poller_json_str_dict: Dict[ClientType, str] = {}
last_poller_json_time: datetime = None
clients_dict: Dict[ClientType, List[WebSocket]] = defaultdict(list)


def sheet_update_loop():
    VANDERBILT_USERNAME: str = os.environ['VANDERBILT_USERNAME']
    VANDERBILT_PASSWORD: str = os.environ['VANDERBILT_PASSWORD']
    ANCHORLINK_ORGANIZATION: str = os.environ['ANCHORLINK_ORGANIZATION']
    ANCHORLINK_EVENT_ID: str = os.environ['ANCHORLINK_EVENT_ID']
    PRINT_LOG_SHEETS_URL: str = os.environ['PRINT_LOG_SHEETS_URL']
    MENTOR_SIGN_IN_SHEETS_URL: str = os.environ['MENTOR_SIGN_IN_SHEETS_URL']
    GOOGLE_SERVICE_ACCOUNT_CREDENTIALS: Dict[str, str] = json.loads(os.environ['GOOGLE_SERVICE_ACCOUNT_CREDENTIALS_JSON'])
    attendance = Attendance(Credentials(VANDERBILT_USERNAME, VANDERBILT_PASSWORD), Event(ANCHORLINK_ORGANIZATION, ANCHORLINK_EVENT_ID))
    print_log_sheet_printee = Sheet(service_account.Credentials.from_service_account_info(GOOGLE_SERVICE_ACCOUNT_CREDENTIALS), PRINT_LOG_SHEETS_URL, 'B', 'Printee_')
    print_log_sheet_mentor = Sheet(service_account.Credentials.from_service_account_info(GOOGLE_SERVICE_ACCOUNT_CREDENTIALS), PRINT_LOG_SHEETS_URL, 'F', 'Mentor_')
    mentor_sign_in_sheet = Sheet(service_account.Credentials.from_service_account_info(GOOGLE_SERVICE_ACCOUNT_CREDENTIALS), MENTOR_SIGN_IN_SHEETS_URL, 'B')

    # First download to cache all known card id codes
    attendance.download()
    while True:
        print_log_sheet_printee.update(attendance)
        print_log_sheet_mentor.update(attendance)
        mentor_sign_in_sheet.update(attendance)
        gevent.sleep(SHEET_UPDATE_PERIOD)

def is_valid(ws: WebSocket) -> bool:
    '''Just a sanity check, sometimes sockets will disappear before we can realize they are gone'''
    return ws is not None and not ws.closed


def poller_json_to_str(ctype: ClientType) -> str:
    if last_poller_json_time is None or datetime.utcnow() - last_poller_json_time > timedelta(seconds=POLLER_JSON_TIMEOUT_SECONDS):
        # Send nothing if no previous json or last update is stale
        return '{}'
    return last_poller_json_str_dict[ctype] if ctype in last_poller_json_str_dict else '{}'


def keep_alive(ws: WebSocket, ctype: ClientType):
    '''
    This prevents Heroku from closing WebSockets.
    Heroku's timeout is at 55 seconds, so this should be safe
    enough to prevent connection killing.
    https://devcenter.heroku.com/articles/websockets#timeouts
    '''
    def send():
        while is_valid(ws):
            ws.send(poller_json_to_str(ctype))
            gevent.sleep(CLIENT_KEEPALIVE_SECONDS)
    gevent.spawn(send)


def update(ws: WebSocket, ctype: ClientType):
    def send():
        try:
            ws.send(poller_json_to_str(ctype))
        except:
            ws.close()
    return gevent.spawn(send)


@sockets.route('/')
def root(ws: WebSocket):
    '''Receive messages from poller-pi'''
    global last_poller_json_str_dict, last_poller_json_time, clients_dict
    try:
        logging.info(f'Potential poller {ws} connected')
        keep_alive(ws, ClientType.POLLER)
        while is_valid(ws):
            gevent.sleep(0.1)
            msg = ws.receive()
            logging.debug(f'Potential poller {ws} sent a message')
            if msg is None:
                continue
            msg_json = json.loads(msg)
            if 'key' not in msg_json:
                logging.warning(f'Potential poller {ws} did not send a key, killing their connection')
                ws.close()
                return

            if not secrets.compare_digest(msg_json['key'], X_API_KEY):
                logging.warning(f'Potential poller {ws} sent an incorrect key, killing their connection')
                ws.close()
                return

            logging.debug(f'Poller {ws} authenticated')
            new_poller_json = msg_json

            last_poller_json_time = datetime.utcnow()

            mentors = get_mentors_on_duty()
            opn = is_open(new_poller_json, mentors)
            if opn is not OpenType.OPEN:
                mentors = []

            new_poller_json_str_dict = {}
            new_poller_json_str_dict[ClientType.PRINTERS] = json.dumps(dict(printers=new_poller_json['printers']))
            new_poller_json_str_dict[ClientType.SIGN] = json.dumps(dict(open=(opn == OpenType.FORCE_OPEN or opn == OpenType.OPEN), mentors=mentors, weather=get_weather()))
            new_poller_json_str_dict[ClientType.HOURS] = json.dumps(list(map(lambda day: day._asdict(), get_hours())))

            for ctype in new_poller_json_str_dict:
                if ctype not in last_poller_json_str_dict or new_poller_json_str_dict[ctype] != last_poller_json_str_dict[ctype]:  # Update all clients if json changed
                    logging.debug(f'Poller {ws} update diff for {ctype} clients is not empty')

                    start = time.time()
                    last_poller_json_str_dict[ctype] = new_poller_json_str_dict[ctype]
                    update_greenlets = [update(c, ctype) for c in clients_dict[ctype] if is_valid(c)]
                    gevent.joinall(update_greenlets, timeout=CLIENT_JOINALL_TIMEOUT_SECONDS)
                    end = time.time()
                    logging.info(f'Poller {ws} update for {ctype} clients processed in {round((end-start)*1000,2)}ms')
                else:
                    logging.debug(f'Poller {ws} update for {ctype} clients was the same')
        logging.info(f'Poller {ws} left')
    except Exception as err:
        logging.exception(err)
        if is_valid(ws):
            ws.close()


@sockets.route('/printers')
def printers(ws: WebSocket):
    '''Send messages to printer clients'''
    global clients_dict
    clients_dict[ClientType.PRINTERS].append(ws)
    logging.info(f'Printer client {ws} joined')
    try:
        keep_alive(ws, ClientType.PRINTERS)
        while is_valid(ws):
            gevent.sleep(.1)
            ws.receive()
        logging.info(f'Printer client {ws} left')
    except:
        logging.error(f'Printer client {ws} forced to leave due to an error')
        if is_valid(ws):
            ws.close()
    finally:
        clients_dict[ClientType.PRINTERS].remove(ws)


@sockets.route('/sign')
def sign(ws: WebSocket):
    '''Send messages to sign clients'''
    global clients_dict
    clients_dict[ClientType.SIGN].append(ws)
    logging.info(f'Sign client {ws} joined')
    try:
        keep_alive(ws, ClientType.SIGN)
        while is_valid(ws):
            gevent.sleep(.1)
            ws.receive()
        logging.info(f'Sign client {ws} left')
    except:
        logging.error(f'Sign client {ws} forced to leave due to an error')
        if is_valid(ws):
            ws.close()
    finally:
        clients_dict[ClientType.SIGN].remove(ws)

@sockets.route('/hours')
def hours(ws: WebSocket):
    '''Send messages to hours clients'''
    global clients_dict
    clients_dict[ClientType.HOURS].append(ws)
    logging.info(f'Hours client {ws} joined')
    try:
        keep_alive(ws, ClientType.HOURS)
        while is_valid(ws):
            gevent.sleep(.1)
            ws.receive()
        logging.info(f'Hours client {ws} left')
    except:
        logging.error(f'Hours client{ws} forced to leave due to an error')
        if is_valid(ws):
            ws.close()
    finally:
        clients_dict[ClientType.HOURS].remove(ws)


if __name__ == '__main__':
    from gevent import pywsgi
    from geventwebsocket.handler import WebSocketHandler
    gevent.spawn(sheet_update_loop)
    server = pywsgi.WSGIServer(('', 5000), app, handler_class=WebSocketHandler)
    server.serve_forever()
