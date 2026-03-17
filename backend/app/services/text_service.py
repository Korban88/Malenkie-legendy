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

# Literary guides per style — injected into the prompt
_STYLE_LITERARY_GUIDES = {
    'magical': (
        'ЛИТЕРАТУРНЫЕ ОРИЕНТИРЫ — волшебный стиль:\n'
        '• Астрид Линдгрен: герой делает невозможное с полной серьёзностью; юмор возникает из столкновения детской логики и мира взрослых\n'
        '• Льюис Кэрролл: логика волшебного мира внутренне последовательна — правила странные, но они соблюдаются строго\n'
        '• Туве Янссон: за уютом прячется тихая тревога; опасность встречается с достоинством, не с паникой\n'
        'ТЕХНИКА: неожиданное решение — проблема решается НЕ силой и НЕ очевидной логикой; первое впечатление о злодее оказывается неверным'
    ),
    'magic': (
        'ЛИТЕРАТУРНЫЕ ОРИЕНТИРЫ — волшебный стиль:\n'
        '• Астрид Линдгрен: герой делает невозможное с полной серьёзностью; юмор возникает из столкновения детской логики и мира взрослых\n'
        '• Льюис Кэрролл: логика волшебного мира внутренне последовательна — правила странные, но они соблюдаются строго\n'
        '• Туве Янссон: за уютом прячется тихая тревога; опасность встречается с достоинством, не с паникой\n'
        'ТЕХНИКА: неожиданное решение — проблема решается НЕ силой и НЕ очевидной логикой; первое впечатление о злодее оказывается неверным'
    ),
    'adventure': (
        'ЛИТЕРАТУРНЫЕ ОРИЕНТИРЫ — приключенческий стиль:\n'
        '• Роальд Даль: мир несправедлив, взрослые часто ошибаются, но дети побеждают хитростью и воображением; тёмный юмор допустим\n'
        '• Жюль Верн: детальные описания создают ощущение реальности невероятного; у каждого приключения есть механика\n'
        '• Роберт Л. Стивенсон: атмосфера важнее экшена; физические ощущения (ветер, усталость, запахи) делают мир живым\n'
        'ТЕХНИКА: в каждой главе что-то идёт НЕ ТАК, как планировал герой; каждый союзник имеет свои интересы'
    ),
    'tender': (
        'ЛИТЕРАТУРНЫЕ ОРИЕНТИРЫ — нежный стиль:\n'
        '• А.А. Милн (Винни-Пух): нет настоящих злодеев — только маленькие катастрофы и большая дружба; диалоги как у Пятачка и Пуха\n'
        '• Туве Янссон: философская глубина в простых вещах; маленькие события имеют большой смысл\n'
        '• Самуил Маршак: ритм и музыкальность прозы; повторяющиеся фразы как рефрен\n'
        'ТЕХНИКА: конфликт решается пониманием, а не борьбой; герой учится через наблюдение, а не через поучения'
    ),
    'nature': (
        'ЛИТЕРАТУРНЫЕ ОРИЕНТИРЫ — природный стиль:\n'
        '• Сетон-Томпсон: у каждого животного своя личность, своя логика; природа не добра и не зла — она честна\n'
        '• Редьярд Киплинг: законы природы как нравственный кодекс; у мира джунглей своя справедливость\n'
        '• Виталий Бианки: точные детали мира природы делают чудо достоверным\n'
        'ТЕХНИКА: животное-спутник думает иначе, чем человек — это источник мудрости и конфликта одновременно'
    ),
    'space': (
        'ЛИТЕРАТУРНЫЕ ОРИЕНТИРЫ — космический стиль:\n'
        '• Кир Булычёв (Алиса Селезнёва): будущее оптимистично; дети равноправны со взрослыми; юмор от несоответствия огромного космоса и бытовых мелочей\n'
        '• Аркадий и Борис Стругацкие: этические дилеммы без простых ответов; технология имеет цену\n'
        'ТЕХНИКА: инопланетное или космическое явление объясняется через детское восприятие — наивно, но точно'
    ),
    'epic': (
        'ЛИТЕРАТУРНЫЕ ОРИЕНТИРЫ — эпический стиль:\n'
        '• Корнелия Функе: магия имеет цену; победа достаётся через настоящую жертву; мир живёт своей жизнью\n'
        '• К.С. Льюис (Нарния): за каждым приключением скрывается более глубокий смысл; союзники могут предать\n'
        '• Дж.Р.Р. Толкин: мир детально проработан до начала истории; у каждого места есть история\n'
        'ТЕХНИКА: герой меняется необратимо — к финалу он уже не тот, кем был в начале'
    ),
}

