"""initial schema

Revision ID: b24df0d48702
Revises:
Create Date: 2026-03-05 12:09:50.451535

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'b24df0d48702'
down_revision: Union[str, Sequence[str], None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'users',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('email', sa.String(255), nullable=False),
        sa.Column('password_hash', sa.String(255), nullable=False),
        sa.Column('name', sa.String(255), server_default=''),
        sa.Column('plan', sa.String(50), server_default='free'),
        sa.Column('stripe_customer_id', sa.String(255), server_default=''),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column('is_active', sa.Boolean(), server_default=sa.text('true')),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_users_email', 'users', ['email'], unique=True)

    op.create_table(
        'api_keys',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('user_id', sa.Integer(), nullable=False),
        sa.Column('key_prefix', sa.String(20), nullable=False),
        sa.Column('key_hash', sa.String(255), nullable=False),
        sa.Column('name', sa.String(255), server_default='Default'),
        sa.Column('is_active', sa.Boolean(), server_default=sa.text('true')),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column('last_used_at', sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(['user_id'], ['users.id']),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_api_keys_key_hash', 'api_keys', ['key_hash'], unique=True)

    op.create_table(
        'usage_records',
        sa.Column('id', sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column('api_key_id', sa.Integer(), nullable=False),
        sa.Column('endpoint', sa.String(100), nullable=False),
        sa.Column('credits_used', sa.Integer(), server_default='1'),
        sa.Column('cached', sa.Boolean(), server_default=sa.text('false')),
        sa.Column('response_time_ms', sa.Integer(), server_default='0'),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.ForeignKeyConstraint(['api_key_id'], ['api_keys.id']),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_usage_records_api_key_id', 'usage_records', ['api_key_id'])
    op.create_index('ix_usage_records_created_at', 'usage_records', ['created_at'])


def downgrade() -> None:
    op.drop_table('usage_records')
    op.drop_table('api_keys')
    op.drop_table('users')
