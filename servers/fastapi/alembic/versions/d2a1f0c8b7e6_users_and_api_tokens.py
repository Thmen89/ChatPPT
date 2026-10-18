"""users and api_tokens

Revision ID: d2a1f0c8b7e6
Revises: c7b70d0f31b1
Create Date: 2026-10-17 09:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
import sqlmodel


# revision identifiers, used by Alembic.
revision: str = 'd2a1f0c8b7e6'
down_revision: Union[str, None] = 'c7b70d0f31b1'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _has_table(table_name: str) -> bool:
    return table_name in sa.inspect(op.get_bind()).get_table_names()


def upgrade() -> None:
    if not _has_table('users'):
        op.create_table(
            'users',
            sa.Column('id', sa.Integer(), nullable=False),
            sa.Column('username', sqlmodel.sql.sqltypes.AutoString(length=128), nullable=False),
            sa.Column('password_hash', sqlmodel.sql.sqltypes.AutoString(length=256), nullable=True),
            sa.Column('is_admin', sa.Boolean(), nullable=False),
            sa.Column('is_active', sa.Boolean(), nullable=False),
            sa.Column('session_version', sa.Integer(), nullable=False),
            sa.Column('source', sqlmodel.sql.sqltypes.AutoString(length=16), nullable=False),
            sa.Column('created_at', sa.Integer(), nullable=False),
            sa.Column('last_login_at', sa.Integer(), nullable=True),
            sa.PrimaryKeyConstraint('id'),
        )
        op.create_index(op.f('ix_users_username'), 'users', ['username'], unique=True)
    if not _has_table('api_tokens'):
        op.create_table(
            'api_tokens',
            sa.Column('id', sa.Integer(), nullable=False),
            sa.Column('user_id', sa.Integer(), nullable=False),
            sa.Column('name', sqlmodel.sql.sqltypes.AutoString(length=128), nullable=False),
            sa.Column('prefix', sqlmodel.sql.sqltypes.AutoString(length=16), nullable=False),
            sa.Column('token_hash', sqlmodel.sql.sqltypes.AutoString(length=64), nullable=False),
            sa.Column('created_at', sa.Integer(), nullable=False),
            sa.Column('last_used_at', sa.Integer(), nullable=True),
            sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
            sa.PrimaryKeyConstraint('id'),
        )
        op.create_index(op.f('ix_api_tokens_user_id'), 'api_tokens', ['user_id'], unique=False)
        op.create_index(op.f('ix_api_tokens_token_hash'), 'api_tokens', ['token_hash'], unique=True)


def downgrade() -> None:
    if _has_table('api_tokens'):
        op.drop_index(op.f('ix_api_tokens_token_hash'), table_name='api_tokens')
        op.drop_index(op.f('ix_api_tokens_user_id'), table_name='api_tokens')
        op.drop_table('api_tokens')
    if _has_table('users'):
        op.drop_index(op.f('ix_users_username'), table_name='users')
        op.drop_table('users')
