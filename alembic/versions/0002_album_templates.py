"""album template management schema

Revision ID: 0002_album_templates
Revises: 0001_initial
Create Date: 2026-06-08
"""
from alembic import op
import sqlalchemy as sa


revision = "0002_album_templates"
down_revision = "0001_initial"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    tables = set(inspector.get_table_names())

    if "album_templates" not in tables:
        op.create_table(
            "album_templates",
            sa.Column("id", sa.BigInteger().with_variant(sa.Integer(), "sqlite"), primary_key=True, autoincrement=True),
            sa.Column("template_id", sa.String(64), nullable=False),
            sa.Column("name", sa.String(128), nullable=False),
            sa.Column("category", sa.String(64), nullable=False, server_default="daily"),
            sa.Column("status", sa.String(32), nullable=False, server_default="draft"),
            sa.Column("min_photo_count", sa.Integer(), nullable=False, server_default="1"),
            sa.Column("max_photo_count", sa.Integer(), nullable=False, server_default="9"),
            sa.Column("theme_tags_json", sa.JSON(), nullable=True),
            sa.Column("style_tags_json", sa.JSON(), nullable=True),
            sa.Column("sort_order", sa.Integer(), nullable=False, server_default="1000"),
            sa.Column("description", sa.Text(), nullable=True),
            sa.Column("current_version", sa.String(32), nullable=False, server_default="v1"),
            sa.Column("published_at", sa.DateTime(), nullable=True),
            sa.Column("archived_at", sa.DateTime(), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.Column("updated_at", sa.DateTime(), nullable=False),
        )
        op.create_index("ix_album_templates_template_id", "album_templates", ["template_id"], unique=True)
        op.create_index("ix_album_templates_category", "album_templates", ["category"])
        op.create_index("ix_album_templates_status", "album_templates", ["status"])

    if "album_template_versions" not in tables:
        op.create_table(
            "album_template_versions",
            sa.Column("id", sa.BigInteger().with_variant(sa.Integer(), "sqlite"), primary_key=True, autoincrement=True),
            sa.Column("template_id", sa.String(64), nullable=False),
            sa.Column("version", sa.String(32), nullable=False, server_default="v1"),
            sa.Column("status", sa.String(32), nullable=False, server_default="draft"),
            sa.Column("template_json", sa.JSON(), nullable=False),
            sa.Column("llm_prompt", sa.Text(), nullable=False),
            sa.Column("matching_rules_json", sa.JSON(), nullable=False),
            sa.Column("render_params_json", sa.JSON(), nullable=False),
            sa.Column("created_by", sa.String(64), nullable=False, server_default="system"),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.Column("updated_at", sa.DateTime(), nullable=False),
            sa.UniqueConstraint("template_id", "version", name="uq_album_template_version"),
        )
        op.create_index("ix_album_template_versions_template_id", "album_template_versions", ["template_id"])
        op.create_index("ix_album_template_versions_status", "album_template_versions", ["status"])

    if "album_template_assets" not in tables:
        op.create_table(
            "album_template_assets",
            sa.Column("id", sa.BigInteger().with_variant(sa.Integer(), "sqlite"), primary_key=True, autoincrement=True),
            sa.Column("asset_id", sa.String(64), nullable=False),
            sa.Column("template_id", sa.String(64), nullable=False),
            sa.Column("version", sa.String(32), nullable=False, server_default="v1"),
            sa.Column("asset_type", sa.String(32), nullable=False),
            sa.Column("file_path", sa.String(1024), nullable=True),
            sa.Column("mime_type", sa.String(64), nullable=False, server_default="image/jpeg"),
            sa.Column("width", sa.Integer(), nullable=True),
            sa.Column("height", sa.Integer(), nullable=True),
            sa.Column("summary_json", sa.JSON(), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.Column("updated_at", sa.DateTime(), nullable=False),
        )
        op.create_index("ix_album_template_assets_asset_id", "album_template_assets", ["asset_id"], unique=True)
        op.create_index("ix_album_template_assets_template_id", "album_template_assets", ["template_id"])
        op.create_index("ix_album_template_assets_asset_type", "album_template_assets", ["asset_type"])

    if "album_template_generation_jobs" not in tables:
        op.create_table(
            "album_template_generation_jobs",
            sa.Column("id", sa.BigInteger().with_variant(sa.Integer(), "sqlite"), primary_key=True, autoincrement=True),
            sa.Column("generation_job_id", sa.String(64), nullable=False),
            sa.Column("festival", sa.String(64), nullable=False),
            sa.Column("target_count", sa.Integer(), nullable=False),
            sa.Column("photo_count_min", sa.Integer(), nullable=False, server_default="1"),
            sa.Column("photo_count_max", sa.Integer(), nullable=False, server_default="9"),
            sa.Column("style_direction", sa.String(255), nullable=True),
            sa.Column("status", sa.String(32), nullable=False, server_default="success"),
            sa.Column("template_ids_json", sa.JSON(), nullable=True),
            sa.Column("request_json", sa.JSON(), nullable=True),
            sa.Column("result_json", sa.JSON(), nullable=True),
            sa.Column("error_message", sa.Text(), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.Column("updated_at", sa.DateTime(), nullable=False),
        )
        op.create_index("ix_album_template_generation_jobs_generation_job_id", "album_template_generation_jobs", ["generation_job_id"], unique=True)
        op.create_index("ix_album_template_generation_jobs_status", "album_template_generation_jobs", ["status"])


def downgrade() -> None:
    for table in [
        "album_template_generation_jobs",
        "album_template_assets",
        "album_template_versions",
        "album_templates",
    ]:
        op.drop_table(table)
