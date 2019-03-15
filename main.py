import os
from typing import Set, List, Dict
import secrets
import logging
import http
import json
import ssl
import pathlib
from datetime import datetime, timedelta
from flask import Flask
from flask_sockets import Sockets
import gevent
from geventwebsocket.websocket import WebSocket

LOGGING_FORMAT: str = '[%(asctime)s] %(levelname)s: %(message)s'
CLIENT_JOINALL_TIMEOUT_SECONDS: float = 5.0
CLIENT_KEEPALIVE_SECONDS: float = 50.0

app = Flask(__name__)
app.config['SECRET_KEY'] = os.urandom(24)
sockets = Sockets(app)

logging.basicConfig(level=logging.INFO, format=LOGGING_FORMAT)

x_api_key: str = os.environ['X_API_KEY']

# Last-value caching of the poller pi response
last_poller_json: Dict = {}
last_poller_json_str: str = '{}'
last_poller_json_time: datetime = None

clients: Set[WebSocket] = set()


def is_valid(ws: WebSocket) -> bool:
    return ws is not None and not ws.closed


def poller_json_to_str() -> str:
    if last_poller_json_time is None or datetime.utcnow() - last_poller_json_time > timedelta(seconds=30):
        return '{}'
    return last_poller_json_str


# This prevents Heroku from closing WebSockets.
# Heroku's timeout is at 55 seconds, so this should be safe
# enough to prevent connection killing.
# https://devcenter.heroku.com/articles/websockets#timeouts
def keep_alive(ws: WebSocket):
    def send():
        if is_valid(ws) and ws in clients:
            ws.send(poller_json_to_str())
            gevent.spawn_later(CLIENT_KEEPALIVE_SECONDS, send)
    send()


def update(ws: WebSocket):
    def send():
        try:
            ws.send(poller_json_to_str())
        except:
            ws.close()
    return gevent.spawn(send)


def handle_message(ws: WebSocket):
    global last_poller_json, last_poller_json_str, last_poller_json_time, clients
    message = ws.receive()
    if message is None:
        return
    message_json = json.loads(message)
    if 'key' in message_json and secrets.compare_digest(message_json['key'], x_api_key):
        if ws in clients:  # Poller-pi is not a client
            clients.remove(ws)
        new_poller_json = message_json
        if new_poller_json != last_poller_json:  # Update if json changed
            logging.info(f'Poller {ws} sent an update')
            last_poller_json = new_poller_json
            last_poller_json_str = json.dumps(new_poller_json)
            last_poller_json_time = datetime.utcnow()
            update_greenlets = [update(c) for c in clients if is_valid(c)]
            gevent.joinall(update_greenlets,
                           timeout=CLIENT_JOINALL_TIMEOUT_SECONDS)
        logging.info(f'Poller {ws} update processed')
    else:
        logging.info(
            f'Client {ws} sent message, but key not found or incorrect')


@sockets.route('/')
def your_print_is_ready(ws: WebSocket):
    clients.add(ws)
    logging.info(f'Client {ws} joined')
    try:
        keep_alive(ws)
        while is_valid(ws):
            gevent.sleep(0.1)
            handle_message(ws)
        logging.info(f'Client {ws} left')
    except:
        logging.error(f'Client {ws} forced to leave due to an error')
        if is_valid(ws):
            ws.close()
    finally:
        clients.remove(ws)

@sockets.route('/sign')
def sign(ws: WebSocket):
    msg = dict(open=True, mentors=["Daiwei L", "Sameer P", "Christina H"], weather='⛅️ 🌡️+73°F 🌬️↑23 mph')
    ws.send(json.dumps(msg))


if __name__ == '__main__':
    from gevent import pywsgi
    from geventwebsocket.handler import WebSocketHandler
    server = pywsgi.WSGIServer(('', 5000), app, handler_class=WebSocketHandler)
    server.serve_forever()
