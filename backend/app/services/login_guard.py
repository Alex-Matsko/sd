"""Ограничение попыток входа (защита от перебора пароля).

Панель сотрудника и портал клиента смотрят в интернет, а вход не был
ограничен ничем: ни числом попыток, ни задержкой. Пароль из восьми символов
перебирается за разумное время, если пробовать можно бесконечно и параллельно.

Счётчик держится в памяти процесса, а не в базе или Redis. Это осознанный
размен: система разворачивается одним экземпляром `app` (docker-compose), и
внешнее хранилище ради счётчика попыток означало бы ещё один контейнер на
администрирование — ровно то, чего мы избегали с уведомлениями. При
масштабировании на несколько экземпляров счётчик станет «на процесс», и
блокировка ослабнет пропорционально их числу; на этот случай ниже оставлен
явный TODO, а не молчаливое допущение.

Ключ — пара (что за вход, идентификатор). Идентификатором служит и адрес, и
IP: блокировка только по адресу позволила бы забить чужую учётку чужими
попытками, только по IP — перебирать разные адреса с одного узла.
"""

import threading
import time
from dataclasses import dataclass, field

# После скольких неудач подряд вход перестаёт приниматься и на какой срок.
MAX_ATTEMPTS = 10
LOCKOUT_SECONDS = 15 * 60
# Окно, за которое считаются неудачи: редкие ошибки живого человека не должны
# накапливаться неделями в блокировку.
WINDOW_SECONDS = 15 * 60


@dataclass
class _Bucket:
    failures: list[float] = field(default_factory=list)
    locked_until: float = 0.0


class LoginGuard:
    def __init__(self) -> None:
        self._buckets: dict[tuple[str, str], _Bucket] = {}
        # Uvicorn обслуживает синхронные обработчики в пуле потоков, поэтому
        # счётчик разделяют несколько потоков одного процесса.
        self._lock = threading.Lock()

    def _bucket(self, scope: str, key: str) -> _Bucket:
        return self._buckets.setdefault((scope, key.lower().strip()), _Bucket())

    def seconds_left(self, scope: str, *keys: str) -> int:
        """Сколько ещё секунд вход закрыт. 0 — можно пробовать."""
        now = time.monotonic()
        with self._lock:
            longest = 0.0
            for key in keys:
                if not key:
                    continue
                longest = max(longest, self._bucket(scope, key).locked_until - now)
            return int(longest) if longest > 0 else 0

    def register_failure(self, scope: str, *keys: str) -> None:
        now = time.monotonic()
        with self._lock:
            for key in keys:
                if not key:
                    continue
                bucket = self._bucket(scope, key)
                bucket.failures = [t for t in bucket.failures if now - t < WINDOW_SECONDS]
                bucket.failures.append(now)
                if len(bucket.failures) >= MAX_ATTEMPTS:
                    bucket.locked_until = now + LOCKOUT_SECONDS
                    bucket.failures.clear()

    def register_success(self, scope: str, *keys: str) -> None:
        """Удачный вход обнуляет счётчик: несколько опечаток подряд с
        последующим верным паролем — обычное поведение человека, а не атака."""
        with self._lock:
            for key in keys:
                if key:
                    self._bucket(scope, key).failures.clear()

    def reset(self) -> None:
        """Для тестов: состояние живёт в процессе и иначе течёт между ними."""
        with self._lock:
            self._buckets.clear()


guard = LoginGuard()
