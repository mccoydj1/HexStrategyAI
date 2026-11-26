import json
from collections import Counter
from pathlib import Path
from random import Random
import tempfile
import unittest

from hexstrategy.ai import BASE, choose, determinize, evaluate, explain, interval, play, public_minimum, simulate_batch
from hexstrategy.board import RESOURCES
from hexstrategy.game import COSTS, DECK, Game, SETUP
from hexstrategy.session import Session


def advance(game):
    while game.phase.startswith("opening"):
        game.step(choose(game.observe(game.actor)))
    return game


def grant(game, player, **resources):
    game.bank_transfer(player, [resources.get(r, 0) for r in RESOURCES], 1)


class Rules(unittest.TestCase):
    def test_geometry_and_tokens(self):
        for seed in range(32):
            board = Game(seed).board
            self.assertEqual((len(board.tiles), len(board.vertices), len(board.edges)), (19, 54, 72))
            self.assertEqual(Counter(t.resource for t in board.tiles),
                             Counter(wood=4, brick=3, wool=4, grain=4, ore=3) + Counter({None: 1}))
            self.assertEqual(Counter(t.number for t in board.tiles),
                             Counter((0, 2, 3, 3, 4, 4, 5, 5, 6, 6, 8, 8, 9, 9, 10, 10, 11, 11, 12)))
            self.assertEqual(Counter(r for _, r in board.ports), Counter(RESOURCES) + Counter({None: 4}))
            self.assertEqual(len({v for edge, _ in board.ports for v in board.edges[edge]}), 18)
            red = [set(board.corners[i]) for i, t in enumerate(board.tiles) if t.number in (6, 8)]
            self.assertTrue(all(len(a & b) <= 1 for i, a in enumerate(red) for b in red[i+1:]))

    def test_opening_order_distance_and_starting_resources(self):
        game = Game(99)
        for turn in SETUP:
            seat = game.seating[turn]
            self.assertEqual(game.actor, seat)
            action = choose(game.observe(seat))
            _, v = action
            before = tuple(game.players[seat].hand)
            game.step(action)
            self.assertTrue(all(game.buildings[n] is None for n in game.board.neighbors[v]))
            amount = Counter(game.board.tiles[t].resource for t in game.board.adjoining[v])
            for i, resource in enumerate(RESOURCES):
                self.assertEqual(game.players[seat].hand[i]-before[i],
                                 amount[resource] if game.setup >= 4 else 0)
            self.assertTrue(all(a[1] in game.board.incident[v] for a in game.legal()))
            game.step(next(game.legal()))
        self.assertEqual((game.phase, game.active), ("roll", game.seating[0]))
        self.assertTrue(all(game.roads.count(p) == game.score(p) == 2 for p in range(4)))

    def test_production_shortage_blocking_and_city(self):
        game = Game(12)
        i = next(i for i, tile in enumerate(game.board.tiles) if tile.number == 2)
        tile = game.board.tiles[i]
        a, _, _, b, _, _ = game.board.corners[i]
        game.buildings[a] = (0, 2)
        game.buildings[b] = (1, 1)
        resource = RESOURCES.index(tile.resource)
        game.bank[resource] = 2
        game.produce(2)
        self.assertEqual(game.players[0].hand[resource], 0)
        self.assertEqual(game.players[1].hand[resource], 0)
        game.bank[resource] = 3
        game.produce(2)
        self.assertEqual(game.players[0].hand[resource], 2)
        self.assertEqual(game.players[1].hand[resource], 1)
        game.robber = i
        game.bank[resource] = 10
        game.produce(2)
        self.assertEqual(game.bank[resource], 10)
        game.robber = -1
        game.buildings[b] = None
        game.bank[resource] = 1
        game.produce(2)
        self.assertEqual(game.players[0].hand[resource], 3)

    def test_coaching_explains_exchange_cost_and_discard_risk(self):
        game = advance(Game(5))
        game.phase = "action"
        seat = game.active
        grant(game, seat, wood=8)
        observation = game.observe(seat)
        exchange = next(action for action in observation.actions if action[:2] == ("bank", 0))
        rate = game.rate(seat, 0)
        self.assertIn(f"costs {rate} wood", explain(observation, exchange))
        total = sum(observation.hand)
        self.assertIn(f"returning {total//2}", explain(observation, ("end",)))

    def test_trades_and_rate(self):
        game = advance(Game(5))
        game.phase = "action"
        seat = game.active
        target = (seat + 1) % 4
        grant(game, seat, brick=4, wood=2)
        grant(game, target, wool=2)
        give, get = (1, 0, 0, 0, 0), (0, 0, 1, 0, 0)
        a, b = game.players[seat], game.players[target]
        before_a, before_b = a.hand[:], b.hand[:]
        game.trade_offer(target, give, get)
        self.assertEqual(game.actor, target)
        game.step(("decline",))
        self.assertEqual((a.hand, b.hand), (before_a, before_b))
        game.trade_offer(target, give, get)
        game.step(("accept",))
        self.assertEqual(a.hand[0], before_a[0]-1)
        self.assertEqual(b.hand[2], before_b[2]-1)
        with self.assertRaises(ValueError):
            game.trade_offer(target, give, give)
        edge, resource = next((e, r) for e, r in game.board.ports if r == "brick")
        game.buildings[game.board.edges[edge][0]] = (seat, 1)
        self.assertEqual(game.rate(seat, 1), 2)
        game.step(("bank", 1, 4))
        self.assertEqual(a.hand[1], before_a[1]-2)

    def test_nonactive_offer_and_counter(self):
        game = advance(Game(5))
        game.phase = "action"
        active = game.active
        visitor = (active+1)%4
        grant(game, active, ore=2)
        grant(game, visitor, brick=3)
        ore = (0, 0, 0, 0, 1)
        brick = (0, 1, 0, 0, 0)
        game.trade_offer(active, brick, ore, visitor)
        self.assertEqual(game.actor, active)
        game.trade_offer(visitor, ore, (0, 2, 0, 0, 0), active)
        self.assertEqual(game.actor, visitor)
        self.assertEqual(game.offer[3], active)
        before = game.players[active].hand[1]
        game.step(("accept",))
        self.assertEqual(game.phase, "action")
        self.assertEqual(game.actor, active)
        self.assertEqual(game.players[active].hand[1], before+2)

    def test_plenty_monopoly_and_free_roads(self):
        game = advance(Game(44))
        seat = game.active
        player = game.players[seat]
        game.turn = 2
        game.phase = "action"
        player.cards = [("plenty", 1), ("monopoly", 1), ("roads", 1)]
        wool = RESOURCES.index("wool")
        bank = game.bank[wool]
        old = player.hand[wool]
        game.step(("plenty", wool, wool))
        self.assertEqual((player.hand[wool], game.bank[wool]), (old+2, bank-2))
        self.assertFalse(any(move[0] == "monopoly" for move in game.legal()))
        game.used_card = False
        available = sum(p.hand[wool] for i, p in enumerate(game.players) if i != seat)
        game.step(("monopoly", wool))
        self.assertEqual(player.hand[wool], old+2+available)
        self.assertTrue(all(p.hand[wool] == 0 for i, p in enumerate(game.players) if i != seat))
        game.used_card = False
        hand = player.hand[:]
        game.step(("roads",))
        old_roads = game.roads.count(seat)
        while game.phase == "roads":
            game.step(next(game.legal()))
        self.assertEqual(game.roads.count(seat), old_roads+2)
        self.assertEqual(player.hand, hand)

    def test_seven_discard_and_steal(self):
        game = advance(Game(3))
        seat = game.active
        victim = (seat + 1) % 4
        grant(game, victim, brick=9)
        rolls = iter([3, 4])
        game.rng.randint = lambda *_: next(rolls)
        game.step(("roll",))
        self.assertEqual((game.actor, game.phase), (victim, "discard"))
        self.assertTrue(all(sum(a[1]) == sum(game.players[victim].hand)//2 for a in game.legal()))
        game.step(next(game.legal()))
        move = next(a for a in game.legal() if a[-1] == victim)
        total = sum(game.players[victim].hand)
        game.step(move)
        self.assertEqual(game.robber, move[1])
        self.assertEqual(sum(game.players[victim].hand), total-1)
        self.assertEqual(game.phase, "action")

    def test_development_timing_knights_and_victory(self):
        game = advance(Game(6))
        seat = game.active
        player = game.players[seat]
        self.assertEqual(Counter(game.deck), Counter(DECK))
        player.cards = [("knight", 0)]
        self.assertNotIn(("knight",), tuple(game.legal()))
        game.turn = 1
        player.knights = 2
        game.step(("knight",))
        self.assertEqual(game.army, seat)
        self.assertEqual(game.phase, "robber")
        game.step(next(game.legal()))
        self.assertEqual(game.phase, "roll")
        self.assertNotIn(("knight",), tuple(game.legal()))
        game.phase = "action"
        player.cards = [("point", 1)]*5
        game.deck = ["point"]
        grant(game, seat, wool=1, grain=1, ore=1)
        game.step(("buy",))
        self.assertEqual(game.winner, seat)

    def test_road_trail_and_cut(self):
        game = Game(22)
        path = game.board.corners[0]
        for a, b in zip(path, path[1:] + path[:1]):
            game.roads[game.board.edges.index(tuple(sorted((a, b))))] = 0
        game.update_longest()
        self.assertEqual(game.road_length(0), 6)
        self.assertEqual(game.longest, 0)
        game.buildings[path[0]] = (1, 1)
        game.buildings[path[3]] = (2, 1)
        game.update_longest()
        self.assertEqual(game.road_length(0), 3)
        self.assertIsNone(game.longest)
        self.assertEqual(Game.award((6, 6, 3, 3), 5, 1), 1)
        self.assertIsNone(Game.award((6, 6, 3, 3), 5, 2))

    def test_full_matches_conserve_inventory(self):
        for seed in range(20):
            game = Game(seed)
            self.assertIn(play(game, (BASE,)*4), range(4))
            for i, bank in enumerate(game.bank):
                self.assertEqual(bank + sum(p.hand[i] for p in game.players), 19)
                self.assertGreaterEqual(bank, 0)
            in_play = Counter(c for player in game.players for c, _ in player.cards)
            self.assertEqual(Counter(DECK), in_play + Counter(game.deck) + Counter(game.revealed))
            self.assertGreaterEqual(game.score(game.winner, True), 10)


class PublicInformation(unittest.TestCase):
    def test_hidden_hands_and_deck_permutation_do_not_affect_observation(self):
        game = advance(Game(4))
        seat = game.active
        a, b = [p for p in range(4) if p != seat][:2]
        grant(game, a, wood=1)
        grant(game, b, wool=1)
        first = game.observe(seat)
        game.players[a].hand[0] -= 1
        game.players[a].hand[2] += 1
        game.players[b].hand[2] -= 1
        game.players[b].hand[0] += 1
        game.deck.reverse()
        second = game.observe(seat)
        self.assertEqual(first, second)
        self.assertEqual(choose(first), choose(second))
        self.assertEqual(determinize(first, 234).observe(seat), second)

    def test_hidden_development_cards_and_engine_rng_are_outside_the_observation(self):
        game = advance(Game(14))
        seat = game.active
        opponents = [p for i, p in enumerate(game.players) if i != seat]
        a, b = opponents[:2]
        a.cards.append((game.deck.pop(), game.turn-1))
        b.cards.append((game.deck.pop(), game.turn-1))
        original = game.observe(seat)
        a.cards, b.cards = b.cards, a.cards
        game.rng.seed(12348)
        altered = game.observe(seat)
        self.assertEqual(original, altered)
        self.assertEqual(determinize(original, 290).deck, determinize(altered, 290).deck)

    def test_sampled_match_respects_known_holdings_and_offer(self):
        game = advance(Game(9))
        seat = game.active
        recipient = (seat+1)%4
        game.phase = "action"
        grant(game, seat, wood=3)
        game.trade_offer(recipient, (3, 0, 0, 0, 0), (0, 0, 1, 0, 0))
        observation = game.observe(recipient)
        for seed in range(15):
            rollout = determinize(observation, seed)
            self.assertEqual(rollout.observe(recipient), observation)
            self.assertGreaterEqual(rollout.players[seat].hand[0], 3)

    def test_public_bounds_and_determinization_in_live_games(self):
        for seed in (40, 188, 272):
            game = Game(seed)
            for step in range(150):
                if game.winner is not None:
                    break
                obs = game.observe(game.actor)
                if step % 6 == 0:
                    self.assertTrue(all(lo <= actual for lower, player in
                        zip(public_minimum(obs), game.players) for lo, actual in zip(lower, player.hand)))
                    self.assertEqual(determinize(obs, seed+step).observe(obs.seat), obs)
                move = choose(obs)
                if move[0] == "offer":
                    game.trade_offer(*move[1:])
                else:
                    game.apply(move)

    def test_simulation_batches_use_disjoint_reproducible_ranges(self):
        game = Game(12)
        observation = game.observe(game.actor)
        action = observation.actions[0]
        full = simulate_batch(observation, action, 0, 4, 11, BASE)
        first = simulate_batch(observation, action, 0, 2, 11, BASE)
        second = simulate_batch(observation, action, 2, 2, 11, BASE)
        self.assertEqual(full, tuple(a+b for a, b in zip(first, second)))

    def test_shared_setup_prefix_matches_independent_games(self):
        game = Game(12)
        for _ in range(2):
            observation = game.observe(game.actor)
            action = observation.actions[0]
            winners = []
            for index in range(6):
                world = Random(711+index).getrandbits(64)
                replica = determinize(observation, world)
                replica.step(action)
                winners.append(play(replica, (BASE,)*4, record_history=False))
            self.assertEqual(simulate_batch(observation, action, 0, 6, 711, BASE),
                             (6, winners.count(observation.seat), winners.count(None)))
            self.assertEqual(game.observe(game.actor), observation)
            game.step(action)

    def test_coach_rejects_insufficient_evidence(self):
        game = Game(12)
        obs = game.observe(game.active)
        with self.assertRaises(ValueError):
            evaluate(obs, obs.actions[:1], count=999)
        self.assertAlmostEqual(interval(50, 100)[0], 0.404, places=3)

    def test_replay_round_trip(self):
        session = Session(402, "Easy")
        for _ in range(100):
            game = session.game
            session.step(choose(game.observe(game.actor)))
        with tempfile.TemporaryDirectory() as temp:
            destination = Path(temp) / "game.hex.json"
            session.save(destination)
            self.assertEqual(json.loads(destination.read_text())["version"], 2)
            other = Session.load(destination)
            self.assertEqual(other.difficulty, "Easy")
            self.assertEqual(other.moves, session.moves)
            self.assertEqual(other.game.rng.getstate(), session.game.rng.getstate())
            for player in range(4):
                self.assertEqual(other.game.observe(player), session.game.observe(player))


if __name__ == "__main__":
    unittest.main()
