import json

import httpx

from ..config import get_settings

settings = get_settings()


STYLE_BY_AGE = {
    range(2, 5): 'tender',
    range(5, 8): 'magical',
    range(8, 11): 'adventure',
    range(11, 13): 'epic',
}


def choose_style(age: int, preferred_style: str) -> str:
    if preferred_style and preferred_style != 'auto':
        return preferred_style
    for age_range, style in STYLE_BY_AGE.items():
        if age in age_range:
            return style
    return 'magical'


def _prompt(payload: dict) -> str:
    return (
        'Ты детский писатель. Сгенерируй безопасную историю на русском языке. '
        'Верни строго JSON без markdown в формате: '
        '{"title":"...","story_text":"...","recap":["..."],'
        '"memory":{"world_state":{},"character_traits":{},"open_threads":[]},'
        '"next_hook":"..."}. '
        f"Данные ребёнка: имя={payload['child_name']}, возраст={payload['age']}, пол={payload['gender']}. "
        f"Стиль: {payload['style']}. Номер эпизода: {payload['episode_number']}. "
        f"Краткая память прошлого: {json.dumps(payload.get('previous_memory', {}), ensure_ascii=False)}. "
        f"Краткий recap прошлых эпизодов: {json.dumps(payload.get('previous_recap', []), ensure_ascii=False)}. "
        f"Заметка родителя: {payload.get('parent_note') or 'нет'}."
        'История должна быть 700-1100 символов, дружелюбная, без насилия.'
    )


def _call_openrouter(payload: dict) -> dict:
    if not settings.openrouter_api_key:
        raise RuntimeError('OPENROUTER_API_KEY is not configured')

    response = httpx.post(
        'https://openrouter.ai/api/v1/chat/completions',
        headers={
            'Authorization': f'Bearer {settings.openrouter_api_key}',
            'Content-Type': 'application/json',
        },
        json={
            'model': settings.openrouter_model,
            'messages': [{'role': 'user', 'content': _prompt(payload)}],
            'temperature': 0.7,
            'response_format': {'type': 'json_object'},
        },
        timeout=60,
    )
    response.raise_for_status()
    raw = response.json()['choices'][0]['message']['content']
    return json.loads(raw)


def _template_fallback(payload: dict) -> dict:
    title = f"{payload['child_name']} и сияющий компас"
    style = payload['style']
    text = (
        f"В этот вечер {payload['child_name']} заметил(а), что звёзды шепчут особенно {style}. "
        'На дорожке у дома появился маленький компас, который показывал не на север, а на добрые дела. '
        'Герой помог светлячкам найти дом, успокоил ветер в парке и научился слушать своё сердце. '
        'К концу прогулки город засиял тёплым светом, а рядом появились новые друзья.'
    )
    return {
        'title': title,
        'story_text': text,
        'recap': ['Герой нашёл волшебный компас.', 'Сделал три добрых дела.', 'Нашёл новых друзей.'],
        'memory': {
            'world_state': {'artifact': 'сияющий компас'},
            'character_traits': {'courage': 'растёт', 'kindness': 'сильная'},
            'open_threads': ['куда приведёт компас дальше'],
        },
        'next_hook': 'Но это только начало: компас вдруг засветился и указал путь к лунному мосту...',
    }


def generate_story_payload(payload: dict) -> dict:
    payload['style'] = choose_style(payload['age'], payload.get('style', 'auto'))
    provider = settings.text_provider

    if provider == 'openrouter':
        try:
            return _call_openrouter(payload)
        except Exception:
            if settings.backup_text_provider == 'template':
                return _template_fallback(payload)
            raise

    if provider == 'template':
        return _template_fallback(payload)

    raise ValueError(f'Unsupported text provider: {provider}')
