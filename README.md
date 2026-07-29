# Автотесты REST API Яндекс.Диска

Пример проекта API-автотестов на Python 3, `pytest` и `requests`.

Тесты работают с боевым REST API по адресу
`https://cloud-api.yandex.net`. Для интеграционных сценариев на Диске
создаётся уникальная папка `disk:/api-autotests-<uuid>`. После тестового
запуска она удаляется без помещения в Корзину.

## Что проверяется

| HTTP-метод | Эндпоинт | Сценарий |
|---|---|---|
| GET | `/v1/disk` | Получение данных о Диске и проверка схемы ответа |
| PUT | `/v1/disk/resources` | Создание папки и проверка её метаданных |
| POST | `/v1/disk/resources/copy` | Копирование папки и проверка результата |
| DELETE | `/v1/disk/resources` | Безвозвратное удаление папки и проверка `404` |

Помимо интеграционных сценариев в проекте есть unit-тесты HTTP-клиента:
они не требуют сети и проверяют URL, заголовок авторизации, параметры и
обработку ошибок.

## Требования

- Python 3.10 или новее;
- OAuth-токен Яндекс.Диска с правами на чтение и запись — только для
  интеграционных тестов.

Токен нельзя добавлять в исходный код, `.env`, коммиты или логи. Проект
получает его исключительно из переменной окружения
`YANDEX_DISK_TOKEN`.

## Локальный запуск

Создайте виртуальное окружение и установите зависимости:

```bash
python -m venv .venv
```

Windows PowerShell:

```powershell
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements-dev.txt
$env:YANDEX_DISK_TOKEN = "ваш_OAuth_токен"
pytest
```

Linux/macOS:

```bash
source .venv/bin/activate
python -m pip install -r requirements-dev.txt
export YANDEX_DISK_TOKEN="ваш_OAuth_токен"
pytest
```

Полезные команды:

```bash
# Только быстрые unit-тесты, сеть и токен не нужны
pytest tests/unit

# Только тесты реального API
pytest -m integration

# Проверка стиля
ruff check .
ruff format --check .
```

Если `YANDEX_DISK_TOKEN` не задан, интеграционные тесты будут отмечены
как `SKIPPED`, а unit-тесты продолжат выполняться.

## Структура

```text
.
├── .github/workflows/tests.yml
├── src/yandex_disk_api/
│   ├── __init__.py
│   └── client.py
├── tests/
│   ├── integration/
│   │   ├── conftest.py
│   │   └── test_resources.py
│   └── unit/
│       └── test_client.py
├── pyproject.toml
├── requirements.txt
└── requirements-dev.txt
```

## CI

GitHub Actions запускает тесты и `ruff` на Python 3.10 и 3.12. Unit-тесты
выполняются всегда, в том числе для pull request. Интеграционные тесты
запускаются для `push` и вручную, если в настройках репозитория создан
Actions secret `YANDEX_DISK_TOKEN`; без него они безопасно пропускаются.

## Документация

- [REST API Яндекс.Диска](https://yandex.ru/dev/disk-api/doc/ru/)
- [Полигон REST API](https://yandex.ru/dev/disk/poligon/)
- [pytest](https://docs.pytest.org/)
- [requests](https://requests.readthedocs.io/)
