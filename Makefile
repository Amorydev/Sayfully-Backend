# Mọi lệnh chạy qua `uv run` -> luôn dùng Python 3.12 trong .venv,
# không bao giờ dính Python 3.9 của macOS.
.PHONY: help setup up down install migrate makemigrations run test cov lint fmt shell superuser reset

help:
	@echo "setup       - cài đặt lần đầu (docker + gói + migrate)"
	@echo "up / down   - bật / tắt Postgres + Redis"
	@echo "install     - cài phụ thuộc"
	@echo "migrate     - tạo & chạy migration"
	@echo "run         - chạy server tại http://localhost:8000"
	@echo "test / cov  - chạy test / test kèm coverage"
	@echo "lint / fmt  - kiểm tra / tự sửa định dạng"
	@echo "superuser   - tạo tài khoản admin"
	@echo "reset       - XOÁ sạch DB rồi migrate lại"

setup: up install migrate
	@echo ""
	@echo "Xong. Chạy 'make superuser' rồi 'make run'."

up:
	docker compose up -d
	@echo "Đợi Postgres sẵn sàng..."
	@until docker compose exec -T db pg_isready -U sayfully >/dev/null 2>&1; do sleep 1; done
	@echo "Postgres OK"

down:
	docker compose down

install:
	uv sync --extra dev

makemigrations:
	uv run python manage.py makemigrations

migrate:
	uv run python manage.py migrate

run:
	uv run python manage.py runserver 0.0.0.0:8000

test:
	uv run pytest

cov:
	uv run pytest --cov=apps --cov-report=term-missing

lint:
	uv run ruff check .

fmt:
	uv run ruff check --fix . && uv run ruff format .

shell:
	uv run python manage.py shell

superuser:
	uv run python manage.py createsuperuser

reset:
	docker compose down -v
	docker compose up -d
	@until docker compose exec -T db pg_isready -U sayfully >/dev/null 2>&1; do sleep 1; done
	uv run python manage.py migrate
