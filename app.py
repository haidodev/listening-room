"""A dependency-free listening library. Run: python3 app.py"""
import argparse
import hmac
import json
import mimetypes
import os
import sqlite3
import secrets
import time
import uuid
from http.cookies import SimpleCookie, CookieError
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

ROOT = Path(__file__).resolve().parent
AUDIO_DIR = ROOT / 'audio'
DB = ROOT / 'listening.sqlite3'
EXTENSIONS = {'.mp3', '.wav', '.ogg', '.m4a', '.aac', '.flac', '.webm'}
TEACHER_PASSWORD = os.environ.get('TEACHER_PASSWORD', 'HAIDOHONG')
SESSION_KEY = secrets.token_bytes(32)
SESSION_AGE = 12 * 60 * 60
MAX_UPLOAD = 100 * 1024 * 1024


def sync_audio():
    AUDIO_DIR.mkdir(exist_ok=True)
    with sqlite3.connect(DB) as db:
        db.execute('CREATE TABLE IF NOT EXISTS audio (id INTEGER PRIMARY KEY, name TEXT NOT NULL, file_path TEXT NOT NULL UNIQUE)')
        columns = {row[1] for row in db.execute('PRAGMA table_info(audio)')}
        for column, default in [('visible', 1), ('allow_replay', 0), ('revision', 0)]:
            if column not in columns:
                db.execute(f'ALTER TABLE audio ADD COLUMN {column} INTEGER NOT NULL DEFAULT {default}')
        for path in sorted(AUDIO_DIR.iterdir()):
            if path.is_file() and path.suffix.lower() in EXTENSIONS:
                db.execute('INSERT OR IGNORE INTO audio (name, file_path) VALUES (?, ?)',
                           (path.stem.replace('_', ' '), path.name))


