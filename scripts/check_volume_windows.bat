@echo off
REM Скрипт для проверки использования volume в Windows

echo ==========================================
echo Проверка volume postgres-data
echo ==========================================
echo.

echo 1. Контейнер использует volume:
docker inspect steam-postgres --format "{{range .Mounts}}{{if eq .Destination \"/var/lib/postgresql/data\"}}{{.Name}}{{end}}{{end}}"
echo.

echo 2. Проверка: какие контейнеры используют этот volume:
docker ps -a --filter volume=steamparser_postgres-data --format "{{.Names}} - {{.Status}}"
echo.

echo 3. Детали volume:
docker volume inspect steamparser_postgres-data
echo.

echo ==========================================
echo Интерпретация:
echo ==========================================
echo.
echo Если volume серый в Docker Desktop, но команда выше показывает,
echo что контейнер его использует - это баг отображения Docker Desktop.
echo.
echo Решение:
echo 1. Обновите Docker Desktop до последней версии
echo 2. Перезапустите Docker Desktop
echo 3. Обновите список volumes (F5 или кнопка обновления)
echo.
echo Volume работает нормально, если контейнер запущен и использует его!
echo.

pause
