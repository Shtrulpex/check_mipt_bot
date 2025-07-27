# Бот телеграм для отслеживания списков поступающих в МФТИ

## Запуск
### Переменные окружения
- BOT_TOKEN - токен бота телеграм
- DB_NAME - название БД в postgresql
- DB_USER - username в postgresql
- DB_PASSWORD - пароль для postgresql
- DB_HOST - расположение базы данных (localhost)
- DB_PORT - порт для базы данных
- LOG_DIR - папка для сохранения логов

### Команда запуска
```bash
python3 main.py
```

## В проекте используются
- aiogram
- apscheduler
- requests
- psycopg2
- beautifulsoup4
