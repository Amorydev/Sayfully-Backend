import pytest
from django.test import Client

from apps.accounts.models import User


@pytest.fixture(autouse=True)
def _disable_ratelimit(settings):
    """Tắt rate limit mặc định; test nào cần thì bật lại tường minh."""
    settings.RATELIMIT_ENABLE = False


@pytest.fixture
def client() -> Client:
    return Client()


@pytest.fixture
def password() -> str:
    return "MatKhauRatManh123"


@pytest.fixture
def user(db, password) -> User:
    return User.objects.create_user(
        email="hocvien@example.com", password=password, full_name="Học Viên"
    )


class ApiClient:
    """Bọc Django test client cho gọn, mặc định đóng vai mobile."""

    def __init__(self, client: Client, web: bool = False):
        self.client = client
        self.web = web

    def _headers(self, token: str | None):
        headers = {"X-Client-Type": "web" if self.web else "mobile"}
        if token:
            headers["Authorization"] = f"Bearer {token}"
        return headers

    def post(self, path, data=None, token=None):
        return self.client.post(
            f"/api/v1{path}", data=data or {}, content_type="application/json",
            headers=self._headers(token),
        )

    def get(self, path, token=None):
        return self.client.get(f"/api/v1{path}", headers=self._headers(token))

    def patch(self, path, data=None, token=None):
        return self.client.patch(
            f"/api/v1{path}", data=data or {}, content_type="application/json",
            headers=self._headers(token),
        )

    def delete(self, path, token=None):
        return self.client.delete(f"/api/v1{path}", headers=self._headers(token))


@pytest.fixture
def api(client) -> ApiClient:
    return ApiClient(client, web=False)


@pytest.fixture
def web_api(client) -> ApiClient:
    return ApiClient(client, web=True)
