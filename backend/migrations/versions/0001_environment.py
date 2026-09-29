"""建立环境迁移基线；本轮不创建业务关系。"""

from alembic import op

revision = "0001_environment"
down_revision = None
branch_labels = None
depends_on = None


def upgrade():
    op.execute("CREATE EXTENSION IF NOT EXISTS postgis")


def downgrade():
    # 扩展可能由官方镜像初始化；回退版本时保留它，避免删除依赖对象。
    pass
