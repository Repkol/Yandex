# Автотесты REST API Яндекс.Диска

Небольшой учебный проект с автотестами для
[REST API Яндекс.Диска](https://yandex.ru/dev/disk-api/doc/ru/).
Написан на Python с использованием `pytest` и `requests`.

В проекте есть быстрые unit-тесты HTTP-клиента и интеграционные тесты,
которые обращаются к реальному API `https://cloud-api.yandex.net`.

## Что покрыто

Тесты проверяют позитивные и негативные сценарии, Happy Path, граничные
значения, авторизацию, пагинацию, Unicode, асинхронные операции и ошибки API.

| Раздел | Эндпоинты |
|---|---|
| Диск | `/v1/disk`, `/v1/disk/operations/{operation_id}` |
| Ресурсы | `/resources`, `/copy`, `/move`, `/download`, `/upload`, `/files`, `/last-uploaded` |
| Публичные ресурсы | `/resources/public`, `/publish`, `/unpublish`, `/public/resources`, `/download`, `/public-settings`, `/save-to-disk` |
| Корзина | `/trash/resources`, `/trash/resources/restore` |

Используются методы `GET`, `POST`, `PUT`, `PATCH` и `DELETE`.

## Быстрый старт

Понадобятся Python 3.10+ и OAuth-токен Яндекс.Диска с правами на чтение
и запись. Токен нужен только интеграционным тестам.

### Windows PowerShell

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements-dev.txt

$env:YANDEX_DISK_TOKEN = "ваш_OAuth_токен"
pytest
```

### Linux и macOS

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements-dev.txt

export YANDEX_DISK_TOKEN="ваш_OAuth_токен"
pytest
```

Не добавляйте настоящий токен в код, `.env`, логи или коммиты.
Если токен не задан, интеграционные тесты будут пропущены, а unit-тесты
продолжат работать.

## Полезные команды

```bash
# Весь набор
pytest -vv

# Только unit-тесты — без сети и токена
pytest tests/unit

# Только реальный API
pytest -m integration

# Проверка стиля
ruff check .
ruff format --check .
```

## Как устроены интеграционные тесты

Перед запуском создаётся отдельная папка
`disk:/api-autotests-<uuid>`. Все тестовые файлы и каталоги размещаются
внутри неё, а после завершения папка удаляется без помещения в Корзину.

Некоторые возможности публичных ссылок зависят от тарифа и настроек
аккаунта. Недоступные аккаунту сценарии корректно отмечаются как `SKIPPED`.
Для временных сетевых ошибок и ответов `429/500/503` предусмотрены
ограниченные повторные попытки там, где операция безопасна и идемпотентна.

## Структура проекта

```text
.
├── src/yandex_disk_api/       # HTTP-клиент
├── tests/
│   ├── unit/                  # быстрые тесты без сети
│   └── integration/           # тесты реального API
├── .github/workflows/         # GitHub Actions
├── pyproject.toml
├── requirements.txt
└── requirements-dev.txt
```

## CI

GitHub Actions запускает `ruff` и unit-тесты на Python 3.10 и 3.12.
Интеграционные тесты выполняются для `push` и ручного запуска, если
в репозитории настроен secret `YANDEX_DISK_TOKEN`.

## Ссылки

- [Документация REST API](https://yandex.ru/dev/disk-api/doc/ru/)
- [Полигон Яндекс.Диска](https://yandex.ru/dev/disk/poligon/)
- [pytest](https://docs.pytest.org/)
- [requests](https://requests.readthedocs.io/)
