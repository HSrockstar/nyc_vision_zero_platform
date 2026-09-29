"""M2运行账号状态边界；使用前向迁移更新已建开发库。"""

from pathlib import Path
import re
from alembic import op
import sqlalchemy as sa

revision = "0004_import_role_guard"
down_revision = "0003_import_pipeline"
branch_labels = None
depends_on = None


def upgrade():
    path = Path(__file__).resolve().parents[1] / "sql/0004_import_role_guard.sql"
    op.execute(sa.text(path.read_text(encoding="utf-8")))


def downgrade():
    if not re.fullmatch(r"vision_zero_m1_test_[0-9a-f]{12}", op.get_bind().scalar(sa.text("SELECT current_database()"))):
        raise RuntimeError("仅允许专用随机验证库降级。")
    path = Path(__file__).resolve().parents[1] / "sql/0003_import_guard.sql"
    source = path.read_text(encoding="utf-8").split("CREATE TRIGGER")[0]
    op.execute(sa.text(source.replace("CREATE FUNCTION", "CREATE OR REPLACE FUNCTION", 1)))
