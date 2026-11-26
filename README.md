# RaidPilot

Windows app that farms the Home Village in Clash of Clans through the MuMu Player emulator: it starts
the emulator, opens the game, zooms out, searches for loot, deploys your army, returns home and repeats.
It **only reads screenshots and sends touch input through ADB**. It does not modify the game, does not
read game memory and never moves your mouse. The emulator window may be hidden behind other windows.

> **Important:** Supercell's Terms of Service forbid bots, including ones that only tap. Your account can
> be banned. Do not use an account you are not prepared to lose. RaidPilot deliberately contains nothing
> to evade detection.

## Setup (once)

1. Install [Python 3.12](https://www.python.org/downloads/).
2. MuMu Player: instance **#0**, resolution **1600×900**, **240 DPI**, with Clash of Clans installed.
3. Clash of Clans language: **English**.
4. In the game, set up the army you want to attack with (it is used as it is).

## Run

1. Double-click `START.bat` (the first start downloads the packages).
2. Pick army, spells and loot threshold on the **Home** tab.
3. Press **START**. The rest happens on its own.

If a **Release** contains `RaidPilot-…-Setup.exe`, the installer can be used instead of Python.

## What the settings do

| Setting | Effect |
|---|---|
| Select Mode | Home Village. Builder Base is not available yet. |
| Select Army | Chooses the deployment pattern for your trained army (line, compact group or all around). |
| Spells | None, Rage Spells (purple spell cards) or Totem Spells (the other spell cards). Cast in two halves: near the edge first, deeper a few seconds later. |
| Minimum Loot | The opponent needs at least this much gold **and** this much elixir. Otherwise it presses "Next" (every "Next" costs gold). |
| Max Storage Capacity | Your storage size (up to 31M); used for "stop when full" and wall upgrades. |
| Deployment Style | Random (one of the two upper sides, which are fully visible), a fixed side or all sides. |
| Deploy Heroes Automatically | **Off by default.** Hero cards are never touched while off. |
| Use Siege Machines | Deploys the siege machine card. |
| Use Event Troops | Deploys cards with the event badge, plus icons saved with "Capture Event Troop". |
| Auto Upgrade Walls (Beta) | Once gold or elixir reaches half of Max Storage Capacity: opens the builder list, picks a wall, upgrades it with gold or elixir and repeats until no wall in the list can be paid (at most 15 per visit). It can use up most of both storages. Needs a free builder. Never uses wall rings and never confirms gem dialogs. |
| Stop When Storage Is Full | Stops once gold and elixir are full. |
| Donate Troops Before Attack (Beta) | Answers donation requests in the clan chat. Never spends gems. |

**Beta** features have not been verified on the real game yet.

## When a battle ends

At the latest 90 seconds after the first troop; earlier when no new loot arrived for 22 seconds (not before
second 50) or when almost nothing is left. The loot gained so far is kept; ending early can cost stars.

## Hero abilities

With "Deploy Heroes Automatically" on, all heroes use their ability about 12 seconds after being placed;
the Grand Warden follows 5 seconds later.

## Reward chests

If a reward chest covers the village after an attack, it is tapped open and closed with "Continue".

## When something is not recognised

The **Log** tab says which step failed. Log file, settings and the latest pictures of an attack (folder
`captures`) are in `%APPDATA%\RaidPilot`.

## Updates

Push a new number in `raidpilot/version.py` to `main`. GitHub builds the installer and the source
package, and the app then offers "Install version …".

## Development

```
pip install -r requirements.txt pytest
python -m pytest
python tools/devserver.py --fake     # window in a browser: http://127.0.0.1:8765/?dev
```

Tests run against a simulated game (`tests/fakegame.py`), not against the real one.
