import json
import logging
import random
import re

import httpx

from ..config import get_settings

settings = get_settings()
log = logging.getLogger(__name__)


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

_PLOT_ARCHETYPES = [
    {
        'name': 'Потерянная песня',
        'setup': 'В мире исчезли все звуки. Деревья не шумят, птицы молчат, река течёт беззвучно. Только герой слышит еле уловимую мелодию — где-то далеко.',
        'twist': 'Оказывается, звуки не исчезли — они спрятались внутри одного существа, которое очень боялось быть услышанным.',
        'forbidden': 'Нельзя: Страж, мост с испытаниями, мудрый старик в домике, три испытания подряд.',
    },
    {
        'name': 'Письмо из прошлого',
        'setup': 'Герой находит старое письмо или предмет, который явно кому-то очень нужен — но отправитель давно исчез.',
        'twist': 'Получатель письма — это не тот, кого герой ищет. Послание важно для кого-то совсем другого — кто стоит рядом с самого начала.',
        'forbidden': 'Нельзя: злодей, погоня, волшебное оружие, испытания-загадки.',
    },
    {
        'name': 'Зеркальный двойник',
        'setup': 'Герой встречает кого-то, кто выглядит почти так же, как он сам — но думает, чувствует и действует иначе.',
        'twist': 'Двойник — не враг и не копия. Это отражение той части героя, которую он в себе не замечал.',
        'forbidden': 'Нельзя: волшебный лес как единственная локация, мудрый старик, замок злодея.',
    },
    {
        'name': 'День, который не заканчивается',
        'setup': 'Время остановилось. Один и тот же момент повторяется — но каждый раз чуть-чуть иначе. Никто вокруг не замечает, кроме героя.',
        'twist': 'Время остановил не злодей — его попросил остановить кто-то, кто боялся, что хорошее закончится. Нужно помочь этому существу отпустить момент.',
        'forbidden': 'Нельзя: физический бой, злодей с тёмными силами, три испытания.',
    },
    {
        'name': 'Невидимый помощник',
        'setup': 'Герою кто-то тайно помогает — оставляет подсказки, убирает препятствия, но никогда не показывается.',
        'twist': 'Невидимый помощник — это не волшебное существо. Это кто-то хорошо знакомый, кто не знал, как попросить о помощи иначе.',
        'forbidden': 'Нельзя: злодей с армией, большое сражение, мост с испытаниями.',
    },
    {
        'name': 'Остров воспоминаний',
        'setup': 'Герой попадает в место, где живут забытые вещи — игрушки, которых перестали замечать, слова, которые не досказали, обещания, которые забыли выполнить.',
        'twist': 'Самое ценное в этом месте — не предметы, а то, что они помнят о людях.',
        'forbidden': 'Нельзя: Страж, туман как угроза, погоня, злодей.',
    },
    {
        'name': 'Дерево желаний',
        'setup': 'Есть дерево, которое исполняет одно желание — но исполняет его по-своему. Герой приходит с чётким желанием, но получает не то, что ожидал.',
        'twist': 'Исполненное желание оказывается правильным — просто герой изначально загадывал не то, что ему по-настоящему нужно.',
        'forbidden': 'Нельзя: злодей, охота за сокровищем, бой, три испытания подряд.',
    },
    {
        'name': 'Город снов',
        'setup': 'Герой попадает в город, который существует только ночью. Жители его — персонажи чужих снов, которые не знают, что они снятся.',
        'twist': 'Этот город скоро исчезнет, потому что один человек перестал мечтать. Герой должен найти этого человека — а это неожиданно близкий человек.',
        'forbidden': 'Нельзя: битва добра со злом, Страж, волшебный лес.',
    },
    {
        'name': 'Последний хранитель',
        'setup': 'Есть одно существо, которое помнит что-то очень важное — как выглядит настоящая радость, или как пахнет лето, или как звучит смех. Но оно забывает.',
        'twist': 'Вернуть память невозможно — можно только создать новые воспоминания прямо сейчас. Герой и есть тот, кто это умеет.',
        'forbidden': 'Нельзя: волшебное оружие, злодей, испытания с загадками.',
    },
    {
        'name': 'Карта неизвестного',
        'setup': 'Герой находит карту — но на ней нарисованы места, которых нет нигде вокруг. Или есть?',
        'twist': 'Карта показывает не физические места, а состояния: "место, где не стыдно ошибаться", "место, где всегда рады". Герой должен найти их в реальном мире.',
        'forbidden': 'Нельзя: сокровище в буквальном смысле, злодей-охотник, волшебный замок.',
    },
    {
        'name': 'Обмен голосами',
        'setup': 'Герой и животное-спутник случайно меняются голосами — теперь герой понимает, что чувствует животное, а животное — что думает герой.',
        'twist': 'Оба узнают кое-что важное друг о друге — то, о чём никогда не решались сказать прямо.',
        'forbidden': 'Нельзя: злодей, погоня, три испытания, мост молчания.',
    },
    {
        'name': 'Фестиваль теней',
        'setup': 'Раз в году тени отделяются от своих хозяев и живут самостоятельно. Тень героя убежала — и ведёт себя совершенно неожиданно.',
        'twist': 'Тень делает всё то, чего герой боялся делать сам. Чтобы вернуть её, нужно понять: почему.',
        'forbidden': 'Нельзя: злодей похищает тень, погоня, физическая битва.',
    },
    {
        'name': 'Библиотека несказанного',
        'setup': 'Есть библиотека, где хранятся книги — но не написанные, а несказанные: слова, которые кто-то хотел произнести, но не решился.',
        'twist': 'Одна из книг предназначена именно герою. Кто её написал — полная неожиданность.',
        'forbidden': 'Нельзя: злодей, волшебный меч, Страж равновесия, мост.',
    },
    {
        'name': 'Гость из другого лета',
        'setup': 'К герою приходит кто-то, кто говорит, что знает его — но они никогда не встречались. Или встречались, но в другое время.',
        'twist': 'Гость — это будущая версия животного-спутника или кого-то близкого, который пришёл сказать что-то важное до того, как момент будет упущен.',
        'forbidden': 'Нельзя: битва со злом, три испытания, злодей.',
    },
    {
        'name': 'Ярмарка умений',
        'setup': 'В городе открылась ярмарка, где каждый может показать своё умение — но оказывается, что у некоторых жителей умение спрятано так глубоко, что они сами о нём не знают.',
        'twist': 'Самое нужное умение на ярмарке — то, которое герой считал обычным и незначительным.',
        'forbidden': 'Нельзя: Страж, мост испытаний, злодей, погоня.',
    },
]

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

