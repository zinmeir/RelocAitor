# 🌍 AI Global Relocation Intelligence System

An interactive, AI-powered decision-support web application that recommends the best countries to relocate to based on personalized user preferences, with curated visa pathway data and a real 3D-pop-out world map.

Built with **Flask + vanilla JavaScript + SVG** — no bulky frontend frameworks, no Streamlit limitations. Fast, smooth, production-grade.

---

## ✨ Features

### Core
- **66 countries** across 7 regions, **9 weighted factors** per country
- **Real country shapes** rendered from public-domain world map GeoJSON
- **True 3D hover pop-out** — countries lift, scale, and glow with CSS 3D transforms
- **Real-time scoring** — every slider change debounces and re-queries the Flask backend

### Scoring factors
| Factor | Description |
|---|---|
| 💰 Salary | Average earnings potential |
| 🛒 Cost of living | Lower is better |
| 🛂 PR ease | Path to permanent residency |
| 💼 Job market | Strength of employment opportunities |
| ☀️ Climate | Climate quality and livability |
| 🛡️ Safety | Personal safety and security |
| 🏥 Healthcare | Healthcare system quality |
| 🗣️ English | English proficiency among locals |
| 🌐 Internet | Internet speed and infrastructure |

### Visa pathways
- **Curated visa data** for all 66 countries (skilled, nomad, investor, study, startup routes)
- Each visa has: difficulty, duration, PR pathway, minimum income, summary
- **Filter by visa type** — see only countries with the visa class you want
- **Color-coded** by category and difficulty

### Insights
- **Rule-based AI reasoning** — explanations, trade-off analysis, user-profile insights
- **Similar-country suggestions** — Euclidean nearest-neighbor matching across all 9 features
- **Click-through navigation** — click similar-country cards to dive into their insights too

### UX polish
- **Reset button** to restore defaults
- **Score categorization** — High / Medium / Low badges
- **Full ranking table** with all 9 metrics for all 66 countries
- **Region filter** — narrow to one continent
- **Dark neon theme** with smooth animations everywhere

---

## 🚀 Running Locally

### Easiest: double-click `run.bat`

The included `run.bat` handles everything: creates the venv, installs dependencies, starts the server, and opens your browser.

### Manual

```bash
cd relocator
python -m venv venv
venv\Scripts\activate         # Windows
# source venv/bin/activate    # Mac/Linux
pip install -r requirements.txt
python app.py
```

Then visit **http://localhost:5000**.

---

## 📁 Project Structure

```
relocator/
├── run.bat                 # One-click setup & run (Windows)
├── app.py                  # Flask backend + API endpoints
├── data.py                 # 66 countries × 10 metrics
├── visas.py                # Curated visa pathways
├── scoring.py              # Weighted scoring + similarity
├── reasoning.py            # Rule-based AI reasoning
├── requirements.txt
├── README.md
├── templates/
│   └── index.html
└── static/
    ├── css/style.css
    └── js/
        ├── countries.js    # World GeoJSON loader
        ├── map.js          # Map rendering & interactions
        └── app.js          # Main controller
```

---

## 🧠 How It Works

### Backend (Flask)

| Endpoint | Purpose |
|---|---|
| `GET /` | Renders `index.html` |
| `POST /api/score` | Returns ranked countries given weights + region + top_n |
| `POST /api/insights` | Returns explanation, tradeoffs, similar countries, visas for one country |
| `POST /api/visas` | Standalone visa lookup with type/difficulty filtering |

### Scoring formula

```
score = Σ (w_i / Σw) × value_i
```

Where each `value_i` is the country's normalized [0,1] score for factor *i*, except for `cost` which is inverted (`1 - cost`) since the user wants low cost. Final score is min-max normalized to [0, 1] for display.

### Frontend
- **`countries.js`** fetches `world-atlas` TopoJSON, projects with `d3-geo` to a 1000×500 SVG viewBox, returns SVG path strings keyed by ISO-3
- **`map.js`** renders all paths, wires hover/click handlers, manages the floating tooltip
- **`app.js`** owns app state, debounces slider input, coordinates API calls + rendering

---

## 📝 Data Disclaimer

All numerical data is normalized approximations for demonstration purposes. Visa information is illustrative — verify with official immigration authorities (or a licensed immigration lawyer) before acting on it.

---

## 🛠️ Tech Stack

| Layer | Tech |
|---|---|
| Backend | Flask, Pandas, NumPy |
| Frontend | Vanilla JavaScript (ES modules), SVG, CSS 3D transforms |
| Map data | topojson/world-atlas (public domain), d3-geo for projection |
| Fonts | Inter, JetBrains Mono (Google Fonts) |

No React, no Vue, no build step, no bundler. Just open and run.

---

## 📄 License

MIT
