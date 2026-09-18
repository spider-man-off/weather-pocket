"""Chat commands separated from network polling for offline tests."""
from .weather import WeatherError, label, render

KEYBOARD = {'keyboard': [[{'text': '🌤 Сейчас'}, {'text': '📅 На 3 дня'}],
                        [{'text': '🏙 Сменить город'}, {'text': '❓ Помощь'}]], 'resize_keyboard': True}
HELP = ('Привет! Я WeatherPocket ☁️\nПришлите название города, например: Новосибирск. '
        'Если вариантов несколько, выберите номер.\n\n'
        '/weather — погода сейчас\n/forecast — прогноз на 3 дня\n'
        '/city Москва — найти и сохранить город\n/cancel — отменить выбор\n'
        '/forget — удалить сохранённый город и настройки\n/help — помощь\n\n'
        'Работаю в личном чате. Погода: Open-Meteo.com. '
        'Названия искомых городов и координаты выбранного города передаются Open-Meteo; '
        'Telegram ID туда не передаётся.')
ALIASES = {'🌤 Сейчас': '/weather', '📅 На 3 дня': '/forecast', '🏙 Сменить город': '/city', '❓ Помощь': '/help'}


class Bot:
    def __init__(self, store, weather):
        self.store, self.weather = store, weather

    def handle(self, user, text):
        try:
            return self._handle(user, text.strip())
        except WeatherError as error:
            return str(error)

    def report(self, user, days=False):
        city = self.store.get(user, 'city')
        if not city:
            return 'Сначала пришлите название города: например, Новосибирск.'
        return render(city, self.weather.forecast(city), days)

    def _handle(self, user, text):
        text = ALIASES.get(text, text)
        parts = text.split(maxsplit=1)
        cmd = parts[0].split('@')[0].lower() if parts else ''
        arg = parts[1].strip() if len(parts) > 1 else ''
        if cmd in ('/start', '/help'):
            return HELP
        if cmd == '/forget':
            self.store.forget(user)
            return 'Сохранённый город и варианты поиска удалены.'
        if cmd == '/cancel':
            self.store.set(user, 'choices', None)
            return 'Выбор отменён. Ранее сохранённый город не изменён.'
        if cmd in ('/weather', '/forecast'):
            return self.report(user, cmd == '/forecast')
        if cmd == '/city' and not arg:
            self.store.set(user, 'choices', None)
            return 'Пришлите название нового города.'
        if cmd.startswith('/') and cmd != '/city':
            return 'Неизвестная команда. Нажмите /help.'
        choices = self.store.get(user, 'choices')
        if text.isascii() and text.isdigit() and choices:
            if len(text) > 2 or not 1 <= int(text) <= len(choices):
                return f'Выберите номер от 1 до {len(choices)} или /cancel.'
            city = choices[int(text) - 1]
            self.store.set(user, 'city', city)
            self.store.set(user, 'choices', None)
            return self.report(user)
        query = arg if cmd == '/city' else text
        if not 2 <= len(query) <= 100:
            return 'Введите название города длиной от 2 до 100 символов.'
        results = self.weather.search(query)
        self.store.set(user, 'choices', results or None)
        if not results:
            return 'Город не найден. Проверьте название или попробуйте латиницей.'
        if len(results) == 1:
            self.store.set(user, 'city', results[0])
            self.store.set(user, 'choices', None)
            return self.report(user)
        return 'Нашлось несколько мест. Пришлите номер:\n\n' + '\n'.join(
            f'{i}. {label(city)}' for i, city in enumerate(results, 1)) + '\n\n/cancel — отменить'
