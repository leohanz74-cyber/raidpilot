# RaidPilot

Windows-App, die in Clash of Clans über einen Android-Emulator Gegner sucht und Truppen absetzt.
Sie **liest nur Bildschirmfotos und sendet Tipp-Befehle über ADB**. Sie verändert das Spiel nicht
und liest keinen Spielspeicher.

> **Wichtig:** Supercell verbietet Bots in seinen Nutzungsbedingungen, auch solche, die nur tippen.
> Der Account kann gesperrt werden. Nutze keinen Account, den du nicht verlieren willst.
> RaidPilot enthält bewusst nichts, um die Erkennung zu umgehen.

## Start

1. [Python 3.12](https://www.python.org/downloads/) muss installiert sein.
2. `START.bat` doppelklicken. Beim ersten Mal werden die Pakete geladen.
3. Profil anlegen (bleibt nur auf deinem PC).

Gibt es unter **Releases** eine `RaidPilot-…-Setup.exe`, reicht stattdessen der Installer.

## Emulator vorbereiten (z. B. MuMuPlayer oder LDPlayer)

- Auflösung **1280×720** (oder 1600×900), Querformat
- ADB-Debugging einschalten
- Spielsprache Deutsch oder Englisch

Dann in RaidPilot: **Optionen → Aktualisieren**, Gerät wählen.

## Vor dem ersten Lauf

**Einrichtung → Werkzeug öffnen → Bild aufnehmen → Erkennung testen.** Mache das im Dorf, im
Angriffsmenü, beim Gegner (mit „Weiter“) und auf dem Ergebnisbildschirm.

- Knopf nicht erkannt? Unter **Knopf** einmal einrahmen.
- Truppen landen nicht? Unter **Seiten** die Absetz-Linien knapp vor die rote Linie legen.
- Falsche Rollen in der Leiste? Unter **Plätze** festlegen.
- Nur bestimmte Truppen oder Event-Truppen? Unter **Truppe** das Symbol erfassen.

## Funktionen

| Bereich | Inhalt |
|---|---|
| Suche | Mindestbeute (zusammen oder einzeln), „Weiter“ bis es passt, Obergrenze |
| Angriff | Seite wählbar oder zufällig, Truppen, Helden samt Fähigkeit, Belagerungsmaschine, Zauber |
| Kampf | endet, wenn keine Beute mehr kommt |
| Lager | anhalten, wenn voll |
| Statistik | Sitzung und Gesamt, optional Meldung an einen eigenen Discord-Webhook |
| Beta | Mauern verbessern, Spenden, Bauarbeiterbasis |

**Beta** heißt: noch nie am echten Spiel erprobt. Bei Juwelen- oder Kaufdialogen wird abgebrochen.

## Updates

Eine neue Nummer in `raidpilot/version.py` auf `main` pushen. GitHub baut Installer und Quellpaket,
die App zeigt dann oben „Version … installieren“.

## Entwicklung

```
pip install -r requirements.txt pytest
python -m pytest
python tools/devserver.py --fake     # Oberfläche im Browser: http://127.0.0.1:8765/?dev
```

Die Tests laufen gegen ein nachgestelltes Spiel (`tests/fakegame.py`), nicht gegen das echte.
