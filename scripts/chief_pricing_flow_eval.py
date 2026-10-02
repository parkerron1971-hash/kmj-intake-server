"""Opt-in model-only conversation check, fictional inputs and no business writes."""
import argparse
import asyncio
import json
from pathlib import Path
import sys
import httpx
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import chief_of_staff as chief
import chief_models
import chief_build_runtime

async def main():
    ctx = {key: [] for key in ('queue', 'events', 'sessions', 'insights', 'modules', 'at_risk', 'contacts_lookup')}
    ctx.update(business={'name': 'Fictional Studio'}, module_counts={},
        contacts_total=0, contacts_by_status={}, avg_health=None)
    system = chief._build_system_prompt(ctx, False) + chief_models.VOICE_DELIVERY_BLOCK
    system += chief_build_runtime.routing_instructions()
    proposal = ('I propose a revenue tracker for $120,000 collected over the next year, '
        'and a growth objective with milestones: validate the offer this month, launch next month, '
        'review retention in three months. I can save those and a note of the assumptions.')
    cases = {
        'approved_scope': [
            {'role': 'assistant', 'content': proposal},
            {'role': 'user', 'content': 'Yes, create those goals with the milestones, and save the note.'}],
        'correct_to_math': [
            {'role': 'user', 'content': 'I want to reach a million dollars in one year.'},
            {'role': 'assistant', 'content': 'I can build goals and save a note. What are your monthly tiers?'},
            {'role': 'user', 'content': 'The monthly prices are $79, $149 and $299. Focus on $79 and $149.'},
            {'role': 'assistant', 'content': "I couldn't start that work because I chose an unsupported build type. Nothing was queued."},
            {'role': 'user', 'content': 'Right now you were supposed to explain the pricing math based on the numbers I just gave you.'}],
    }
    failures = []
    async with httpx.AsyncClient(timeout=90) as client:
        for name, messages in cases.items():
            raw = await chief._call_claude(client, system, messages,
                model=chief_models.model_for('voice'), effort=chief_models.effort_for('voice'),
                max_tokens=chief_models.max_tokens_for('voice'), enable_web_search=False,
                read_tools=None, stable_tools=False)
            actions, clean = chief._extract_actions_and_clean(raw)
            print(json.dumps({'case': name, 'answer': clean, 'actions': actions}), flush=True)
            if name == 'correct_to_math':
                if actions or not any(n in clean for n in ('79', '149')):
                    failures.append(name + ': correction must answer supplied prices without writes')
            else:
                types = {a.get('type') for a in actions}
                if not {'create_goal', 'create_growth_objective', 'save_note'} <= types:
                    failures.append(name + ': approved requested artifacts missing')
                if any(a.get('type') == 'submit_work_order' and a.get('kind') == 'goal_setup' for a in actions):
                    failures.append(name + ': unsupported build kind')
    if failures:
        raise AssertionError('; '.join(failures))

if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--live', action='store_true')
    if not parser.parse_args().live:
        parser.error('--live is required; this calls the configured provider')
    asyncio.run(main())
