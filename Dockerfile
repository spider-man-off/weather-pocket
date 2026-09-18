FROM python:3.13-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 WEATHER_DB=/data/weather.sqlite3
RUN useradd --uid 10001 --create-home bot && mkdir /data && chown bot:bot /data
WORKDIR /app
COPY weather_pocket/ weather_pocket/
USER bot
CMD ["python", "-m", "weather_pocket"]
