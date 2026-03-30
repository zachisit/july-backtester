# Private Strategies Guide

## What This Is

The backtester now supports **two types of strategies**:

1. **Public strategies** - Example strategies everyone can see (in `custom_strategies/`)
2. **Private strategies** - YOUR strategies that stay private (in `custom_strategies/private/`)

Your private strategies are stored in a **separate private repository** so they never become public.

---

## For Interns: First-Time Setup

### Step 1: Clone the Main Repo

```bash
git clone https://github.com/zachisit/july-backtester.git
cd july-backtester
```

### Step 2: Get Access to Private Strategies

Ask Zach to add you to the private repository. You'll receive an invitation email.

### Step 3: Initialize Private Strategies

After you have access, run these commands:

```bash
git submodule update --init --recursive
cd custom_strategies/private/
git checkout main
cd ../..
```

This downloads the private strategies folder and puts you on the main branch (important for pushing later).

### Step 4: Verify It Worked

Check that the private folder exists:

```bash
ls custom_strategies/private/
```

You should see:
- `README.md`
- `_TEMPLATE_strategy.py`
- `.gitkeep`

---

## How to Add Your Strategy

### Option 1: Copy the Template

```bash
cd custom_strategies/private/
cp _TEMPLATE_strategy.py my_strategy.py
```

Now edit `my_strategy.py` with your strategy logic.

### Option 2: Create From Scratch

Create a new file `custom_strategies/private/my_strategy.py`:

```python
from helpers.registry import register_strategy
from helpers.indicators import calculate_rsi

@register_strategy(
    name="My RSI Strategy",
    dependencies=[],
    params={"period": 14},
)
def my_rsi_strategy(df, **kwargs):
    """My private RSI strategy"""
    period = kwargs["period"]
    df["RSI"] = calculate_rsi(df["Close"], period)

    df["Signal"] = 0
    df.loc[df["RSI"] < 30, "Signal"] = 1   # Buy
    df.loc[df["RSI"] > 70, "Signal"] = -1  # Sell

    return df
```

---

## How to Save Your Strategy (Push to Private Repo)

### Step 1: Go to the Private Folder

```bash
cd custom_strategies/private/
```

### Step 2: Make Sure You're on Main Branch

```bash
git checkout main
```

(This ensures you're not in "detached HEAD" state)

### Step 3: Check What Changed

```bash
git status
```

### Step 4: Add Your File

```bash
git add my_strategy.py
```

### Step 5: Commit

```bash
git commit -m "Add my strategy"
```

### Step 6: Push

```bash
git push
```

**That's it!** Your strategy is now saved in the private repo.

---

## Important Rules

### ✅ DO

- Create your strategies in `custom_strategies/private/`
- Test your strategies before pushing
- Commit often with clear messages
- Ask for help if you're stuck

### ❌ DON'T

- Put strategies in the public `custom_strategies/` folder (they become public!)
- Commit API keys or passwords
- Push code that doesn't run
- Delete the `.gitkeep` or `_TEMPLATE_strategy.py` files

---

## How to Run Your Private Strategy

Just run the backtester normally! It automatically finds strategies in both folders.

```bash
python main.py
```

Your private strategies will show up in the output alongside public strategies.

---

## Troubleshooting

### "I don't see custom_strategies/private/"

You need to initialize the submodule:

```bash
git submodule update --init --recursive
```

### "Permission denied when I try to push"

You don't have access to the private repo yet. Ask Zach to add you.

### "git push says 'You are not currently on a branch'"

This means you're in "detached HEAD" state. Fix it:

```bash
cd custom_strategies/private/
git checkout main
git push
```

Always run `git checkout main` before pushing.

### "My strategy doesn't show up in the backtester"

1. Make sure your file ends with `.py`
2. Make sure it has `@register_strategy` decorator
3. Check that `custom_strategies/private/` exists
4. Try running `python main.py --dry-run` to see what strategies are loaded

### "I accidentally put my strategy in the wrong folder"

If you put it in `custom_strategies/` (public) instead of `custom_strategies/private/`:

1. Move it to the right folder: `git mv custom_strategies/my_strategy.py custom_strategies/private/`
2. Go to the private folder: `cd custom_strategies/private/`
3. Commit and push: `git add my_strategy.py && git commit -m "Move strategy to private" && git push`
4. Go back to main repo: `cd ../..`
5. Update main repo: `git add custom_strategies/ && git commit -m "Remove strategy from public folder"`

---

## Summary

**Main repo (public):**
```
july-backtester/
├── custom_strategies/          ← Public example strategies
│   ├── mean_reversion.py
│   └── private/                ← Your private strategies (separate repo)
```

**When you work on strategies:**
1. Create in `custom_strategies/private/`
2. Test locally
3. `cd custom_strategies/private/`
4. `git add`, `git commit`, `git push`
5. Done!

**Questions?** Ask Zach or Will.