# Reflexive verb grammar fixes: "лася" → "лась", "лося" → "лось"
# Catches: "остановилася" → "остановилась", "вернулася" → "вернулась", etc.
_REFLEXIVE_LASIA = re.compile(r'(\w+)лася\b', re.IGNORECASE)
_REFLEXIVE_LOSIA = re.compile(r'(\w+)лося\b', re.IGNORECASE)
# Special character cleanup
_SPECIAL_CHAR = re.compile(r'✦')


def _fix_common_grammar(text: str) -> str:
    """Auto-correct the most common LLM grammar errors in Russian text."""
    # "остановилася" → "остановилась", "улыбнулася" → "улыбнулась"
    text = _REFLEXIVE_LASIA.sub(lambda m: m.group(0)[:-4] + 'лась', text)
    # "вернулося" → "вернулось"
    text = _REFLEXIVE_LOSIA.sub(lambda m: m.group(0)[:-4] + 'лось', text)
    # Replace ✦ (not in DejaVu fonts, shows as box in PDF) with ◆
    text = _SPECIAL_CHAR.sub('◆', text)
    return text


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


def _prompt(payload: dict, archetype: dict | None = None) -> str:
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

    # Random archetype for plot variety
    arc = archetype or random.choice(_PLOT_ARCHETYPES)
    archetype_block = (
        f'АРХЕТИП СЮЖЕТА — ОБЯЗАТЕЛЕН, отклонение недопустимо:\n'
        f'Название: «{arc["name"]}»\n'
        f'Завязка: {arc["setup"]}\n'
        f'Обязательный поворот: {arc["twist"]}\n'
        f'СТРОГО ЗАПРЕЩЕНО в этой сказке: {arc["forbidden"]}\n'
        f'Сюжет должен быть узнаваемо построен вокруг этого архетипа — '
        f'не как упоминание, а как основа всей истории.\n'
    )

    return (
        'Ты мастер детской литературы мирового уровня. '
        'Твоя задача — написать персональную сказку, неотличимую от работы живого писателя.\n\n'
        'Верни СТРОГО JSON без markdown-обёртки:\n'
        '{"title":"...","story_text":"...","image_prompts":["...x4"],'
        '"recap":["..."],'
        '"memory":{"world_name":"...","world_state":{"locations":[],"artifacts":[],"resolved":[]},'
        '"character_traits":{"courage":"...","kindness":"...","special_power":"..."},'
        '"character_level":1,"allies":[],"open_threads":[]},'
        '"next_hook":"..."}\n\n'
        f'ГЕРОЙ: {name}, {age} лет. {gender_hint}\n'
        f'СТИЛЬ: {style_ru}. ЭПИЗОД №{episode}.\n\n'
        f'{continuation_block}\n'
        f'{archetype_block}\n'
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
        'ТРЕБОВАНИЯ К IMAGE PROMPTS (РОВНО 4 штуки, на английском, 45–60 слов каждый):\n'
        f'КАЖДЫЙ промпт — КОНКРЕТНАЯ ЖИВАЯ СЦЕНА из текста: кто что делает, где, '
        f'{animal} активно участвует в каждом кадре. '
        'НЕЛЬЗЯ описывать внешность героя — она добавится автоматически.\n'
        'КАЖДЫЙ промпт начинается с АКТИВНОГО ГЛАГОЛА. '
        'ОБЯЗАТЕЛЬНО указывай план съёмки: "wide establishing shot" / "medium full-body shot" / '
        '"dynamic wide-angle shot".\n'
        f'ОБЯЗАТЕЛЬНО в каждом промпте: детально описать ОКРУЖЕНИЕ "{place}" — '
        'архитектурные детали замка / звёзды и планеты космоса / деревья и лесной свет / морские волны и т.д. '
        f'Герои живут В мире "{place}", а не висят в пустоте.\n\n'
        f'[0] ОБЛОЖКА — epic wide establishing shot: {name} в пике самого захватывающего момента '
        f'сказки, {animal} рядом активно участвует, окружение "{place}" прорисовано богато '
        f'и атмосферно — текстуры, свет, глубина пространства. '
        f'Диагональная динамичная композиция, ощущение большого приключения, магическое освещение.\n\n'
        f'[1] ГЛАВА 1-2 — wide establishing shot: первое волшебное событие из текста, '
        f'{name} и {animal} вместе открывают что-то удивительное, '
        f'ОБЯЗАТЕЛЬНО: детальное окружение "{place}" занимает половину кадра — '
        f'конкретные детали места (цвета, материалы, световые эффекты). '
        f'Эмоция удивления, восторга или предвкушения приключения.\n\n'
        f'[2] ГЛАВА 3 — wide shot: ключевой момент с ДРУГИМИ ПЕРСОНАЖАМИ истории (союзник, '
        f'мудрый наставник, персонаж-противник или волшебное существо из текста), '
        f'{name} и {animal} в центре, вокруг — богатый мир сказки с другими героями. '
        f'Все персонажи этой сцены видны полностью, каждый — живой персонаж, не силуэт. '
        f'Атмосфера: напряжение, удивление или важный момент взаимодействия.\n\n'
        f'[3] КУЛЬМИНАЦИЯ-ФИНАЛ — dynamic wide-angle shot: {name}, {animal} и ВСЕ СОЮЗНИКИ '
        f'вместе в финальный момент победы, полное окружение "{place}" на пике красоты — '
        f'золотой или магический свет, ощущение завершения пути и торжества. '
        f'Все главные персонажи видны, мир вокруг сияет.\n\n'
        f'КРИТИЧНО: 4 промпта = 4 РАЗНЫХ ОСВЕЩЕНИЯ + 4 РАЗНЫХ РАКУРСА + '
        f'{animal} действует в каждом + "{place}" чётко виден в каждом кадре. '
        'Никаких описаний внешности — только сцена, мир, действие!\n\n'
        'КРЮЧОК (next_hook) — ПСИХОЛОГИЧЕСКИЙ КРЮЧОК НА ПОКУПКУ следующей сказки:\n'
        'НЕ тизер сюжета. НЕ "узнаем в следующий раз". НЕ описание следующей серии.\n'
        f'• Обращение к {name} НАПРЯМУЮ, с теплотой и близостью — про что-то, что зацепило сердце в этой сказке\n'
        '• Создай ЭМОЦИОНАЛЬНЫЙ ГОЛОД: незакрытый вопрос-мечта, на который ребёнок мысленно кричит "ДА, ХОЧУ!"\n'
        '• Финальное предложение — мягкое, но психологически точное обращение к маме/папе\n'
        '• Тон: тёплый, мечтательный, как лучший друг шепчет на ухо перед сном\n'
        '• СТРОГО 3 предложения:\n'
        f'  1) К {name} напрямую — про что-то конкретное из сказки, что тронуло больше всего\n'
        '  2) Вопрос-мечта: "А вдруг..." / "Интересно, правда ли..." / "Как думаешь..."\n'
        '  3) К маме/папе: нежный вопрос-намёк ("Мама, а можно мне ещё одну сказку?" — или аналог)\n\n'
        'ГРАММАТИКА — АБСОЛЮТНЫЙ ПРИОРИТЕТ. КАЖДОЕ ПРЕДЛОЖЕНИЕ ПРОВЕРЯЕТСЯ ПЕРЕД ЗАПИСЬЮ.\n\n'
        'РОД ГЛАГОЛОВ — САМАЯ ЧАСТАЯ ОШИБКА:\n'
        f'• Главный герой {name} — {"ДЕВОЧКА, ЖЕНСКИЙ РОД ВЕЗДЕ" if gender == "female" else "МАЛЬЧИК, МУЖСКОЙ РОД ВЕЗДЕ"}. '
        f'Пример: {"«она пошла», «она увидела», «она остановилась», «смелая», «добрая»" if gender == "female" else "«он пошёл», «он увидел», «он остановился», «смелый», «добрый»"}.\n'
        f'• ЖИВОТНОЕ-СПУТНИК «{animal}»: его пол определяется ГРАММАТИЧЕСКИМ РОДОМ СЛОВА, а НЕ родом героя. '
        f'Пример: «волк» — мужской → "сказал волк", "он прыгнул"; «лиса» — женский → "сказала лиса", "она прыгнула". '
        f'НИКОГДА не используй пол героя вместо пола животного в речи и действиях животного.\n\n'
        'СТРОГО ЗАПРЕЩЁННЫЕ КОНСТРУКЦИИ — НЕМЕДЛЕННО ПЕРЕПИСЫВАТЬ:\n'
        '• «лася»-окончания: «остановилася», «улыбнулася», «вернулася», «поднялася» — '
        'ТАКИХ СЛОВ НЕТ В РУССКОМ ЯЗЫКЕ. Только «остановилась», «улыбнулась», «вернулась», «поднялась».\n'
        '• «Из-за дуба выскочил что-то» — ОШИБКА. «что-то» — средний род → «выскочило что-то».\n'
        '• «она говорил», «он сказала» — недопустимо. Глагол ОБЯЗАН согласоваться с подлежащим.\n'
        '• «Наконец-то, — сказала волк» — «волк» м.р. → «сказал волк».\n'
        '• «В один из ясных утра» — ГРУБАЯ ОШИБКА. Только «Одним ясным утром» / «Ранним утром».\n'
        '• «Войдя в лес, начался дождь» — деепричастие и подлежащее разные. Только «Войдя в лес, герой увидел...».\n'
        '• «собака сенбернара» — ОШИБКА ПАДЕЖА. Если нужен родительный падеж: «собаки-сенбернара» / «сенбернар».\n'
        '• «Из горыа», «в горые», «до горыи» — НЕСУЩЕСТВУЮЩИЕ ФОРМЫ. «гора»: из горы, в горе, до горы, по горе.\n'
        '• «Звов из горы», «зов горыа» — слово «зов» + родительный «горы»: «зов горы» (без лишних букв).\n\n'
        'СКЛОНЕНИЕ СУЩЕСТВИТЕЛЬНЫХ — ПРОВЕРЯЙ:\n'
        '• Топонимы и названия мест не получают лишних букв: «из леса» (не «из лесыа»), '
        '«в горе» (не «в горые»), «из замка» (не «из замкыа»).\n'
        '• Согласование прилагательных с родом: "Звёздное Сияние" (ср.р.), "Золотой Ветер" (м.р.) — НЕ "Звёздный Сияние"\n'
        '• Числительные + существительные: "два дня", "три часа", "пять минут" — по всем падежам\n'
        '• Глаголы движения: "пошёл В лес", "вышел ИЗ леса" — предлоги строго по смыслу\n'
        f'• Кличка животного-спутника должна совпадать с родом слова «{animal}»: '
        f'если существительное мужского рода → мужская кличка; женского → женская.\n'
        '• ТОЛЬКО РЕАЛЬНЫЕ РУССКИЕ СЛОВА. Не изобретай несуществующих форм.\n'
        '• Перед финальной записью прочитай вслух КАЖДОЕ предложение — звучит ли оно по-русски?\n'
        '• ТЕСТ: найди все глаголы прошедшего времени → проверь согласование с подлежащим. '
        'Найди все слова на «-ся» → проверь: нет ли «-лася» или «-лося».'
    )


