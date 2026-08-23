"""account recovery: reset codes, verification, token revocation

Revision ID: 9f2b71c4d8ae
Revises: 7c31d0a45f9e
Create Date: 2026-08-24

token_version defaults to 0 for existing rows, which matches what a token
without the claim decodes to - so sessions issued before this migration keep
working rather than logging everybody out on deploy.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision: str = '9f2b71c4d8ae'
down_revision: str | None = '7c31d0a45f9e'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column('users', sa.Column('email_verified_at', sa.DateTime(timezone=True), nullable=True))
    op.add_column(
        'users',
        sa.Column('token_version', sa.Integer(), server_default='0', nullable=False),
    )

    op.create_table(
        'auth_tokens',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('user_id', sa.Integer(), nullable=False),
        sa.Column('purpose', sa.String(length=32), nullable=False),
        sa.Column('token_hash', sa.String(length=64), nullable=False),
        sa.Column('expires_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('used_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('CURRENT_TIMESTAMP'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('CURRENT_TIMESTAMP'), nullable=False),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_auth_tokens_token_hash', 'auth_tokens', ['token_hash'], unique=True)
    op.create_index('ix_auth_tokens_user_id', 'auth_tokens', ['user_id'])
    op.create_index('ix_auth_tokens_purpose', 'auth_tokens', ['purpose'])


def downgrade() -> None:
    op.drop_index('ix_auth_tokens_purpose', table_name='auth_tokens')
    op.drop_index('ix_auth_tokens_user_id', table_name='auth_tokens')
    op.drop_index('ix_auth_tokens_token_hash', table_name='auth_tokens')
    op.drop_table('auth_tokens')
    op.drop_column('users', 'token_version')
    op.drop_column('users', 'email_verified_at')
