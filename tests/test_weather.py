import json
import tempfile
import unittest
from unittest.mock import Mock, patch
from urllib.error import URLError
from weather_pocket.bot import Bot
from weather_pocket.storage import Store
from weather_pocket.weather import Weather, WeatherError, render
from weather_pocket.telegram import Telegram, TelegramError, deliver, run

CITY = {'name': 'Новосибирск', 'latitude': 55.03, 'longitude': 82.92, 'country': 'Россия'}
DATA = {'timezone': 'Asia/Novosibirsk', 'current': {'time': '2026-09-18T12:00', 'temperature_2m': 12,
        'apparent_temperature': 10, 'relative_humidity_2m': 65, 'wind_speed_10m': 3, 'weather_code': 3},
        'daily': {'time': ['2026-09-18', '2026-09-19', '2026-09-20'], 'weather_code': [0, 61, 71],
        'temperature_2m_min': [1, 2, 3], 'temperature_2m_max': [10, 11, 12], 'precipitation_probability_max': [0, 50, 90]}}


class Commands(unittest.TestCase):
    def setUp(self):
        self.store = Store(':memory:')
        self.addCleanup(self.store.close)
        self.weather = Mock()
        self.weather.search.return_value = [CITY]
        self.weather.forecast.return_value = DATA
        self.bot = Bot(self.store, self.weather)

    def test_city_and_current(self):
        self.assertIn('12 °C', self.bot.handle(1, 'Новосибирск'))
        self.assertEqual(self.store.get(1, 'city'), CITY)
        self.assertIn('12 °C', self.bot.handle(1, '🌤 Сейчас'))

    def test_ambiguous_city_selection(self):
        other = dict(CITY, country='Другая страна')
        self.weather.search.return_value = [CITY, other]
        self.assertIn('2.', self.bot.handle(1, '/city Test'))
        self.assertIn('Выберите номер', self.bot.handle(1, '9'))
        self.assertIn('Другая страна', self.bot.handle(1, '2'))
        self.assertEqual(self.store.get(1, 'city'), other)

    def test_isolation_and_forget(self):
        self.bot.handle(1, 'Новосибирск')
        self.assertIn('Сначала', self.bot.handle(2, '/weather'))
        self.bot.handle(1, '/forget')
        self.assertIsNone(self.store.get(1, 'city'))

    def test_forecast(self):
        self.bot.handle(1, 'Новосибирск')
        result = self.bot.handle(1, '📅 На 3 дня')
        self.assertIn('2026-09-20', result)
        self.assertIn('90%', result)

    def test_missing_city_and_bad_input(self):
        self.assertIn('Сначала', self.bot.handle(1, '/forecast'))
        self.assertIn('от 2 до 100', self.bot.handle(1, 'x' * 101))
        self.assertIn('Неизвестная', self.bot.handle(1, '/nope'))
        self.assertIn('WeatherPocket', self.bot.handle(1, '/start@WeatherPocket'))

    def test_not_found_keeps_old_city(self):
        self.bot.handle(1, 'Новосибирск')
        self.weather.search.return_value = []
        self.assertIn('не найден', self.bot.handle(1, 'Unknown'))
        self.assertEqual(self.store.get(1, 'city'), CITY)

    def test_weather_failure_is_friendly(self):
        self.weather.search.side_effect = WeatherError('Попробуйте позже')
        self.assertEqual(self.bot.handle(1, 'Москва'), 'Попробуйте позже')

    def test_cancel(self):
        self.store.set(1, 'choices', [CITY, CITY])
        self.bot.handle(1, '/cancel')
        self.assertIsNone(self.store.get(1, 'choices'))


