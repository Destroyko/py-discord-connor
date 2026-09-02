"""Коги по модулям (один ``commands.Cog`` на модуль вики).

Порядок реализации: P2 независимые (moderation_chat, purge, ban_kick, mute) →
P3 кластер «работяга» (anti → check → role_giver) → P4 Voices (rooms → xp →
selfmod → ladder) → P6 misc (!kiss). Список — см. IMPLEMENTATION_PLAN.md.
"""