def _call_openai_direct(payload: dict, archetype: dict | None = None) -> dict:
    """Call OpenAI gpt-4o-mini directly (bypass OpenRouter) using the same prompt.

    Used as secondary fallback when OpenRouter is unavailable, so users always
    get a unique LLM-generated story instead of the static template.
    """
    if not settings.openai_api_key:
        raise RuntimeError('OPENAI_API_KEY not configured — cannot use OpenAI direct fallback')
    from openai import OpenAI
    client = OpenAI(api_key=settings.openai_api_key)
    prompt_text = _prompt(payload, archetype=archetype)
    resp = client.chat.completions.create(
        model='gpt-4o-mini',
        messages=[{'role': 'user', 'content': prompt_text}],
        temperature=0.88,
        max_tokens=8000,
        response_format={'type': 'json_object'},
    )
    raw = resp.choices[0].message.content
    return json.loads(raw)


def _call_openrouter(payload: dict, archetype: dict | None = None) -> dict:
    from ..services.cost_guard import check as _guard_check, CostGuardError  # noqa: F401

    if not settings.openrouter_api_key:
        raise RuntimeError('OPENROUTER_API_KEY is not configured')

    prompt_text = _prompt(payload, archetype=archetype)
    messages = [{'role': 'user', 'content': prompt_text}]

    # ── Cost-safety pre-flight ─────────────────────────────────────────────────
    _guard_check(
        model=settings.openrouter_model,
        messages=messages,
        tools=None,          # tools are NEVER used in story generation
        pipeline='story_generation',
    )

    response = httpx.post(
        'https://openrouter.ai/api/v1/chat/completions',
        headers={
            'Authorization': f'Bearer {settings.openrouter_api_key}',
            'Content-Type': 'application/json',
        },
        json={
            'model':           settings.openrouter_model,
            'messages':        messages,
            'temperature':     0.88,
            'max_tokens':      8000,
            'response_format': {'type': 'json_object'},
            # Explicit: no tools, no streaming — single-shot text generation only
        },
        timeout=120,
    )
    response.raise_for_status()
    raw = response.json()['choices'][0]['message']['content']
    return json.loads(raw)