class Infrastructure(unittest.TestCase):
    def test_persistence(self):
        with tempfile.TemporaryDirectory() as folder:
            db = Store(folder + '/db.sqlite3')
            db.set(42, 'city', CITY)
            db.queue(8, 42, 'answer')
            db.close()
            db = Store(folder + '/db.sqlite3')
            self.assertEqual(db.get(42, 'city'), CITY)
            self.assertEqual(db.pending(8), (42, 'answer'))
            db.advance(8)
            self.assertEqual(db.offset(), 9)
            self.assertIsNone(db.pending(8))
            db.close()

    def test_cache_and_expiration(self):
        fetch, clock = Mock(return_value=DATA), Mock(return_value=0)
        weather = Weather(fetch, clock)
        weather.forecast(CITY); weather.forecast(CITY)
        self.assertEqual(fetch.call_count, 1)
        clock.return_value = 601
        weather.forecast(CITY)
        self.assertEqual(fetch.call_count, 2)
        self.assertIn('wind_speed_unit=ms', fetch.call_args[0][0])

    def test_missing_values_and_unknown_code(self):
        result = render(CITY, {'current': {}, 'daily': {'time': ['2026-09-18']}}, True)
        self.assertIn('нет данных', result)
        self.assertIn('Нет описания', result)

    def test_malformed_weather(self):
        with self.assertRaises(WeatherError):
            Weather(Mock(return_value={'error': True})).forecast(CITY)

    def test_unicode_search_is_encoded(self):
        fetch = Mock(return_value={})
        self.assertEqual(Weather(fetch).search('Москва'), [])
        self.assertNotIn('Москва', fetch.call_args[0][0])

    def test_no_token_in_network_error(self):
        with patch('weather_pocket.telegram.urlopen', side_effect=URLError('secret-token')):
            with self.assertRaises(TelegramError) as error:
                Telegram('secret-token').call('getMe')
        self.assertNotIn('secret', str(error.exception))

    def test_send_retry_and_blocked_user(self):
        api, sleep = Mock(), Mock()
        api.send.side_effect = [TelegramError(429, 2), None]
        deliver(api, 1, 'text', sleep)
        sleep.assert_called_once_with(2)
        api.send.side_effect = TelegramError(403)
        deliver(api, 1, 'text', sleep)

    def test_polling_and_replay(self):
        store = Store(':memory:')
        self.addCleanup(store.close)
        bot, api = Mock(), Mock()
        bot.handle.return_value = 'weather answer'
        update = {'update_id': 7, 'message': {'chat': {'id': 1, 'type': 'private'}, 'text': '/weather'}}
        api.call.side_effect = [{}, [update], [update], KeyboardInterrupt]
        with self.assertRaises(KeyboardInterrupt):
            run(api, bot, store, Mock())
        bot.handle.assert_called_once_with(1, '/weather')
        self.assertEqual(store.offset(), 8)

    def test_delivery_failure_reuses_outbox(self):
        store = Store(':memory:'); self.addCleanup(store.close)
        bot, api = Mock(), Mock()
        bot.handle.return_value = 'answer'
        update = {'update_id': 7, 'message': {'chat': {'id': 1, 'type': 'private'}, 'text': '2'}}
        api.call.side_effect = [{}, [update], [update], KeyboardInterrupt]
        api.send.side_effect = [TelegramError(500), TelegramError(500), TelegramError(500), None]
        with self.assertRaises(KeyboardInterrupt): run(api, bot, store, Mock())
        bot.handle.assert_called_once()
        self.assertEqual(store.offset(), 8)

    def test_webhook_is_not_deleted(self):
        api = Mock(); api.call.return_value = {'url': 'https://example.org/hook'}
        with self.assertRaises(RuntimeError): run(api, Mock(), Mock())
        api.call.assert_called_once_with('getWebhookInfo')

    def test_groups_and_media_skipped(self):
        store = Store(':memory:'); self.addCleanup(store.close)
        api, bot = Mock(), Mock()
        api.call.side_effect = [{}, [{'update_id': 1, 'message': {'chat': {'id': 1, 'type': 'group'}, 'text': 'x'}},
                                      {'update_id': 2, 'message': {'chat': {'id': 1, 'type': 'private'}, 'photo': []}}], KeyboardInterrupt]
        with self.assertRaises(KeyboardInterrupt): run(api, bot, store)
        bot.handle.assert_not_called()
        self.assertEqual(store.offset(), 3)


if __name__ == '__main__':
    unittest.main()
