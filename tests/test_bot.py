"""End to end: the real automation with real text recognition against the simulated game."""
import pytest
from raidpilot import settings
from raidpilot.bot import Bot
from raidpilot.logbook import Log
from raidpilot.screen import Screen
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


def middle_of_top_left():
    return (int(0.27 * 1600), int(0.24 * 900))


def test_red_spot_in_the_middle_of_the_side(ocr):
    # A building makes the middle of the line red: troops and heroes must find another place
    game = FakeGame(loots=[(900_000, 900_000, 0)])
    game.red = [(*middle_of_top_left(), 110)]
    bot, stats, log = run_bot(game, ocr, heroes=True, spell="none")
    assert not bot.last_error and stats.session["attacks"] == 1, log
    assert game.deployed == {"dragon": 14, "king": 1, "queen": 1, "warden": 1}, (game.deployed, log)
    assert not [line for line in log if "could not be deployed" in line], log


def card(name, count, left):
    colours = {"dragon": (60, 190, 90), "king": (40, 90, 220), "queen": (60, 200, 190), "warden": (200, 40, 180),
               "champion": (40, 160, 230), "rage": (210, 90, 210)}
    return [name, count, colours[name], left]


ARMIES = {
    "no hero (all upgrading)": ([card("dragon", 8, 118), card("rage", 2, 270)], {"dragon": 8, "rage": 2}),
    "two heroes": ([card("dragon", 17, 118), card("queen", None, 253), card("warden", None, 374),
                    card("rage", 5, 509)], {"dragon": 17, "queen": 1, "warden": 1, "rage": 5}),
    "four heroes, one dragon": ([card("dragon", 1, 118), card("king", None, 253), card("queen", None, 374),
                                 card("warden", None, 495), card("champion", None, 616), card("rage", 3, 751)],
                                {"dragon": 1, "king": 1, "queen": 1, "warden": 1, "champion": 1, "rage": 3}),
}


@pytest.mark.parametrize("roster,expected", ARMIES.values(), ids=ARMIES.keys())
def test_any_number_of_troops_and_heroes(ocr, roster, expected):
    game = FakeGame(loots=[(900_000, 900_000, 0)])
    game.roster = roster
    bot, stats, log = run_bot(game, ocr, heroes=True)
    assert not bot.last_error and stats.session["attacks"] == 1, log
    assert game.deployed == expected, (game.deployed, log)
    assert not [line for line in log if "could not be" in line], log


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


@pytest.mark.parametrize("found,sides", [(True, "Bottom Right"), (False, None)])
def test_most_loot_deploys_next_to_the_storages(ocr, monkeypatch, found, sides):
    from raidpilot import storages

    seen = [storages.Storage("gold", 0.71, 0.58, 1.0), storages.Storage("elixir", 0.67, 0.62, 0.9)]
    monkeypatch.setattr(storages.Finder, "find", lambda self, image: seen if found else [])
    game = FakeGame(loots=[(900_000, 900_000, 0)])
    bot, stats, log = run_bot(game, ocr, style="loot")
    assert not bot.last_error and stats.session["attacks"] == 1, log
    assert game.deployed == {"dragon": 14, "rage": 5}, log
    placed = [(x, y) for state, x, y in game.taps if state in ("scout", "battle") and y < 735 and x > 200]
    if found:
        assert f"Deploying from: {sides}" in log and any("Most loot near Bottom Right" in t for t in log), log
        assert all(x > 800 for x, _ in placed), placed
    else:
        assert "Storages not recognised on this base, using a random side." in log
        assert "Deploying from: Top Left" in log or "Deploying from: Top Right" in log


def test_game_is_not_relaunched_when_the_village_is_open(ocr):
    game = FakeGame(loots=[(900_000, 900_000, 0)])
    bot, _, log = run_bot(game, ocr)
    assert not bot.last_error and "launch" not in game.events and "stop" not in game.events, log
    assert game.events.count("zoom:home") == 1


