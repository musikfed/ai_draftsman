"""Versioned, read-only starter graph blueprints (no GPU or external imports).

Stored as independent SQLite rows at project initialization. A user choosing
a template receives copies of nodes and edges in their own project, never
a live link that would rewrite an existing project on app restart.
"""
from __future__ import annotations

import json
import sqlite3

SCHEMA_VERSION = 1
BUILTIN_TEMPLATES = json.loads(r'''[
  {
    "id": "comic_storyboard",
    "title_ru": "Комикс — сюжет и 5 свайпов",
    "title_en": "Comic — story and 5 swipes",
    "category": "story",
    "summary_ru": "Один выпуск: сюжет, паспорт персонажа, визуальный стиль и пять связанных свайпов. Узлы — отдельные сцены, не варианты Seed.",
    "summary_en": "One episode with shared character/style and five linked swipe scenes.",
    "base_prompt": "Vertical 4:5 comic artwork, coherent character identity, crisp ink outlines, expressive gestures, clean panel hierarchy, consistent palette, no generated text.",
    "negative_prompt": "inconsistent faces, changing outfits, wrong limbs, watermarks, illegible typography, unintended extra panels",
    "system_prompt": "Keep character and outfit continuity across linked slides. Each slide is one scene; do not treat alternative seeds as new scenes. Place exact speech lettering outside image generation.",
    "nodes": [
      {
        "key": "brief",
        "title": "Сюжет выпуска",
        "kind": "lesson",
        "notes": "Сформулируй конфликт, поворот и финальную реплику. Каждый свайп — самостоятельный эпизод общей последовательности.",
        "prompt": "",
        "negative_prompt": "",
        "x": 40,
        "y": 30
      },
      {
        "key": "hero",
        "title": "Паспорт персонажей",
        "kind": "character",
        "notes": "Опиши героя, лицо, одежду, отличительные признаки и неизменяемые детали; при необходимости сохрани референс отдельно.",
        "prompt": "",
        "negative_prompt": "",
        "x": 40,
        "y": 180
      },
      {
        "key": "style",
        "title": "Библия стиля",
        "kind": "style",
        "notes": "Зафиксируй палитру, линию, освещение, соотношение 4:5, правила контрастности и расположения текста.",
        "prompt": "",
        "negative_prompt": "",
        "x": 40,
        "y": 330
      },
      {
        "key": "s1",
        "title": "01 — Завязка",
        "kind": "slide",
        "notes": "Первый свайп: где мы и кто герой, без лишних персонажей.",
        "prompt": "A clear opening comic scene, establish the hero and setting, dynamic framing.",
        "negative_prompt": "",
        "x": 310,
        "y": 30
      },
      {
        "key": "s2",
        "title": "02 — Проблема",
        "kind": "slide",
        "notes": "Второй свайп: событие или задача; персонажи, одежда и окружение продолжаются.",
        "prompt": "Same characters and setting, the central problem becomes visible.",
        "negative_prompt": "",
        "x": 560,
        "y": 30
      },
      {
        "key": "s3",
        "title": "03 — Ошибка",
        "kind": "slide",
        "notes": "Третий свайп: ошибочная попытка решить задачу, узнаваемое движение персонажа.",
        "prompt": "Same protagonist in a comedic failed attempt, clear readable action.",
        "negative_prompt": "",
        "x": 810,
        "y": 30
      },
      {
        "key": "s4",
        "title": "04 — Решение",
        "kind": "slide",
        "notes": "Четвёртый свайп: рациональное решение после подсказки.",
        "prompt": "Same hero understands the solution, expressive but readable gesture.",
        "negative_prompt": "",
        "x": 1060,
        "y": 30
      },
      {
        "key": "s5",
        "title": "05 — Финал",
        "kind": "slide",
        "notes": "Пятый свайп: развязка и визуальный панчлайн; надписи вне генератора.",
        "prompt": "Final comic scene, same character design, satisfying visual punchline.",
        "negative_prompt": "",
        "x": 1310,
        "y": 30
      },
      {
        "key": "out",
        "title": "Проверка и сборка выпуска",
        "kind": "output",
        "notes": "Проверь 5 разных свайпов, одинаковых героев, корректный пояс, порядок и размер; сборка не выполняется автоматически.",
        "prompt": "",
        "negative_prompt": "",
        "x": 1560,
        "y": 30
      }
    ],
    "edges": [
      [
        "brief",
        "s1"
      ],
      [
        "hero",
        "s1"
      ],
      [
        "style",
        "s1"
      ],
      [
        "s1",
        "s2"
      ],
      [
        "s2",
        "s3"
      ],
      [
        "s3",
        "s4"
      ],
      [
        "s4",
        "s5"
      ],
      [
        "s5",
        "out"
      ],
      [
        "hero",
        "s3"
      ],
      [
        "style",
        "s4"
      ]
    ]
  },
  {
    "id": "illustration_series",
    "title_ru": "Серия иллюстраций — один стиль",
    "title_en": "Illustration series — shared look",
    "category": "art",
    "summary_ru": "Несколько картинок для книги/соцсетей с одним стилем и повторяющимся персонажем.",
    "summary_en": "Coherent multi-image illustration series for books or social media.",
    "base_prompt": "Cohesive editorial illustration series, consistent character design, balanced composition, controlled color palette.",
    "negative_prompt": "inconsistent style, random wardrobe changes, watermark, duplicate objects, unwanted text",
    "system_prompt": "Preserve style and recurring objects across the series. Treat each scene as a separate illustration and reuse approved character descriptions.",
    "nodes": [
      {
        "key": "brief",
        "title": "Задача серии",
        "kind": "note",
        "notes": "Для чего серия, аудитория, набор сюжетов и ограничения.",
        "prompt": "",
        "negative_prompt": "",
        "x": 40,
        "y": 40
      },
      {
        "key": "character",
        "title": "Общий герой",
        "kind": "character",
        "notes": "Неизменные черты лица, аксессуары и одежда для всей серии.",
        "prompt": "",
        "negative_prompt": "",
        "x": 40,
        "y": 180
      },
      {
        "key": "style",
        "title": "Единый стиль",
        "kind": "style",
        "notes": "Палитра, композиционные правила, штрихи, пропорции и свет.",
        "prompt": "",
        "negative_prompt": "",
        "x": 40,
        "y": 320
      },
      {
        "key": "a",
        "title": "Иллюстрация 01",
        "kind": "scene",
        "notes": "Первая ключевая сцена: героя видно достаточно ясно.",
        "prompt": "Editorial illustration of the main character in the opening scene.",
        "negative_prompt": "",
        "x": 320,
        "y": 40
      },
      {
        "key": "b",
        "title": "Иллюстрация 02",
        "kind": "scene",
        "notes": "Продолжение темы; неизменные признаки героя и цветовая система.",
        "prompt": "Related scene, same character identity, matching illustration style.",
        "negative_prompt": "",
        "x": 580,
        "y": 40
      },
      {
        "key": "c",
        "title": "Иллюстрация 03",
        "kind": "scene",
        "notes": "Новая композиция в рамках той же визуальной серии.",
        "prompt": "Third scene with varied framing but same artistic visual language.",
        "negative_prompt": "",
        "x": 840,
        "y": 40
      },
      {
        "key": "out",
        "title": "Сверка серии",
        "kind": "output",
        "notes": "Сравни три результата, контраст, костюм и цвет; выбери финальные версии вручную.",
        "prompt": "",
        "negative_prompt": "",
        "x": 1100,
        "y": 40
      }
    ],
    "edges": [
      [
        "brief",
        "a"
      ],
      [
        "style",
        "a"
      ],
      [
        "character",
        "a"
      ],
      [
        "a",
        "b"
      ],
      [
        "b",
        "c"
      ],
      [
        "c",
        "out"
      ],
      [
        "style",
        "c"
      ]
    ]
  },
  {
    "id": "product_catalog",
    "title_ru": "Предметная съёмка — товар",
    "title_en": "Product photography — catalog",
    "category": "commercial",
    "summary_ru": "Главный ракурс, деталь и товар в контексте. Фиксируй форму продукта по эталонной фотографии.",
    "summary_en": "Hero shot, detail and lifestyle frame from one product reference.",
    "base_prompt": "Commercial product photography, accurate object silhouette, studio lighting, premium clean background.",
    "negative_prompt": "wrong product geometry, invented labels, extra objects, distorted details, watermark",
    "system_prompt": "Treat product identity and shape as constraints. A textual reference node does not itself attach an image: select an actual img2img reference in the rendering UI.",
    "nodes": [
      {
        "key": "brief",
        "title": "Требования к товару",
        "kind": "note",
        "notes": "Товар, аудитория, ключевые свойства, фон и размеры.",
        "prompt": "",
        "negative_prompt": "",
        "x": 40,
        "y": 40
      },
      {
        "key": "ref",
        "title": "Фото-эталон товара",
        "kind": "reference",
        "notes": "Описание точной геометрии. Изображение нужно отдельно загрузить в img2img для реального визуального контроля.",
        "prompt": "",
        "negative_prompt": "",
        "x": 40,
        "y": 185
      },
      {
        "key": "style",
        "title": "Свет и фон",
        "kind": "style",
        "notes": "Единая фотосхема, чистый фон, фактура и цвет.",
        "prompt": "",
        "negative_prompt": "",
        "x": 40,
        "y": 330
      },
      {
        "key": "hero",
        "title": "Главное фото",
        "kind": "scene",
        "notes": "Покажи товар целиком и без искажений.",
        "prompt": "Single product hero shot on a clean neutral background.",
        "negative_prompt": "",
        "x": 320,
        "y": 40
      },
      {
        "key": "detail",
        "title": "Крупный план",
        "kind": "scene",
        "notes": "Покажи материал и реальную деталь без выдуманной маркировки.",
        "prompt": "Close-up detail photograph of the same product and materials.",
        "negative_prompt": "",
        "x": 580,
        "y": 40
      },
      {
        "key": "life",
        "title": "В использовании",
        "kind": "scene",
        "notes": "Товар в контексте, идентичная форма и пропорции.",
        "prompt": "Lifestyle photograph featuring exactly the same product.",
        "negative_prompt": "",
        "x": 840,
        "y": 40
      },
      {
        "key": "out",
        "title": "Экспорт карточки товара",
        "kind": "output",
        "notes": "Проверить соответствие эталону, одинаковый цвет, отсутствие ложного текста, экспорт вручную.",
        "prompt": "",
        "negative_prompt": "",
        "x": 1100,
        "y": 40
      }
    ],
    "edges": [
      [
        "brief",
        "hero"
      ],
      [
        "ref",
        "hero"
      ],
      [
        "style",
        "hero"
      ],
      [
        "hero",
        "detail"
      ],
      [
        "ref",
        "detail"
      ],
      [
        "detail",
        "life"
      ],
      [
        "life",
        "out"
      ]
    ]
  },
  {
    "id": "portrait_character",
    "title_ru": "Персонаж — ракурсы и эмоции",
    "title_en": "Character sheet — angles and moods",
    "category": "art",
    "summary_ru": "Паспорт героя, эталон, портрет, полный рост и эмоция — основа для будущих сцен и LoRA.",
    "summary_en": "Character identity sheet, portrait, body and expression variations.",
    "base_prompt": "Consistent original character sheet, same face and costume, clear anatomy, clean presentation.",
    "negative_prompt": "face drift, inconsistent costume, extra arms, asymmetric eyes, watermark",
    "system_prompt": "Keep precise character identity in all outputs. Text-only reference nodes are not vision conditioning; use img2img or a compatible character LoRA when available.",
    "nodes": [
      {
        "key": "identity",
        "title": "Паспорт героя",
        "kind": "character",
        "notes": "Имя, лицо, рост, палитра одежды, уникальные признаки; замораживаем постоянные черты.",
        "prompt": "",
        "negative_prompt": "",
        "x": 40,
        "y": 40
      },
      {
        "key": "ref",
        "title": "Эталонный референс",
        "kind": "reference",
        "notes": "Перечисли обязательные свойства. Для повторения картинки загружай файл отдельно в img2img.",
        "prompt": "",
        "negative_prompt": "",
        "x": 40,
        "y": 190
      },
      {
        "key": "style",
        "title": "Стиль персонажа",
        "kind": "style",
        "notes": "Толщина линий, свет, оттенки, фон.",
        "prompt": "",
        "negative_prompt": "",
        "x": 40,
        "y": 340
      },
      {
        "key": "portrait",
        "title": "Портрет",
        "kind": "scene",
        "notes": "Фронтальный или 3/4 портрет; лицо и аксессуары строго по паспорту.",
        "prompt": "Head and shoulders portrait, same original character identity.",
        "negative_prompt": "",
        "x": 320,
        "y": 40
      },
      {
        "key": "body",
        "title": "В полный рост",
        "kind": "scene",
        "notes": "Сохрани пропорции и одежду; задай позу.",
        "prompt": "Full body pose of the same original character and costume.",
        "negative_prompt": "",
        "x": 580,
        "y": 40
      },
      {
        "key": "mood",
        "title": "Эмоция и действие",
        "kind": "scene",
        "notes": "Новая эмоция без смены лица и костюма.",
        "prompt": "Expressive pose of the same character, consistent anatomy.",
        "negative_prompt": "",
        "x": 840,
        "y": 40
      },
      {
        "key": "out",
        "title": "Лист персонажа",
        "kind": "output",
        "notes": "Сравни ракурсы. Несовпадения правь img2img или обученной LoRA; автоматической сборки нет.",
        "prompt": "",
        "negative_prompt": "",
        "x": 1100,
        "y": 40
      }
    ],
    "edges": [
      [
        "identity",
        "portrait"
      ],
      [
        "ref",
        "portrait"
      ],
      [
        "style",
        "portrait"
      ],
      [
        "portrait",
        "body"
      ],
      [
        "identity",
        "body"
      ],
      [
        "body",
        "mood"
      ],
      [
        "mood",
        "out"
      ]
    ]
  },
  {
    "id": "technical_diagram",
    "title_ru": "Техническая схема — архитектура",
    "title_en": "Technical diagram — architecture",
    "category": "technical",
    "summary_ru": "Требования, компоненты, связи, слои, окончательная схема. Подписи и точные стрелки проверяются вручную.",
    "summary_en": "Requirements, components, dependencies and diagram review.",
    "base_prompt": "Clean engineering schematic, neat blocks, legible hierarchy, high contrast, simple modular layout.",
    "negative_prompt": "invented ports, wrong wiring, illegible text, random circuits, unnecessary 3D, watermark",
    "system_prompt": "Do not invent physical wiring or specifications. Verify all links and labels against the engineer's data. Diffusion output is conceptual; manually overlay exact labels and connections.",
    "nodes": [
      {
        "key": "requirements",
        "title": "Техническое задание",
        "kind": "note",
        "notes": "Опиши компоненты, ограничения, реальные размеры/порты и инварианты; это источник истины.",
        "prompt": "",
        "negative_prompt": "",
        "x": 40,
        "y": 40
      },
      {
        "key": "inventory",
        "title": "Компоненты",
        "kind": "reference",
        "notes": "Список блоков и допустимых связей, схемы или чертежи из документации.",
        "prompt": "",
        "negative_prompt": "",
        "x": 40,
        "y": 190
      },
      {
        "key": "style",
        "title": "Условные обозначения",
        "kind": "style",
        "notes": "Блок-схема 2D, толщина линий, цветовая легенда, сетка.",
        "prompt": "",
        "negative_prompt": "",
        "x": 40,
        "y": 340
      },
      {
        "key": "topology",
        "title": "Топология",
        "kind": "scene",
        "notes": "Размести основные блоки и направления потока без свободной фантазии.",
        "prompt": "A clean conceptual block diagram of system architecture.",
        "negative_prompt": "",
        "x": 320,
        "y": 40
      },
      {
        "key": "flow",
        "title": "Связи и потоки",
        "kind": "prompt",
        "notes": "Проверь направление стрелок и названия каналов по ТЗ.",
        "prompt": "Diagram showing clear data flow arrows and grouped system modules.",
        "negative_prompt": "",
        "x": 580,
        "y": 40
      },
      {
        "key": "layers",
        "title": "Слои и подсистемы",
        "kind": "scene",
        "notes": "Раздели сеть, вычисления, хранение, питание или данные.",
        "prompt": "Layered infrastructure architecture visual diagram.",
        "negative_prompt": "",
        "x": 840,
        "y": 40
      },
      {
        "key": "out",
        "title": "Техническая проверка",
        "kind": "output",
        "notes": "Уточни реальные подписи и соединения вручную. Не используйте рисунок как проверенный проект платы.",
        "prompt": "",
        "negative_prompt": "",
        "x": 1100,
        "y": 40
      }
    ],
    "edges": [
      [
        "requirements",
        "topology"
      ],
      [
        "inventory",
        "topology"
      ],
      [
        "style",
        "topology"
      ],
      [
        "topology",
        "flow"
      ],
      [
        "flow",
        "layers"
      ],
      [
        "requirements",
        "layers"
      ],
      [
        "layers",
        "out"
      ]
    ]
  },
  {
    "id": "infographic",
    "title_ru": "Инфографика — данные и блоки",
    "title_en": "Infographic — facts and sections",
    "category": "communication",
    "summary_ru": "Сначала проверенные цифры, затем макет, два блока и итоговая композиция. Текст добавляется после генерации.",
    "summary_en": "Verified facts, layout, key visuals and final infographic assembly.",
    "base_prompt": "Editorial infographic design, grid-aligned blocks, restrained colors, generous white space, clean iconography.",
    "negative_prompt": "unverified figures, fake lettering, illegible labels, cluttered composition, watermark",
    "system_prompt": "Do not invent numbers, units or conclusions. Generate only decorative visual elements; put exact text and data into a separate vector or HTML editing stage.",
    "nodes": [
      {
        "key": "facts",
        "title": "Проверенные факты",
        "kind": "note",
        "notes": "Цифры, единицы измерения, источники; вручную проверить перед публикацией.",
        "prompt": "",
        "negative_prompt": "",
        "x": 40,
        "y": 40
      },
      {
        "key": "style",
        "title": "Сетка и палитра",
        "kind": "style",
        "notes": "Иерархия текста, пропорции 4:5, акцентные цвета, контраст.",
        "prompt": "",
        "negative_prompt": "",
        "x": 40,
        "y": 190
      },
      {
        "key": "structure",
        "title": "Композиция",
        "kind": "prompt",
        "notes": "Заголовок, вводный блок, ключевой график, заключение; место под текст.",
        "prompt": "Infographic visual hierarchy with empty text placeholders, icons and clear sections.",
        "negative_prompt": "",
        "x": 320,
        "y": 40
      },
      {
        "key": "visual",
        "title": "Главная иллюстрация",
        "kind": "scene",
        "notes": "Основной тематический рисунок без чисел и букв.",
        "prompt": "Minimal editorial hero illustration matching an infographic.",
        "negative_prompt": "",
        "x": 580,
        "y": 40
      },
      {
        "key": "panel",
        "title": "Дополнительные блоки",
        "kind": "slide",
        "notes": "Пиктограммы и визуальные сравнения; значения накладывай при верстке.",
        "prompt": "Simple coherent icon set and comparison blocks, no rendered words.",
        "negative_prompt": "",
        "x": 840,
        "y": 40
      },
      {
        "key": "out",
        "title": "Проверка и верстка",
        "kind": "output",
        "notes": "Собрать инфографику во внешнем редакторе, вставить точные числа и подписи.",
        "prompt": "",
        "negative_prompt": "",
        "x": 1100,
        "y": 40
      }
    ],
    "edges": [
      [
        "facts",
        "structure"
      ],
      [
        "style",
        "structure"
      ],
      [
        "structure",
        "visual"
      ],
      [
        "visual",
        "panel"
      ],
      [
        "facts",
        "panel"
      ],
      [
        "panel",
        "out"
      ]
    ]
  },
  {
    "id": "concept_art",
    "title_ru": "Концепт-арт — среда и варианты",
    "title_en": "Concept art — environment variations",
    "category": "art",
    "summary_ru": "От брифа к общей палитре, основной сцене, альтернативному свету и деталям мира.",
    "summary_en": "Environment brief, references, master scene, light variants and detail pass.",
    "base_prompt": "High-quality environment concept art, cohesive art direction, thoughtful lighting, consistent architectural forms.",
    "negative_prompt": "inconsistent architecture, disjoint scale, stretched perspective, random details, watermark",
    "system_prompt": "Keep location geometry and art direction consistent; vary one factor per branch (light, weather or camera) rather than redesigning everything.",
    "nodes": [
      {
        "key": "brief",
        "title": "Описание мира",
        "kind": "note",
        "notes": "Жанр, эпоха, функция пространства, узнаваемые формы.",
        "prompt": "",
        "negative_prompt": "",
        "x": 40,
        "y": 40
      },
      {
        "key": "ref",
        "title": "Референсы окружения",
        "kind": "reference",
        "notes": "Что точно сохраняем в архитектуре, фактурах и композиции.",
        "prompt": "",
        "negative_prompt": "",
        "x": 40,
        "y": 190
      },
      {
        "key": "style",
        "title": "Свет и палитра",
        "kind": "style",
        "notes": "Задай цвет, погоду, перспективу и уровень детализации.",
        "prompt": "",
        "negative_prompt": "",
        "x": 40,
        "y": 340
      },
      {
        "key": "master",
        "title": "Главный ракурс",
        "kind": "scene",
        "notes": "Зафиксируй читаемую геометрию сцены.",
        "prompt": "Wide establishing shot of a coherent original environment.",
        "negative_prompt": "",
        "x": 320,
        "y": 40
      },
      {
        "key": "light",
        "title": "Другая погода или свет",
        "kind": "scene",
        "notes": "Меняется только освещение или погода; геометрия та же.",
        "prompt": "The same environment in different cinematic lighting.",
        "negative_prompt": "",
        "x": 580,
        "y": 40
      },
      {
        "key": "detail",
        "title": "Крупный план окружения",
        "kind": "scene",
        "notes": "Покажи деталь пространства с той же палитрой и материалами.",
        "prompt": "Close-up environment concept detail in the same art direction.",
        "negative_prompt": "",
        "x": 840,
        "y": 40
      },
      {
        "key": "out",
        "title": "Согласование концепта",
        "kind": "output",
        "notes": "Сверить геометрию, выбор ракурсов и пригодность для 3D/иллюстрации.",
        "prompt": "",
        "negative_prompt": "",
        "x": 1100,
        "y": 40
      }
    ],
    "edges": [
      [
        "brief",
        "master"
      ],
      [
        "ref",
        "master"
      ],
      [
        "style",
        "master"
      ],
      [
        "master",
        "light"
      ],
      [
        "master",
        "detail"
      ],
      [
        "light",
        "out"
      ],
      [
        "detail",
        "out"
      ]
    ]
  }
]''')
VALID_KINDS = frozenset(("scene", "character", "style", "prompt", "reference", "note", "output", "lesson", "slide"))


