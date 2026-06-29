"""Bot-owned Tortoise models."""

from __future__ import annotations

from typing import TYPE_CHECKING

from tortoise import fields
from tortoise.models import Model

if TYPE_CHECKING:
    from arcade_helper.storage.tortoise.models import User


class Event(Model):
    """赛事表：存储赛事信息"""

    id = fields.IntField(primary_key=True)
    name = fields.CharField(max_length=128, unique=True)
    group_id = fields.CharField(max_length=32, null=True, db_index=True)
    extra_group_ids = fields.JSONField(default=list)
    start_time = fields.DatetimeField()
    end_time = fields.DatetimeField()
    songs = fields.JSONField(default=list)
    created_by: fields.ForeignKeyNullableRelation[User] = fields.ForeignKeyField(
        "models.User",
        related_name="created_events",
        on_delete=fields.SET_NULL,
        null=True,
    )
    created_at = fields.DatetimeField(auto_now_add=True)
    updated_at = fields.DatetimeField(auto_now=True)

    class Meta(Model.Meta):
        table = "events"


class Team(Model):
    """队伍表：存储队伍信息"""

    id = fields.IntField(primary_key=True)
    name = fields.CharField(max_length=128, unique=True)
    real_name = fields.CharField(max_length=128, null=True)
    icon = fields.TextField(null=True)
    event: fields.ForeignKeyRelation[Event] = fields.ForeignKeyField(
        "models.Event",
        related_name="teams",
        on_delete=fields.CASCADE,
        db_index=True,
    )
    scores = fields.JSONField(default=dict)
    created_by: fields.ForeignKeyNullableRelation[User] = fields.ForeignKeyField(
        "models.User",
        related_name="created_teams",
        on_delete=fields.SET_NULL,
        null=True,
    )
    created_at = fields.DatetimeField(auto_now_add=True)
    updated_at = fields.DatetimeField(auto_now=True)

    members: fields.ManyToManyRelation[User] = fields.ManyToManyField(
        "models.User",
        related_name="teams",
        through="team_members",
    )

    class Meta(Model.Meta):
        table = "teams"


__all__ = [
    "Event",
    "Team",
]
