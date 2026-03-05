import json
import re

import httpx

from ..config import get_settings

settings = get_settings()


STYLE_BY_AGE = {
    range(2, 5): 'tender',
    range(5, 8): 'magical',
    range(8, 11): 'adventure',
    range(11, 13): 'epic',
}

STYLE_NAMES_RU = {
    'tender':    'нежный и тёплый',
    'magical':   'волшебный и сказочный',
    'adventure': 'приключенческий',
    'epic':      'эпический',
}

STYLE_ADVERBS_RU = {
    'tender':    'нежно',
    'magical':   'волшебно',
    'adventure': 'таинственно',
    'epic':      'торжественно',
}

_STYLE_WORDS_RE = re.compile(
    r'\b(magical|tender|adventure|epic|fairy[\s_]?tale)\b', re.IGNORECASE
)


def choose_style(age: int, preferred_style: str) -> str:
    if preferred_style and preferred_style != 'auto':
        return preferred_style
    for age_range, style in STYLE_BY_AGE.items():
        if age in age_range:
            return style
    return 'magical'


def _strip_english_style_words(text: str) -> str:
    return _STYLE_WORDS_RE.sub('', text)


def _format_paragraphs(text: str, sentences_per_para: int = 3) -> str:
    parts = re.split(r'(?<=[.!?])\s+', text.strip())
    paragraphs = []
    for i in range(0, len(parts), sentences_per_para):
        chunk = ' '.join(parts[i:i + sentences_per_para])
        if chunk:
            paragraphs.append(chunk)
    return '\n\n'.join(paragraphs)


def _prompt(payload: dict) -> str:
    style_ru = STYLE_NAMES_RU.get(payload['style'], payload['style'])
    return (
        'Ты детский писатель. Сгенерируй безопасную историю на русском языке. '
        'Верни строго JSON без markdown в формате: '
        '{"title":"...","story_text":"...","recap":["..."],'
        '"memory":{"world_state":{},"character_traits":{},"open_threads":[]},'
        '"next_hook":"..."}. '
        f"Данные ребёнка: имя={payload['child_name']}, возраст={payload['age']}, пол={payload['gender']}. "
        f"Стиль: {style_ru}. Номер эпизода: {payload['episode_number']}. "
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
    style_adv = STYLE_ADVERBS_RU.get(payload['style'], STYLE_NAMES_RU.get(payload['style'], payload['style']))
    text = (
        f"В этот вечер {payload['child_name']} заметил(а), что звёзды шепчут особенно {style_adv}. "
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
            result = _call_openrouter(payload)
        except Exception:
            if settings.backup_text_provider == 'template':
                result = _template_fallback(payload)
            else:
                raise
    elif provider == 'template':
        result = _template_fallback(payload)
    else:
        raise ValueError(f'Unsupported text provider: {provider}')

    result['story_text'] = _format_paragraphs(_strip_english_style_words(result['story_text']))
    return result
