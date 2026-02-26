from __future__ import annotations

import os


# NOTE:
# На CI/локальных тестах режим WAL в некоторых средах может инициализироваться
# очень медленно для каждого нового файла БД. Для тестового контура достаточно
# режима DELETE, он существенно быстрее на cold-start.
os.environ.setdefault("ANKEY_SQLITE__CACHE_JOURNAL_MODE", "DELETE")

