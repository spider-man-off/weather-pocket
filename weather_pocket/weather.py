"""Open-Meteo client and Russian weather presentation."""
import json
import time
from urllib.parse import urlencode
from urllib.request import urlopen
from urllib.error import URLError


class WeatherError(Exception):
    """A recoverable upstream failure with no private URL in its message."""


def get_json(url):
    try:
        with urlopen(url, timeout=15) as response:
            return json.load(response)
    except (URLError, OSError, ValueError):
        raise WeatherError('Сервис погоды временно недоступен. Попробуйте позже.') from None


def label(city):
    return ', '.join(dict.fromkeys(str(city[k]) for k in ('name', 'admin1', 'country') if city.get(k)))


class Weather:
    def __init__(self, fetch=get_json, clock=time.monotonic):
        self.fetch, self.clock, self.cache = fetch, clock, {}

    def search(self, name):
        data = self.fetch('https://geocoding-api.open-meteo.com/v1/search?' + urlencode(
            {'name': name, 'count': 5, 'language': 'ru', 'format': 'json'}))
        if not isinstance(data, dict) or data.get('error'):
            raise WeatherError('Не удалось найти город. Попробуйте позже.')
        return data.get('results', [])

    def forecast(self, city):
        key = (city['latitude'], city['longitude'])
        saved = self.cache.get(key)
        if saved and self.clock() - saved[0] < 600:
            return saved[1]
        params = dict(latitude=key[0], longitude=key[1], timezone='auto', forecast_days=3,
                      wind_speed_unit='ms', current='temperature_2m,apparent_temperature,relative_humidity_2m,weather_code,wind_speed_10m',
                      daily='weather_code,temperature_2m_max,temperature_2m_min,precipitation_probability_max')
        data = self.fetch('https://api.open-meteo.com/v1/forecast?' + urlencode(params))
        if not isinstance(data, dict) or not isinstance(data.get('current'), dict) or not isinstance(data.get('daily'), dict):
            raise WeatherError('Сервис вернул неполные данные. Попробуйте позже.')
        if len(self.cache) >= 256:
            self.cache.pop(next(iter(self.cache)))
        self.cache[key] = (self.clock(), data)
        return data


def description(code):
    groups = [((0,), 'Ясно ☀️'), ((1, 2), 'Переменная облачность 🌤'), ((3,), 'Пасмурно ☁️'),
              ((45, 48), 'Туман 🌫'), ((51, 53, 55, 56, 57), 'Морось 🌧'),
              ((61, 63, 65, 66, 67, 80, 81, 82), 'Дождь 🌧'),
              ((71, 73, 75, 77, 85, 86), 'Снег ❄️'), ((95, 96, 99), 'Гроза ⛈')]
    return next((text for codes, text in groups if code in codes), 'Нет описания')


def value(number, suffix=''):
    return 'нет данных' if number is None else f'{number}{suffix}'


def render(city, data, days=False):
    title = label(city)
    zone = data.get('timezone', 'местное время')
    if not days:
        now = data['current']
        text = (f'📍 {title}\n{description(now.get("weather_code"))}\n'
                f'Температура: {value(now.get("temperature_2m"), " °C")}\n'
                f'Ощущается: {value(now.get("apparent_temperature"), " °C")}\n'
                f'Влажность: {value(now.get("relative_humidity_2m"), " %")}\n'
                f'Ветер: {value(now.get("wind_speed_10m"), " м/с")}\n'
                f'Данные на {now.get("time", "—").replace("T", " ")} ({zone})')
    else:
        daily = data['daily']
        lines = [f'📍 {title}', f'Прогноз на 3 дня ({zone})']
        for i, day in enumerate(daily.get('time', [])[:3]):
            def at(field):
                items = daily.get(field) or []
                return items[i] if i < len(items) else None
            lines.append(f'\n{day}: {description(at("weather_code"))}\n'
                         f'{value(at("temperature_2m_min"))}…{value(at("temperature_2m_max"))} °C · '
                         f'Вероятность осадков: {value(at("precipitation_probability_max"), "%")}')
        text = '\n'.join(lines)
    return text + '\n\nИсточник: Open-Meteo.com · данные погодных моделей'
