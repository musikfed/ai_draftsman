# PEGINELAB AI Draftsman — универсальная архитектура

## Основной принцип

Универсальная студия в обычном браузере, независимо от предметной области. Никакого заранее заданного числа узлов, сцен или кадров. Karate Linux — **подключаемый шаблон**, а не встроенная предметная модель.

### Компоненты

```text
Browser 192.168.0.100:9898 (HTML + vanilla JS, без polling)
  ├── Project editor: имя, brief, базовый / негативный prompt, LLM system prompt
  ├── Editable graph canvas: узлы / связи / координаты / статусы
  ├── Prompt inspector: что создать, исключения, контекст предков
  ├── LLM manager: список установленных Ollama, ручной pull, статус
  ├── Reference library: PNG/JPG/WEBP и совместимые SDXL LoRA
  ├── Image parameters: mode, variants, resolution, seed, steps, CFG, strength
  └── On-demand telemetry CPU/RAM/VRAM/SWAP/disks/zombies
         |
Flask (Python 3.12 + uv, лёгкий процесс)
  ├── SQLite: projects / nodes / edges / per-project knowledge FTS5
  ├── GraphRetriever: обход входящих связей с ограничением глубины и циклов
  ├── Prompt assembler: project + connected nodes + selected node + negative
  ├── Ollama client: выбранная проектом LLM, JSON draft и explicit /api/pull
  └── GPU job dispatcher
         |
Dedicated subprocess: python -m studio.worker
  └── PyTorch + Diffusers + SDXL + optional LoRA → master PNG + PNG-8
      (после завершения процесс и CUDA-контекст прекращаются)
```

## Схема данных

- `studio_projects`: независимые проекты, описание, base_prompt, negative_prompt, system_prompt, llm_model, kind
- `studio_nodes`: тип, название, заметки, prompt/negative_prompt, x/y, статус draft/approved, последний job
- `studio_edges`: направленные связи между узлами **одного проекта** (циклы допустимы, обход защищён от них)
- `studio_knowledge`: проектная полнотекстовая FTS5 память; UTF-8 TXT/MD
- Старые таблицы `slides/rag/rag_fts` остаются для совместимости; удалять или заменять их не нужно.

Режим шаблона Karate импортирует главы в отдельный проект. По кнопке на главе можно подтянуть отдельные существующие слайды; личные старые данные не подменяются.

## Как работает LLM-агент

1. Пользователь выбирает узел и заполняет описание и/или сам prompt.
2. Сервер читает проектный **system prompt** и общий визуальный стиль.
3. Обходит входящие рёбра выбранного узла (до 5 уровней, ограниченный набор), формирует контекст из родительских узлов.
4. Выбирает до четырёх подходящих фрагментов TXT/MD знаний внутри этого же проекта.
5. Отправляет эти данные выбранной локальной LLM по Ollama `/api/chat`.
6. Полученный JSON: `prompt`, `negative_prompt`, `explanation`; записывает **только черновик выбранного узла**, не перестраивает весь граф самостоятельно.
7. Пользователь проверяет и утверждает. Генерация рисунка происходит отдельно.

Система помогает следовать плану, но **LLM не может гарантировать соблюдение всех ограничений**. Детализированный валидатор канона, контроль поз/персонажей, векторный поиск и обучение LoRA — дальнейшие модули.

## Изображения

- Отдельный рабочий Python-venv с CUDA 12.4, PyTorch и Diffusers; Flask без импортов GPU-библиотек.
- Выбираемые SDXL-модели Illustrious XL 2.0 и SDXL Base 1.0, один reference в img2img и optional SDXL LoRA, 1–48 вариантов **одного узла**, исходные размеры 768×960 или 896×1120.
- Output 800×1000 indexed PNG-8 (до 256 цветов) + полноцветный master.
- Ни модель, ни GPU процесс не запускаются при открытии панели.
- LLM Ollama и изображения — отдельные модели и разные задачи.
- Чтобы не портить другие программы, GPU-контекст освобождается после завершения отдельного image worker; кнопка VRAM только запрашивает выгрузку Ollama при отсутствии активных рендеров.

## Хранение и защита существующей среды

- Каталог: `/1tbdisk/PegineLab/ai_draftsman`; не изменять mount permissions.
- `data/draftsman.db`, `data/jobs`, `data/references`, `data/huggingface`, `models/`, `runtime/gpu-venv` не коммитятся в Git.
- Системные драйверы NVIDIA, Ollama, Docker, WireGuard, другие проекты не меняются.
- `OLLAMA_MODELS` студия не переопределяет: загрузка LLM через Ollama идёт в **каталог, уже настроенный для её службы**. Проверить свободное место на этом диске до новых больших загрузок.
- Тестовый LAN на 9898 без авторизации, не публиковать наружу.

## Действительно реализовано

- Проекты и CRUD, настраиваемые узлы и связи, координаты, drag graph
- Ручной выбор LLM + explicit pull + progress
- Общий положительный/отрицательный и узловой positive/negative prompt
- Графовый контекст + проектный FTS5 RAG и JSON draft с Ollama
- Image job запуск Diffusers и варианты, предпросмотр, мониторинг
- Тесты общего графа на временной SQLite

Не сделано: multi-reference beyond 1 img2img, векторный RAG, визуальные embeddings, LoRA training, полный автоматический конвейер комиксов и надписи поверх изображений. Реальный GPU inference на Huananzhi ещё не проверен.
