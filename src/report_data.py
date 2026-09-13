"""Versioned report projection. Does not import AstrBot or perform I/O."""
from collections import defaultdict
from typing import Iterable, Optional

from .ai_summary_service import score_std_dev
from .models import Vote


def enrich_report(payload: dict, votes: Optional[Iterable[Vote]] = None,
                  include_participants: bool = True, minimum_votes: int = 5) -> dict:
    rows = payload['candidates']
    by_id = {row['candidate_id']: row for row in rows}
    sent = {row['candidate_id'] for row in rows if row['send_status'] == 'sent'}
    session = payload['session']
    people_count = payload['statistics']['unique_voters']
    for row in rows:
        counts = {int(k): int(v) for k, v in row['score_distribution'].items()}
        row['standard_deviation'] = score_std_dev(counts) if row['vote_count'] >= 2 else None
        row['low_sample'] = 0 < row['vote_count'] < minimum_votes
        row['coverage'] = row['vote_count'] / people_count if people_count and row['candidate_id'] in sent else None
    payload['schema_version'] = 2
    payload['report_mode'] = 'directory'
    payload['privacy'] = 'participants' if include_participants else 'aggregate'
    payload['methodology'] = {
        'minimum_votes': minimum_votes,
        'ranking': 'average_desc,votes_desc,display_index_asc',
        'vote_history': 'final_effective_votes_only',
        'coverage_denominator': 'successfully_sent_candidates',
    }
    sent_votes = sum(r['vote_count'] for r in rows if r['candidate_id'] in sent)
    payload['metrics'] = {
        'sent_count': len(sent),
        'failed_count': sum(r['send_status'] == 'send_failed' for r in rows),
        'pending_count': sum(r['send_status'] == 'pending' for r in rows),
        'unrated_count': sum(r['candidate_id'] in sent and r['vote_count'] == 0 for r in rows),
        'low_sample_count': sum(r['low_sample'] for r in rows),
        'votes_per_sent_candidate': sent_votes / len(sent) if sent else None,
        'filling_coverage': sent_votes / (len(sent) * people_count) if sent and people_count else None,
        'partial': len(sent) < len(rows),
        'legacy_unexposed_votes': payload['statistics']['total_valid_votes'] - sent_votes,
    }
    eligible = [r for r in rows if r['vote_count'] >= minimum_votes]
    payload['insights'] = {
        'featured': [r['candidate_id'] for r in sorted(eligible, key=lambda r: r['rank'] or 10**9)[:3]],
        'dispersed': [r['candidate_id'] for r in sorted(eligible, key=lambda r: (-(r['standard_deviation'] or 0), r['display_index']))[:3]],
        'low_rated': [r['candidate_id'] for r in sorted(eligible, key=lambda r: (r['average_score'], -r['vote_count'], r['display_index']))[:3]],
    }
    payload['participants'] = []
    payload['votes'] = []
    payload['participant_details_available'] = votes is not None and include_participants
    if not include_participants:
        # Remove at serialization time, not just by hiding controls in CSS.
        session.pop('group_id', None)
        return payload
    if votes is None:
        return payload
    grouped = defaultdict(list)
    for vote in votes:
        if (vote.session_id == session['id'] and vote.candidate_id in by_id
                and session['score_min'] <= vote.score <= session['score_max']):
            grouped[vote.voter_id].append(vote)
    for index, voter_id in enumerate(sorted(grouped)):
        participant_id = 'p%d' % (index + 1)
        person_votes = grouped[voter_id]
        latest = max(person_votes, key=lambda v: (v.updated_at or v.created_at or '', v.candidate_id))
        payload['participants'].append({
            'id': participant_id,
            'name': latest.voter_name or '参与者 %d' % (index + 1),
            'avatar': None,
            'vote_count': len(person_votes),
            'average_score': sum(v.score for v in person_votes) / len(person_votes),
            'coverage': sum(v.candidate_id in sent for v in person_votes) / len(sent) if sent else None,
        })
        payload['votes'].extend({
            'participant_id': participant_id,
            'candidate_id': v.candidate_id,
            'score': v.score,
            'created_at': v.created_at,
            'updated_at': v.updated_at,
        } for v in person_votes)
    return payload
