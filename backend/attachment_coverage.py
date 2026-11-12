"""Bounded, case-scoped attachment coverage for an already visible project.

Source attachment metadata and imported workspace file versions are separate
populations. Neither count establishes source-field completeness or file access.
"""


def source_attachment_coverage(project):
    """Summarize only the attachment fields carried by ``project``."""
    attachments = project.get('source_attachments') or []
    counts = dict.fromkeys(('indexed', 'source_missing',
                            'metadata_unavailable', 'unknown'), 0)
    for attachment in attachments:
        status = attachment.get('status')
        counts[status if status in counts else 'unknown'] += 1
    return {
        'scope': 'case_only',
        'metadata_records': len(attachments),
        'metadata_status_counts': counts,
        'workspace_versions': len(project.get('files') or []),
        'unmatched_metadata_access': 'outside_case_scope',
        'source_field_coverage': 'not_reported',
        'file_content_access': 'not_verified',
    }