_HOBBY_VERB: dict[str, str] = {
    'рисование':   'рисовать',
    'спорт':       'заниматься спортом',
    'музыка':      'играть музыку',
    'чтение':      'читать',
    'игры':        'играть',
    'готовка':     'готовить',
    'наука':       'проводить опыты',
    'садоводство': 'ухаживать за растениями',
}


def _name_gen(name: str) -> str:
    """Genitive case for names: Митя→Мити, Маша→Маши, Иван→Ивана."""
    if name.endswith('я') or name.endswith('а'):
        return name[:-1] + 'и'
    return name + 'а'


def _name_acc(name: str) -> str:
    """Accusative case for names: Митя→Митю, Маша→Машу, Иван→Ивана."""
    if name.endswith('я'):
        return name[:-1] + 'ю'
    if name.endswith('а'):
        return name[:-1] + 'у'
    return name + 'а'


_ANIMAL_GRAM_GENDER: dict[str, str] = {
    # masculine
    'кот': 'male', 'котёнок': 'male', 'пёс': 'male', 'щенок': 'male',
    'волк': 'male', 'лисёнок': 'male', 'медведь': 'male', 'медвежонок': 'male',
    'заяц': 'male', 'зайчик': 'male', 'кролик': 'male', 'ёж': 'male', 'ёжик': 'male',
    'дракон': 'male', 'единорог': 'male', 'попугай': 'male', 'попугайчик': 'male',
    'слон': 'male', 'тигр': 'male', 'хомяк': 'male', 'пони': 'male',
    # feminine
    'кошка': 'female', 'собака': 'female', 'лиса': 'female', 'черепаха': 'female',
    'черепашка': 'female', 'сова': 'female', 'белка': 'female', 'лошадь': 'female',
    'обезьяна': 'female',
}


