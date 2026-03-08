"""add organisations, org_members tables and extend api_keys/usage_records

Revision ID: 003_organisations
Revises: b24df0d48702
Create Date: 2026-03-08 10:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '003_organisations'
down_revision: Union[str, Sequence[str]] = 'b24df0d48702'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # --- organisations table ---
    op.create_table(
        'organisations',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('name', sa.String(255), nullable=False),
        sa.Column('slug', sa.String(100), nullable=False),
        sa.Column('plan', sa.String(50), server_default='free'),
        sa.Column('stripe_customer_id', sa.String(255), server_default=''),
        sa.Column('monthly_credits', sa.Integer(), server_default='1000'),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column('is_active', sa.Boolean(), server_default=sa.text('true')),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_organisations_slug', 'organisations', ['slug'], unique=True)

    # --- org_members table ---
    op.create_table(
        'org_members',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('org_id', sa.Integer(), nullable=False),
        sa.Column('user_id', sa.Integer(), nullable=False),
        sa.Column('role', sa.String(50), server_default='member'),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.ForeignKeyConstraint(['org_id'], ['organisations.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('org_id', 'user_id', name='uq_org_member'),
    )

    # --- extend api_keys ---
    op.add_column('api_keys', sa.Column('org_id', sa.Integer(), nullable=True))
    op.add_column('api_keys', sa.Column('environment', sa.String(20), server_default='production'))
    op.add_column('api_keys', sa.Column('description', sa.Text(), server_default=''))
    op.create_foreign_key('fk_api_keys_org_id', 'api_keys', 'organisations', ['org_id'], ['id'])

    # --- extend usage_records ---
    op.add_column('usage_records', sa.Column('org_id', sa.Integer(), nullable=True))
    op.create_foreign_key('fk_usage_records_org_id', 'usage_records', 'organisations', ['org_id'], ['id'])
    op.create_index('ix_usage_records_org_id', 'usage_records', ['org_id'])


def downgrade() -> None:
    op.drop_index('ix_usage_records_org_id', table_name='usage_records')
    op.drop_constraint('fk_usage_records_org_id', 'usage_records', type_='foreignkey')
    op.drop_column('usage_records', 'org_id')

    op.drop_constraint('fk_api_keys_org_id', 'api_keys', type_='foreignkey')
    op.drop_column('api_keys', 'description')
    op.drop_column('api_keys', 'environment')
    op.drop_column('api_keys', 'org_id')

    op.drop_table('org_members')
    op.drop_table('organisations')
