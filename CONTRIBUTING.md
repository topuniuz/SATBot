# 🤝 Contributing to SATBot

Thank you for your interest in contributing to **SATBot**! We welcome contributions from developers, educators, and SAT tutors to make SATBot the ultimate testing companion for students worldwide.

---

## 🛠 Getting Started

### 1. Fork & Clone
```bash
git clone https://github.com/topuniuz/SATBot.git
cd SATBot
```

### 2. Environment Setup
```bash
python3 -m venv venv
source venv/bin/activate  # Windows: venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env
```

### 3. Run the Test Suite
Ensure all existing unit tests pass before making any changes:
```bash
python3 test_bot.py
```

---

## 📋 Contribution Guidelines

1. **Feature Branching**:
   - Create a dedicated branch for your change:
     ```bash
     git checkout -b feature/your-feature-name
     # or
     git checkout -b fix/your-bug-fix
     ```

2. **Code Standards**:
   - Follow standard **PEP 8** style guidelines.
   - Keep asynchronous code non-blocking (`async`/`await`).
   - SQLite queries should use parameterized values to prevent SQL injection.

3. **Updating Official SAT Dates**:
   - When College Board announces new test dates, update `SAT_SCHEDULE` in `config.py`.
   - Verify date entries against [satsuite.collegeboard.org](https://satsuite.collegeboard.org/scores/score-release-dates).

4. **Testing**:
   - Add test cases in `test_bot.py` covering new functions or routes.
   - Run `python3 test_bot.py` to confirm 100% pass rate.

5. **Submitting a Pull Request**:
   - Push your branch to your fork.
   - Open a Pull Request against the `main` branch with a clear title and description of your changes.

---

## 🌟 Areas Where We Welcome Help
- 🌍 Adding new localized language templates (Uzbek, Russian, Spanish, Turkish, etc.)
- 📱 Developing rich Telegram Mini Apps (Web Apps) for visual countdowns
- 📊 Improving Early Score Release detection heuristics
- 🎒 Expanding test-day strategy checklists and Desmos tips

Thank you for helping students worldwide excel on their SAT! 🚀
