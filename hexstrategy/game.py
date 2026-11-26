"""Authoritative four-player rules and player-scoped observations."""
from dataclasses import dataclass, field
from itertools import combinations_with_replacement, product
from random import Random
from typing import NamedTuple

from .board import Board, RESOURCES

WOOD, BRICK, WOOL, GRAIN, ORE = range(5)
COSTS = {"road": (1, 1, 0, 0, 0), "settlement": (1, 1, 1, 1, 0),
         "city": (0, 0, 0, 2, 3), "buy": (0, 0, 1, 1, 1)}
DECK = ("knight",)*14 + ("point",)*5 + ("roads",)*2 + ("plenty",)*2 + ("monopoly",)*2
SETUP = (0, 1, 2, 3, 3, 2, 1, 0)


def route_length(board, buildings, roads, seat):
    """Find the longest trail, stopping at another player's building."""
    def walk(vertex, trail):
        piece = buildings[vertex]
        if trail and piece and piece[0] != seat:
            return 0
        best = 0
        for edge in board.incident[vertex]:
            if edge in roads and not trail & (1 << edge):
                a, b = board.edges[edge]
                best = max(best, 1 + walk(a+b-vertex, trail | (1 << edge)))
        return best

    endpoints = {v for edge in roads for v in board.edges[edge]}
    return max((walk(v, 0) for v in endpoints), default=0)


@dataclass
class Player:
    hand: list[int] = field(default_factory=lambda: [0]*5)
    cards: list[tuple[str, int]] = field(default_factory=list)
    knights: int = 0


class Observation(NamedTuple):
    board: Board
    seat: int
    active: int
    phase: str
    turn: int
    setup: int
    anchor: int
    robber: int
    buildings: tuple
    roads: tuple
    bank: tuple
    card_totals: tuple
    development_totals: tuple
    hand: tuple
    cards: tuple
    knights: tuple
    longest: int | None
    army: int | None
    history: tuple
    actions: tuple
    deck_size: int
    revealed: tuple
    pending: tuple
    free_roads: int
    resume: str
    used_card: bool
    offer: tuple | None
    traded: bool
    seating: tuple


