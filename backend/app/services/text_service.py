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
    'tender':    'нежный и тёплый (как у Туве Янссон в Муми-троллях)',
    'magical':   'волшебный и сказочный (как у Астрид Линдгрен)',
    'magic':     'волшебный и сказочный (как у Астрид Линдгрен)',
    'adventure': 'приключенческий (как у Роальда Даля)',
    'nature':    'про природу и живой мир (как у Сетона-Томпсона)',
    'space':     'космический и фантастический (как у Кира Булычёва)',
    'epic':      'эпический (как у Корнелии Функе)',
}

_STYLE_WORDS_RE = re.compile(
    r'\b(magical|tender|adventure|epic|fairy[\s_]?tale|magic|nature|space)\b', re.IGNORECASE
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


def _prompt(payload: dict) -> str:
    style_ru = STYLE_NAMES_RU.get(payload['style'], payload['style'])
    gender = payload['gender']
    age = payload['age']
    name = payload['child_name']
    episode = payload['episode_number']

    if gender == 'male':
        gender_hint = (
            'Главный герой — МАЛЬЧИК. Строго используй мужской род во всех глаголах и прилагательных: '
            '"он пошёл", "он увидел", "он решил", "он улыбнулся", "смелый", "добрый".'
        )
        gender_word = 'boy'
    elif gender == 'female':
        gender_hint = (
            'Главный герой — ДЕВОЧКА. Строго используй женский род во всех глаголах и прилагательных: '
            '"она пошла", "она увидела", "она решила", "она улыбнулась", "смелая", "добрая".'
        )
        gender_word = 'girl'
    else:
        gender_hint = 'Пол нейтральный — используй только имя, избегай глаголов с родовой формой.'
        gender_word = 'child'

    # Child preferences for personalization
    animal = payload.get('favorite_animal') or 'кот'
    color = payload.get('favorite_color') or 'синий'
    hobby = payload.get('hobby') or 'рисование'
    place = payload.get('favorite_place') or 'лес'

    # Serial story context
    prev_memory = payload.get('previous_memory') or {}
    prev_recap = payload.get('previous_recap') or []
    parent_note = payload.get('parent_note') or 'нет'

    is_continuation = episode > 1 and (prev_memory or prev_recap)

    if is_continuation:
        continuation_block = (
            f'ПРОДОЛЖЕНИЕ СЕРИИ (эпизод №{episode}):\n'
            f'Предыдущие события (коротко): {json.dumps(prev_recap, ensure_ascii=False)}\n'
            f'Мир и персонажи: {json.dumps(prev_memory, ensure_ascii=False)}\n'
            'ОБЯЗАТЕЛЬНО: начни с отсылки к событиям прошлого эпизода, '
            'развивай тех же союзников и мир, герой встречает новые и бо́льшие испытания, '
            'его способности и опыт растут. Увеличь character_level на 1.\n'
        )
    else:
        continuation_block = f'Первый эпизод серии. Создай уникальный волшебный мир с именем (world_name).\n'

    return (
        'Ты мастер детской литературы мирового уровня. '
        'Твоя задача — создать персональную сказку, сочетающую лучшее от великих авторов: '
        'живые характеры и тёплый юмор Астрид Линдгрен, неожиданные повороты и богатое воображение Роальда Даля, '
        'уютный философский мир Туве Янссон и глубокий магический реализм Корнелии Функе.\n\n'
        'Верни СТРОГО JSON без markdown-обёртки, в точном формате:\n'
        '{"title":"...","story_text":"...","image_prompts":["...","...","...","...","..."],'
        '"recap":["...", "..."],'
        '"memory":{"world_name":"...","world_state":{"locations":[],"artifacts":[],"resolved":[]}'
        ',"character_traits":{"courage":"...","kindness":"...","special_power":"..."},'
        '"character_level":1,"allies":[],"open_threads":[]},'
        '"next_hook":"..."}\n\n'
        f'ГЕРОЙ: {name}, {age} лет. {gender_hint}\n'
        f'СТИЛЬ: {style_ru}. ЭПИЗОД №{episode}.\n\n'
        f'{continuation_block}\n'
        f'ПРЕДПОЧТЕНИЯ РЕБЁНКА (ОБЯЗАТЕЛЬНО включи в сюжет — это создаёт вау-эффект!):\n'
        f'• Любимое животное: "{animal}" — должно стать ключевым персонажем или волшебным союзником\n'
        f'• Любимый цвет: "{color}" — используй в описаниях магии, одежды, волшебных предметов\n'
        f'• Любимое занятие: "{hobby}" — покажи как особую способность или суперсилу героя в нужный момент\n'
        f'• Любимое место: "{place}" — там происходит важнейшее событие сказки\n\n'
        f'ПОЖЕЛАНИЕ РОДИТЕЛЯ: {parent_note}\n\n'
        'ТРЕБОВАНИЯ К ТЕКСТУ:\n'
        '1) story_text — СТРОГО 7000–9000 символов (полноценная сказка на 15–20 минут чтения вслух)\n'
        '2) Структура: яркое начало (захватывает с первой фразы) → 4–5 развёрнутых приключений '
        '→ кульминация (самый напряжённый момент) → развязка с ненавязчивой моралью\n'
        '3) Каждая глава начинается с "Глава [порядковый номер словами]. [Название]"\n'
        '4) Диалоги живые, с характером персонажей, через тире; минимум 10–12 реплик\n'
        '5) Все четыре предпочтения ребёнка играют сюжетную роль — не просто упоминаются\n'
        '6) Герой проявляет настоящий характер: смелость, доброту, смекалку, иногда страх или сомнение\n'
        '7) Текст разбит на абзацы двойным переносом строки \\n\\n\n\n'
        'ТРЕБОВАНИЯ К IMAGE PROMPTS (5 штук на английском, 18–25 слов каждый):\n'
        f'[0] WORLD SHOT: atmospheric panoramic view of the magical world/location — NO characters, wide establishing shot, rich details\n'
        f'[1] DISCOVERY: {age}-year-old {gender_word} named {name} discovering something magical for the first time, wonder on face, medium shot\n'
        f'[2] CHALLENGE: dramatic tense moment, the main obstacle or danger, dynamic angle, intense atmosphere\n'
        f'[3] HELPER: {animal} as magical companion or ally, expressive close-up, magical glow, detailed\n'
        f'[4] TRIUMPH: {name} celebrating victory, wide joyful shot, warm golden light, triumphant expression\n'
        'Все 5 промптов ВИЗУАЛЬНО РАЗНЫЕ: разные планы, освещение, акценты. Добавляй: "children\'s book illustration, watercolor style, warm colors, safe for children, no text"'
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
            'temperature': 0.85,
            'max_tokens': 6000,
            'response_format': {'type': 'json_object'},
        },
        timeout=120,
    )
    response.raise_for_status()
    raw = response.json()['choices'][0]['message']['content']
    return json.loads(raw)


