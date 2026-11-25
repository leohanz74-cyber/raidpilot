"""Ende-zu-Ende: der echte Ablauf mit echter Texterkennung gegen das nachgestellte Spiel."""
from raidpilot import settings
from raidpilot.bot import Bot
from raidpilot.logbook import Log
from raidpilot.stats import Stats

from .fakegame import FakeGame


def run_bot(game, ocr, **overrides):
    config = settings.load()
    config.update({"max_attacks": 1, "spell_delay": 2, "style": "tl", "hero_ability_after": 4}, **overrides)
    log, stats = Log(to_file=False), Stats("test")
    bot = Bot(game, ocr, lambda: config, stats, log, clock=game.clock, sleep=game.sleep)
    bot.run()
    return bot, stats, [line["text"] for line in log.since()]


def test_full_attack(ocr):
    game = FakeGame()
    bot, stats, log = run_bot(game, ocr)
    assert not bot.last_error, log
    assert game.base == 1, "das arme Dorf muss mit Weiter übersprungen werden"
    assert game.deployed == {"dragon": 10, "king": 1, "queen": 1, "rage": 3}, log
    assert {"ability:king", "ability:queen"} <= set(game.events)
    assert stats.session["attacks"] == 1
    assert (stats.session["gold"], stats.session["elixir"]) == (315_000, 336_000)
    assert game.state == "home"


def test_siege_and_toggles(ocr):
    game = FakeGame(loots=[(900_000, 900_000, 0)])
    bot, _, log = run_bot(game, ocr, siege=True, heroes=False, spell="none")
    assert not bot.last_error, log
    assert game.deployed == {"dragon": 10, "siege": 1}, log


def test_loot_rule_each(ocr):
    game = FakeGame(loots=[(900_000, 100_000, 0), (700_000, 700_000, 0)])
    bot, _, log = run_bot(game, ocr, loot_rule="each", min_loot=600_000)
    assert not bot.last_error, log
    assert game.base == 1


def test_stops_when_storage_full(ocr):
    game = FakeGame(storage=(20_000_000, 20_000_000))
    bot, stats, log = run_bot(game, ocr, stop_full=True, max_storage=20_000_000)
    assert not bot.last_error
    assert "Lager sind voll." in log
    assert not game.taps and stats.session["attacks"] == 0


def test_gives_up_after_max_searches(ocr):
    game = FakeGame(loots=[(1_000, 1_000, 0)])
    config_searches = 5
    original = game._search

    def stop_after_first_round():
        original()
        if game.base >= config_searches + 1:
            bot_holder[0].stop()

    bot_holder = []
    game._search = stop_after_first_round
    config = settings.load()
    config.update({"max_searches": config_searches})
    log = Log(to_file=False)
    bot = Bot(game, ocr, lambda: config, Stats("t"), log, clock=game.clock, sleep=game.sleep)
    bot_holder.append(bot)
    bot.run()
    texts = [line["text"] for line in log.since()]
    assert any("ohne Treffer" in t for t in texts), texts
    assert "end" in game.events and not game.deployed
