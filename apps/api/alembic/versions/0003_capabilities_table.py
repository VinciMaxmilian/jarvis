"""capabilities — catálogo persistido (v1.1)

Revision ID: 0003
Revises: 6c0c7a8deed0
Create Date: 2026-07-30

O registry era um dicionário reconstruído por varredura de disco a cada boot:
`health` e `last_used_at` não sobreviviam a um `restart`. O manifest continua no
disco, versionado com o código; esta tabela guarda o estado operacional e o que
o gate aprovou (`approved_commit`).

`name` é UNIQUE por ser a chave natural — o nome do diretório da capability, que
o `discover()` já exige bater com o do manifest.
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0003"
down_revision: str | None = "6c0c7a8deed0"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    capability_status = postgresql.ENUM(
        "pending_approval", "approved", "active", "disabled",
        name="capability_status", create_type=True,
    )
    # Saúde é medida, `status` é decisão. Dois enums porque uma falha de rede não
    # pode desaprovar uma capability, nem uma aprovação apagar o histórico.
    capability_health = postgresql.ENUM(
        "unknown", "healthy", "degraded", "failing",
        name="capability_health", create_type=True,
    )

    op.create_table(
        "capabilities",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("name", sa.String(200), nullable=False, unique=True),
        sa.Column("version", sa.String(50), nullable=False, server_default="0.0.0"),
        sa.Column("runtime", sa.String(50), nullable=False, server_default="mcp_stdio"),
        sa.Column("status", capability_status, nullable=False, server_default="pending_approval"),
        sa.Column("permissions", postgresql.JSONB, nullable=False, server_default="{}"),
        sa.Column("dependencies", postgresql.JSONB, nullable=False, server_default="[]"),
        sa.Column("approved_commit", sa.String(128), nullable=True),
        sa.Column("health", capability_health, nullable=False, server_default="unknown"),
        sa.Column("last_used_at", sa.DateTime(timezone=True), nullable=True),
    )
    # Consulta quente do registry: "o que está `active`?" a cada resolve().
    op.create_index("ix_capabilities_status", "capabilities", ["status"])


def downgrade() -> None:
    op.drop_index("ix_capabilities_status", table_name="capabilities")
    op.drop_table("capabilities")
    op.execute("DROP TYPE IF EXISTS capability_health")
    op.execute("DROP TYPE IF EXISTS capability_status")