class Handler(BaseHTTPRequestHandler):
    def has_teacher_session(self):
        try:
            cookies = SimpleCookie(self.headers.get('Cookie', ''))
            token = cookies['teacher_session'].value
            expiry, nonce, signature = token.split('.')
            message = f'{expiry}.{nonce}'
            expected = hmac.new(SESSION_KEY, message.encode(), 'sha256').hexdigest()
            return hmac.compare_digest(signature, expected) and time.time() < int(expiry)
        except (KeyError, ValueError, CookieError):
            return False

    def teacher_authenticated(self):
        if self.has_teacher_session():
            return True
        self.send_response(401)
        self.send_header('Cache-Control', 'no-store')
        self.end_headers()
        return False

    def teacher_login(self):
        try:
            length = int(self.headers.get('Content-Length', '0'))
            if not 0 < length <= 4096:
                raise ValueError
            data = json.loads(self.rfile.read(length))
            password = data.get('password')
            if not isinstance(password, str):
                raise ValueError
        except (ValueError, AttributeError):
            self.send_error(400, 'Invalid login request')
            return
        if not hmac.compare_digest(password.encode(), TEACHER_PASSWORD.encode()):
            self.send_response(401)
            self.send_header('Cache-Control', 'no-store')
            self.end_headers()
            return
        message = f'{int(time.time()) + SESSION_AGE}.{secrets.token_hex(16)}'
        signature = hmac.new(SESSION_KEY, message.encode(), 'sha256').hexdigest()
        self.send_response(200)
        self.send_header('Set-Cookie', f'teacher_session={message}.{signature}; HttpOnly; SameSite=Strict; Path=/; Max-Age={SESSION_AGE}')
        self.send_header('Cache-Control', 'no-store')
        self.send_header('Content-Length', '0')
        self.end_headers()

    def do_POST(self):
        parsed = urlparse(self.path)
        if parsed.path not in ('/api/teacher/upload', '/api/teacher/settings', '/api/teacher/login', '/api/teacher/logout', '/api/teacher/rename', '/api/teacher/delete'):
            self.send_error(404)
            return
        # Reject cross-origin submissions to teacher endpoints.
        origin = self.headers.get('Origin')
        if origin and urlparse(origin).netloc != self.headers.get('Host'):
            self.send_error(403)
            return
        if parsed.path == '/api/teacher/login':
            self.teacher_login()
            return
        if parsed.path == '/api/teacher/logout':
            self.send_response(303)
            self.send_header('Set-Cookie', 'teacher_session=; HttpOnly; SameSite=Strict; Path=/; Max-Age=0; Expires=Thu, 01 Jan 1970 00:00:00 GMT')
            self.send_header('Location', '/teacher')
            self.send_header('Cache-Control', 'no-store')
            self.send_header('Content-Length', '0')
            self.end_headers()
            return
        if not self.teacher_authenticated():
            return
        if parsed.path in ('/api/teacher/rename', '/api/teacher/delete'):
            try:
                length = int(self.headers.get('Content-Length', '0'))
                if not 0 < length <= 4096:
                    raise ValueError
                data = json.loads(self.rfile.read(length))
                if type(data.get('id')) is not int:
                    raise ValueError
                if parsed.path.endswith('/rename'):
                    name = data.get('name')
                    if not isinstance(name, str) or not 0 < len(name.strip()) <= 200:
                        raise ValueError
            except (ValueError, AttributeError):
                self.send_error(400, 'Invalid audio details')
                return
            sync_audio()
            try:
                with sqlite3.connect(DB) as db:
                    row = db.execute('SELECT file_path FROM audio WHERE id = ?', (data['id'],)).fetchone()
                    if not row:
                        self.send_error(404)
                        return
                    if parsed.path.endswith('/rename'):
                        db.execute('UPDATE audio SET name = ? WHERE id = ?', (name.strip(), data['id']))
                    else:
                        path = self.audio_path(row[0])
                        if path:
                            path.unlink()
                        db.execute('DELETE FROM audio WHERE id = ?', (data['id'],))
            except (OSError, sqlite3.Error):
                self.send_error(500, 'Could not update audio. Try again.')
                return
            self.send_bytes(b'{"saved":true}', 'application/json')
            return
        if parsed.path == '/api/teacher/settings':
            try:
                length = int(self.headers.get('Content-Length', '0'))
                if not 0 < length <= 4096:
                    raise ValueError
                data = json.loads(self.rfile.read(length))
                if type(data.get('id')) is not int or any(type(data.get(k)) is not bool for k in ('visible', 'allow_replay')):
                    raise ValueError
            except (ValueError, AttributeError):
                self.send_error(400, 'Invalid audio settings')
                return
            sync_audio()
            with sqlite3.connect(DB) as db:
                result = db.execute('UPDATE audio SET revision = revision + CASE WHEN visible != ? OR allow_replay != ? THEN 1 ELSE 0 END, visible = ?, allow_replay = ? WHERE id = ?',
                                    (data['visible'], data['allow_replay'], data['visible'], data['allow_replay'], data['id']))
            if not result.rowcount:
                self.send_error(404)
                return
            self.send_bytes(b'{"saved":true}', 'application/json')
            return
        query = parse_qs(parsed.query)
        filename = query.get('filename', [''])[0]
        extension = Path(filename).suffix.lower()
        name = query.get('name', [''])[0].strip() or Path(filename).stem.replace('_', ' ')
        try:
            length = int(self.headers.get('Content-Length', '0'))
        except ValueError:
            length = 0
        if extension not in EXTENSIONS or not name or len(name) > 200:
            self.send_error(400, 'Choose a supported audio file and a name of at most 200 characters.')
            return
        if length <= 0 or length > MAX_UPLOAD:
            self.send_error(413, 'Choose a non-empty file up to 100 MB.')
            return
        sync_audio()
        path = AUDIO_DIR / (uuid.uuid4().hex + extension)
        staging = path.with_suffix('.upload')
        try:
            with staging.open('xb') as destination:
                remaining = length
                while remaining:
                    chunk = self.rfile.read(min(65536, remaining))
                    if not chunk:
                        raise ValueError('Incomplete upload')
                    destination.write(chunk)
                    remaining -= len(chunk)
            with sqlite3.connect(DB) as db:
                cursor = db.execute('INSERT INTO audio (name, file_path) VALUES (?, ?)', (name, path.name))
                staging.replace(path)
            self.send_bytes(json.dumps({'id': cursor.lastrowid, 'name': name}).encode(), 'application/json')
        except (OSError, sqlite3.Error, ValueError):
            staging.unlink(missing_ok=True)
            path.unlink(missing_ok=True)
            self.send_error(500, 'Upload failed. Please try again.')

    def do_GET(self):
        route = urlparse(self.path).path
        if route == '/':
            self.send_response(302)
            self.send_header('Location', '/listening')
            self.end_headers()
        elif route in ('/listening', '/listening/'):
            self.send_file(ROOT / 'static/index.html', 'text/html; charset=utf-8')
        elif route in ('/teacher', '/teacher/'):
            page = 'teacher.html' if self.has_teacher_session() else 'teacher-login.html'
            self.send_file(ROOT / 'static' / page, 'text/html; charset=utf-8')
        elif route == '/app.js':
            self.send_file(ROOT / 'static/app.js', 'text/javascript; charset=utf-8')
        elif route in ('/api/audio', '/api/teacher/audio'):
            teacher = route == '/api/teacher/audio'
            if teacher and not self.teacher_authenticated():
                return
            sync_audio()
            with sqlite3.connect(DB) as db:
                rows = db.execute('SELECT id, name, file_path, visible, allow_replay, revision FROM audio ORDER BY name COLLATE NOCASE').fetchall()
            data = [{'id': i, 'name': n, 'visible': bool(v), 'allow_replay': bool(r), 'revision': revision}
                    for i, n, p, v, r, revision in rows if (teacher or v) and self.audio_path(p)]
            self.send_bytes(json.dumps(data).encode(), 'application/json')
        elif route.startswith('/media/') and route.removeprefix('/media/').isdigit():
            with sqlite3.connect(DB) as db:
                row = db.execute('SELECT file_path FROM audio WHERE id = ? AND visible = 1', (int(route.split('/')[-1]),)).fetchone()
            path = self.audio_path(row[0]) if row else None
            if path:
                self.send_file(path, mimetypes.guess_type(path)[0] or 'application/octet-stream', ranges=True)
            else:
                self.send_error(404)
        else:
            self.send_error(404)

    def audio_path(self, name):
        path = (AUDIO_DIR / name).resolve()
        return path if path.is_relative_to(AUDIO_DIR.resolve()) and path.is_file() else None

    def send_bytes(self, data, content_type):
        self.send_response(200)
        self.send_header('Content-Type', content_type)
        self.send_header('Content-Length', str(len(data)))
        self.send_header('Cache-Control', 'no-store')
        self.end_headers()
        self.wfile.write(data)

    def send_file(self, path, content_type, ranges=False):
        size = path.stat().st_size
        start, end = 0, size - 1
        partial = ranges and 'Range' in self.headers
        if partial:
            try:
                unit, span = self.headers['Range'].split('=')
                first, last = span.split('-')
                if unit != 'bytes' or not (first or last):
                    raise ValueError
                if first:
                    start = int(first)
                    end = min(int(last), end) if last else end
                else:
                    start = max(0, size - int(last))
                if start < 0 or start > end or start >= size:
                    raise ValueError
            except ValueError:
                self.send_response(416)
                self.send_header('Content-Range', f'bytes */{size}')
                self.end_headers()
                return
        self.send_response(206 if partial else 200)
        self.send_header('Content-Type', content_type)
        self.send_header('Content-Length', str(max(0, end - start + 1)))
        self.send_header('Cache-Control', 'no-store')
        self.send_header('X-Content-Type-Options', 'nosniff')
        if ranges:
            self.send_header('Accept-Ranges', 'bytes')
            self.send_header('Content-Disposition', 'inline')
        if partial:
            self.send_header('Content-Range', f'bytes {start}-{end}/{size}')
        self.end_headers()
        try:
            with path.open('rb') as source:
                source.seek(start)
                remaining = end - start + 1
                while remaining > 0:
                    chunk = source.read(min(65536, remaining))
                    if not chunk:
                        break
                    self.wfile.write(chunk)
                    remaining -= len(chunk)
        except (BrokenPipeError, ConnectionResetError):
            pass


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--host', default='0.0.0.0', help='Bind address (default: all network interfaces)')
    parser.add_argument('--port', type=int, default=8000)
    args = parser.parse_args()
    sync_audio()
    server = ThreadingHTTPServer((args.host, args.port), Handler)
    print(f'Listening on {args.host}:{server.server_port}', flush=True)
    print(f'Local URL: http://localhost:{server.server_port}/listening', flush=True)
    server.serve_forever()
