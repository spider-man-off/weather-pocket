"""Run with python -m weather_pocket."""
import logging
import os
from .bot import Bot
from .storage import Store
from .telegram import Telegram, TelegramError, run
from .weather import Weather


def main():
    logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(message)s')
    token = os.environ.get('BOT_TOKEN', '').strip()
    if not token:
        raise SystemExit('Set BOT_TOKEN first. See README.md.')
    store = Store(os.environ.get('WEATHER_DB', 'data/weather.sqlite3'))
    try:
        run(Telegram(token), Bot(store, Weather()), store)
    except KeyboardInterrupt:
        logging.info('Stopped.')
    except (RuntimeError, TelegramError) as error:
        raise SystemExit(str(error)) from None
    finally:
        store.close()


if __name__ == '__main__':
    main()
