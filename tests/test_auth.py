# tests/test_auth.py
"""
Tests for auth routes (login, logout, signup).
Run from the project root:
    PYTHONPATH=src/backend python -m pytest tests/test_auth.py -v
"""
import sys
import os
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src', 'backend'))


@pytest.fixture
def app():
    try:
        from app import app as flask_app
    except Exception:
        pytest.skip("Flask app could not be loaded (missing data/model files)")
    flask_app.config['TESTING'] = True
    flask_app.config['SECRET_KEY'] = 'test-secret-key'
    flask_app.config['WTF_CSRF_ENABLED'] = False
    return flask_app


@pytest.fixture
def client(app):
    return app.test_client()


class TestLogin:
    def test_login_page_renders(self, client):
        resp = client.get('/login')
        assert resp.status_code == 200

    def test_login_with_valid_credentials(self, client):
        resp = client.post('/login', data={'username': 'demo', 'password': 'password123'},
                           follow_redirects=True)
        assert resp.status_code == 200

    def test_login_with_invalid_credentials(self, client):
        resp = client.post('/login', data={'username': 'demo', 'password': 'wrongpassword'})
        assert b'Invalid' in resp.data

    def test_logout_redirects(self, client):
        # Log in first
        client.post('/login', data={'username': 'demo', 'password': 'password123'})
        resp = client.get('/logout', follow_redirects=False)
        assert resp.status_code in (301, 302)


class TestSignup:
    def test_signup_page_renders(self, client):
        resp = client.get('/signup')
        assert resp.status_code == 200

    def test_signup_creates_user(self, client):
        resp = client.post('/signup', data={
            'username': 'newuser_test',
            'password': 'testpassword',
            'email': 'test@example.com',
            'name': 'Test User',
        }, follow_redirects=True)
        assert resp.status_code == 200

    def test_signup_duplicate_username(self, client):
        # Register once
        client.post('/signup', data={
            'username': 'duplicate_user',
            'password': 'password',
            'email': 'a@example.com',
            'name': 'User A',
        })
        # Try again with same username
        resp = client.post('/signup', data={
            'username': 'duplicate_user',
            'password': 'password2',
            'email': 'b@example.com',
            'name': 'User B',
        })
        assert b'already exists' in resp.data


class TestProtectedRoutes:
    def test_my_treatment_plans_requires_login(self, client):
        resp = client.get('/my-treatment-plans', follow_redirects=False)
        assert resp.status_code in (301, 302)
        assert 'login' in resp.headers.get('Location', '').lower()
