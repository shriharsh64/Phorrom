"""Curated free / open-source resource & learning catalog.

Problem solved: the local-first fallback for the Resource & Tooling Advisor. Even with no
working model (offline, or the LLM returned junk), the advisor must still surface genuinely
useful, free resources and a prerequisite-ordered learning plan. This is hand-maintained data,
not code — extend it freely.

Focus is **ideation & understanding**: every domain includes a "understand the problem space"
angle, and learning links are ordered prerequisite-first (lower ``order`` = earlier).
"""

from __future__ import annotations

from typing import TypedDict


class Link(TypedDict):
    title: str
    source: str  # youtube|arxiv|freecodecamp|mdn|docs|other
    url: str


class ConceptEntry(TypedDict):
    name: str
    order: int
    rationale: str
    links: list[Link]


class ResourceEntry(TypedDict):
    kind: str  # library|api|dataset|hardware|service|tool
    name: str
    stage: str
    url: str
    rationale: str


class DomainEntry(TypedDict):
    match: list[str]
    resources: list[ResourceEntry]
    concepts: list[ConceptEntry]


# Always included — the heart of "ideation & understanding".
FOUNDATIONS: list[ConceptEntry] = [
    {
        "name": "Problem-domain research & framing",
        "order": 0,
        "rationale": "Understand the space well enough to ideate: who has the problem, what's been tried, where the gap is.",
        "links": [
            {"title": "How to do a literature / prior-art landscape", "source": "arxiv", "url": "https://arxiv.org/"},
            {"title": "Design Thinking crash course", "source": "youtube", "url": "https://www.youtube.com/results?search_query=design+thinking+crash+course"},
        ],
    },
    {
        "name": "Structured ideation techniques",
        "order": 1,
        "rationale": "Generate and evaluate ideas systematically (SCAMPER, How-Might-We, feasibility vs novelty).",
        "links": [
            {"title": "IDEO / Stanford d.school method cards", "source": "docs", "url": "https://dschool.stanford.edu/resources"},
            {"title": "SCAMPER ideation explained", "source": "youtube", "url": "https://www.youtube.com/results?search_query=SCAMPER+ideation"},
        ],
    },
]

GENERAL_RESOURCES: list[ResourceEntry] = [
    {"kind": "dataset", "name": "Hugging Face Datasets", "stage": "research", "url": "https://huggingface.co/datasets", "rationale": "Thousands of free, ready datasets across modalities."},
    {"kind": "dataset", "name": "Kaggle Datasets", "stage": "research", "url": "https://www.kaggle.com/datasets", "rationale": "Free community datasets + notebooks to learn from."},
    {"kind": "api", "name": "public-apis (free APIs index)", "stage": "prototyping", "url": "https://github.com/public-apis/public-apis", "rationale": "Curated list of free public APIs by category."},
    {"kind": "service", "name": "GitHub (repos + Actions CI)", "stage": "all", "url": "https://github.com", "rationale": "Free version control, CI, and hosting for open-source."},
]


