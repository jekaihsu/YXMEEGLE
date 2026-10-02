"""Business scope approved on 2026-09-27; not an end-user setting."""
FEATURE_LEARNING = False
LEARNING_DISABLED_MESSAGE = '業主裁示停用：訓練、能力認定及考評暫停'


def require_learning():
    from .workflow import require
    require(FEATURE_LEARNING, LEARNING_DISABLED_MESSAGE, 404)
