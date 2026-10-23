"""Preserve quote decision history when its assigned principals change."""
from .workflow import now


def invalidate_pending_quote_reviews(project):
    for review in project.get('quote_reviews', []):
        if review.get('status') == 'pending':
            review.update(status='invalidated', invalidated_at=now(),
                          invalidated_reason='PM 或業務職責已改派，原投票失效')