CATALOG: dict[str, DomainEntry] = {
    "python": {
        "match": ["python", "fastapi", "flask", "django", "pandas", "numpy"],
        "resources": [
            {"kind": "library", "name": "Python standard library", "stage": "all", "url": "https://docs.python.org/3/", "rationale": "Batteries-included, free."},
            {"kind": "library", "name": "pandas", "stage": "prototyping", "url": "https://pandas.pydata.org/docs/", "rationale": "Tabular data wrangling."},
        ],
        "concepts": [
            {"name": "Python fundamentals", "order": 2, "rationale": "Core language to build anything in this stack.", "links": [
                {"title": "freeCodeCamp — Python full course", "source": "freecodecamp", "url": "https://www.youtube.com/watch?v=rfscVS0vtbw"},
                {"title": "Official Python tutorial", "source": "docs", "url": "https://docs.python.org/3/tutorial/"},
            ]},
        ],
    },
    "ml": {
        "match": ["ml", "machine learning", "pytorch", "tensorflow", "scikit", "sklearn", "model", "classifier", "regression", "neural"],
        "resources": [
            {"kind": "library", "name": "scikit-learn", "stage": "prototyping", "url": "https://scikit-learn.org/stable/", "rationale": "Classical ML, great for small data."},
            {"kind": "library", "name": "PyTorch", "stage": "prototyping", "url": "https://pytorch.org/tutorials/", "rationale": "Deep learning, free + open-source."},
            {"kind": "dataset", "name": "UCI ML Repository", "stage": "research", "url": "https://archive.ics.uci.edu/", "rationale": "Classic free benchmark datasets."},
        ],
        "concepts": [
            {"name": "ML foundations", "order": 2, "rationale": "Understand supervised vs unsupervised, train/test, overfitting before ideating ML features.", "links": [
                {"title": "Google ML Crash Course", "source": "docs", "url": "https://developers.google.com/machine-learning/crash-course"},
                {"title": "fast.ai — Practical Deep Learning", "source": "docs", "url": "https://course.fast.ai/"},
            ]},
            {"name": "Model evaluation & metrics", "order": 3, "rationale": "Know how to judge whether an idea is feasible/measurable.", "links": [
                {"title": "scikit-learn model evaluation guide", "source": "docs", "url": "https://scikit-learn.org/stable/modules/model_evaluation.html"},
            ]},
        ],
    },
    "nlp": {
        "match": ["nlp", "language", "text", "llm", "chatbot", "summariz", "transformer", "embedding"],
        "resources": [
            {"kind": "library", "name": "Hugging Face Transformers", "stage": "prototyping", "url": "https://huggingface.co/docs/transformers", "rationale": "Open models + pipelines, free."},
            {"kind": "service", "name": "Ollama (local LLMs)", "stage": "prototyping", "url": "https://ollama.com/", "rationale": "Run open LLMs locally at ₹0."},
        ],
        "concepts": [
            {"name": "How language models work", "order": 2, "rationale": "Understand tokens, context windows, and embeddings to ideate realistic LLM features.", "links": [
                {"title": "Hugging Face NLP Course", "source": "docs", "url": "https://huggingface.co/learn/nlp-course"},
                {"title": "Attention Is All You Need", "source": "arxiv", "url": "https://arxiv.org/abs/1706.03762"},
            ]},
        ],
    },
    "cv": {
        "match": ["vision", "image", "opencv", "detection", "camera", "ocr", "video"],
        "resources": [
            {"kind": "library", "name": "OpenCV", "stage": "prototyping", "url": "https://docs.opencv.org/", "rationale": "Free, comprehensive computer vision."},
            {"kind": "library", "name": "Tesseract OCR", "stage": "prototyping", "url": "https://github.com/tesseract-ocr/tesseract", "rationale": "Open-source OCR."},
        ],
        "concepts": [
            {"name": "Computer vision basics", "order": 2, "rationale": "Understand pixels, filters, and detection vs classification before scoping vision ideas.", "links": [
                {"title": "OpenCV Python tutorials", "source": "docs", "url": "https://docs.opencv.org/4.x/d6/d00/tutorial_py_root.html"},
            ]},
        ],
    },
    "web": {
        "match": ["web", "react", "frontend", "javascript", "typescript", "node", "ui", "dashboard"],
        "resources": [
            {"kind": "library", "name": "React", "stage": "prototyping", "url": "https://react.dev/learn", "rationale": "Free, dominant UI library."},
            {"kind": "library", "name": "Vite", "stage": "prototyping", "url": "https://vitejs.dev/", "rationale": "Fast free build tool."},
        ],
        "concepts": [
            {"name": "Web fundamentals (HTML/CSS/JS)", "order": 2, "rationale": "Needed to ideate and prototype any user-facing interface.", "links": [
                {"title": "MDN Web Docs — Learn", "source": "mdn", "url": "https://developer.mozilla.org/en-US/docs/Learn"},
                {"title": "freeCodeCamp — Responsive Web Design", "source": "freecodecamp", "url": "https://www.freecodecamp.org/learn/2022/responsive-web-design/"},
            ]},
        ],
    },
    "iot": {
        "match": ["iot", "sensor", "arduino", "raspberry", "esp32", "hardware", "embedded", "robot"],
        "resources": [
            {"kind": "hardware", "name": "ESP32 dev board", "stage": "prototyping", "url": "https://www.espressif.com/en/products/socs/esp32", "rationale": "Cheap WiFi/BLE microcontroller for IoT prototypes."},
            {"kind": "hardware", "name": "Raspberry Pi", "stage": "prototyping", "url": "https://www.raspberrypi.com/documentation/", "rationale": "Low-cost edge compute."},
            {"kind": "tool", "name": "Arduino IDE", "stage": "prototyping", "url": "https://www.arduino.cc/en/software", "rationale": "Free firmware toolchain."},
        ],
        "concepts": [
            {"name": "Embedded & sensor basics", "order": 2, "rationale": "Understand sampling, GPIO, and power limits to scope feasible hardware ideas.", "links": [
                {"title": "Random Nerd Tutorials (ESP32)", "source": "docs", "url": "https://randomnerdtutorials.com/projects-esp32/"},
            ]},
        ],
    },
    "data": {
        "match": ["data", "etl", "analytics", "sql", "database", "pipeline", "visualization"],
        "resources": [
            {"kind": "library", "name": "SQLite", "stage": "all", "url": "https://www.sqlite.org/docs.html", "rationale": "Zero-config local database, free."},
            {"kind": "tool", "name": "Kaggle Learn", "stage": "research", "url": "https://www.kaggle.com/learn", "rationale": "Free short courses on data skills."},
        ],
        "concepts": [
            {"name": "Data handling & SQL", "order": 2, "rationale": "Understand how to source, store, and query data your idea depends on.", "links": [
                {"title": "Kaggle — Intro to SQL", "source": "docs", "url": "https://www.kaggle.com/learn/intro-to-sql"},
            ]},
        ],
    },
}
