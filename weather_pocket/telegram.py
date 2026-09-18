"""Small synchronous Telegram Bot API adapter with bounded retries."""
import json
import logging
import time
from urllib.request import Request, urlopen
from urllib.error import HTTPError, URLError
from .bot import KEYBOARD

log = logging.getLogger(__name__)


class TelegramError(Exception):
    def __init__(self, code, retry_after=3):
        self.code, self.retry_after = code, retry_after
        super().__init__(f'Telegram API error {code}')


class Telegram:
    def __init__(self, token):
        self.token = token

    def call(self, method, **payload):
        req = Request(f'https://api.telegram.org/bot{self.token}/{method}',
                      data=json.dumps(payload).encode(), headers={'Content-Type': 'application/json'})
        try:
            with urlopen(req, timeout=40) as response:
                result = json.load(response)
        except HTTPError as error:
            try:
                body = json.loads(error.read())
            except (ValueError, OSError):
                body = {}
            raise TelegramError(error.code, body.get('parameters', {}).get('retry_after', 3)) from None
        except (URLError, OSError, ValueError):
            raise TelegramError(0) from None
        if not result.get('ok'):
            raise TelegramError(result.get('error_code', 0), result.get('parameters', {}).get('retry_after', 3))
        return result['result']

    def send(self, chat, text):
        for start in range(0, len(text), 1800):
            self.call('sendMessage', chat_id=chat, text=text[start:start + 1800], reply_markup=KEYBOARD)


def deliver(api, chat, text, sleep=time.sleep):
    for attempt in range(3):
        try:
            api.send(chat, text)
            return
        except TelegramError as error:
            if error.code == 403:
                return  # User blocked the bot; keep polling for everyone else.
            if error.code not in (0, 429) and error.code < 500:
                raise
            if attempt == 2:
                raise
            sleep(max(1, min(error.retry_after, 120)))


def run(api, bot, store, sleep=time.sleep):
    # Refuse an existing webhook; never silently disable another deployment.
    info = api.call('getWebhookInfo')
    if info.get('url'):
        raise RuntimeError('Webhook is configured. Disable it explicitly before polling.')
    log.info('WeatherPocket started. Press Ctrl+C to stop.')
    while True:
        try:
            updates = api.call('getUpdates', offset=store.offset(), timeout=25, allowed_updates=['message'])
            for update in updates:
                if update['update_id'] < store.offset():
                    continue
                msg = update.get('message', {})
                chat = msg.get('chat', {})
                if chat.get('type') == 'private' and isinstance(msg.get('text'), str):
                    pending = store.pending(update['update_id'])
                    if not pending:
                        answer = bot.handle(chat['id'], msg['text'])
                        store.queue(update['update_id'], chat['id'], answer)
                        pending = (chat['id'], answer)
                    deliver(api, pending[0], pending[1], sleep)
                store.advance(update['update_id'])
        except TelegramError as error:
            if error.code in (400, 401, 404, 409):
                raise RuntimeError(f'Telegram error {error.code}: check token and other running instances.') from None
            log.warning('Telegram unavailable (code %s); retrying.', error.code)
            sleep(max(1, min(error.retry_after, 120)))