# Purpose-driven story hints
_PURPOSE_HINTS = {
    'brave': (
        'ЦЕЛЬ СКАЗКИ — помочь ребёнку стать смелее.\n'
        'Герой несколько раз отступает перед страхом — это нормально и показывается честно. '
        'Но каждый маленький шаг навстречу страху имеет последствия и награду. '
        'Смелость — не отсутствие страха, а действие вопреки ему. '
        'Финал: герой делает то, что раньше казалось невозможным — и удивляется, что смог.'
    ),
    'fear': (
        'ЦЕЛЬ СКАЗКИ — помочь справиться со страхом.\n'
        'В центре сюжета — конкретный страх (темнота, одиночество, неизвестность). '
        'Страх персонифицирован как персонаж — и оказывается не таким страшным, каким казался. '
        'Герой не "побеждает" страх — он понимает его природу, и страх теряет власть.'
    ),
    'creativity': (
        'ЦЕЛЬ СКАЗКИ — раскрыть творческий потенциал ребёнка.\n'
        'Герой побеждает не силой и не хитростью — только воображением и нестандартным мышлением. '
        'Там, где все ищут очевидное решение, герой видит неожиданную связь между вещами. '
        'Творчество показывается как реальная суперсила, меняющая мир вокруг.'
    ),
    'friendship': (
        'ЦЕЛЬ СКАЗКИ — научить дружить.\n'
        'Герой в начале одинок или не умеет открываться другим. '
        'Дружба завоёвывается поступками, а не словами — герой должен рискнуть и оказаться уязвимым. '
        'Новый друг тоже несовершенен — и это делает дружбу настоящей.'
    ),
    'confidence': (
        'ЦЕЛЬ СКАЗКИ — помочь поверить в себя.\n'
        'Герой в начале недооценивает себя — и есть конкретная причина для этого. '
        'Через испытания герой открывает в себе скрытый потенциал — не потому что кто-то сказал "ты можешь", '
        'а потому что он сам убедился в этом на деле. '
        'Самый важный момент: герой принимает решение сам, без подсказок.'
    ),
    'bedtime': (
        'ЦЕЛЬ СКАЗКИ — уютная сказка на ночь.\n'
        'Приключение настоящее, но не пугающее. Темп замедляется к финалу. '
        'Финальные сцены тёплые, домашние, успокаивающие. '
        'Последние абзацы должны создавать ощущение безопасности и покоя.'
    ),
}

_IMG_STYLE_FOR_PROMPT = {
    'ghibli':     'Studio Ghibli style, soft anime-inspired hand-painted watercolor, gentle whimsical atmosphere',
    'disney':     'Disney fairy tale style, vibrant cheerful colors, cute rounded characters, magical sparkles',
    'pixar':      'Pixar 3D animation style, richly detailed, warm cinematic lighting, expressive characters',
    'watercolor': 'soft watercolor illustration, dreamy pastel tones, gentle brushstrokes, traditional art',
    'cartoon':    'cartoon illustration, bold black outlines, bright saturated colors, playful fun style',
    'storybook':  "classic children's storybook illustration, detailed ink and watercolor, warm cozy feeling",
    'soviet':     'Soviet Soyuzmultfilm animation style exactly as in Cheburashka 1966, classic USSR cartoon, thick clean outlines, warm muted earthy palette, flat 2D, 1970s aesthetic',
}

