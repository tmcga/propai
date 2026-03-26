# Contributing to PropAI

Thanks for your interest in contributing. PropAI is an open-source project and community contributions are what make it better.

## Ways to contribute

- **Bug reports** — open a GitHub issue with steps to reproduce
- **Financial model improvements** — corrections, additional metrics, new asset class logic
- **New data source integrations** — additional free market data APIs
- **Frontend components** — React UI for deal input, charts, memo viewer
- **Jupyter notebooks** — demo notebooks showing real deal analysis
- **Documentation** — improve setup guides, add examples, fix typos
- **Tests** — additional coverage for edge cases and new features

## Getting started

```bash
git clone https://github.com/your-org/propai.git
cd propai

# Backend
cd backend
python -m venv venv && source venv/bin/activate
pip install -r requirements.txt
uvicorn main:app --reload    # http://localhost:8000/docs

# Run tests before and after your changes
pytest tests/ -v
```

## Code style

- Python: follow PEP 8, use type hints throughout
- Docstrings on every public function — include the real estate formula or concept being implemented
- Financial engine functions should be pure (no side effects, no I/O)
- API clients should handle errors gracefully and never raise on missing data

## Pull request checklist

- [ ] Tests pass: `pytest tests/ -v`
- [ ] New code has type hints
- [ ] New financial formulas have docstrings explaining the RE concept
- [ ] No hardcoded API keys or credentials
- [ ] `docker-compose up` still works

## Financial model contributions

The financial engine (`backend/engine/financial/`) is the most sensitive part of the codebase. If you're improving a formula or adding a metric:

1. Add a clear docstring with the formula and any standard reference
2. Write a test with a known-good expected value (calculate it by hand or cross-check with a spreadsheet)
3. Note any industry conventions your implementation follows (e.g., "management fee calculated on EGI, not GSI")

## Questions

Open a GitHub Discussion or join the Discord.