@pytest.mark.parametrize("gold,tried", [(15_600_000, True), (15_000_000, False)])
def test_walls_start_at_half_full_storage(ocr, gold, tried):
    game = FakeGame(loots=[(900_000, 900_000, 0)], storage=(gold, 1_000_000))
    bot, stats, log = run_bot(game, ocr, walls=True)
    assert not bot.last_error, log
    assert any(e.startswith("wall:") for e in game.events) == tried, (game.events, log)
    waiting = [line for line in log if line.startswith("Walls start once gold or elixir reaches 15.5M")]
    assert len(waiting) == (0 if tried else 1), log


def test_walls_spend_gold_then_elixir(ocr):
    game = FakeGame(loots=[(900_000, 900_000, 0)], storage=(17_000_000, 9_000_000))
    bot, stats, log = run_bot(game, ocr, walls=True, spell="none")
    assert not bot.last_error, log
    bought = [e for e in game.events if e.startswith("wall:")]
    # 17M gold + 9M elixir pay for all five walls: two for 4.8M, three for 4M
    assert len(bought) == 5 and {"wall:gold", "wall:elixir"} <= set(bought), (bought, log)
    assert stats.session["walls"] == 5
    assert "gems" not in game.events and "ring" not in game.events
    assert game.state == "home" and stats.session["attacks"] == 1


def test_gem_offer_is_closed_and_the_other_resource_used(ocr):
    game = FakeGame(loots=[(900_000, 900_000, 0)], storage=(20_000_000, 10_000_000))
    game.refuse = {"gold"}  # the game says gold is not enough, whatever the bot has read
    bot, stats, log = run_bot(game, ocr, walls=True, spell="none")
    assert not bot.last_error, log
    assert "gems" not in game.events, game.events
    assert [e for e in game.events if e.startswith("wall:")] == ["wall:elixir"] * 2, (game.events, log)
    assert stats.session["walls"] == 2 and stats.session["attacks"] == 1


def test_builder_list_is_closed_and_zoomed_out_after_walls(ocr):
    game = FakeGame(loots=[(900_000, 900_000, 0)], storage=(17_000_000, 9_000_000))
    bot, stats, log = run_bot(game, ocr, walls=True, spell="none")
    assert not bot.last_error and stats.session["attacks"] == 1, log
    first_attack = game.events.index("card:dragon")
    # The list ignores the back key, so only its X leads home; then the camera is zoomed out again
    assert game.events[:first_attack].count("zoom:home") == 2, game.events
    assert "Walls finished: 5 upgraded. Back to attacking." in log


def test_camera_is_checked_and_moved_out_after_walls(ocr):
    game = FakeGame(loots=[(900_000, 900_000, 0)], storage=(17_000_000, 9_000_000))
    bot, stats, log = run_bot(game, ocr, walls=True, spell="none")
    assert not bot.last_error and not game.close_up and stats.session["attacks"] == 1, log
    assert "stop" not in game.events and not any("Zoom check" in line for line in log), log
    assert game.deployed == {"dragon": 14}, log


def test_game_that_ignores_zooming_after_walls_is_restarted(ocr):
    game = FakeGame(loots=[(900_000, 900_000, 0)], storage=(17_000_000, 9_000_000))
    game.stuck_after_walls = True
    bot, stats, log = run_bot(game, ocr, walls=True, spell="none")
    assert not bot.last_error and stats.session["attacks"] == 1, (game.events, log)
    assert any(line.startswith("Zooming out has no effect, restarting the game.") for line in log), log
    assert game.events.index("stop") < game.events.index("card:dragon"), game.events
    assert game.deployed == {"dragon": 14} and not game.close_up and "redzone" not in game.events, log


def test_mouse_wheel_is_used_when_the_gesture_does_nothing(ocr):
    game = FakeGame(loots=[(900_000, 900_000, 0)])
    game.zoom_ok, game.close_up = {"wheel"}, True
    bot, stats, log = run_bot(game, ocr, spell="none")
    assert not bot.last_error and game.zoom_method == "wheel" and "stop" not in game.events, log
    assert "Zooming with the mouse wheel from now on." in log and game.deployed == {"dragon": 14}, log


