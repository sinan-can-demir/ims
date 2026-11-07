import pytest

from app.database import normalize_database_url


@pytest.mark.parametrize(
    "url,expected",
    [
        ("postgresql://u:p@h:5432/db", "postgresql+psycopg2://u:p@h:5432/db"),
        ("postgres://u:p@h:5432/db", "postgresql+psycopg2://u:p@h:5432/db"),
        ("postgresql+psycopg2://u:p@h/db", "postgresql+psycopg2://u:p@h/db"),
        ("postgresql+psycopg://u:p@h/db", "postgresql+psycopg://u:p@h/db"),
        ("sqlite://", "sqlite://"),
        ("sqlite:///x.db", "sqlite:///x.db"),
    ],
)
def test_normalize_database_url(url, expected):
    assert normalize_database_url(url) == expected


def test_password_containing_scheme_text_untouched():
    url = "postgresql://u:postgresql://@h/db"
    assert normalize_database_url(url) == "postgresql+psycopg2://u:postgresql://@h/db"