def _animal_gender(animal: str) -> str:
    """Return grammatical gender ('male'/'female') of the animal noun."""
    key = animal.lower().strip()
    if key in _ANIMAL_GRAM_GENDER:
        return _ANIMAL_GRAM_GENDER[key]
    # Heuristic: -а/-я endings → female; -ь needs context (default female for unknown); else male
    last = key[-1] if key else ''
    if last in 'ая':
        return 'female'
    if last == 'ь':
        return 'female'   # most unknown -ь animals (форель, лань, рысь...) are feminine
    return 'male'


def _animal_genitive(animal: str, ag: str) -> str:
    """Generate genitive case (родительный падеж) of an animal noun."""
    w = animal.strip()
    if not w:
        return w
    last = w[-1].lower()
    pre = w[-2].lower() if len(w) > 1 else ''
    if last == 'й':
        return w[:-1] + 'я'            # попугай → попугая
    if last == 'ь':
        if ag == 'female':
            return w[:-1] + 'и'        # форель → форели, лошадь → лошади
        return w[:-1] + 'я'            # медведь → медведя
    if last == 'а':
        # после шипящих и г/к/х → и; иначе → ы
        return w[:-1] + ('и' if pre in 'гкхжшщч' else 'ы')  # лиса→лисы, кошка→кошки
    if last == 'я':
        return w[:-1] + 'и'            # обезьяна→обезьяны... wait 'яна' ends 'а'
    if last in 'бвгджзклмнпрстфхцчшщ':
        return w + 'а'                 # волк→волка, кот→кота, тигр→тигра
    return w + 'а'                     # fallback


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

    # Hero gender forms
    if gender == 'female':
        vyshel = 'вышла'; poshel = 'пошла'; skazal = 'сказала'
        vernulsya = 'вернулась'; pobezhal = 'побежала'
        ponyal = 'поняла'; vzyal = 'взяла'; uslyshal = 'услышала'
        zametil = 'заметила'; pron = 'она'; g_suf = 'а'
        zasmeyal = 'засмеялась'; sprosil = 'спросила'
        oglyadelsya = 'огляделась'; ego = 'её'; sebya_suf = 'саму'
    else:
        vyshel = 'вышел'; poshel = 'пошёл'; skazal = 'сказал'
        vernulsya = 'вернулся'; pobezhal = 'побежал'
        ponyal = 'понял'; vzyal = 'взял'; uslyshal = 'услышал'
        zametil = 'заметил'; pron = 'он'; g_suf = ''
        zasmeyal = 'засмеялся'; sprosil = 'спросил'
        oglyadelsya = 'огляделся'; ego = 'его'; sebya_suf = 'самого'

    # Animal grammatical gender forms (independent of hero gender!)
    _ag = _animal_gender(animal)
    an_skazal     = 'сказала'    if _ag == 'female' else 'сказал'
    an_iskal      = 'искала'     if _ag == 'female' else 'искал'
    an_suf        = 'а'          if _ag == 'female' else ''
    an_pron       = 'она'        if _ag == 'female' else 'он'
    an_okazalsya  = 'оказалась'  if _ag == 'female' else 'оказался'
    an_obychny    = 'обычная'    if _ag == 'female' else 'обычный'
    an_ulyb       = 'улыбнулась' if _ag == 'female' else 'улыбнулся'
    an_genit_pron = 'неё'        if _ag == 'female' else 'него'

    hobby_verb = _HOBBY_VERB.get(hobby.lower().strip(), f'заниматься {hobby}ом')
    name_gen = _name_gen(name)
    name_acc = _name_acc(name)

    style_titles = {
        'magic':     'и Хранитель Утреннего Света',
        'magical':   'и Хранитель Утреннего Света',
        'adventure': 'и Карта Незнакомых Дорог',
        'nature':    'и Говорящий Родник',
        'space':     'и Звёздный Маяк',
        'tender':    'и Серебряный Колокольчик',
        'epic':      'и Меч Рассвета',
    }
    ep_suffix = f' (Эпизод {episode})' if episode > 1 else ''
    title = f'{name} {style_titles.get(style, "и Волшебное Приключение")}{ep_suffix}'

    # Alternate between two plot templates by name seed to avoid repetition
    seed = sum(ord(c) for c in name) + episode
    use_variant_b = (seed % 2 == 1)

    if not use_variant_b:
        # --- Template A: Страж ---
        text = (
            f"Глава первая. Странное утро в {place}е\n\n"
            f"Тот день начался обычно — {name} {vyshel} на улицу и сразу остановил{g_suf}ся. "
            f"Что-то было не так. Воздух в {place}е пах иначе: острее, живее, совсем не как обычно.\n\n"
            f"— Странно, — пробормотал{g_suf} {name} вполголоса и {oglyadelsya} по сторонам.\n\n"
            f"Из-за широкого дерева выскочило что-то маленькое и быстрое. "
            f"Это {an_okazalsya} {animal} — но совсем не {an_obychny}. "
            f"Глаза светились тёплым светом, и, главное, — {an_pron} говорил{an_suf}.\n\n"
            f"— Наконец-то! — {an_skazal} {animal} без приветствий. — Я {an_iskal} тебя с самого утра.\n\n"
            f"— Меня? — удивил{g_suf}ся {name}. — Почему именно меня?\n\n"
            f"— Потому что ты умеешь {hobby_verb}. В {place}е больше никто не умеет. "
            f"А нам сейчас это очень нужно.\n\n"
            f"Так {name} узнал{g_suf}: в глубине {place}а дремлет Страж — "
            f"древнее существо, которое следит за порядком вещей. "
            f"Три дня назад Страж заснул, и {place} начал меняться не в ту сторону.\n\n"

            f"Глава вторая. Мост Молчания\n\n"
            f"Они шли туда, где {place} становился всё бледнее. "
            f"{animal.capitalize()} объяснял{an_suf} на ходу: "
            f"чтобы разбудить Стража, нужно пройти три испытания. Первое — Мост Молчания.\n\n"
            f"Мост был необычным: он держался, только пока никто не говорил вслух. "
            f"Стоило открыть рот — доски начинали дрожать.\n\n"
            f"— Как же нам общаться? — чуть не {skazal} {name} вслух, но вовремя остановил{g_suf}ся.\n\n"
            f"{name} {oglyadelsya} и {ponyal}: на перилах были нарисованы значки — "
            f"стрелки, точки, маленькие фигурки. Своя азбука. Нужно читать её, а не придумывать слова.\n\n"
            f"Они перешли молча — {name} показывал{g_suf} дорогу знаками, {animal} следовал{an_suf} точно. "
            f"На той стороне {animal} тихо кивнул{an_suf} — это было лучше любых слов.\n\n"

            f"Глава третья. Хранитель\n\n"
            f"За мостом стоял старый домик. "
            f"Внутри сидел Хранитель — седой старичок с добрыми, но очень внимательными глазами.\n\n"
            f"— Второе испытание, — сказал он, не поднимая взгляда. "
            f"— Ответь честно на один вопрос.\n\n"
            f"— Слушаю, — {skazal} {name}.\n\n"
            f"— Когда тебе по-настоящему хорошо — ты один или с кем-то?\n\n"
            f"{name} задумал{g_suf}ся. {animal.capitalize()} молчал{an_suf} рядом — "
            f"это испытание было явно не для {an_genit_pron}.\n\n"
            f"— По-настоящему хорошо — когда есть кто-то рядом, — {skazal} наконец {name}. "
            f"— Даже если молчим. Главное — что не один.\n\n"
            f"Хранитель кивнул.\n"
            f"— Правильный ответ — тот, которому сам веришь. Ты ответил{g_suf} честно.\n\n"

            f"Глава четвёртая. Умение как ключ\n\n"
            f"Третье испытание оказалось самым необычным. "
            f"Перед {name_gen} стояла старая деревянная дверь без ручки и без замка.\n\n"
            f"— Она открывается не ключом, — {an_skazal} {animal} тихо. — Только тем, что умеешь ты.\n\n"
            f"{name} {ponyal} не сразу. {vzyal.capitalize()} глубокий вдох и начал{g_suf} "
            f"делать то, что умел{g_suf} лучше всего — {hobby_verb}. "
            f"Поначалу казалось, что ничего не происходит. "
            f"Но потом в воздухе что-то сдвинулось — тихо, почти незаметно.\n\n"
            f"Дверь медленно открылась — как будто наконец услышала то, чего давно ждала.\n\n"
            f"— Я знал{an_suf}, — тихо {an_skazal} {animal}.\n\n"

            f"Глава пятая. Пробуждение\n\n"
            f"За дверью дремал Страж. Огромный — больше любого дерева, меньше горы — "
            f"и совсем не пугающий. Скорее очень усталый.\n\n"
            f"— Как его разбудить? — шёпотом {sprosil} {name}.\n\n"
            f"— Позови его так, чтобы он услышал сердцем, — {an_skazal} {animal}.\n\n"
            f"{name} {skazal} негромко, но уверенно: — Мы здесь. {place.capitalize()} ждёт тебя.\n\n"
            f"Страж открыл глаза. Посмотрел на {name_acc} долгим и удивлённым взглядом.\n\n"
            f"— Давно никто не приходил, — произнёс он медленно. — Я думал, всем всё равно.\n\n"
            f"— Не всем, — {skazal} {name}. — Нам — не всё равно.\n\n"
            f"Страж {zasmeyal} — тихо, как будто заново вспоминал, как это делается. "
            f"И {place} вокруг стал прежним — живым и настоящим.\n\n"
            f"Когда {name} {vernulsya} домой, {animal} {pobezhal} рядом. "
            f"О том, что было, не говорили — некоторые вещи не нуждаются в словах.\n\n"
            f"А потом {name} {zametil}: {place} не изменился. Изменил{g_suf}ся {pron} {sebya_suf}."
        )
        image_prompts = [
            f'running through the magical {place} at dawn, {animal} leaping alongside, '
            f'golden light filtering through, wide establishing shot, sense of adventure beginning',
            f'crossing a wooden bridge in {place} in total silence, moving carefully, '
            f'{animal} following closely, atmospheric mist below, wide shot',
            f'sitting opposite a wise old man in a cosy small house, {animal} nearby, '
            f'warm lamplight, thoughtful atmosphere, medium wide shot',
            f'channelling the power of {hobby} before an ancient wooden door in {place}, '
            f'soft magical glow, {animal} watching with hope, warm amber light, medium shot',
            f'celebrating with {animal} in a beautifully restored {place}, '
            f'golden light everywhere, joyful wide shot, magical sparkles, triumphant mood',
        ]
        recap_items = [
            f'{name} прошёл{"а" if gender == "female" else ""} три испытания в {place}е.',
            f'Разбудил{"а" if gender == "female" else ""} Стража.',
            f'Открыл{"а" if gender == "female" else ""}: умение {hobby_verb} — настоящая суперсила.',
        ]
        next_hook = (
            f'Той ночью {name} слышал{g_suf} знакомый голос во сне. '
            f'{animal.capitalize()} говорил{an_suf}: "В {place}е появилось кое-что новое. '
            f'Я видел{an_suf} сам. Тебе нужно это увидеть..."'
        )
        world_locations = [place, 'Мост Молчания', 'Домик Хранителя']
        world_resolved = ['Страж разбужен']

    else:
        # --- Template B: Исчезнувшие краски ---
        text = (
            f"Глава первая. Когда {place} стал серым\n\n"
            f"Всё началось утром. {name} {vyshel} из дома — и остановил{g_suf}ся как вкопанный{g_suf}.\n\n"
            f"Что-то было не так с {place}ем. Краски будто смыло: всё стало блёклым и тусклым. "
            f"Даже солнце казалось белым и холодным, словно забыло, как светить.\n\n"
            f"— Это началось вчера ночью, — раздался голос рядом.\n\n"
            f"{name} обернул{g_suf}ся. Рядом стоял{an_suf} {animal} — глаза его светились по-прежнему тепло.\n\n"
            f"— Туманный Вор забрал все краски. Он прячется в Серебряной Пещере, — {an_skazal} {animal}. "
            f"— Ты умеешь {hobby_verb}. Именно поэтому только ты можешь ему помочь.\n\n"
            f"— Помочь вору? — удивил{g_suf}ся {name}.\n\n"
            f"— Он не злой, — тихо {an_skazal} {animal}. — Он просто очень одинок.\n\n"

            f"Глава вторая. Путь через туман\n\n"
            f"Они шли туда, где {place} становился всё бледнее. "
            f"Дорогу указывал{an_suf} {animal}: {an_pron} чувствовал{an_suf} тепло там, "
            f"где глаза видели только серое.\n\n"
            f"На полпути дорогу перегородил Туманный Страж — огромная фигура из клубящегося дыма.\n\n"
            f"— Назад, — произнёс он. — Чужим здесь не место.\n\n"
            f"— Мы не чужие, — {skazal} {name} спокойно. — Мы пришли помочь.\n\n"
            f"Страж замолчал. В его туманных глазах мелькнуло что-то похожее на удивление. "
            f"Таких слов он, кажется, не слышал очень давно. Он посторонился.\n\n"
            f"{animal.capitalize()} тихо кивнул{an_suf} {name_acc}: — Ты {skazal}{g_suf} правильно.\n\n"

            f"Глава третья. Туманный Вор\n\n"
            f"В глубине пещеры среди серых камней сидело маленькое существо. "
            f"Оно было почти незаметным — такое же бесцветное, как похищенный мир вокруг.\n\n"
            f"— Ты Туманный Вор? — {sprosil} {name}.\n\n"
            f"— Я не хотел красть, — прошептало существо. — Я просто хотел посмотреть. "
            f"Краски были такими красивыми. А у меня своих никогда не было.\n\n"
            f"{name} {ponyal}: это было не воровство. Это было одиночество.\n\n"
            f"— А ты умеешь видеть красоту? — {sprosil} {name} тихо.\n\n"
            f"— Не знаю. Никто никогда не показывал, — ответило существо.\n\n"
            f"{animal.capitalize()} {an_skazal} мягко: — Сейчас покажет.\n\n"

            f"Глава четвёртая. Дар\n\n"
            f"{name} {oglyadelsya}. В пещере было темно и серо, "
            f"но {pron} знал{g_suf}: умение {hobby_verb} — это не просто занятие. "
            f"Это способность создавать то, чего раньше не было.\n\n"
            f"Начал{g_suf}. Медленно, сосредоточенно — так, как умел{g_suf} только {pron}.\n\n"
            f"Сначала в воздухе появились лёгкие золотистые искры. "
            f"Потом краски начали возвращаться — сначала по одной, потом всё быстрее.\n\n"
            f"Туманный Вор смотрел широко открытыми глазами — впервые видел, "
            f"как кто-то создаёт красоту и дарит её просто так.\n\n"
            f"— Можно... и мне попробовать? — прошептало существо.\n\n"
            f"— Конечно, — {skazal} {name} с улыбкой. — Я покажу.\n\n"

            f"Глава пятая. Возвращение красок\n\n"
            f"Когда они вышли из пещеры, {place} был совсем другим. "
            f"Краски вернулись — даже ярче прежнего, словно {place} соскучил{g_suf}ся по ним.\n\n"
            f"Туманный Вор шёл рядом — уже не серый, а чуть золотистый по краям. "
            f"И впервые не прятался.\n\n"
            f"— Спасибо, — {an_skazal} {animal} {name_acc} тихо. — Ты {skazal}{g_suf} ему то, "
            f"что не смог бы сказать я.\n\n"
            f"— Я просто показал{g_suf}, — ответил{g_suf} {name}.\n\n"
            f"— Иногда это самое важное, — {an_ulyb} {animal}.\n\n"
            f"Когда {name} {vernulsya} домой, {animal} {pobezhal} рядом — "
            f"и в воздухе между ними чувствовалось что-то тёплое, не требующее слов.\n\n"
            f"А потом {name} {zametil}: в {place}е появился новый житель. "
            f"И {pron} {ego} немного знал{g_suf}."
        )
        image_prompts = [
            f'walking through a faded grey {place} with warmly glowing {animal} companion, '
            f'striking contrast between colourless world and magical warm light, '
            f'wide establishing shot, sense of mystery and quest',
            f'facing a tall misty guardian figure on a grey path in {place}, '
            f'standing confidently while {animal} stands close, cool silver mist, dramatic wide shot',
            f'discovering a small colourless creature in a silver cave, '
            f'{animal} approaching gently, warm light appearing, medium emotional shot',
            f'using the power of {hobby} to fill the cave with golden colour and light, '
            f'magical particles swirling, creature watching in wonder, {animal} beside, wide shot',
            f'returning to a brilliantly colourful {place} with {animal} and a newly golden creature, '
            f'joyful wide shot, warm golden light, magical sparkles everywhere',
        ]
        recap_items = [
            f'{name} спас{"ла" if gender == "female" else ""} краски {place}а.',
            f'Помог{"ла" if gender == "female" else ""} Туманному Вору найти своё место.',
            f'Открыл{"а" if gender == "female" else ""}: умение {hobby_verb} меняет мир.',
        ]
        next_hook = (
            f'Перед сном {animal} шепнул{an_suf} {name_acc} кое-что важное: '
            f'"В {place}е есть ещё одно место, о котором никто не знает. '
            f'Я видел{an_suf} его сегодня — оно ждёт именно тебя."'
        )
        world_locations = [place, 'Серебряная Пещера']
        world_resolved = ['Краски возвращены', 'Туманный Вор обрёл дом']

    return {
        'title': title,
        'story_text': text,
        'image_prompts': image_prompts,
        'recap': recap_items,
        'memory': {
            'world_name': f'Волшебный {place.capitalize()}',
            'world_state': {
                'locations': world_locations,
                'artifacts': [],
                'resolved': world_resolved,
            },
            'character_traits': {
                'courage': 'растёт',
                'kindness': 'главная черта',
                'special_power': f'умение {hobby_verb} как суперсила',
            },
            'character_level': episode,
            'allies': [f'волшебный {animal}'],
            'open_threads': [f'{animal.capitalize()} {an_iskal} кое-что новое в {place}е'],
        },
        'next_hook': next_hook,
    }