class Game:
    def __init__(self, seed=None):
        self.rng = Random(seed)
        self.board = Board.random(self.rng)
        self.deck = list(DECK)
        self.rng.shuffle(self.deck)
        self.players = [Player() for _ in range(4)]
        self.seating = list(range(4))
        self.rng.shuffle(self.seating)
        self.active = self.seating[0]
        self.buildings = [None]*len(self.board.vertices)
        self.roads = [None]*len(self.board.edges)
        self.robber = next(i for i, tile in enumerate(self.board.tiles) if not tile.number)
        self.bank = [19]*5
        self.phase = "opening"
        self.setup = self.turn = 0
        self.anchor = -1
        self.longest = self.army = self.winner = None
        self.history, self.revealed, self.pending = [], [], []
        self.record_history = True
        self.used_card = False
        self.resume = "action"
        self.free_roads = 0
        self.offer = None
        self.traded = False
        self.dice = None

    @property
    def actor(self):
        if self.phase == "discard":
            return self.pending[0]
        if self.phase == "trade_response":
            return self.offer[0]
        return self.active

    def observe(self, seat):
        actions = tuple(self.legal()) if seat == self.actor else ()
        return self._observation(seat, actions)

    def _observation(self, seat, actions):
        player = self.players[seat]
        return Observation(
            self.board, seat, self.active, self.phase, self.turn, self.setup,
            self.anchor, self.robber, tuple(self.buildings), tuple(self.roads),
            tuple(self.bank), tuple(sum(p.hand) for p in self.players),
            tuple(len(p.cards) for p in self.players), tuple(player.hand),
            tuple(player.cards), tuple(p.knights for p in self.players),
            self.longest, self.army, tuple(self.history) if self.record_history else (),
            actions, len(self.deck),
            tuple(self.revealed), tuple(self.pending), self.free_roads, self.resume,
            self.used_card, self.offer, self.traded, tuple(self.seating),
        )

    def score(self, seat, private=False):
        points = sum(piece[1] for piece in self.buildings if piece and piece[0] == seat)
        points += 2*((self.longest == seat) + (self.army == seat))
        if private:
            points += sum(card == "point" for card, _ in self.players[seat].cards)
        return points

    def settlement_sites(self, seat, opening=False):
        for v, piece in enumerate(self.buildings):
            if piece or any(self.buildings[n] for n in self.board.neighbors[v]):
                continue
            if opening or any(self.roads[e] == seat for e in self.board.incident[v]):
                yield v

    def road_sites(self, seat):
        if self.roads.count(seat) >= 15:
            return
        origins = {v for v, piece in enumerate(self.buildings) if piece and piece[0] == seat}
        for i, owner in enumerate(self.roads):
            if owner == seat:
                origins.update(v for v in self.board.edges[i] if self.buildings[v] is None)
        yield from sorted({e for v in origins for e in self.board.incident[v]
                           if self.roads[e] is None})

    def rates(self, seat):
        rates = [4]*5
        general = 4
        for edge, resource in self.board.ports:
            a, b = self.board.edges[edge]
            first, second = self.buildings[a], self.buildings[b]
            if (first and first[0] == seat) or (second and second[0] == seat):
                if resource is None:
                    general = 3
                else:
                    rates[RESOURCES.index(resource)] = 2
        if general == 3:
            return [min(rate, 3) for rate in rates]
        return rates

    def rate(self, seat, give):
        return self.rates(seat)[give]

    def robber_moves(self):
        for tile, vertices in enumerate(self.board.corners):
            if tile == self.robber:
                continue
            victims = {self.buildings[v][0] for v in vertices if self.buildings[v]}
            victims.discard(self.active)
            for victim in sorted(victims) if victims else (None,):
                yield ("rob", tile, victim)

    def legal(self):
        seat = self.actor
        player = self.players[seat]
        hand = player.hand
        if self.phase == "finished":
            return
        if self.phase == "opening":
            yield from (("settlement", v) for v in self.settlement_sites(seat, True))
            return
        if self.phase == "opening_road":
            yield from (("road", e) for e in self.board.incident[self.anchor]
                        if self.roads[e] is None)
            return
        if self.phase == "discard":
            count = sum(hand)//2
            for first in product(*(range(min(h, count)+1) for h in hand[:4])):
                last = count-sum(first)
                if 0 <= last <= hand[4]:
                    yield ("discard", first+(last,))
            return
        if self.phase == "robber":
            yield from self.robber_moves()
            return
        if self.phase == "roads":
            yield from (("road", e) for e in self.road_sites(seat))
            return
        if self.phase == "trade_response":
            yield ("decline",)
            if self.affords(seat, self.offer[2]):
                yield ("accept",)
            return
        if not self.used_card:
            cards = {card for card, acquired in player.cards if acquired < self.turn}
            if "knight" in cards:
                yield ("knight",)
            if "roads" in cards and any(True for _ in self.road_sites(seat)):
                yield ("roads",)
            if "monopoly" in cards:
                yield from (("monopoly", i) for i in range(5))
            if "plenty" in cards:
                available = [i for i, count in enumerate(self.bank) if count]
                if sum(self.bank) == 1:
                    yield ("plenty", *available)
                for a, b in combinations_with_replacement(available, 2):
                    if a != b or self.bank[a] >= 2:
                        yield ("plenty", a, b)
        if self.phase == "roll":
            yield ("roll",)
            return
        yield ("end",)
        if self.affords(seat, COSTS["road"]):
            yield from (("road", e) for e in self.road_sites(seat))
        if self.buildings.count((seat, 1)) < 5 and self.affords(seat, COSTS["settlement"]):
            yield from (("settlement", v) for v in self.settlement_sites(seat))
        if self.buildings.count((seat, 2)) < 4 and self.affords(seat, COSTS["city"]):
            yield from (("city", v) for v, piece in enumerate(self.buildings) if piece == (seat, 1))
        if self.deck and self.affords(seat, COSTS["buy"]):
            yield ("buy",)
        if max(hand) < 2:
            return
        for give, rate in enumerate(self.rates(seat)):
            if hand[give] >= rate:
                yield from (("bank", give, get) for get in range(5)
                            if get != give and self.bank[get])

    def affords(self, seat, cost):
        wood, brick, wool, grain, ore = self.players[seat].hand
        wood_cost, brick_cost, wool_cost, grain_cost, ore_cost = cost
        return (wood >= wood_cost and brick >= brick_cost and wool >= wool_cost
                and grain >= grain_cost and ore >= ore_cost)

    def trade_offer(self, target, give, get, sender=None):
        self.offer = self.validate_trade_offer(target, give, get, sender)
        if self.record_history:
            self.history.append((self.offer[3], "offer", self.offer))
        self.phase = "trade_response"

    def validate_trade_offer(self, target, give, get, sender=None):
        sender = self.active if sender is None else sender
        if sender not in range(4) or target not in range(4) or sender == target:
            raise ValueError("Choose a different trade partner.")
        counter = self.phase == "trade_response" and sender == self.actor and target == self.offer[3]
        if self.active not in (sender, target) or (self.phase != "action" and not counter):
            raise ValueError("Trades must involve the active player during the action phase.")
        give, get = tuple(give), tuple(get)
        if any(len(bundle) != 5 or any(type(n) is not int or n < 0 for n in bundle)
               or not sum(bundle) for bundle in (give, get)):
            raise ValueError("Each side must offer a positive resource bundle.")
        if any(a and b for a, b in zip(give, get)) or not self.affords(sender, give):
            raise ValueError("The offered resources are invalid or unavailable.")
        return target, give, get, sender

    def bank_transfer(self, seat, amounts, direction):
        for i, n in enumerate(amounts):
            self.players[seat].hand[i] += direction*n
            self.bank[i] -= direction*n

    def produce(self, roll):
        requests = [[0]*4 for _ in range(5)]
        for index, tile in enumerate(self.board.tiles):
            if tile.number == roll and index != self.robber:
                for vertex in self.board.corners[index]:
                    piece = self.buildings[vertex]
                    if piece:
                        seat, amount = piece
                        requests[RESOURCES.index(tile.resource)][seat] += amount
        paid = [[0]*5 for _ in self.players] if self.record_history else None
        for resource, demands in enumerate(requests):
            shortage = sum(demands) > self.bank[resource]
            if shortage and sum(bool(n) for n in demands) > 1:
                continue
            for seat, demand in enumerate(demands):
                amount = min(demand, self.bank[resource])
                self.players[seat].hand[resource] += amount
                self.bank[resource] -= amount
                if paid is not None:
                    paid[seat][resource] = amount
        if paid is not None:
            self.history.append(("production", roll, tuple(map(tuple, paid))))

    def road_length(self, seat):
        owned = {edge for edge, owner in enumerate(self.roads) if owner == seat}
        return route_length(self.board, self.buildings, owned, seat)

    @staticmethod
    def award(values, threshold, holder):
        leaders = [i for i, n in enumerate(values) if n == max(values) and n >= threshold]
        if holder in leaders:
            return holder
        return leaders[0] if len(leaders) == 1 else None

    def step(self, action):
        if action not in self.legal():
            raise ValueError(f"Illegal action {action!r} during {self.phase}")
        self.apply(action)

    def apply(self, action):
        """Apply an action already validated by the caller."""
        seat, phase = self.actor, self.phase
        player = self.players[seat]
        kind, *args = action
        if self.record_history:
            public_args = tuple(args)
            if kind == "discard":
                public_args = (sum(args[0]),)
            elif kind == "bank":
                public_args += (self.rate(seat, args[0]),)
            elif kind == "accept":
                public_args = (self.offer[3], self.offer[1], self.offer[2])
            elif kind == "monopoly":
                public_args += (tuple(p.hand[args[0]] if i != seat else 0
                                      for i, p in enumerate(self.players)),)
            self.history.append((seat, kind, public_args))
        if kind in ("accept", "decline"):
            _, give, get, sender = self.offer
            if kind == "accept":
                for i in range(5):
                    self.players[sender].hand[i] += get[i]-give[i]
                    player.hand[i] += give[i]-get[i]
            self.offer = None
            self.traded = True
            self.phase = "action"
        elif kind == "roll":
            self.dice = self.rng.randint(1, 6), self.rng.randint(1, 6)
            roll = sum(self.dice)
            if roll == 7:
                first = self.seating.index(seat)
                order = self.seating[first:] + self.seating[:first]
                self.pending = [p for p in order if sum(self.players[p].hand) > 7]
                self.resume = "action"
                self.phase = "discard" if self.pending else "robber"
            else:
                self.produce(roll)
                self.phase = "action"
        elif kind == "discard":
            self.bank_transfer(seat, args[0], -1)
            self.pending.pop(0)
            if not self.pending:
                self.phase = "robber"
        elif kind == "rob":
            self.robber, victim = args
            if victim is not None and any(self.players[victim].hand):
                source = self.players[victim].hand
                resource = self.rng.choices(range(5), weights=source)[0]
                source[resource] -= 1
                player.hand[resource] += 1
            self.phase = self.resume
        elif kind == "bank":
            give, get = args
            rate = self.rate(seat, give)
            player.hand[give] -= rate
            self.bank[give] += rate
            player.hand[get] += 1
            self.bank[get] -= 1
        elif kind == "end":
            self.active = self.seating[(self.seating.index(seat)+1)%4]
            self.turn += 1
            self.used_card = self.traded = False
            self.phase = "roll"
        elif kind in COSTS:
            if phase == "action":
                self.bank_transfer(seat, COSTS[kind], -1)
            if kind == "buy":
                player.cards.append((self.deck.pop(), self.turn))
            elif kind == "city":
                self.buildings[args[0]] = (seat, 2)
            elif kind == "settlement":
                self.buildings[args[0]] = (seat, 1)
                if phase == "opening":
                    self.anchor = args[0]
                    self.phase = "opening_road"
                    if self.setup >= 4:
                        for tile in self.board.adjoining[self.anchor]:
                            resource = self.board.tiles[tile].resource
                            if resource:
                                r = RESOURCES.index(resource)
                                player.hand[r] += 1
                                self.bank[r] -= 1
                self.update_longest()
            else:
                self.roads[args[0]] = seat
                self.update_longest()
                if phase == "opening_road":
                    self.setup += 1
                    if self.setup == 8:
                        self.phase = "roll"
                    else:
                        self.active = self.seating[SETUP[self.setup]]
                        self.phase = "opening"
                elif phase == "roads":
                    self.free_roads -= 1
                    if not self.free_roads or not any(self.road_sites(seat)):
                        self.phase = self.resume
        else:
            card = next(entry for entry in player.cards
                        if entry[0] == kind and entry[1] < self.turn)
            player.cards.remove(card)
            self.revealed.append(kind)
            self.used_card = True
            if kind == "knight":
                player.knights += 1
                self.army = self.award([p.knights for p in self.players], 3, self.army)
                self.resume, self.phase = phase, "robber"
            elif kind == "roads":
                self.free_roads = 2
                self.resume, self.phase = phase, "roads"
            elif kind == "plenty":
                self.bank_transfer(seat, tuple(args.count(i) for i in range(5)), 1)
            elif kind == "monopoly":
                resource = args[0]
                for other, opponent in enumerate(self.players):
                    if other != seat:
                        player.hand[resource] += opponent.hand[resource]
                        opponent.hand[resource] = 0
        scoring_move = kind in ("settlement", "city", "road", "buy", "rob", "end")
        if scoring_move and self.phase in ("action", "roll", "roads") and self.score(self.active, True) >= 10:
            self.winner = self.active
            self.phase = "finished"
            if self.record_history:
                points = sum(card == "point" for card, _ in self.players[self.winner].cards)
                self.history.append((self.winner, "victory", (points,)))

    def update_longest(self):
        self.longest = self.award([self.road_length(p) if self.roads.count(p) >= 5 else 0
                                   for p in range(4)], 5, self.longest)
