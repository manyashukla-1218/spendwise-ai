"""auth users api keys audit actor

Revision ID: 0002
Revises: 0001
Create Date: 2026-11-27 02:30:12.638191
"""
from alembic import op
import sqlalchemy as sa


revision = '0002'
down_revision = '0001'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table('api_keys',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('tenant_id', sa.String(length=40), nullable=False),
    sa.Column('name', sa.String(length=100), nullable=False),
    sa.Column('prefix', sa.String(length=16), nullable=False),
    sa.Column('key_hash', sa.String(length=64), nullable=False),
    sa.Column('role', sa.String(length=20), nullable=False),
    sa.Column('is_active', sa.Boolean(), nullable=False),
    sa.Column('created_at', sa.DateTime(), nullable=True),
    sa.Column('last_used_at', sa.DateTime(), nullable=True),
    sa.ForeignKeyConstraint(['tenant_id'], ['tenants.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    with op.batch_alter_table('api_keys', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_api_keys_key_hash'), ['key_hash'], unique=True)
        batch_op.create_index(batch_op.f('ix_api_keys_tenant_id'), ['tenant_id'], unique=False)

    op.create_table('users',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('tenant_id', sa.String(length=40), nullable=False),
    sa.Column('email', sa.String(length=200), nullable=False),
    sa.Column('password_hash', sa.String(length=300), nullable=False),
    sa.Column('role', sa.String(length=20), nullable=False),
    sa.Column('is_active', sa.Boolean(), nullable=False),
    sa.Column('created_at', sa.DateTime(), nullable=True),
    sa.ForeignKeyConstraint(['tenant_id'], ['tenants.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    with op.batch_alter_table('users', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_users_email'), ['email'], unique=True)
        batch_op.create_index(batch_op.f('ix_users_tenant_id'), ['tenant_id'], unique=False)

    with op.batch_alter_table('audit_logs', schema=None) as batch_op:
        batch_op.add_column(sa.Column('actor', sa.String(length=200), nullable=True))

    # Data migration: existing plain-text tenant keys keep working, but are stored only as SHA-256 hashes
    # (role "admin", because that is what a tenant key could do before roles existed).
    import hashlib
    from datetime import datetime

    tenants = sa.table("tenants", sa.column("id", sa.String), sa.column("api_key", sa.String))
    api_keys = sa.table("api_keys", sa.column("tenant_id", sa.String), sa.column("name", sa.String),
                        sa.column("prefix", sa.String), sa.column("key_hash", sa.String), sa.column("role", sa.String),
                        sa.column("is_active", sa.Boolean), sa.column("created_at", sa.DateTime))
    existing = op.get_bind().execute(sa.select(tenants.c.id, tenants.c.api_key)).fetchall()
    rows = [{"tenant_id": tid, "name": "migrated-tenant-key", "prefix": key[:10],
             "key_hash": hashlib.sha256(key.encode()).hexdigest(), "role": "admin", "is_active": True,
             "created_at": datetime.utcnow()} for tid, key in existing if key]
    if rows:
        op.bulk_insert(api_keys, rows)

    with op.batch_alter_table('tenants', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_tenants_api_key'))
        batch_op.drop_column('api_key')


def downgrade() -> None:
    with op.batch_alter_table('tenants', schema=None) as batch_op:
        # plain-text keys cannot be recovered from hashes, so the restored column is empty (nullable)
        batch_op.add_column(sa.Column('api_key', sa.VARCHAR(length=100), nullable=True))
        batch_op.create_index(batch_op.f('ix_tenants_api_key'), ['api_key'], unique=False)

    with op.batch_alter_table('audit_logs', schema=None) as batch_op:
        batch_op.drop_column('actor')

    with op.batch_alter_table('users', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_users_tenant_id'))
        batch_op.drop_index(batch_op.f('ix_users_email'))

    op.drop_table('users')
    with op.batch_alter_table('api_keys', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_api_keys_tenant_id'))
        batch_op.drop_index(batch_op.f('ix_api_keys_key_hash'))

    op.drop_table('api_keys')
