"""Полнота реестра моделей и отсутствие дрейфа схемы.

Модель, не импортированная в app/models/__init__.py, для Alembic не
существует: `env.py` берёт метаданные оттуда, и autogenerate предложит
**удалить** её таблицу. Именно это и произошло — список перестали пополнять
после Этапа 5, и к Этапу 10 автогенерация предлагала снести восемь таблиц.
Уследить за этим глазами нельзя, поэтому здесь тест.
"""

import pkgutil

from sqlalchemy.orm import Session

import app.models
from app.models.base import Base


def _model_modules() -> list[str]:
    return [
        module.name
        for module in pkgutil.iter_modules(app.models.__path__)
        if module.name != "base"
    ]


def test_all_models_are_registered():
    """Каждый модуль в app/models должен быть импортирован пакетом."""
    import importlib

    registered_tables = set(Base.metadata.tables)
    missing = []

    for name in _model_modules():
        module = importlib.import_module(f"app.models.{name}")
        tables = {
            obj.__tablename__
            for obj in vars(module).values()
            if isinstance(obj, type) and issubclass(obj, Base) and hasattr(obj, "__tablename__")
        }
        # Модуль мог импортировать чужую модель — интересны только те таблицы,
        # которых нет в метаданных вообще.
        if tables and not (tables & registered_tables):
            missing.append(f"{name} ({', '.join(sorted(tables))})")

    assert not missing, (
        "Не импортированы в app/models/__init__.py: "
        + "; ".join(missing)
        + ". Без этого autogenerate предложит удалить их таблицы."
    )


def test_schema_matches_the_models(db: Session):
    """Живая база должна совпадать с моделями: расхождение означает либо
    забытую миграцию, либо миграцию, отставшую от модели."""
    from alembic.autogenerate import compare_metadata
    from alembic.migration import MigrationContext

    context = MigrationContext.configure(db.connection())
    diff = compare_metadata(context, Base.metadata)

    assert diff == [], "Схема разошлась с моделями:\n" + "\n".join(str(d)[:200] for d in diff)
