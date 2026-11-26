"""End to end: the real automation with real text recognition against the simulated game."""
import pytest
from raidpilot import settings
from raidpilot.bot import Bot
from raidpilot.logbook import Log
from raidpilot.stats import Stats

from .fakegame import FakeGame, FakeMumu


def run_bot(game, ocr, emulator=None, attacks=1, **overrides):
    config = settings.load()
    config.update({"style": "tl"}, **overrides)
    log, stats = Log(to_file=False), Stats("test")
    names = []
    bot = Bot(game, ocr, lambda: config, stats, log, emulator=emulator, clock=game.clock, sleep=game.sleep,
              on_player=names.append)

    def after_attack():
        if stats.session["attacks"] >= attacks:
            bot.stop()

    game.after_attack = after_attack
    bot.run()
    bot.names = names
    return bot, stats, [line["text"] for line in log.since()]


def test_afk_from_powered_off_emulator(ocr):
    game = FakeGame(welcome=True)
    mumu = FakeMumu(game)
    bot, stats, log = run_bot(game, ocr, emulator=mumu)
    assert not bot.last_error, log
    assert mumu.launched and "connect:127.0.0.1:16384" in game.events
    assert game.base == 1, "the poor village must be skipped with Next"
    assert "zoom:home" in game.events and "zoom:scout" in game.events
    # Defaults: no heroes, no siege machine, no event troops
    assert game.deployed == {"dragon": 14, "rage": 5}, log
    assert not [e for e in game.events if e in ("card:king", "card:queen", "card:siege", "card:event")]
    assert stats.session["attacks"] == 1
    got = game.total()
    assert (stats.session["gold"], stats.session["elixir"], stats.session["dark"]) == got, log
    assert bot.names == ["TestChief"]
    assert game.state == "home"


def test_all_toggles(ocr):
    game = FakeGame(loots=[(900_000, 900_000, 0)])
    game.endless = True  # long enough for the hero abilities
    bot, _, log = run_bot(game, ocr, heroes=True, siege=True, event_troops=True, spell="none")
    assert not bot.last_error, log
    assert game.deployed == {"dragon": 14, "event": 30, "siege": 1, "king": 1, "queen": 1, "warden": 1}, log
    # Every ability exactly once, the Grand Warden last
    abilities = [e for e in game.events if e.startswith("ability:")]
    assert abilities == ["ability:king", "ability:queen", "ability:warden"], (abilities, log)


def test_several_attacks_in_a_row(ocr):
    game = FakeGame(loots=[(900_000, 900_000, 2_000)])
    bot, stats, log = run_bot(game, ocr, attacks=3, style="all", army="sneaky_goblin")
    assert not bot.last_error, log
    assert stats.session["attacks"] == 3
    assert stats.session["gold"] == 3 * game.total()[0]
    assert stats.lifetime()["attacks"] == 3


def test_battle_without_new_loot_is_ended_early(ocr):
    game = FakeGame(loots=[(900_000, 900_000, 0)])
    game.endless = True  # the loot stops at half and the battle never ends on its own
    bot, stats, log = run_bot(game, ocr, spell="none")
    assert not bot.last_error, log
    assert "end" in game.events and stats.session["attacks"] == 1, log
    assert 45 <= game.raid_ended - game.raid_started <= 95, log


def test_game_is_not_relaunched_when_the_village_is_open(ocr):
    game = FakeGame(loots=[(900_000, 900_000, 0)])
    bot, _, log = run_bot(game, ocr)
    assert not bot.last_error and "launch" not in game.events, log
    assert game.events.count("zoom:home") == 1


@pytest.mark.parametrize("gold,tried", [(12_500_000, True), (11_000_000, False)])
def test_walls_start_at_half_full_storage(ocr, gold, tried):
    game = FakeGame(loots=[(900_000, 900_000, 0)], storage=(gold, 1_000_000))
    bot, _, log = run_bot(game, ocr, walls=True, max_storage=24_000_000)
    assert not bot.last_error, log
    assert ("No wall was found in the builder list." in log) == tried, log


def test_loot_counts_when_stopped_during_a_battle(ocr):
    game = FakeGame(loots=[(900_000, 900_000, 0)])
    game.endless = True
    holder = []
    original = game.screenshot

    def screenshot():
        if game.state == "battle" and game.ticks >= 10 and holder:
            holder[0].stop()
        return original()

    game.screenshot = screenshot
    log = Log(to_file=False)
    config = settings.load()
    config["spell"] = "none"
    stats = Stats("t")
    bot = Bot(game, ocr, lambda: config, stats, log, clock=game.clock, sleep=game.sleep)
    holder.append(bot)
    bot.run()
    texts = [line["text"] for line in log.since()]
    assert any(t.startswith("Stopped during a battle") for t in texts), texts
    assert stats.session["attacks"] == 1 and 0 < stats.session["gold"] < 900_000


def test_stops_when_storage_full(ocr):
    game = FakeGame(storage=(20_000_000, 20_000_000))
    bot, stats, log = run_bot(game, ocr, stop_full=True, max_storage=20_000_000)
    assert not bot.last_error
    assert "Storages are full." in log
    assert not game.taps and stats.session["attacks"] == 0


def test_gives_up_after_many_searches(ocr, monkeypatch):
    from raidpilot import bot as bot_module

    monkeypatch.setattr(bot_module, "MAX_SEARCHES", 4)
    game = FakeGame(loots=[(1_000, 1_000, 0)])
    holder = []
    original = game._search

    def search():
        original()
        if game.base >= 5:
            holder[0].stop()

    game._search = search
    log = Log(to_file=False)
    config = settings.load()
    bot = Bot(game, ocr, lambda: config, Stats("t"), log, clock=game.clock, sleep=game.sleep)
    holder.append(bot)
    bot.run()
    texts = [line["text"] for line in log.since()]
    assert any("No match after 4" in t for t in texts), texts
    assert "end" in game.events and not game.deployed


def test_offline_device_is_reported(ocr):
    game = FakeGame()
    game.online = ""
    bot, _, log = run_bot(game, ocr, device="127.0.0.1:9999")
    assert "not online" in bot.last_error and not game.taps
