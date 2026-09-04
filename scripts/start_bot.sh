#!/usr/bin/env bash
# Start command for the bot service.
# Migrations run here and only here, so two services never race each other.
set -e
python -m alembic upgrade head
exec python -m lyfe.bot.main