def _template_fallback(payload: dict) -> dict:
    """Fallback story when AI is unavailable. Uses child preferences."""
    name = payload['child_name']
    gender = payload.get('gender', 'neutral')
    style = payload.get('style', 'magical')
    age = payload.get('age', 7)
    episode = payload.get('episode_number', 1)
    animal = payload.get('favorite_animal') or 'кот'
    color = payload.get('favorite_color') or 'синий'
    hobby = payload.get('hobby') or 'рисование'
    place = payload.get('favorite_place') or 'лес'

    # Gender-specific verb forms
    if gender == 'female':
        vyshel = 'вышла'; poshel = 'пошла'; uvidel = 'увидела'; skazal = 'сказала'
        nashel = 'нашла'; vernulsya = 'вернулась'; stal = 'стала'; reshil = 'решила'
        podoshel = 'подошла'; uslyshal = 'услышала'; podnyal = 'подняла'; doshel = 'дошла'
        zametil = 'заметила'; pobezhal = 'побежала'; ponyal = 'поняла'
        ulybнulsya = 'улыбнулась'; vzyal = 'взяла'; byl = 'была'; znal = 'знала'
        hotel = 'хотела'; pron = 'она'; pron_gen = 'её'; pron_dat = 'ей'
        g_suf = 'а'; g_adj = 'ая'
    else:
        vyshel = 'вышел'; poshel = 'пошёл'; uvidel = 'увидел'; skazal = 'сказал'
        nashel = 'нашёл'; vernulsya = 'вернулся'; stal = 'стал'; reshil = 'решил'
        podoshel = 'подошёл'; uslyshal = 'услышал'; podnyal = 'поднял'; doshel = 'дошёл'
        zametil = 'заметил'; pobezhal = 'побежал'; ponyal = 'понял'
        ulybнulsya = 'улыбнулся'; vzyal = 'взял'; byl = 'был'; znal = 'знал'
        hotel = 'хотел'; pron = 'он'; pron_gen = 'его'; pron_dat = 'ему'
        g_suf = ''; g_adj = 'ый'

    style_titles = {
        'magic': f'и Тайна {color.capitalize()} Звезды',
        'magical': f'и Тайна {color.capitalize()} Звезды',
        'adventure': 'и Остров Потерянных Карт',
        'nature': 'и Говорящий Родник',
        'space': 'и Звёздный Маяк',
        'tender': f'и Серебрян{g_adj} {animal.capitalize()}',
        'epic': 'и Меч Рассвета',
    }
    ep_suffix = f' (Эпизод {episode})' if episode > 1 else ''
    title = f'{name} {style_titles.get(style, "и Волшебное Приключение")}{ep_suffix}'

    text = (
        f"Глава первая. Необычное утро в {place}\n\n"
        f"В то утро {place} выглядел{'' if place.endswith('а') else 'о'} по-особенному. "
        f"{name} {vyshel} из дома и сразу {uvidel}: вся трава переливается {color}ными огоньками, "
        f"будто кто-то рассыпал тысячи крохотных звёзд прямо на землю.\n\n"
        f"— Вот это да! — {skazal} {name} и {podoshel} ближе.\n\n"
        f"Огоньки не гасли. Они прыгали с травинки на травинку и складывались в узор — "
        f"настоящую стрелку! Стрелка указывала вглубь {place}а.\n\n"
        f"Вдруг из кустов {uslyshal} {name} знакомый звук. Там сидел{'' if animal[-1] in 'аяь' else ''} "
        f"маленьк{g_adj if animal[-1] not in 'аяь' else 'ая'} {animal} с блестящими глазами.\n\n"
        f"— Наконец-то! — {skazal} {animal.capitalize()} человеческим голосом. "
        f"— Я так долго ждал{'а' if animal[-1] in 'аяь' else ''} тебя, {name}. "
        f"Ты нужен{'а' if gender == 'female' else ''} нам — только ты можешь спасти {place}!\n\n"
        f"{name} широко раскрыл{g_suf} глаза. {animal.capitalize()} умел говорить!\n\n"

        f"Глава вторая. Первое испытание\n\n"
        f"Пока {name} и {animal} шли по {place}у, {animal} объяснял{'а' if animal[-1] in 'аяь' else ''}: "
        f"злой Серый Туман похитил Хрустальный Камень, который согревал весь {place}. "
        f"Без него здесь скоро станет холодно и темно. "
        f"Но Туман спрятал камень за тремя загадочными дверями.\n\n"
        f"Первая дверь оказалась из чистого льда. На ней было написано: "
        f"«Открою тому, кто умеет создавать красоту».\n\n"
        f"— {hobby.capitalize()}! — догадал{g_suf}ся {name}. — Это же про меня!\n\n"
        f"{name} взял{g_suf} найденный рядом уголёк и начал{g_suf} рисовать прямо на льду. "
        f"Сначала — маленькое солнышко. Потом — цветы. Потом — силуэты деревьев {place}а. "
        f"Под каждой линией лёд теплел, трескался и таял. Вскоре дверь открылась!\n\n"
        f"— Молодец{'а' if gender == 'female' else ''}! — восхитился {animal}. — Так я и знал{'а' if animal[-1] in 'аяь' else ''}!\n\n"

        f"Глава третья. Тайна {color.capitalize()} Реки\n\n"
        f"За первой дверью оказалась {color}ная река. Она текла в никуда и нигде не начиналась — "
        f"просто была. По берегу ходил старый Ёж с блокнотом и что-то бормотал себе под нос.\n\n"
        f"— Вторая дверь под водой, — {skazal} Ёж, не поднимая глаз. "
        f"— Но переплыть реку нельзя: она слишком холодная. Нужно найти мост.\n\n"
        f"— А где мост? — спросил{g_suf} {name}.\n\n"
        f"— Его нет. Его нужно построить из слов.\n\n"
        f"Ёж объяснил: эта река слышит только добрые слова. Чем добрее слова — "
        f"тем больше камней поднимается со дна.\n\n"
        f"{name} {podoshel} к воде и начал{g_suf} говорить. Про маму и папу. "
        f"Про {animal}а, который такой смелый. Про {place}, который такой красивый. "
        f"Про то, как хорошо, когда все счастливы.\n\n"
        f"С каждым словом из воды поднимался камень. Через несколько минут {name} "
        f"{poshel} по каменному мосту, как по ступенькам!\n\n"

        f"Глава четвёртая. Серый Туман\n\n"
        f"Третья дверь охранял сам Серый Туман. Он был огромным — до самых облаков — "
        f"и говорил голосом, похожим на зимний ветер:\n\n"
        f"— Уходите! Камень мой! Я хочу, чтобы везде было серо и холодно!\n\n"
        f"— Почему? — спокойно спросил{g_suf} {name}.\n\n"
        f"Туман замолчал. Никто раньше не спрашивал «почему».\n\n"
        f"— Потому что... — начал Туман медленнее. — Потому что когда всё серое, "
        f"меня не видно. А когда вокруг {color}ные цветы и яркий свет — я становлюсь совсем маленьким...\n\n"
        f"— Ты просто одинок, — {ponyal} {name}. — Тебе нужен друг.\n\n"
        f"{name} {vzyal} {pron_gen} рисунок — тот самый, что нарисовал{g_suf} на льду — "
        f"и протянул Туману. На рисунке был нарисован Туман, но красивый: "
        f"с {color}ными звёздами внутри.\n\n"
        f"Туман долго смотрел на рисунок. Потом тихо {skazal}:\n\n"
        f"— Никто ещё не видел во мне красоты...\n\n"
        f"И медленно отступил, открывая третью дверь.\n\n"

        f"Глава пятая. Свет возвращается\n\n"
        f"За дверью лежал Хрустальный Камень — тёплый, {color}ного цвета, "
        f"размером с два кулака. {name} {podnyal} его, и {place} сразу изменился: "
        f"трава стала ярче, воздух — теплее, {color}ные огоньки запрыгали повсюду.\n\n"
        f"— Ты сделал{g_suf} это! — закричал{g_suf} {animal} и {pobezhal} к {name}. "
        f"— Ты спас{g_suf} {place}!\n\n"
        f"{name} {zasmeyal_suf} — и поднял{g_suf} {animal}а на руки.\n\n"
        f"— Мы сделали это вместе. Ты, я и... даже Туман помог в конце.\n\n"
        f"Когда {name} {vernulsya} домой, в кармане лежал маленький {color}ный камушек — "
        f"подарок от {animal}а. Каждый раз, когда {name} {zametil} его, "
        f"{pron} {ulybнulsya}: настоящие друзья находятся там, где их меньше всего ждёшь.\n\n"
        f"Мораль: Смелость — это не когда не страшно. "
        f"Смелость — это когда страшно, но ты всё равно идёшь вперёд. "
        f"И ещё: иногда в самом хмуром и сером человеке прячется тот, кто просто хочет дружить."
    ).replace('{zasmeyal_suf}', 'засмеял' + g_suf + 'ся' if gender != 'female' else 'засмеялась')

    # Fix the template string issue
    text = text.replace(
        f"{name} {{zasmeyal_suf}} — и поднял{g_suf} {animal}а на руки.",
        f"{name} {'засмеялась' if gender == 'female' else 'засмеялся'} — и поднял{g_suf} {animal}а на руки."
    )

    child_desc = f"{'girl' if gender == 'female' else 'boy'}, age {age}, brown curly hair, adventurous expression"
    image_prompts = [
        f"children's book illustration, wide panoramic view of magical {place}, glowing {color} lights on grass, "
        f"enchanted atmosphere, no characters, warm golden light, watercolor style, detailed",
        f"children's book illustration, {child_desc}, discovering sparkling {color} lights in magical {place}, "
        f"wonder and curiosity on face, medium shot, soft morning light, watercolor style",
        f"children's book illustration, {child_desc}, drawing on icy door with charcoal, "
        f"creative and determined, dramatic angle, cool blue light turning warm, watercolor style",
        f"children's book illustration, cute magical {animal} with shining eyes, speaking, expressive, "
        f"close-up portrait, magical {color} glow around, forest background, watercolor style",
        f"children's book illustration, {child_desc}, holding glowing {color} crystal with both hands, "
        f"triumphant joyful expression, magical {animal} jumping nearby, wide shot, golden warm light, watercolor style",
    ]

    prev_recap = payload.get('previous_recap') or []
    recap_items = [
        f'{name} спас{"ла" if gender == "female" else ""} {place} от Серого Тумана.',
        f'Нашёл{"а" if gender == "female" else ""} Хрустальный Камень за тремя дверями.',
        f'Подружился{"ась" if gender == "female" else ""} с волшебным {animal}ом.',
    ]

    return {
        'title': title,
        'story_text': text,
        'image_prompts': image_prompts,
        'recap': recap_items,
        'memory': {
            'world_name': f'Волшебный {place.capitalize()}',
            'world_state': {
                'locations': [place, f'{color}ная река', 'Ледяная дверь'],
                'artifacts': ['Хрустальный Камень', f'{color}ный камушек'],
                'resolved': ['Серый Туман помирился', 'Хрустальный Камень возвращён'],
            },
            'character_traits': {
                'courage': 'сильная' if gender == 'female' else 'сильный',
                'kindness': 'главная черта',
                'special_power': f'умение {hobby}а как суперсила',
            },
            'character_level': episode,
            'allies': [f'волшебный {animal}', 'Серый Туман (бывший враг)'],
            'open_threads': [f'{animal.capitalize()} намекнул{"а" if animal[-1] in "аяь" else ""} на новое приключение'],
        },
        'next_hook': (
            f'Той ночью {name} увидел{"а" if gender == "female" else ""} сон: '
            f'{animal.capitalize()} бежал{"а" if animal[-1] in "аяь" else ""} по серебристой дороге '
            f'и оборачивал{"ась" if animal[-1] in "аяь" else "ся"}, зовя за собой...'
        ),
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

    story = _strip_english_style_words(result['story_text'])
    result['story_text'] = story
    return result