def test_battle_is_left_at_once_when_nothing_can_be_placed(ocr):
    game = FakeGame(loots=[(900_000, 900_000, 0)])
    game.zoom_ok, game.close_up = set(), True  # nothing moves the camera
    bot, stats, log = run_bot(game, ocr, heroes=True)
    assert game.deployed == {} and "card:king" not in game.events and "card:rage" not in game.events, log
    assert game.events.count("end") == 5, game.events
    assert bot.last_error == "No attack was possible five times in a row.", log
    assert any("Nothing can be placed" in line for line in log)


def test_pc_is_kept_awake_only_while_the_bot_runs(ocr, monkeypatch):
    from raidpilot import power

    calls = []
    monkeypatch.setattr(power, "keep_awake", lambda on: calls.append(on) or True)
    game = FakeGame(loots=[(900_000, 900_000, 0)])
    bot, _, log = run_bot(game, ocr, spell="none")
    assert calls == [True, False] and any("stays awake" in line for line in log), (calls, log)


def test_walls_stop_when_nothing_is_affordable(ocr):
    # After one wall both storages are below one million: leave the menu without searching on
    game = FakeGame(loots=[(900_000, 900_000, 0)], storage=(16_000_000, 600_000))
    game.walls = [[15_400_000, 3]]
    bot, stats, log = run_bot(game, ocr, walls=True, spell="none")
    assert not bot.last_error and stats.session["walls"] == 1 and stats.session["attacks"] == 1, (game.events, log)
    bought = game.events.index("wall:gold")
    assert "swipe" not in game.events[bought:], game.events


def test_menu_is_left_when_every_wall_costs_too_much(ocr):
    # More than a million left, but less than any wall: search the whole list once, then go on attacking
    game = FakeGame(loots=[(900_000, 900_000, 0)], storage=(16_000_000, 2_000_000))
    game.walls = [[18_000_000, 3]]
    game.after_walls = ["Archer Queen", "Grand Warden"]
    bot, stats, log = run_bot(game, ocr, walls=True, spell="none")
    assert not bot.last_error, log
    assert stats.session["walls"] == 0 and stats.session["attacks"] == 1, (game.events, log)
    assert not [e for e in game.events if e.startswith("wall:")]
    assert "No affordable wall was found in the builder list." in log


def test_walls_found_when_the_list_opens_below_them(ocr):
    game = FakeGame(loots=[(900_000, 900_000, 0)], storage=(17_000_000, 1_000_000))
    game.after_walls = [f"Hero Hall {n}" for n in range(12)]
    game.open_at = len(game.rows()) - 10
    bot, stats, log = run_bot(game, ocr, walls=True, spell="none")
    assert not bot.last_error and stats.session["walls"] >= 1 and stats.session["attacks"] == 1, (game.events, log)


def test_open_builder_list_is_closed_on_the_way_home(ocr):
    game = FakeGame(loots=[(900_000, 900_000, 0)])
    game.state = "panel"  # left open, for example by stopping the bot in the middle of an upgrade
    bot, stats, log = run_bot(game, ocr, spell="none")
    assert not bot.last_error and stats.session["attacks"] == 1, (game.events, log)
    assert "stop" not in game.events, "the list must be closed, not the game restarted"


def test_no_free_builder_skips_walls(ocr):
    game = FakeGame(loots=[(900_000, 900_000, 0)], storage=(20_000_000, 1_000_000))
    game.builders = 0
    bot, stats, log = run_bot(game, ocr, walls=True, spell="none")
    assert not bot.last_error and stats.session["walls"] == 0, log
    assert any("No free builder" in line for line in log), log


def test_both_resources_must_reach_the_minimum(ocr):
    game = FakeGame(loots=[(2_000_000, 590_000, 0), (590_000, 2_000_000, 0), (610_000, 620_000, 0)])
    bot, stats, log = run_bot(game, ocr, spell="none")
    assert not bot.last_error, log
    assert game.base == 2 and stats.session["searches"] == 2, log
    assert "end" not in [e for e in game.events[:game.events.index("card:dragon")]]  # skipped with Next


def test_late_troop_bar_is_waited_for(ocr):
    game = FakeGame(loots=[(900_000, 900_000, 0)])
    game.bar_delay = 4  # missing during the first looks
    bot, stats, log = run_bot(game, ocr, spell="none")
    assert not bot.last_error and stats.session["attacks"] == 1, log
    assert game.deployed["dragon"] == 14


