# AnkeyIDM---Employee-Data-Synchronization

CLI коннектор для импорта сотрудников в Ankey IDM через REST API.

## Быстрый старт (dev)
python -m venv .venv
source .venv/bin/activate
pip install -U pip
pip install -e ".[dev]"

connector --help

## Этап 3: validate CSV
Команда:
syncEmployees validate --csv employees.csv --csv-has-header

CSV требования:
- кодировка UTF-8 (допускается BOM)
- разделитель `;`
- 14 колонок в строгом порядке:
  email, lastName, firstName, middleName, isLogonDisable, userName, phone, password,
  personnelNumber, managerId, organization_id, position, avatarId, usrOrgTabNum

Коды возврата:
- 0: ошибок данных нет
- 1: есть ошибки в данных
- 2: системная ошибка (нет файла, ошибка чтения/формата)

Артефакты:
- `logs/validate_<runId>.log`
- `reports/report_validate_<runId>.json`
