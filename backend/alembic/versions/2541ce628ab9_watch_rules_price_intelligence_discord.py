"""watch rules, price intelligence, discord

Revision ID: 2541ce628ab9
Revises: 88916a33f702
Create Date: 2026-08-13 13:41:56.100418

Hand-adjusted after autogenerate, which cannot know three things:

* every NOT NULL column added to a populated table needs a `server_default`,
  or the ALTER fails on any database that already has rows;
* the notifications -> watch_rules foreign key needs a name, or the downgrade
  cannot drop it (batch mode renders `DROP CONSTRAINT None`);
* `watched_availability` should start from the value it most resembles rather
  than from 'unknown', which would blank every card until the next check.
"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = '2541ce628ab9'
down_revision: str | None = '88916a33f702'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        'watch_rules',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('user_id', sa.Integer(), nullable=False),
        sa.Column('tracked_product_id', sa.Integer(), nullable=False),
        sa.Column('tracked_variant_id', sa.Integer(), nullable=True),
        sa.Column('label', sa.String(length=160), nullable=True),
        sa.Column('stock_condition', sa.String(length=24), nullable=False, server_default='any'),
        sa.Column('price_condition', sa.String(length=24), nullable=False, server_default='any'),
        sa.Column('combine', sa.String(length=8), nullable=False, server_default='all'),
        sa.Column('price_value', sa.Numeric(precision=12, scale=2), nullable=True),
        sa.Column('percent_value', sa.Numeric(precision=6, scale=2), nullable=True),
        sa.Column('notify_browser', sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column('notify_email', sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column('notify_discord', sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column('is_active', sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column('cooldown_minutes', sa.Integer(), nullable=False, server_default='720'),
        sa.Column('last_triggered_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('trigger_count', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=False),
        sa.ForeignKeyConstraint(['tracked_product_id'], ['tracked_products.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['tracked_variant_id'], ['tracked_variants.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
    )
    with op.batch_alter_table('watch_rules', schema=None) as batch_op:
        batch_op.create_index('ix_watch_rules_product_active', ['tracked_product_id', 'is_active'], unique=False)
        batch_op.create_index(batch_op.f('ix_watch_rules_tracked_product_id'), ['tracked_product_id'], unique=False)
        batch_op.create_index(batch_op.f('ix_watch_rules_user_id'), ['user_id'], unique=False)

    with op.batch_alter_table('notifications', schema=None) as batch_op:
        batch_op.add_column(sa.Column('watch_rule_id', sa.Integer(), nullable=True))
        # Existing alerts predate per-alert channels; browser and email were
        # what they would have used, so that is what they keep.
        batch_op.add_column(sa.Column('channel_browser', sa.Boolean(), nullable=False, server_default=sa.true()))
        batch_op.add_column(sa.Column('channel_email', sa.Boolean(), nullable=False, server_default=sa.true()))
        batch_op.add_column(sa.Column('channel_discord', sa.Boolean(), nullable=False, server_default=sa.false()))
        batch_op.add_column(sa.Column('discord_sent_at', sa.DateTime(timezone=True), nullable=True))
        batch_op.add_column(sa.Column('discord_error', sa.Text(), nullable=True))
        batch_op.create_foreign_key(
            'fk_notifications_watch_rule_id', 'watch_rules', ['watch_rule_id'], ['id'], ondelete='SET NULL'
        )

    with op.batch_alter_table('tracked_products', schema=None) as batch_op:
        batch_op.add_column(
            sa.Column('watched_availability', sa.String(length=20), nullable=False, server_default='unknown')
        )

    # Seed it from the value it replaces. Not exactly right for a product whose
    # watched size is sold out while another is not - but that is precisely the
    # case the next check corrects, and starting from the old answer is far
    # better than showing "unknown" on every card until then.
    op.execute('UPDATE tracked_products SET watched_availability = availability')

    with op.batch_alter_table('users', schema=None) as batch_op:
        batch_op.add_column(
            sa.Column('discord_notifications', sa.Boolean(), nullable=False, server_default=sa.false())
        )
        batch_op.add_column(sa.Column('discord_webhook_url', sa.String(length=512), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table('users', schema=None) as batch_op:
        batch_op.drop_column('discord_webhook_url')
        batch_op.drop_column('discord_notifications')

    with op.batch_alter_table('tracked_products', schema=None) as batch_op:
        batch_op.drop_column('watched_availability')

    with op.batch_alter_table('notifications', schema=None) as batch_op:
        batch_op.drop_constraint('fk_notifications_watch_rule_id', type_='foreignkey')
        batch_op.drop_column('discord_error')
        batch_op.drop_column('discord_sent_at')
        batch_op.drop_column('channel_discord')
        batch_op.drop_column('channel_email')
        batch_op.drop_column('channel_browser')
        batch_op.drop_column('watch_rule_id')

    with op.batch_alter_table('watch_rules', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_watch_rules_user_id'))
        batch_op.drop_index(batch_op.f('ix_watch_rules_tracked_product_id'))
        batch_op.drop_index('ix_watch_rules_product_active')

    op.drop_table('watch_rules')
