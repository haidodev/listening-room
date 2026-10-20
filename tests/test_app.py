import io
from email.parser import BytesParser
import json
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import app


class ListeningTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        root = Path(self.temp.name)
        self.patch_db = patch.object(app, 'DB', root / 'test.sqlite3')
        self.patch_audio = patch.object(app, 'AUDIO_DIR', root / 'audio')
        self.patch_db.start()
        self.patch_audio.start()
        app.sync_audio()
        (app.AUDIO_DIR / 'lesson_one.mp3').write_bytes(b'0123456789')
        app.sync_audio()

    def tearDown(self):
        self.patch_db.stop()
        self.patch_audio.stop()
        self.temp.cleanup()

    def get(self, path, headers=None, method='GET', payload=b''):
        request = f'{method} {path} HTTP/1.0\r\n'
        request += ''.join(f'{key}: {value}\r\n' for key, value in (headers or {}).items())
        class Connection:
            def __init__(self):
                self.output = io.BytesIO()
            def makefile(self, *args):
                return io.BytesIO((request + '\r\n').encode() + payload)
            def sendall(self, data):
                self.output.write(data)
        connection = Connection()
        app.Handler(connection, ('127.0.0.1', 1), None)
        head, body = connection.output.getvalue().split(b'\r\n\r\n', 1)
        status_line, headers_raw = head.split(b'\r\n', 1)
        return int(status_line.split()[1]), dict(BytesParser().parsebytes(headers_raw)), body

    def teacher_headers(self):
        payload = json.dumps({'password': app.TEACHER_PASSWORD}).encode()
        status, headers, _ = self.get('/api/teacher/login', {'Content-Length': str(len(payload))}, 'POST', payload)
        self.assertEqual(status, 200)
        return {'Cookie': headers['Set-Cookie'].split(';')[0], 'Content-Length': '5', 'Host': 'localhost:8000'}

    def test_teacher_settings_visibility_and_replay(self):
        payload = json.dumps({'id': 1, 'visible': False, 'allow_replay': True}).encode()
        headers = self.teacher_headers() | {'Content-Length': str(len(payload))}
        self.assertEqual(self.get('/api/teacher/settings', method='POST', payload=payload)[0], 401)
        self.assertEqual(self.get('/api/teacher/audio')[0], 401)
        self.assertEqual(self.get('/api/teacher/settings', headers, 'POST', payload)[0], 200)
        self.assertEqual(json.loads(self.get('/api/audio')[2]), [])
        self.assertEqual(self.get('/media/1')[0], 404)
        teacher_items = json.loads(self.get('/api/teacher/audio', self.teacher_headers())[2])
        self.assertEqual(teacher_items[0]['visible'], False)
        self.assertEqual(teacher_items[0]['allow_replay'], True)
        self.assertEqual(teacher_items[0]['revision'], 1)
        self.assertEqual(self.get('/api/teacher/settings', headers, 'POST', payload)[0], 200)
        self.assertEqual(json.loads(self.get('/api/teacher/audio', self.teacher_headers())[2])[0]['revision'], 1)
        payload = json.dumps({'id': 1, 'visible': True, 'allow_replay': True}).encode()
        headers['Content-Length'] = str(len(payload))
        self.assertEqual(self.get('/api/teacher/settings', headers, 'POST', payload)[0], 200)
        self.assertEqual(json.loads(self.get('/api/audio')[2])[0]['allow_replay'], True)
        self.assertEqual(json.loads(self.get('/api/audio')[2])[0]['revision'], 2)
        self.assertEqual(self.get('/media/1')[0], 200)

    def test_migrates_old_single_table(self):
        app.DB.unlink()
        with sqlite3.connect(app.DB) as db:
            db.execute('CREATE TABLE audio (id INTEGER PRIMARY KEY, name TEXT NOT NULL, file_path TEXT NOT NULL UNIQUE)')
            db.execute("INSERT INTO audio VALUES (1, 'Original', 'lesson_one.mp3')")
        app.sync_audio()
        app.sync_audio()
        with sqlite3.connect(app.DB) as db:
            self.assertEqual(db.execute('SELECT name, visible, allow_replay FROM audio').fetchall(), [('Original', 1, 0)])

    def test_rename_and_delete(self):
        def post(action, data, authenticated=True):
            payload = json.dumps(data).encode()
            headers = self.teacher_headers() if authenticated else {}
            headers['Content-Length'] = str(len(payload))
            return self.get('/api/teacher/' + action, headers, 'POST', payload)[0]
        self.assertEqual(post('rename', {'id': 1, 'name': 'Renamed'}, False), 401)
        self.assertEqual(post('delete', {'id': 1}, False), 401)
        self.assertEqual(post('rename', {'id': 1, 'name': '  Renamed lesson  '}), 200)
        item = json.loads(self.get('/api/audio')[2])[0]
        self.assertEqual(item['name'], 'Renamed lesson')
        self.assertEqual(item['revision'], 0)
        self.assertEqual(post('rename', {'id': 1, 'name': '   '}), 400)
        self.assertEqual(post('rename', {'id': 999, 'name': 'Missing'}), 404)
        self.assertEqual(post('delete', {'id': 1}), 200)
        self.assertFalse((app.AUDIO_DIR / 'lesson_one.mp3').exists())
        app.sync_audio()
        self.assertEqual(json.loads(self.get('/api/audio')[2]), [])
        self.assertEqual(self.get('/media/1')[0], 404)
        self.assertEqual(post('delete', {'id': 1}), 404)

    def test_teacher_authentication(self):
        status, headers, body = self.get('/teacher')
        self.assertEqual(status, 200)
        self.assertIn(b'Teacher sign in', body)
        self.assertNotIn('WWW-Authenticate', headers)
        self.assertEqual(self.get('/api/teacher/audio', {'Cookie': 'teacher_session=forged'})[0], 401)
        payload = b'{"password":"wrong"}'
        self.assertEqual(self.get('/api/teacher/login', {'Content-Length': str(len(payload))}, 'POST', payload)[0], 401)
        self.assertEqual(self.get('/teacher', self.teacher_headers())[0], 200)
        self.assertEqual(self.get('/api/teacher/upload?filename=a.mp3', method='POST', payload=b'audio')[0], 401)

    def test_logout_clears_cookie_and_redirects_even_if_session_expired(self):
        for headers in (self.teacher_headers(), {'Cookie': 'teacher_session=expired'}, {}):
            status, response_headers, _ = self.get('/api/teacher/logout', headers, 'POST')
            self.assertEqual(status, 303)
            self.assertEqual(response_headers['Location'], '/teacher')
            self.assertIn('Max-Age=0', response_headers['Set-Cookie'])
            self.assertIn('Path=/', response_headers['Set-Cookie'])
            cleared_cookie = response_headers['Set-Cookie'].split(';')[0]
            self.assertIn(b'Teacher sign in', self.get('/teacher', {'Cookie': cleared_cookie})[2])
            self.assertEqual(self.get('/api/teacher/audio', {'Cookie': cleared_cookie})[0], 401)

    def test_upload_persists_and_rejects_invalid_requests(self):
        path = '/api/teacher/upload?filename=lesson_one.mp3&name=New%20lesson'
        status, _, body = self.get(path, self.teacher_headers(), 'POST', b'audio')
        self.assertEqual(status, 200)
        item = json.loads(body)
        self.assertEqual(item['name'], 'New lesson')
        self.assertEqual(self.get(f'/media/{item["id"]}')[2], b'audio')
        self.assertEqual((app.AUDIO_DIR / 'lesson_one.mp3').read_bytes(), b'0123456789')
        self.assertEqual(len(json.loads(self.get('/api/audio')[2])), 2)
        self.assertEqual(self.get('/api/teacher/upload?filename=a.html', self.teacher_headers(), 'POST', b'audio')[0], 400)
        headers = self.teacher_headers() | {'Origin': 'https://other.example'}
        self.assertEqual(self.get(path, headers, 'POST', b'audio')[0], 403)
        headers = self.teacher_headers() | {'Content-Length': str(app.MAX_UPLOAD + 1)}
        self.assertEqual(self.get(path, headers, 'POST')[0], 413)

    def test_discovery_is_idempotent_and_keeps_custom_names(self):
        with sqlite3.connect(app.DB) as db:
            db.execute("UPDATE audio SET name = 'Lesson 1'")
        app.sync_audio()
        status, _, body = self.get('/api/audio')
        self.assertEqual(status, 200)
        self.assertEqual(json.loads(body), [{'id': 1, 'name': 'Lesson 1', 'visible': True, 'allow_replay': False, 'revision': 0}])

    def test_stream_ranges_and_private_files(self):
        self.assertEqual(self.get('/listening')[0], 200)
        self.assertEqual(self.get('/media/1')[2], b'0123456789')
        status, headers, body = self.get('/media/1', {'Range': 'bytes=2-5'})
        self.assertEqual((status, body), (206, b'2345'))
        self.assertEqual(headers['Content-Range'], 'bytes 2-5/10')
        self.assertEqual(self.get('/media/1', {'Range': 'bytes=90-'})[0], 416)
        self.assertEqual(self.get('/audio/lesson_one.mp3')[0], 404)
        self.assertEqual(self.get('/listening.sqlite3')[0], 404)

    def test_missing_and_outside_files_are_hidden(self):
        (app.AUDIO_DIR / 'lesson_one.mp3').unlink()
        outside = Path(self.temp.name) / 'secret.mp3'
        outside.write_bytes(b'secret')
        with sqlite3.connect(app.DB) as db:
            db.execute('INSERT INTO audio (name, file_path) VALUES (?, ?)', ('Secret', str(outside)))
        self.assertEqual(json.loads(self.get('/api/audio')[2]), [])
        self.assertEqual(self.get('/media/1')[0], 404)
        self.assertEqual(self.get('/media/2')[0], 404)
