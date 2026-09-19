# 钉死的全局配置：重力加速度是全系统唯一的 g 来源，
# 任何物理模块都必须 `from app.config import get_settings` 取 g，禁止再定义第二个本地常数。

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="WAVE_", env_file=".env", extra="ignore")

    # 物理常数（服务内钉死，不允许被环境变量覆盖，确保任何模块共用同一个 g）
    gravity: float = 9.80665

    # 相对水深判据：kh > pi 深水；kh < pi/10 浅水；之间为中等水深（走完整 tanh）
    deep_water_threshold: float = 3.141592653589793            # π
    shallow_water_threshold: float = 0.3141592653589793       # π/10

    # 线性波适用上限：波高/水深（本服务口径的“波陡”）
    linear_limit: float = 0.5

    # 色散求根容差与最大迭代次数
    solver_tolerance: float = 1.0e-12
    solver_max_iterations: int = 100

    # 存储
    database_url: str = "postgresql+psycopg://waves:waves@db:5432/waves"

    # 启动时是否初始化数据库（测试时关闭）
    auto_init_db: bool = True


@lru_cache
def get_settings() -> Settings:
    return Settings()
