# Football Predictor — WC 2026

Mobile-first football match prediction app with Hebrew RTL UI, Python FastAPI backend, and Dixon-Coles goal model calibrated on World Cup 2022.

## Architecture

```
Flutter (mobile/web)  ←→  FastAPI (Python)
                              ├── math_engine.py      Dixon-Coles + Poisson/NB
                              ├── team_power.py       Elo decomposition
                              ├── elo_updater.py      Dynamic rating updates
                              ├── tournament_sim.py   Monte Carlo groups + champion
                              ├── backtest.py         WC 2022 evaluation
                              └── data/
                                  ├── database.py     48 official WC 2026 teams
                                  ├── api_football.py Optional live stats
                                  └── wc2022.py       Historical backtest data
```

## Quick Start

### Backend
```powershell
cd my_football_predictor
.\start_backend.ps1 -Port 8001
```

Optional live stats:
```powershell
$env:API_FOOTBALL_KEY = "your-key"
```

### Flutter (Chrome / Android)
```powershell
cd mobile
flutter run -d chrome
```

API URL in settings: `http://127.0.0.1:8001`

## API Endpoints

| Method | Path | Description |
|--------|------|-------------|
| GET | `/api/health` | Server status + live stats availability |
| GET | `/api/teams` | 48 teams list |
| GET | `/api/groups` | Groups A–L with Elo |
| GET | `/api/teams/info?name=` | Team group + Elo |
| POST | `/api/predict` | Match prediction (1X2, top-10 scores, coverage band) |
| POST | `/api/elo/update` | Update Elo after real result |
| POST | `/api/simulate/group` | Monte Carlo group standings |
| POST | `/api/simulate/champion` | Tournament winner odds |

## Model (v1.6 — WC 2022 calibrated)

| Parameter | Value |
|-----------|-------|
| Dixon-Coles ρ | −0.15 |
| Avg goals | 3.0 |
| Overdispersion α | 0.0 |
| Home advantage | 0 (neutral WC default) |
| Power formula | 45% Elo + 25% Form + 15% Attack − 15% Defense |

## Backtesting

```powershell
cd backend
python run_backtest.py
python run_calibrate.py
pytest tests/ -v
```

**WC 2022 results (calibrated):** 57.8% 1X2 · 12.5% exact score · 37.5% top-3 hit rate
