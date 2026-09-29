"""迁移显式读取独立配置；不在INI内存放连接密码。"""

from alembic import context
from sqlalchemy import text

from app.config import Settings
from app.db.base import Base
from app.db.connection import database_engine


def include_object(obj, name, kind, reflected, compare_to):
    # PostGIS扩展关系不参与业务模型的自动迁移差异。
    return not (kind == "table" and name == "spatial_ref_sys")


settings = Settings()
if context.is_offline_mode():
    context.configure(
        url=settings.connection_url(migration=True),
        target_metadata=Base.metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        include_object=include_object,
    )
    with context.begin_transaction():
        context.run_migrations()
else:
    engine = database_engine(settings, migration=True)
    try:
        with engine.begin() as connection:
            # 官方镜像还暴露tiger/topology；自动差异只处理public业务空间。
            connection.execute(text("SET LOCAL search_path TO public"))
            context.configure(
                connection=connection,
                target_metadata=Base.metadata,
                include_object=include_object,
            )
            with context.begin_transaction():
                context.run_migrations()
    finally:
        engine.dispose()