def generate_story_payload(payload: dict) -> dict:
    payload['style'] = choose_style(payload['age'], payload.get('style', 'auto'))
    provider = settings.text_provider
    name = payload.get('child_name', '?')

    # Pick one archetype per generation so both primary and fallback use the same plot
    archetype = random.choice(_PLOT_ARCHETYPES)
    log.info('[text] Plot archetype for %s: %s', name, archetype['name'])

    if provider == 'openrouter':
        # Try 1: OpenRouter
        try:
            result = _call_openrouter(payload, archetype=archetype)
            log.info('[text] OpenRouter OK for %s', name)
        except Exception as e1:
            log.warning('[text] OpenRouter FAILED for %s: %s — trying OpenAI direct', name, e1)
            # Try 2: OpenAI direct (same model, bypasses OpenRouter)
            try:
                result = _call_openai_direct(payload, archetype=archetype)
                log.info('[text] OpenAI direct OK for %s', name)
            except Exception as e2:
                log.error('[text] OpenAI direct FAILED for %s: %s — using template fallback', name, e2)
                if settings.backup_text_provider == 'template':
                    result = _template_fallback(payload)
                else:
                    raise RuntimeError(f'All text providers failed. OpenRouter: {e1}. OpenAI: {e2}') from e2
    elif provider == 'template':
        result = _template_fallback(payload)
    else:
        raise ValueError(f'Unsupported text provider: {provider}')

    story = _strip_english_style_words(result['story_text'])
    story = _strip_all_english_words(story)
    story = _fix_common_grammar(story)
    # Normalize paragraph separators: LLM sometimes sends single \n instead of \n\n
    if '\n\n' not in story and '\n' in story:
        story = story.replace('\n', '\n\n')
    result['story_text'] = story
    # Inject deterministic char_desc so image_service can prefix every prompt consistently
    result['char_desc'] = _build_char_desc(
        payload['child_name'], payload['age'], payload.get('gender', 'neutral'),
        payload.get('favorite_animal', 'кот'),
    )
    return result