# Animal visual descriptions for character consistency in image prompts
_ANIMAL_VISUAL: dict[str, str] = {
    'кот':        'small tabby cat with bright amber eyes and striped grey-orange fur',
    'кошка':      'small tabby cat with bright amber eyes and striped grey-orange fur',
    'котёнок':    'tiny fluffy kitten with wide bright eyes and soft striped tabby pattern',
    'пёс':        'medium friendly dog with floppy ears, warm brown eyes, and golden-tan fur',
    'собака':     'medium friendly dog with floppy ears, warm brown eyes, and golden-tan fur',
    'щенок':      'small fluffy puppy with big soft eyes and golden-tan fur',
    'лиса':       'bright orange fox with a bushy white-tipped tail and sharp green eyes',
    'лисёнок':    'small bright orange fox kit with oversized pointy ears and curious green eyes',
    'заяц':       'fluffy grey rabbit with long upright ears and bright curious eyes',
    'зайчик':     'small fluffy white rabbit with long upright ears and curious bright eyes',
    'кролик':     'fluffy white rabbit with long upright ears and bright curious eyes',
    'медведь':    'large friendly brown bear with a round face and warm dark eyes',
    'медвежонок': 'small plump teddy-bear cub with round ears and warm dark eyes',
    'волк':       'silvery-grey wolf with piercing yellow eyes and a flowing bushy tail',
    'дракон':     'small friendly dragon with emerald-green scales, tiny wings, and a cheerful expression',
    'единорог':   'small white unicorn with a shimmering silver horn, flowing mane, and gentle blue eyes',
    'черепаха':   'small green tortoise with a patterned shell and wise bright eyes',
    'черепашка':  'tiny green tortoise with a patterned shell and wise bright eyes',
    'попугай':    'bright tropical parrot with vivid red-green-blue feathers and a curious tilted head',
    'попугайчик': 'small bright parakeet with vivid green-yellow feathers and curious round eyes',
    'сова':       'round fluffy owl with large amber eyes and spotted brown-cream feathers',
    'белка':      'small rusty-red squirrel with a huge bushy tail and bright black eyes',
    'ёжик':       'tiny hedgehog with soft brown spines, a pink nose, and small curious eyes',
    'лошадь':     'chestnut horse with a flowing dark mane, warm brown eyes, and a graceful build',
    'пони':       'small chestnut pony with a flowing mane, warm eyes, and a friendly expression',
    'слон':       'small friendly elephant with large floppy ears, long trunk, and wise gentle eyes',
    'обезьяна':   'small golden-brown monkey with big bright eyes and a long curling tail',
    'тигр':       'young tiger with bright orange-and-black striped fur and vivid green eyes',
    'хомяк':      'small round hamster with puffy cheeks, tiny paws, and bright curious eyes',
}

_STYLE_WORDS_RE = re.compile(
    r'\b(magical|tender|adventure|epic|fairy[\s_]?tale|magic|nature|space)\b', re.IGNORECASE
)
_ENGLISH_WORDS_RE = re.compile(r'(?<![а-яёА-ЯЁ])\b[a-zA-Z]{2,}\b(?![а-яёА-ЯЁ])')