def initialize_templates(connection: sqlite3.Connection) -> None:
    connection.execute("""
        CREATE TABLE IF NOT EXISTS studio_graph_templates (
            id TEXT PRIMARY KEY,
            title_ru TEXT NOT NULL,
            title_en TEXT NOT NULL,
            category TEXT NOT NULL,
            summary_ru TEXT NOT NULL,
            summary_en TEXT NOT NULL,
            schema_version INTEGER NOT NULL DEFAULT 1,
            definition_json TEXT NOT NULL,
            built_in INTEGER NOT NULL DEFAULT 1,
            updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        )
    """)
    for definition in BUILTIN_TEMPLATES:
        validate_template(definition)
        # Existing templates are never overwritten on application start.
        connection.execute("""
            INSERT OR IGNORE INTO studio_graph_templates (
                id,title_ru,title_en,category,summary_ru,summary_en,
                schema_version,definition_json,built_in
            ) VALUES(?,?,?,?,?,?,?,?,1)
        """, (
            definition["id"],definition["title_ru"],definition["title_en"],
            definition["category"],definition["summary_ru"],definition["summary_en"],
            SCHEMA_VERSION,json.dumps(definition,ensure_ascii=False),
        ))


def validate_template(template: dict) -> None:
    nodes = template["nodes"]
    keys = [node["key"] for node in nodes]
    if len(nodes) < 3 or len(nodes) > 24 or len(set(keys)) != len(keys):
        raise ValueError("Invalid graph template node count or duplicate keys")
    if not all(node["kind"] in VALID_KINDS and 0 <= node["x"] <= 5000
               and 0 <= node["y"] <= 5000 for node in nodes):
        raise ValueError("Invalid graph template node type or coordinates")
    if not all(a in keys and b in keys and a != b for a,b in template["edges"]):
        raise ValueError("Invalid graph template edge references")
    graph = {key: [] for key in keys}
    for a,b in template["edges"]:
        graph[a].append(b)
    colors = {}
    def visit(k):
        if colors.get(k) == 1:
            raise ValueError("Graph template contains a cycle")
        if colors.get(k) == 2:
            return
        colors[k] = 1
        for nxt in graph[k]:
            visit(nxt)
        colors[k] = 2
    for key in keys:
        visit(key)


def list_templates(connection: sqlite3.Connection) -> list[dict]:
    return [dict(row) for row in connection.execute("""
        SELECT id,title_ru,title_en,category,summary_ru,summary_en,
               schema_version,built_in
        FROM studio_graph_templates ORDER BY built_in DESC,id
    """)]


def get_template(connection: sqlite3.Connection, template_id: str) -> dict | None:
    row = connection.execute(
        "SELECT definition_json FROM studio_graph_templates WHERE id=?",
        (template_id,)
    ).fetchone()
    if row is None:
        return None
    template = json.loads(row["definition_json"])
    validate_template(template)
    return template
