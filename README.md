# 🎯 UBC Study Sniper

Automated UBC library room booking tool with a cyberpunk terminal UI. Scans LibCal across all UBC libraries and books rooms on your behalf — with a live animated gradient interface that runs the whole time.

![Python](https://img.shields.io/badge/python-3.11+-blue) ![Playwright](https://img.shields.io/badge/playwright-async-green) ![Arch](https://img.shields.io/badge/platform-linux-lightgrey)


<img width="2528" height="1507" alt="image" src="https://github.com/user-attachments/assets/70376ec4-99b1-451e-8837-6e638c641d04" />

---

## Features

- **Auto mode** — finds and books the next available room across all libraries instantly
- **Manual mode** — pick a library, give a time range, see every bookable slot and room laid out, then pick oneram
- **Smart suggestions** — shows similar rooms and nearby time slots when your preferred time is taken

## Libraries Supported

| # | Library |
|---|---------|
| 1 | Irving K. Barber Learning Centre (IKB) |
| 2 | Koerner Library |
| 3 | Woodward Library |
| 4 | Music, Art & Architecture (MAA) Library |

---

## Requirements

- Python 3.11+
- A UBC CWL account with library booking access
- Chromium (installed via Playwright)

---

## Setup

**1. Clone the repo**
```bash
git clone git@github.com:angelogiu/StudySniper.git
cd StudySniper
```

**2. Create a virtual environment and install dependencies**
```bash
python -m venv .venv
source .venv/bin/activate.fish   # fish shell
# or: source .venv/bin/activate  # bash/zsh

pip install playwright python-dotenv
playwright install chromium
```

**3. Create your `.env` file**
```bash
cp .env.example .env
```

Edit `.env` with your credentials:
```
UBC_USERNAME=your_cwl_username
UBC_PASSWORD=your_password
BOOKING_DURATION_HOURS=1
DEBUG_SHOTS=false
```

> ⚠️ Never commit your `.env` file. It's in `.gitignore` by default.

---

## Usage

```bash
python main.py
```

### Home Screen

```
[1]  AUTO    — instantly book the next available room
[2]  MANUAL  — choose library, time range, and preferences
[3]  EXIT    — quit Study Sniper
```

### Auto Mode
Calculates the next whole hour slot, scans all 4 libraries in order, and books the first available room it finds.

### Manual Mode
1. Pick a library
2. Enter a date
3. Enter a time range (e.g. `09:00` to `17:00`)
4. Optionally filter by keyword (room number, floor, etc.)
5. See every available slot and room listed out
6. Pick a number to book

### CWL Login
When the booking page requires authentication, a banner appears and a browser window comes to the front. Log in with your CWL credentials and complete Duo MFA — the script resumes automatically once you're authenticated.

---

## Disclaimer

This tool is for personal convenience only. Make sure your use complies with UBC Library's booking policies. Don't use it to hoard rooms.