def test_reward_chest_is_opened(ocr):
    game = FakeGame(loots=[(900_000, 900_000, 0)])
    original = game.tap
    shown = []

    def tap(x, y):
        before = game.state
        original(x, y)
        if before == "result" and game.state == "home" and not shown:
            shown.append(True)
            game.state = "chest"

    game.tap = tap
    bot, stats, log = run_bot(game, ocr, attacks=2, spell="none")
    assert not bot.last_error, log
    assert "reward" in game.events and stats.session["attacks"] == 2, (game.events, log)
    assert "Reward collected." in log


def test_a_screen_that_does_not_close_ends_in_a_game_restart(ocr, monkeypatch):
    from raidpilot import bot as bot_module

    monkeypatch.setattr(bot_module, "REWARD_TAPS", 3)
    game = FakeGame(loots=[(900_000, 900_000, 0)])
    game.state = "chest"
    game.chest_taps = -1000  # never opens
    bot, stats, log = run_bot(game, ocr, spell="none")
    assert not bot.last_error, log
    assert log.count("The reward screen does not close.") == 1, log
    assert "stop" in game.events and stats.session["attacks"] == 1, (game.events, log)


def test_reward_that_pops_up_on_battle_costs_no_attempt(ocr):
    game = FakeGame(loots=[(900_000, 900_000, 0)])
    game.chest_on_battle = True
    bot, stats, log = run_bot(game, ocr, spell="none")
    assert not bot.last_error, log
    assert "reward" in game.events and stats.session["attacks"] == 1, (game.events, log)
    assert "No opponent screen reached, trying again." not in log


def test_star_bonus_window_over_the_village_is_claimed(ocr):
    game = FakeGame(loots=[(900_000, 900_000, 0)])
    game.state = "claim"
    bot, stats, log = run_bot(game, ocr, spell="none")
    assert not bot.last_error, log
    assert game.events.count("claimed") == 1 and stats.session["attacks"] == 1, (game.events, log)


def test_reward_in_the_attack_menu_is_claimed(ocr):
    game = FakeGame(loots=[(900_000, 900_000, 0)])
    game.menu_claim = True
    bot, stats, log = run_bot(game, ocr, spell="none")
    assert not bot.last_error, log
    assert game.events.count("claimed") == 1 and stats.session["attacks"] == 1, (game.events, log)


def test_a_claim_button_next_to_a_price_is_not_touched(ocr):
    game = FakeGame(loots=[(900_000, 900_000, 0)])
    game.state = "offer"
    bot, stats, log = run_bot(game, ocr, spell="none")
    assert not bot.last_error, log
    assert "offer" not in game.events and stats.session["attacks"] == 1, (game.events, log)


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


def test_walls_survive_a_list_title_that_is_not_always_found_at_the_same_place(ocr, monkeypatch):
    # On the real game the position taken for the list moves between two looks (seen: 0.86 and 0.90)
    real, looks = Screen.upgrade_panel, []

    def wandering(self):
        found = real(self)
        looks.append(found)
        return found and (found[0] + (60 if len(looks) % 2 else 0), found[1])

    monkeypatch.setattr(Screen, "upgrade_panel", wandering)
    game = FakeGame(loots=[(900_000, 900_000, 0)], storage=(17_000_000, 9_000_000))
    bot, stats, log = run_bot(game, ocr, walls=True, spell="none")
    assert not bot.last_error and stats.session["walls"] == 5 and stats.session["attacks"] == 1, log
    assert not any("The wall upgrade failed" in line for line in log), log


def test_a_fault_in_the_wall_upgrade_does_not_stop_the_bot(ocr, monkeypatch):
    def broken(self, money, skipped=()):
        self._open_builder_list()
        raise ValueError("boom")

    monkeypatch.setattr(Bot, "_find_wall_entry", broken)
    game = FakeGame(loots=[(900_000, 900_000, 0)], storage=(17_000_000, 9_000_000))
    bot, stats, log = run_bot(game, ocr, walls=True, spell="none")
    assert not bot.last_error and stats.session["attacks"] == 1 and game.state == "home", log
    assert any(line.startswith("The wall upgrade failed, attacking goes on.") and "boom" in line
               for line in log), log

