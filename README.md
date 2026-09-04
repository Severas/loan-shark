# 🛡️ CTA Attendance — Albion Online

<p align="center">
  <img src="https://img.shields.io/badge/Python-3.10+-blue?logo=python">
  <img src="https://img.shields.io/badge/OS-Linux%20%7C%20Windows-green">
  <img src="https://img.shields.io/badge/Status-In%20development-orange">
  <img src="https://img.shields.io/badge/License-MIT%20(partial)-yellow">
</p>

---

## 📌 About the Project

Attendance tracking and fine system for guild CTAs (Call To Arms) in Albion
Online. From in-game party screenshots, the system:

- Automatically detects the party members and the author on screen
- Runs OCR on each name and corrects it against the guild's roster
- Cross-references detected attendees with the roster (`Last Seen` time and roles) to apply fine rules
- Exports a CSV report ready for the guild's records

The project was created to replace manual attendance checking, which was
slow and error-prone, with an automated pipeline from the screenshots the
CTA leader already takes.

> ⚠️ **This repository is not fully open source.** The detection and
> name-matching internals are closed-source, kept as the technical
> foundation of the commercial **Loan Shark** bot (see [License](#-license)).
> What's published here is the pipeline orchestration — CLI, fine rules,
> data format — which is enough to understand how the system works end to
> end.

---

## 🚀 Quick Navigation

- [📂 Structure](#-project-structure)
- [⚙️ Installation](#️-installation)
- [📄 roster.tsv format](#-rostertsv-format)
- [▶️ Usage](#️-usage)
- [🧠 How the pipeline works](#-how-the-pipeline-works)
- [💰 Fine rules](#-fine-rules)
- [📊 Sample output](#-sample-output)
- [❗ Common issues](#-common-issues)
- [🗺️ Roadmap](#️-roadmap)
- [📄 License](#-license)

---

## 📂 Project Structure

```
cta-attendance/
│
├── cta_run.py            # CLI: orchestrates the whole pipeline
├── cta_attendance.py     # OCR + name correction per image
├── cta_fines.py          # Fine rules (roster x attendance x time)
├── roster.example.tsv     # Sample roster exported from the guild
├── requirements.txt
├── README.md
└── LICENSE
```

Two internal modules the pipeline depends on (screenshot region detection
and fuzzy name matching) are closed-source and not included in this
repository — see [License](#-license).

---

## ⚙️ Installation

### Arch Linux

```bash
sudo pacman -S python python-pip
python -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

### Windows

1. Install Python: https://www.python.org/downloads/ (check **Add Python to PATH**)

```bash
python -m venv venv
venv\Scripts\activate
pip install -r requirements.txt
```

### OCR engine

The system uses a single OCR engine: **RapidOCR** (`rapidocr-onnxruntime`) —
lightweight, ONNX, no torch/CUDA. There's no fallback chain trying multiple
engines one after another; that used to cost memory and time importing
libraries (like EasyOCR's torch dependency) that were rarely the one
actually needed.

---

## 📄 roster.tsv format

Tab-separated `.tsv` file with a header, in the format:

```
nome	last_seen	roles
LuckySeveras	Online	VIP
Artemix666	07/07/2026 01:19:03	
RyuVex	07/06/2026 22:40:11	VIP AVALON
```

- **nome**: exact nickname as it appears in the guild roster
- **last_seen**: `MM/DD/YYYY HH:MM:SS` or `Online` when the player is connected
- **roles**: roles separated by `;` (e.g. `VIP;Recruiter`). Players with `VIP` or `VIP AVALON` are exempt from absence fines

---

## ▶️ Usage

```bash
python cta_run.py roster.tsv \
  --cta "07/07/2026 21:00:00" \
  party1.png party2.png \
  --record "07/07/2026 21:20:00" \
  --grace 15 \
  --presentes Fulano Ciclano \
  --csv relatorio.csv \
  --multa 500000
```

| Argument | Description |
|---|---|
| `roster` | path to `roster.tsv` |
| `imagens` | one or more CTA party screenshots |
| `--cta` | CTA start time (`MM/DD/YYYY HH:MM:SS`) |
| `--record` | time the roster was exported (optional; uses the roster's highest `Last Seen` if omitted) |
| `--grace` | minutes before the start that already count as a no-show (default: 15) |
| `--presentes` | manually provided attendee names, complementing OCR |
| `--csv` | path to export the report as CSV |
| `--multa` | fine amount per fined player, used only for export |
| `--limiar` | fuzzy matching threshold (0-100); can be safely lowered in pool mode |
| `--debug` | shows what OCR read on each strip, useful for tuning |
| `--json` | prints the full report as JSON |

---

## 🧠 How the pipeline works

1. The relevant regions of the screenshot (author + party members) are detected automatically, regardless of resolution or whether the image is a full screen capture or a crop.
2. `cta_attendance.py` crops each detected name and runs OCR, with a few preprocessing variants tried only until a read is confident enough — this keeps OCR calls low on large parties or multiple screenshots.
3. Each read name is corrected against the guild roster (or a restricted pool of plausible candidates) via fuzzy matching, with unique assignment per player.
4. `cta_fines.py` cross-references the resulting attendee list with the full roster, `Last Seen`, the grace window, and exempt roles, to classify each player as present, fined, VIP-exempt, or not expected to attend.
5. `cta_run.py` orchestrates all of the above from the command line and generates the final report (text, JSON, or CSV).

---

## 💰 Fine rules

A player is **fined** when they are not in the party and:

- they are `Online` in the roster (they should have joined the group), or
- their `Last Seen` falls within the window `[CTA start - grace .. record time]`

A player is **exempt** when they hold the `VIP` or `VIP AVALON` role.

A player is **not expected** when their `Last Seen` predates the grace window (they were offline well before the CTA started).

---

## 📊 Sample output

```
== CTA 07/07/2026 21:00:00 | window since 07/07/2026 20:45:00 | record 07/07/2026 21:20:00 ==

PRESENT (9): Artemix666, DRACKOVI, Domeuno, BadZimmer, LuckySeveras, ...

FINED (2):
  LuizMeireles       left_up_to_15min_before_start      07/07/2026 18:04:00
  yura7642             online_outside_the_party           Online

VIP-EXEMPT absent (1): RyuVex

NOT EXPECTED (offline before the window): 4
```

---

## ❗ Common issues

**No OCR engine installed**
```bash
pip install rapidocr-onnxruntime
```

**OCR frequently misreads names**
- Run with `--debug` to see exactly what each strip returned before fuzzy correction
- Safely lower `--limiar` when using the pool mode (`--cta`/roster already restrict the plausible candidates)

**Fails to detect the party or the author in the image**
- Make sure the screenshot shows both clearly, without other UI elements overlapping

---

## 🤖 Coming next: the "Loan Shark" Discord bot

This project is the technical foundation of **Loan Shark**, a Discord bot in
development for the guild, with automatic fine collection, administrative
and social features, and Discord integrations. The bot is planned to become
a commercial product (monthly subscription) and is maintained in a separate,
closed repository, outside the scope of this project.

---

## 🗺️ Roadmap

- [ ] Support for multiple side-by-side party columns on ultrawide screens
- [ ] Simple interface for manual review of low-score name reads
- [ ] Automated tests with a reference set of screenshots
- [ ] Turn the pipeline into a Discord bot (Loan Shark): automatic fine collection, administrative and social features

---

## 👨‍💻 Author

David Marcelo Gois
GitHub: https://github.com/Severas

---

## 📄 License

This repository is licensed under **MIT**, covering `cta_run.py`,
`cta_attendance.py`, and `cta_fines.py`.

The screenshot-detection and name-matching internals, as well as the
**Loan Shark** bot once published, are closed-source and not covered by
this license.
