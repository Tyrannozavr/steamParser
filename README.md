# Steam Market Parser

Система для парсинга Steam Market с поддержкой фильтров, прокси и Telegram бота.

## 📚 Документация

### API Документация

- **Интерактивная документация (Swagger UI)**: [https://api.yedu.ae/api/docs](https://api.yedu.ae/api/docs)
- **Скачать OpenAPI спецификацию (JSON)**: [https://api.yedu.ae/api/docs/openapi.json](https://api.yedu.ae/api/docs/openapi.json)
- **Скачать OpenAPI спецификацию (YAML)**: [https://api.yedu.ae/api/docs/openapi.yaml](https://api.yedu.ae/api/docs/openapi.yaml)

## 🚀 Быстрый старт

### Требования

- Docker и Docker Compose
- Python 3.12+
- PostgreSQL
- Redis

### Установка

1. Клонируйте репозиторий:
```bash
git clone <repository_url>
cd steam
```

2. Создайте файл `.env` на основе `.env.example`:
```bash
cp .env.example .env
```

3. Запустите через Docker Compose:
```bash
docker compose up -d
```

## 📖 Дополнительная документация

Дополнительная документация находится в директории `docs/`.
