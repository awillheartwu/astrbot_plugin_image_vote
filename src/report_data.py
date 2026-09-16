"""Versioned report projection. Does not import AstrBot or perform I/O."""
from collections import defaultdict
from typing import Iterable, Optional

from .ai_summary_service import score_std_dev, parse_summary
from .models import Vote


def enrich_report(payload: dict, votes: Optional[Iterable[Vote]] = None,
                  include_participants: bool = True, minimum_votes: int = 5) -> dict:
    rows = payload['candidates']
    by_id = {row['candidate_id']: row for row in rows}
    characters = payload.setdefault('characters', [])
    by_character = {row['character']: row for row in characters}
    sent_images = {row['candidate_id'] for row in rows if row['send_status'] == 'sent'}
    sent_characters = {
        row['character'] for row in rows if row['candidate_id'] in sent_images
    }
    session = payload['session']
    people_count = payload['statistics']['unique_voters']
    for row in rows:
        # 图片是人物素材，不再承担独立评分。
        row.pop('vote_count', None)
        row.pop('average_score', None)
        row.pop('score_distribution', None)
        row.pop('rank', None)
    for character in characters:
        counts = {int(k): int(v) for k, v in character['score_distribution'].items()}
        character['standard_deviation'] = score_std_dev(counts) if character['vote_count'] >= 2 else None
        character['low_sample'] = 0 < character['vote_count'] < minimum_votes
        character['coverage'] = (
            character['vote_count'] / people_count
            if people_count and character['character'] in sent_characters else None
        )
    payload['ai_analysis'] = parse_summary(payload.get('ai_summary'))
    payload['schema_version'] = 3
    payload['report_mode'] = 'directory'
    payload['privacy'] = 'participants' if include_participants else 'aggregate'
    payload['methodology'] = {
        'minimum_votes': minimum_votes,
        'vote_target': 'character',
        'ranking': 'average_desc,votes_desc,character_first_appearance_asc',
        'vote_history': 'final_effective_votes_only',
        'coverage_denominator': 'characters_with_at_least_one_successfully_sent_image',
    }
    valid_votes = sum(character['vote_count'] for character in characters if character['character'] in sent_characters)
    payload['metrics'] = {
        'sent_count': len(sent_images),
        'character_count': len(characters),
        'sent_character_count': len(sent_characters),
        'failed_count': sum(r['send_status'] == 'send_failed' for r in rows),
        'pending_count': sum(r['send_status'] == 'pending' for r in rows),
        'unrated_count': sum(c['character'] in sent_characters and c['vote_count'] == 0 for c in characters),
        'low_sample_count': sum(c['low_sample'] for c in characters),
        'votes_per_sent_character': valid_votes / len(sent_characters) if sent_characters else None,
        'filling_coverage': valid_votes / (len(sent_characters) * people_count) if sent_characters and people_count else None,
        'partial': len(sent_images) < len(rows),
        'legacy_unexposed_votes': payload['statistics']['total_valid_votes'] - valid_votes,
    }
    eligible = [c for c in characters if c['vote_count'] >= minimum_votes]
    payload['insights'] = {
        'featured': [c['character'] for c in sorted(eligible, key=lambda c: c['rank'] or 10**9)[:3]],
        'dispersed': [c['character'] for c in sorted(eligible, key=lambda c: (-(c['standard_deviation'] or 0), c['character']))[:3]],
        'low_rated': [c['character'] for c in sorted(eligible, key=lambda c: (c['average_score'], -c['vote_count'], c['character']))[:3]],
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
        character = vote.character or (by_id.get(vote.candidate_id) or {}).get('character')
        if (vote.session_id == session['id'] and character in by_character
                and session['score_min'] <= vote.score <= session['score_max']):
            grouped[vote.voter_id].append((vote, character))
    for index, voter_id in enumerate(sorted(grouped)):
        participant_id = 'p%d' % (index + 1)
        person_votes = grouped[voter_id]
        latest = max(person_votes, key=lambda item: (item[0].updated_at or item[0].created_at or '', item[1]))[0]
        payload['participants'].append({
            'id': participant_id,
            'name': latest.voter_name or '参与者 %d' % (index + 1),
            'avatar': None,
            'vote_count': len(person_votes),
            'average_score': sum(v.score for v, _ in person_votes) / len(person_votes),
            'coverage': sum(character in sent_characters for _, character in person_votes) / len(sent_characters) if sent_characters else None,
        })
        payload['votes'].extend({
            'participant_id': participant_id,
            'character': character,
            'source_candidate_id': v.candidate_id,
            'score': v.score,
            'created_at': v.created_at,
            'updated_at': v.updated_at,
        } for v, character in person_votes)
    return payload
