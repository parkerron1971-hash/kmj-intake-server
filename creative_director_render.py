"""Image-provider rendering and its usage accounting, separate from LLM planning."""
import base64
import os
import image_studio as images


async def render(client, row, prompt, raw_refs):
    from creative_director import guard
    await guard(row['business_id'])
    payload = {k: row[k] for k in ('model', 'quality', 'size')}
    payload.update(prompt=prompt, n=1, output_format='png')
    headers = {'Authorization': 'Bearer ' + os.environ.get('OPENAI_API_KEY', '')}
    if raw_refs:
        response = await client.post('https://api.openai.com/v1/images/edits', headers=headers, data=payload,
            files=[('image[]', (f'reference-{i}.png', raw, 'image/png')) for i, raw in enumerate(raw_refs)])
    else:
        response = await client.post('https://api.openai.com/v1/images/generations', headers=headers, json=payload)
    if not response.is_success:
        raise images.provider_error(response, row['model'])
    data = response.json(); usage = data.get('usage') or {}
    cost = images.image_cost(usage)
    estimate = cost if cost is not None else (usage.get('input_tokens', 0)*8 + usage.get('output_tokens', 0)*30)/1_000_000
    decoded = False
    try:
        raw = images.normalize_image(base64.b64decode(data['data'][0]['b64_json'], validate=True))
        decoded = True
    finally:
        # Record a returned paid render even if decoding, storage or review fails.
        await images.log_api_usage(endpoint='/platform/chief/director/render', model=row['model'],
            business_id=row['business_id'], input_tokens=usage.get('input_tokens', 0), output_tokens=usage.get('output_tokens', 0),
            task_type='image_generation', cost_cents_override=estimate*100,
            units=images.image_units(row['quality']) if decoded else 0, ok=decoded)
    return raw, usage, cost