def _build_char_desc(name: str, age: int, gender: str, animal: str = 'кот') -> str:
    """
    Build a SPECIFIC, DETERMINISTIC character description including the animal companion.
    Same name → always same hair/eyes/clothes → DALL-E draws the same child.
    """
    seed = sum(ord(c) for c in name)

    if gender == 'female':
        hair_styles = [
            'long dark brown hair in two braids',
            'short wavy light brown hair with a hairband',
            'long straight black hair tied in a ponytail',
            'curly chestnut hair with a small braid on one side',
        ]
        clothes = [
            'a bright teal jacket and dark blue leggings with white trainers',
            'a red-and-white striped sweater and dark jeans with yellow boots',
            'a cozy orange hoodie and gray skirt with white sneakers',
            'a purple vest over white shirt and dark trousers with pink shoes',
        ]
    else:
        hair_styles = [
            'short neat dark brown hair slightly tousled',
            'short curly black hair',
            'short straight sandy blond hair',
            'short reddish-brown hair with a slight wave',
        ]
        clothes = [
            'a green hooded jacket and dark jeans with white trainers',
            'a red-and-blue plaid shirt and khaki trousers with brown boots',
            'a navy blue sweater and gray cargo pants with orange sneakers',
            'a yellow rain jacket and dark jeans with dark sneakers',
        ]

    eye_colors = ['warm brown', 'hazel', 'bright blue-gray', 'deep green']

    hair = hair_styles[seed % len(hair_styles)]
    eyes = eye_colors[(seed // 3) % len(eye_colors)]
    outfit = clothes[(seed // 7) % len(clothes)]
    gender_word = 'girl' if gender == 'female' else ('boy' if gender == 'male' else 'child')

    animal_key = animal.lower().strip()
    animal_visual = _ANIMAL_VISUAL.get(
        animal_key,
        f'small friendly {animal_key} with bright expressive eyes',
    )

    return (
        f'{age}-year-old {gender_word} with fair pale light skin complexion (European), '
        f'{hair}, {eyes} eyes, wearing {outfit}. '
        f'Constant animal companion: {animal_visual} — always beside the hero, same in every illustration'
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


def _strip_all_english_words(text: str) -> str:
    return _ENGLISH_WORDS_RE.sub('', text)


def _prompt(payload: dict) -> str:
    style_ru = STYLE_NAMES_RU.get(payload['style'], payload['style'])
    gender = payload['gender']
    age = payload['age']
    name = payload['child_name']
    episode = payload['episode_number']
    image_style = payload.get('image_style', 'watercolor')
    purpose = payload.get('purpose', 'bedtime')

    if gender == 'male':
        gender_hint = (
            'Главный герой — МАЛЬЧИК. Строго мужской род: '
            '"он пошёл", "он увидел", "смелый", "добрый".'
        )
        gender_word = 'boy'
    elif gender == 'female':
        gender_hint = (
            'Главный герой — ДЕВОЧКА. Строго женский род: '
            '"она пошла", "она увидела", "смелая", "добрая".'
        )
        gender_word = 'girl'
    else:
        gender_hint = 'Пол нейтральный — используй только имя, избегай глаголов с родовой формой.'
        gender_word = 'child'

    animal = payload.get('favorite_animal') or 'кот'
    color = payload.get('favorite_color') or 'синий'
    hobby = payload.get('hobby') or 'рисование'
    place = payload.get('favorite_place') or 'лес'

    prev_memory = payload.get('previous_memory') or {}
    prev_recap = payload.get('previous_recap') or []
    is_continuation = episode > 1 and (prev_memory or prev_recap)

    if is_continuation:
        continuation_block = (
            f'ПРОДОЛЖЕНИЕ СЕРИИ (эпизод №{episode}):\n'
            f'Предыдущие события: {json.dumps(prev_recap, ensure_ascii=False)}\n'
            f'Мир и персонажи: {json.dumps(prev_memory, ensure_ascii=False)}\n'
            'ОБЯЗАТЕЛЬНО: начни с отсылки к прошлому эпизоду, развивай тех же союзников, '
            'герой встречает новые испытания, его способности растут. Увеличь character_level на 1.\n'
        )
    else:
        continuation_block = 'Первый эпизод. Создай уникальный волшебный мир (world_name).\n'

    literary_guide = _STYLE_LITERARY_GUIDES.get(payload['style'], '')
    purpose_hint = _PURPOSE_HINTS.get(purpose, _PURPOSE_HINTS['bedtime'])

    return (
        'Ты мастер детской литературы мирового уровня. '
        'Твоя задача — написать персональную сказку, неотличимую от работы живого писателя.\n\n'
        'Верни СТРОГО JSON без markdown-обёртки:\n'
        '{"title":"...","story_text":"...","image_prompts":["...x5"],'
        '"recap":["..."],'
        '"memory":{"world_name":"...","world_state":{"locations":[],"artifacts":[],"resolved":[]},'
        '"character_traits":{"courage":"...","kindness":"...","special_power":"..."},'
        '"character_level":1,"allies":[],"open_threads":[]},'
        '"next_hook":"..."}\n\n'
        f'ГЕРОЙ: {name}, {age} лет. {gender_hint}\n'
        f'СТИЛЬ: {style_ru}. ЭПИЗОД №{episode}.\n\n'
        f'{continuation_block}\n'
        f'{literary_guide}\n\n'
        f'{purpose_hint}\n\n'
        'ПРЕДПОЧТЕНИЯ РЕБЁНКА — важны, но вписываются ОРГАНИЧНО:\n'
        f'• Любимое животное: "{animal}" — волшебный союзник с именем, характером и репликами. НЕ ЗАМЕНЯТЬ другим!\n'
        f'• Любимый цвет: "{color}" — используй ТОЛЬКО как 1-2 особые символические детали (не перекрашивай всё)\n'
        f'• Любимое занятие: "{hobby}" — особая способность героя в ключевой момент\n'
        f'• Любимое место: "{place}" — главная локация, описанная подробно и атмосферно\n\n'
        f'ПОЖЕЛАНИЕ РОДИТЕЛЯ: {payload.get("parent_note") or "нет"}\n\n'
        'ТРЕБОВАНИЯ К ТЕКСТУ:\n'
        '1) story_text — СТРОГО 7500–9000 символов. Минимум 15 минут чтения вслух.\n'
        '2) Структура: 5 глав. Каждая — минимум 4–6 абзацев по 3–5 предложений. НЕ СОКРАЩАЙ.\n'
        '3) Глава начинается: "Глава [номер словами]. [Название]"\n'
        '4) ДИАЛОГИ (минимум 12 реплик): персонажи говорят ВОКРУГ темы, не прямолинейно. '
        'Каждый имеет уникальную манеру. Минимум 2 диалога с неожиданным поворотом или двойным смыслом.\n'
        '5) СЮЖЕТ: минимум ОДИН поворот, которого читатель не ожидал. '
        'Проблема решается нестандартно. Деталь из начала возвращается в финале (чеховское ружьё).\n'
        f'6) "{animal}" присутствует от начала до конца с развивающимся характером.\n'
        '7) Абзацы разделены двойным \\n\\n\n\n'
        'ТРЕБОВАНИЯ К IMAGE PROMPTS (РОВНО 6 штук, на английском, 45–60 слов каждый):\n'
        f'КАЖДЫЙ промпт описывает КОНКРЕТНУЮ СЦЕНУ ИЗ ТЕКСТА: кто что делает, где, '
        f'обязательно упомянуть {animal} (что конкретно делает в этой сцене). '
        'НЕЛЬЗЯ описывать внешность героя — она добавится автоматически.\n'
        'КАЖДЫЙ промпт начинается с АКТИВНОГО ГЛАГОЛА. '
        'ОБЯЗАТЕЛЬНО указывай план съёмки: "wide establishing shot" / "medium full-body shot" / '
        '"dynamic wide-angle shot". Герои ДЕЙСТВУЮТ — не стоят, не смотрят в камеру.\n\n'
        f'[0] ОБЛОЖКА: epic wide establishing shot — {name} в самом захватывающем действии '
        f'всей истории, {animal} рядом активно участвует, фон {place}. '
        f'Диагональная динамичная композиция, большое приключение.\n\n'
        f'[1] ГЛАВА 1 — конкретная сцена из текста главы 1: первая встреча {name} с {animal} '
        f'или момент открытия магического мира. Wide establishing shot. '
        f'Конкретное место и действие точно из текста главы 1.\n\n'
        f'[2] ГЛАВА 2 — конкретная сцена из текста главы 2: {name} и {animal} вместе '
        f'преодолевают испытание или препятствие. Medium full-body shot. '
        f'Напряжение в кадре, конкретная локация из текста главы 2.\n\n'
        f'[3] ГЛАВА 3 — конкретная сцена из текста главы 3: неожиданный поворот или открытие. '
        f'{name} и {animal} реагируют на что-то удивительное или пугающее. '
        f'Wide shot, другое место и освещение чем в [2].\n\n'
        f'[4] ГЛАВЫ 4-5 — КУЛЬМИНАЦИЯ: самый напряжённый момент финала из текста. '
        f'{name} и {animal} в решающем действии. Максимальная динамика, '
        f'яркий драматический свет. Dynamic wide-angle shot.\n\n'
        f'[5] ФИНАЛ: wide peaceful shot — {name} и {animal} после победы, '
        f'радость и покой, золотой закатный свет, широкий план {place}а. '
        f'Ощущение завершённого путешествия и открытых горизонтов.\n\n'
        f'КРИТИЧНО: 6 промптов = 6 РАЗНЫХ мест + 6 РАЗНЫХ действий + {animal} в каждом кадре. '
        'Никаких описаний внешности — только сцена, действие, атмосфера!\n\n'
        'КРЮЧОК (next_hook) — НЕ пересказ следующей серии, а ФИЗИЧЕСКАЯ ИНТРИГА:\n'
        '• Неожиданная находка или знак в самый последний момент ("Уже почти дома...")\n'
        '• Один конкретный загадочный элемент БЕЗ объяснения — что-то увидел, услышал, нашёл\n'
        '• Финальная фраза — вопрос или обрыв на полуслове: читатель должен физически '
        'захотеть немедленно узнать продолжение\n'
        '• Последнее предложение ОБЯЗАНО заканчиваться отсылкой к следующей сказке: "...но это уже история следующей сказки!" или "Узнаем в следующий раз!"\n'
        '• Максимум 2-3 предложения. Намёк, тайна и интрига к следующей серии.\n\n'
        'ГРАММАТИКА — ОБЯЗАТЕЛЬНАЯ ПРОВЕРКА КАЖДОГО ПРЕДЛОЖЕНИЯ:\n'
        '• Согласование прилагательных с родом: "Звёздное Сияние" (ср.р.), "Золотой Ветер" (м.р.) — НЕ "Звёздный Сияние"\n'
        '• Конструкция со временем суток: ТОЛЬКО "Одним ясным утром" / "В ясное утро" / "Ранним утром" — НИКОГДА "В один из ясных утра" (это грубая ошибка!)\n'
        '• Числительные + существительные: "два дня", "три часа", "пять минут" — по всем падежам\n'
        '• Деепричастные обороты: субъект деепричастия = субъект глагола. НЕ "Войдя в лес, начался дождь"\n'
        '• Глаголы движения: "пошёл В лес", "вышел ИЗ леса" — предлоги строго по смыслу\n'
        f'• ПОЛ ИМЕНИ ЖИВОТНОГО-СПУТНИКА ({animal}): кличка должна грамматически совпадать с родом существительного. '
        f'Пример: "лошадь" — женский род → кличка "Звёздочка", "Ромашка", "Буря" (не "Ветерок", не "Орёл"). '
        f'"кот" — мужской род → кличка "Рыжик", "Уголёк". '
        f'"собака" — женский род → "Дружок" только если явно задан мужской характер, иначе "Найда", "Белка".\n'
        '• ТОЛЬКО РЕАЛЬНЫЕ РУССКИЕ СЛОВА: не изобретай несуществующих слов. '
        '"воробейка", "лисёнок" (если это взрослая лиса) — недопустимо. '
        'Птица-воробей = "воробей" (м.р.) или "воробьиха" только если подчёркнут женский пол.\n'
        '• Перед финальной записью мысленно прочитай вслух КАЖДОЕ предложение — звучит ли оно по-русски?'
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
            'temperature': 0.88,
            'max_tokens': 8000,
            'response_format': {'type': 'json_object'},
        },
        timeout=120,
    )
    response.raise_for_status()
    raw = response.json()['choices'][0]['message']['content']
    return json.loads(raw)


def _template_fallback(payload: dict) -> dict:
    name = payload['child_name']
    gender = payload.get('gender', 'neutral')
    style = payload.get('style', 'magical')
    age = payload.get('age', 7)
    episode = payload.get('episode_number', 1)
    animal = payload.get('favorite_animal') or 'кот'
    color = payload.get('favorite_color') or 'синий'
    hobby = payload.get('hobby') or 'рисование'
    place = payload.get('favorite_place') or 'лес'

    if gender == 'female':
        vyshel = 'вышла'; poshel = 'пошла'; uvidel = 'увидела'; skazal = 'сказала'
        nashel = 'нашла'; vernulsya = 'вернулась'; podoshel = 'подошла'
        uslyshal = 'услышала'; podnyal = 'подняла'; pobezhal = 'побежала'
        ponyal = 'поняла'; ulybнulsya = 'улыбнулась'; vzyal = 'взяла'
        zametil = 'заметила'; pron = 'она'; g_suf = 'а'; zasmeyal = 'засмеялась'
    else:
        vyshel = 'вышел'; poshel = 'пошёл'; uvidel = 'увидел'; skazal = 'сказал'
        nashel = 'нашёл'; vernulsya = 'вернулся'; podoshel = 'подошёл'
        uslyshal = 'услышал'; podnyal = 'поднял'; pobezhal = 'побежал'
        ponyal = 'понял'; ulybнulsya = 'улыбнулся'; vzyal = 'взял'
        zametil = 'заметил'; pron = 'он'; g_suf = ''; zasmeyal = 'засмеялся'

    style_titles = {
        'magic': 'и Тайна Хрустального Камня',
        'magical': 'и Тайна Хрустального Камня',
        'adventure': 'и Остров Потерянных Карт',
        'nature': 'и Говорящий Родник',
        'space': 'и Звёздный Маяк',
        'tender': 'и Серебряный Колокольчик',
        'epic': 'и Меч Рассвета',
    }
    ep_suffix = f' (Эпизод {episode})' if episode > 1 else ''
    title = f'{name} {style_titles.get(style, "и Волшебное Приключение")}{ep_suffix}'

    text = (
        f"Глава первая. Зов из {place}а\n\n"
        f"Тот день начался обычно. {name} {vyshel} на улицу и сразу остановил{g_suf}ся — "
        f"что-то изменилось. Воздух в {place}е пах иначе: острее, живее, будто перед грозой.\n\n"
        f"— Странно, — пробормотал{g_suf} {name} и {poshel} ближе к деревьям.\n\n"
        f"Из-за старого дуба выскочил{'' if animal[-1] not in 'аяь' else 'о'} что-то маленькое. "
        f"Это оказался{'' if animal[-1] not in 'аяь' else 'ась'} {animal} — но не обычный{'' if animal[-1] not in 'аяь' else 'ая'}. "
        f"Шерсть переливалась, глаза светились, и, главное — {pron} говорил{'а' if animal[-1] in 'аяь' else ''}.\n\n"
        f"— Наконец-то, — {skazal} {animal} без лишних предисловий. — Я искал{'а' if animal[-1] in 'аяь' else ''} тебя три дня.\n\n"
        f"— Меня? — {uvidel} {name} недоумение во взгляде {animal}а. — Почему меня?\n\n"
        f"— Потому что ты умеешь {hobby}. В {place}е нет больше никого, кто умеет. "
        f"А нам это очень нужно.\n\n"
        f"Так {name} узнал{g_suf}: в глубине {place}а живёт Страж Равновесия — "
        f"древнее существо, которое следит, чтобы мир не перекосился. "
        f"Но три дня назад Страж заснул, и теперь в {place}е всё начало меняться не в ту сторону.\n\n"

        f"Глава вторая. Испытание первое\n\n"
        f"Они шли долго. {animal.capitalize()} объяснял{'а' if animal[-1] in 'аяь' else ''} на ходу: "
        f"чтобы разбудить Стража, нужно пройти три испытания. Первое — Зеркальный Лабиринт.\n\n"
        f"Лабиринт выглядел как сад из стекла: стены отражали всё, и можно было идти часами, "
        f"возвращаясь к началу.\n\n"
        f"— Обычной дорогой не выйдешь, — {skazal} {animal}. — Здесь нужна твоя голова.\n\n"
        f"{name} огляделся. Стены отражали его самого — сотни раз, под разными углами. "
        f"И тут {ponyal} {name}: отражения слегка запаздывали. Буквально на полшага.\n\n"
        f"— Нужно идти против отражения, — {skazal} {name} медленно. — Туда, куда оно НЕ идёт.\n\n"
        f"Это было труднее, чем казалось — каждый шаг противоречил инстинктам. "
        f"Но через десять минут они стояли у выхода. {animal.capitalize()} смотрел{'а' if animal[-1] in 'аяь' else ''} на {name} с чем-то похожим на уважение.\n\n"

        f"Глава третья. Разговор у реки\n\n"
        f"За лабиринтом текла река. Не обычная — она текла бесшумно, и вода в ней была тёмной, "
        f"как поздний вечер. На берегу сидел старик с удочкой, хотя рыбы в реке явно не было.\n\n"
        f"— Второе испытание, — {skazal} старик, не оборачиваясь. — Ответь мне на вопрос.\n\n"
        f"— Какой? — спросил{g_suf} {name}.\n\n"
        f"— Что страшнее: потерять что-то важное или никогда не иметь?\n\n"
        f"{name} думал долго. {animal.capitalize()} молчал{'а' if animal[-1] in 'аяь' else ''} рядом — "
        f"видно, что это испытание не для {pron}.\n\n"
        f"— Никогда не иметь, — {skazal} наконец {name}. — Потому что потеря — это значит, что оно было. "
        f"А если не было — ты даже не знаешь, чего лишился.\n\n"
        f"Старик кивнул и исчез вместе с удочкой. Река начала светлеть.\n\n"

        f"Глава четвёртая. {hobby.capitalize()} как ключ\n\n"
        f"Третье испытание было самым странным: огромная каменная дверь с надписью "
        f"«Открою тому, кто создаст то, чего здесь не было».\n\n"
        f"— Что здесь есть? — {uslyshal} {name}.\n\n"
        f"— Камень. Мох. Темнота. Тишина.\n\n"
        f"— А чего нет?\n\n"
        f"{animal.capitalize()} {ulybнulsya}: — Всего остального.\n\n"
        f"{name} понял{'а' if gender == 'female' else ''}. Взял{g_suf} острый камень и начал{g_suf} "
        f"использовать {hobby} — так, как умел{g_suf} только {pron}. "
        f"Под руками {name}а что-то стало появляться: сначала тени, потом образы, потом почти настоящее. "
        f"Дверь медленно открылась — как будто тоже удивилась.\n\n"

        f"Глава пятая. Пробуждение\n\n"
        f"За дверью спал Страж. Он был огромным — больше дерева, меньше горы — "
        f"и совсем не страшным. Скорее усталым.\n\n"
        f"— Как его разбудить? — шёпотом спросил{g_suf} {name}.\n\n"
        f"— Позови по имени, — {skazal} {animal}. — Его имя — «Равновесие».\n\n"
        f"— Равновесие, — {skazal} {name} вслух. Не громко — но уверенно.\n\n"
        f"Страж открыл глаза. Посмотрел на {name}а долгим взглядом.\n\n"
        f"— Три дня прошло, — произнёс он голосом, похожим на эхо в пещере. — Я думал, никто не придёт.\n\n"
        f"— Мы пришли, — {skazal} {name}. — Потому что {place} — это важно.\n\n"
        f"Страж {zasmeyal}ся — тихо, как будто забыл, как это делается. И {place} снова стал собой.\n\n"
        f"Когда {name} {vernulsya} домой, {animal} {pobezhal} рядом. "
        f"Ни слова о том, что было. Некоторые вещи не нуждаются в словах.\n\n"
        f"А потом {name} {zametil}: всё, что случилось, изменило не {place} — изменило его самого."
    )

    image_prompts = [
        f'leaping through magical {place} in an epic adventure moment, {animal} racing alongside, '
        f'golden magical light bursting overhead, wide dramatic shot, sense of great adventure beginning',
        f'crouching to face small magical {animal} that has appeared from nowhere, '
        f'both looking at each other with surprise and wonder, dappled magical light, medium shot',
        f'running through hall of mirrored glass walls, reflections multiplying everywhere, '
        f'determined expression, dramatic low angle, cool silver light with warm glow ahead',
        f'using {hobby} skill in a daring moment, magical energy radiating from hands, '
        f'{animal} watching intently, warm golden light, tense dramatic atmosphere',
        f'celebrating triumphant victory in {place} with {animal} companion, '
        f'joyful wide shot, golden sunset light, magical sparkles, peaceful yet triumphant mood',
    ]

    recap_items = [
        f'{name} прошёл{"а" if gender == "female" else ""} три испытания в {place}е.',
        f'Разбудил{"а" if gender == "female" else ""} Стража Равновесия.',
        f'Открыл{"а" if gender == "female" else ""}: {hobby} — настоящая суперсила.',
    ]

    return {
        'title': title,
        'story_text': text,
        'image_prompts': image_prompts,
        'recap': recap_items,
        'memory': {
            'world_name': f'Волшебный {place.capitalize()}',
            'world_state': {
                'locations': [place, 'Зеркальный Лабиринт', 'Тёмная Река'],
                'artifacts': ['Ключ Равновесия'],
                'resolved': ['Страж разбужен', 'Равновесие восстановлено'],
            },
            'character_traits': {
                'courage': 'растёт',
                'kindness': 'главная черта',
                'special_power': f'умение {hobby}а как суперсила',
            },
            'character_level': episode,
            'allies': [f'волшебный {animal}', 'Страж Равновесия'],
            'open_threads': [f'{animal.capitalize()} упомянул{"а" if animal[-1] in "аяь" else ""} о втором {place}е'],
        },
        'next_hook': (
            f'Той ночью {name} слышал{"а" if gender == "female" else ""} знакомый голос во сне. '
            f'{animal.capitalize()} говорил{"а" if animal[-1] in "аяь" else ""}: "Это был только первый {place}. '
            f'Есть ещё один. Там всё иначе..."'
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
    story = _strip_all_english_words(story)
    result['story_text'] = story
    # Inject deterministic char_desc so image_service can prefix every prompt consistently
    result['char_desc'] = _build_char_desc(
        payload['child_name'], payload['age'], payload.get('gender', 'neutral'),
        payload.get('favorite_animal', 'кот'),
    )
    return result
