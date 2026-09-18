"""SQLite settings and durable polling state; no message history."""
import json
import sqlite3
from pathlib import Path


class Store:
    def __init__(self, path):
        if str(path) != ':memory:':
            Path(path).parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(path)
        self.db.execute('CREATE TABLE IF NOT EXISTS users (id INTEGER PRIMARY KEY, city TEXT, choices TEXT)')
        self.db.execute('CREATE TABLE IF NOT EXISTS state (key TEXT PRIMARY KEY, value INTEGER)')
        self.db.execute('CREATE TABLE IF NOT EXISTS outbox (id INTEGER PRIMARY KEY, chat INTEGER, text TEXT)')
        self.db.commit()

    def get(self, user, field):
        if field not in ('city', 'choices'):
            raise ValueError('Unknown field')
        row = self.db.execute(f'SELECT {field} FROM users WHERE id=?', (user,)).fetchone()
        return json.loads(row[0]) if row and row[0] else None

    def set(self, user, field, data):
        if field not in ('city', 'choices'):
            raise ValueError('Unknown field')
        with self.db:
            self.db.execute('INSERT OR IGNORE INTO users(id) VALUES(?)', (user,))
            self.db.execute(f'UPDATE users SET {field}=? WHERE id=?', (json.dumps(data, ensure_ascii=False), user))

    def forget(self, user):
        with self.db:
            self.db.execute('DELETE FROM users WHERE id=?', (user,))

    def offset(self):
        row = self.db.execute("SELECT value FROM state WHERE key='offset'").fetchone()
        return row[0] if row else 0

    def advance(self, update_id):
        with self.db:
            self.db.execute("INSERT OR REPLACE INTO state VALUES ('offset', ?)", (update_id + 1,))
            self.db.execute('DELETE FROM outbox WHERE id<=?', (update_id,))

    def close(self):
        self.db.close()

    def pending(self, update_id):
        return self.db.execute('SELECT chat,text FROM outbox WHERE id=?', (update_id,)).fetchone()

    def queue(self, update_id, chat, text):
        with self.db:
            self.db.execute('INSERT OR REPLACE INTO outbox VALUES (?,?,?)', (update_id, chat, text))
