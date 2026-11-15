import pytest

from umami_api.config import ConfigurationError, load_settings, normalize_database_url


def test_live_lab_submission_cannot_be_enabled(monkeypatch):
    monkeypatch.setenv("LAB_LIVE_SUBMISSION_ENABLED", "true")
    with pytest.raises(ConfigurationError, match="must remain false"):
        load_settings()
    monkeypatch.setenv("LAB_LIVE_SUBMISSION_ENABLED", "maybe")
    with pytest.raises(ConfigurationError):
        load_settings()
    monkeypatch.setenv("LAB_LIVE_SUBMISSION_ENABLED", "false")
    assert load_settings().lab_live_submission_enabled is False


def test_database_urls_are_normalised_for_psycopg():
    assert normalize_database_url("postgres://u:p@h/db?sslmode=require") == \
        "postgresql+psycopg://u:p@h/db?sslmode=require"
    assert normalize_database_url("postgresql://u@h/db").startswith("postgresql+psycopg://")
    with pytest.raises(ConfigurationError) as error:
        normalize_database_url("mysql://secret-value@h/db")
    assert "secret-value" not in str(error.value)


def test_short_bootstrap_tokens_and_bad_origins_are_rejected(monkeypatch):
    monkeypatch.setenv("UMAMI_BOOTSTRAP_TOKEN", "short")
    with pytest.raises(ConfigurationError):
        load_settings()
    monkeypatch.setenv("UMAMI_BOOTSTRAP_TOKEN", "y" * 40)
    monkeypatch.setenv("CORS_ALLOW_ORIGINS", "https://ok.example, javascript:alert(1)")
    with pytest.raises(ConfigurationError):
        load_settings()
    monkeypatch.setenv("CORS_ALLOW_ORIGINS", "https://umami-avocado.onrender.com/")
    assert load_settings().cors_origins == ("https://umami-avocado.onrender.com",)


def test_v1_api_without_database_is_unavailable_not_successful(monkeypatch):
    from fastapi.testclient import TestClient

    from umami_api.main import create_app
    monkeypatch.delenv("DATABASE_URL", raising=False)
    with TestClient(create_app()) as client:
        response = client.get("/api/v1/me")
        assert response.status_code == 503
        assert response.json()["error"]["code"] == "unavailable"
        assert client.get("/api/readiness").json()["status"] == "foundation-only"
