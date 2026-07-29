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
| GET | `/v1/disk/resources` | Happy Path, `fields`, пагинация, Unicode, `400/401/404` |
| PUT | `/v1/disk/resources` | Создание папки и проверка её метаданных |
| POST | `/v1/disk/resources/copy` | Копирование папки и проверка результата |
| DELETE | `/v1/disk/resources` | Корзина и permanent delete, async, md5, `400/401/404/409` |

Помимо интеграционных сценариев в проекте есть unit-тесты HTTP-клиента:
они не требуют сети и проверяют URL, заголовок авторизации, параметры и
обработку ошибок.

### Матрица сценариев `/v1/disk/resources`

| Метод | Категория | Проверка | Ожидаемый результат |
|---|---|---|---|
| GET | Happy Path | Метаинформация существующей папки | `200`, корректные `path`, `name`, `type`, `_embedded` |
| GET | Позитивный | Ограничение ответа через `fields` | `200`, только запрошенные поля |
| GET | Позитивный | `limit`, `offset`, `sort` | Корректная страница вложенных ресурсов |
| GET | Краевой | Unicode и пробелы в пути | Ресурс найден, путь не искажён |
| GET | Краевой | `offset` больше числа элементов | `200`, пустой `items` |
| GET | Негативный | Нет обязательного `path` | `400 FieldValidationError` |
| GET | Негативный | Нечисловой `limit` | `400` и стандартная схема ошибки |
| GET | Негативный | Ресурс отсутствует | `404 DiskNotFoundError` |
| GET | Негативный | Невалидный OAuth-токен | `401 UnauthorizedError` |
| DELETE | Happy Path | `permanently=true` | `202` или `204`, затем ресурс получает `404` |
| DELETE | Позитивный | `permanently` не передан | Ресурс перемещён в Корзину и затем очищен тестом |
| DELETE | Позитивный | `force_async=true` для непустой папки | `202`, ссылка на операцию, успешное завершение |
| DELETE | Позитивный | Корректный `md5` файла | Файл удалён |
| DELETE | Негативный | `md5` передан для папки | `400`, папка сохранена |
| DELETE | Негативный | Неверный `md5` файла | `409`, файл сохранён |
| DELETE | Негативный | Нет обязательного `path` | `400 FieldValidationError` |
| DELETE | Негативный | Ресурс отсутствует | `404 DiskNotFoundError` |
| DELETE | Негативный | Невалидный OAuth-токен | `401`, ресурс сохранён |
| DELETE | Краевой | Повторное удаление | Первый запрос успешен, второй получает `404` |

Ответы `403`, `412`, `423`, `429` и `503` зависят от тарифа, режима
«только чтение», блокировки ресурса, квот и состояния сервиса. Они
указаны в контракте API, но намеренно не провоцируются live-тестами:
такие проверки должны выполняться на управляемом стенде или через
стаб/мок соответствующего ответа.

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
│   │   ├── test_delete_resource.py
│   │   ├── test_get_resource.py
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
