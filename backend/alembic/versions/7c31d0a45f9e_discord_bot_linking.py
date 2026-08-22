"""discord bot: account linking

Revision ID: 7c31d0a45f9e
Revises: 2541ce628ab9
Create Date: 2026-08-23

Adds the Discord account a user has linked, and the short-lived codes that
prove the link. Nothing here is required: an installation without the bot has
a null column and an empty table.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision: str = '7c31d0a45f9e'
down_revision: str | None = '2541ce628ab9'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column('users', sa.Column('discord_user_id', sa.String(length=32), nullable=True))
    # Unique so one Discord account cannot receive two accounts' alerts, and
    # indexed because the bot looks users up by it on every command.
    op.create_index('ix_users_discord_user_id', 'users', ['discord_user_id'], unique=True)

    op.create_table(
        'discord_link_codes',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('code', sa.String(length=16), nullable=False),
        sa.Column('user_id', sa.Integer(), nullable=False),
        sa.Column('expires_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('used_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('CURRENT_TIMESTAMP'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('CURRENT_TIMESTAMP'), nullable=False),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_discord_link_codes_code', 'discord_link_codes', ['code'], unique=True)
    op.create_index('ix_discord_link_codes_user_id', 'discord_link_codes', ['user_id'])


def downgrade() -> None:
    op.drop_index('ix_discord_link_codes_user_id', table_name='discord_link_codes')
    op.drop_index('ix_discord_link_codes_code', table_name='discord_link_codes')
    op.drop_table('discord_link_codes')
    op.drop_index('ix_users_discord_user_id', table_name='users')
    op.drop_column('users', 'discord_user_id')
