"""run_preview — картинка первой страницы у записи журнала запусков.

Одна колонка: `project_runs.preview_artifact_id`. В ней лежит идентификатор
артефакта — PNG первой страницы документа, собранного этим запуском. Картинку
кладёт сборка, а показывает её карточка отчёта в списке.

**Своё поле, а не `artifact_id`.** То отвечает на вопрос «что запуск
произвёл» — DOCX, XML схемы, — и по нему файл скачивают; это отвечает на
вопрос «чем его узнать в списке». Одно поле на оба означало бы выбор между
«скачать» и «увидеть».

**Строка в базе, а не обход тома.** Список отчётов работы читается целиком, с
картинкой у каждой строки, и искать превью перебором артефактов значило бы
обходить каталог на каждую отрисовку списка. Сами байты при этом остаются
артефактом: он адресуется содержимым и отдаётся тем же маршрутом, что и всё
прочее содержимое работы.

Пусто — законное значение: отчёт, который ещё ни разу не собирали, показывается
наброском страницы, а не пустотой.

Revision ID: b6d3f0a17c92
Revises: a7c2e51f8b03
Create Date: 2026-09-05
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = 'b6d3f0a17c92'
down_revision = 'a7c2e51f8b03'
branch_labels = None
depends_on = None

# Та же длина, что у `artifact_id` по соседству: идентификатор артефакта один и
# тот же, и вторая длина рядом с первой разошлась бы при первом удлинении среза.
ARTIFACT_LEN = 32


def upgrade() -> None:
    with op.batch_alter_table('project_runs', schema=None) as batch:
        batch.add_column(sa.Column('preview_artifact_id',
                                   sa.String(length=ARTIFACT_LEN),
                                   nullable=True))


def downgrade() -> None:
    with op.batch_alter_table('project_runs', schema=None) as batch:
        batch.drop_column('preview_artifact_id')
