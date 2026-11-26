"""Observation-only policies and paired, information-set rollouts."""
from dataclasses import dataclass
from functools import lru_cache
from math import sqrt
from random import Random

from .board import RESOURCES
from .game import COSTS, DECK, SETUP, Game, Player, route_length

BASE = (1.0, 1.0, 0.85, 1.15, 1.1, 1.0, 1.0, 1.0)
REASONS = {
    "settlement": "Adds a point and production. Site values account for dice odds and resource coverage.",
    "city": "Adds a point and doubles production at the selected site.",
    "road": "Extends the network toward legal building sites or the route award.",
    "buy": "Exchanges resources for an uncertain card that can add points or improve a future turn.",
    "rob": "Denies production and may take a resource. Blocking a leader carries more value.",
    "bank": "Converts a surplus to a resource needed for construction.",
    "discard": "Preserves resources for the next attainable construction.",
    "end": "Keeps resources for later and passes the turn.",
    "roll": "Starts production with the current board and robber placement.",
    "knight": "Moves the robber and advances toward the army award.",
    "plenty": "Takes available resources from the supply.",
    "monopoly": "Collects all opposing holdings of the chosen resource.",
    "roads": "Adds up to two connected roads without spending resources.",
    "accept": "Exchanges the offered bundles. Both players gain resources they requested.",
    "wait": "Makes no offer and lets the active player continue the turn.",
    "offer": "Trades the proposed bundle if the recipient accepts. The recipient may gain a useful resource too.",
    "decline": "Preserves your hand and avoids supplying the active player.",
}


@lru_cache(maxsize=128)
def site_values(board, weights):
    return tuple(sum((6-abs(7-board.tiles[t].number)) * weights[
        RESOURCES.index(board.tiles[t].resource)] for t in tiles
        if board.tiles[t].resource) for tiles in board.adjoining)


@lru_cache(maxsize=2048)
def building_metrics(board, buildings):
    owned = [[], [], [], []]
    points = [0]*4
    clear = []
    for v, piece in enumerate(buildings):
        if piece:
            seat, level = piece
            owned[seat].append(v)
            points[seat] += level
        clear.append(piece is None and not any(buildings[n] for n in board.neighbors[v]))
    return tuple(map(tuple, owned)), tuple(points), tuple(clear)


def ranked(obs, weights=BASE):
    if len(weights) in (10, 13, 14, 15):
        return strategic(obs, weights)
    if len(obs.actions) <= 1:
        return [(0, a) for a in obs.actions]
    board, seat, hand = obs.board, obs.seat, obs.hand
    sites = site_values(board, weights[:5])
    sites_by_player, base_points, clear = building_metrics(board, obs.buildings)
    owned = sites_by_player[seat]
    covered = {board.tiles[t].resource for v in owned for t in board.adjoining[v]}
    targets = [cost for kind, cost in COSTS.items() if kind != "city" or owned]
    points = [n + 2*((obs.longest == p)+(obs.army == p))
              for p, n in enumerate(base_points)]

    def deficit(resources):
        return min(sum(max(0, n-h) for n, h in zip(cost, resources))
                   for cost in targets if cost != COSTS["road"])

    accessible = None
    current_deficit = None
    tile_denials = {}

    def value(action):
        nonlocal accessible, current_deficit
        kind, *args = action
        if kind == "settlement":
            v = args[0]
            diversity = {board.tiles[t].resource for t in board.adjoining[v]} - covered - {None}
            return 25 + sites[v] + len(diversity)*2.5*weights[5]
        if kind == "city":
            return 29 + sites[args[0]]
        if kind == "road":
            a, b = board.edges[args[0]]
            def reach(v):
                if obs.buildings[v]:
                    return 0
                return (9 + sites[v]*0.65 if clear[v] else max(
                    (sites[n]*0.55 for n in board.neighbors[v] if clear[n]), default=0))
            expansion = max(reach(a), reach(b))
            if obs.phase in ("opening_road", "roads"):
                return expansion
            if accessible is None:
                accessible = any(clear[v] and any(obs.roads[e] == seat for e in board.incident[v])
                                 for v in range(len(clear)))
            return expansion - (12 if accessible else 5) + weights[6]*(
                4 if obs.roads.count(seat) >= 4 and obs.longest != seat else 0)
        if kind == "buy":
            return 10.5*weights[7] + 2*(points[seat] >= 7)
        if kind == "rob":
            t, victim = args
            if t not in tile_denials:
                number = board.tiles[t].number
                denial = sum(piece[1] * (-3 if piece[0] == seat else 1 + .22*points[piece[0]])
                             for v in board.corners[t] if (piece := obs.buildings[v]))
                tile_denials[t] = denial * (6-abs(7-number))
            theft = points[victim]*0.45+3 if victim is not None and obs.card_totals[victim] else 0
            return tile_denials[t] + theft
        if kind == "discard":
            remaining = tuple(h-n for h, n in zip(hand, args[0]))
            return -4*deficit(remaining) + sum(min(n, 3)*w for n, w in zip(remaining, weights))
        if kind == "bank":
            give, get = args
            rate = min((2 if resource == RESOURCES[give] else 3
                        for e, resource in board.ports if resource in (None, RESOURCES[give])
                        and any(v in owned for v in board.edges[e])), default=4)
            after = list(hand)
            after[give] -= rate
            after[get] += 1
            if current_deficit is None:
                current_deficit = deficit(hand)
            return 3*(current_deficit-deficit(after)) - 0.5 + (sum(hand) >= 9)*0.7
        if kind == "knight":
            return 5 + 3*(obs.knights[seat] == 2 and obs.army is None)
        if kind == "roads":
            return 7
        if kind == "plenty":
            after = tuple(h+args.count(i) for i, h in enumerate(hand))
            return 2 + 3*(deficit(hand)-deficit(after))
        if kind == "monopoly":
            i = args[0]
            available = 19 - obs.bank[i] - hand[i]
            after = list(hand)
            after[i] += available
            return (available-2)*1.5 + 2*(deficit(hand)-deficit(after))
        if kind == "accept":
            _, give, get, sender = obs.offer
            after = tuple(h+a-b for h, a, b in zip(hand, give, get))
            return 3*(deficit(hand)-deficit(after)) + sum(give)-sum(get) - points[sender]*.15
        if kind == "roll":
            return 3
        return 0

    return sorted(((value(action), action) for action in obs.actions), key=lambda pair: -pair[0])


def choose(observation, weights=BASE):
    action = ranked(observation, weights)[0][1]
    if action == ("end",):
        return suggested_offer(observation, weights) or action
    return action


def determinize(obs, seed, minimum=None):
    """Sample hidden cards subject to visible inventories and acquisition timing."""
    game = Game.__new__(Game)
    game.rng = rng = Random(seed)
    copy = ("board", "active", "phase", "turn", "setup", "anchor", "robber", "longest",
            "army", "free_roads", "resume", "used_card", "offer", "traded")
    for attr in copy:
        setattr(game, attr, getattr(obs, attr))
    for attr in ("buildings", "roads", "bank", "pending", "revealed", "seating"):
        setattr(game, attr, list(getattr(obs, attr)))
    game.winner = None
    game.dice = None
    game.history = list(obs.history)
    game.record_history = True
    game.players = [Player(knights=n) for n in obs.knights]
    player = game.players[obs.seat]
    player.hand = list(obs.hand)
    player.cards = list(obs.cards)
    minimum = public_minimum(obs) if minimum is None else minimum
    unseen = [i for i, bank in enumerate(obs.bank)
              for _ in range(19-bank-sum(hand[i] for hand in minimum))]
    rng.shuffle(unseen)
    deck = list(DECK)
    for card in list(obs.revealed) + [card for card, _ in obs.cards]:
        deck.remove(card)
    rng.shuffle(deck)
    recent = sum(event[0] == obs.active and event[1] == "buy"
                 for event in reversed(obs.history[1+max(
                     (i for i, e in enumerate(obs.history) if e[1] == "end"), default=-1):]))
    for i, opponent in enumerate(game.players):
        if i == obs.seat:
            continue
        opponent.hand = list(minimum[i])
        for _ in range(obs.card_totals[i]-sum(opponent.hand)):
            opponent.hand[unseen.pop()] += 1
        for j in range(obs.development_totals[i]):
            acquired = obs.turn if i == obs.active and j < recent else obs.turn-1
            opponent.cards.append((deck.pop(), acquired))
    game.deck = deck
    return game


def play(game, policies, turn_limit=450, record_history=True, decision=choose):
    game.record_history = record_history
    while game.winner is None and game.turn < turn_limit:
        actor = game.actor
        actions = tuple(game.legal())
        if decision is choose and len(actions) == 1 and actions[0] != ("end",):
            action = actions[0]
        else:
            action = decision(game._observation(actor, actions), policies[actor])
        if action[0] == "offer":
            game.trade_offer(*action[1:])
        else:
            game.apply(action)
    return game.winner


@dataclass(frozen=True)
class Estimate:
    action: tuple
    games: int
    wins: int
    unresolved: int
    probability: float
    interval: tuple[float, float]
    explanation: str


def interval(wins, total):
    z = 1.95996398454
    p = wins/total
    denominator = 1+z*z/total
    center = (p+z*z/(2*total))/denominator
    offset = z*sqrt(p*(1-p)/total+z*z/(4*total*total))/denominator
    return max(0., center-offset), min(1., center+offset)


def simulate_batch(obs, action, start, count, seed, weights, opponent_weights=None):
    """Return actual wins and unfinished games in a disjoint seed range."""
    wins = unresolved = 0
    minimum = public_minimum(obs)
    policies = tuple(weights if i == obs.seat else opponent_weights or weights for i in range(4))
    for index in range(start, start+count):
        world = Random(seed+index).getrandbits(64)
        game = determinize(obs, world, minimum)
        if action[0] == "offer":
            game.trade_offer(*action[1:])
        elif action != ("wait",):
            game.step(action)
        winner = play(game, policies, max(450, obs.turn+300), record_history=False)
        wins += winner == obs.seat
        unresolved += winner is None
    return count, wins, unresolved


def estimate(obs, action, batches):
    games = wins = unresolved = 0
    for count, victories, unfinished in batches:
        games += count
        wins += victories
        unresolved += unfinished
    if games < 1000:
        raise ValueError("Coaching requires at least 1,000 outcomes per action.")
    return Estimate(action, games, wins, unresolved, wins/games,
                    interval(wins, games), explain(obs, action))


def evaluate(obs, candidates, count=1000, seed=0, weights=BASE):
    """Compare first actions in identical sampled worlds."""
    if count < 1000:
        raise ValueError("Coaching requires at least 1,000 outcomes per action.")
    estimates = [estimate(obs, action, [simulate_batch(obs, action, 0, count, seed, weights)])
                 for action in candidates]
    return sorted(estimates, key=lambda result: -result.probability)


def strategic(obs, weights):
    """Score the opportunity cost of building against an explicit production plan."""
    if len(obs.actions) <= 1:
        return [(0, move) for move in obs.actions]
    if obs.phase in ("robber", "trade_response"):
        return ranked(obs, BASE)
    seat, board = obs.seat, obs.board
    hand = obs.hand
    sites_by_player, base_points, clear = building_metrics(board, obs.buildings)
    owned = sites_by_player[seat]
    own_roads = {e for e, owner in enumerate(obs.roads) if owner == seat}
    scores = [n + 2*((obs.longest == p)+(obs.army == p))
              for p, n in enumerate(base_points)]
    own_score = scores[seat] + sum(card == "point" for card, _ in obs.cards)
    pips = production(board)
    totals = [sum(pips[v][i]*obs.buildings[v][1] for v in owned) for i in range(5)]
    close = len(weights) >= 13
    current_length = None
    opposition_lengths = None
    number_counts = {}
    if close:
        for v in owned:
            for t in board.adjoining[v]:
                number = board.tiles[t].number
                if number:
                    number_counts[number] = number_counts.get(number, 0) + 1
    scarcity = [weights[i]*(1.1 if not totals[i] else 0.9 if totals[i] < 6 else 0.65)
                for i in range(5)]
    connected = {v for e in own_roads for v in board.edges[e]}
    available = [v for v in connected if clear[v]]
    targets = {"city": 8 + weights[6], "buy": 6 + weights[7],
               "settlement": 8 + weights[5]}
    if not available or obs.buildings.count((seat, 1)) >= 5:
        targets.pop("settlement")
    if not any(obs.buildings[v][1] == 1 for v in owned) or obs.buildings.count((seat, 2)) >= 4:
        targets.pop("city")
    if not obs.deck_size:
        targets.pop("buy")

    def utility(resources):
        return max((value - sum(max(0, n-h)*(1.5 + scarcity[i]*1.4)
                                for i, (n, h) in enumerate(zip(COSTS[kind], resources)))
                    for kind, value in targets.items()), default=0)

    site_scores = {}

    def site(v):
        if v in site_scores:
            return site_scores[v]
        value = sum((p*weights[i] + min(p, max(0, 6-totals[i]))*0.65)
                    for i, p in enumerate(pips[v]))
        if close:
            numbers = [board.tiles[t].number for t in board.adjoining[v] if board.tiles[t].number]
            value -= weights[10]*sum(number_counts.get(number, 0) for number in numbers)
            value += weights[11]*min(pips[v][3]+totals[3], pips[v][4]+totals[4], 9)*0.2
        if any(v in board.edges[e] and resource is None for e, resource in board.ports):
            value += 1.7
        for e, resource in board.ports:
            if resource and v in board.edges[e]:
                i = RESOURCES.index(resource)
                value += 0.5 + totals[i]*0.24 + pips[v][i]*0.23
        site_scores[v] = value
        return value

    def road(e):
        nonlocal current_length, opposition_lengths
        a, b = board.edges[e]
        best = 0
        for v in (a, b):
            if v in connected or obs.buildings[v]:
                continue
            if clear[v]:
                best = max(best, site(v)+3)
            for edge in board.incident[v]:
                if edge == e or obs.roads[edge] is not None:
                    continue
                x, y = board.edges[edge]
                n = x+y-v
                if clear[n] and n not in connected:
                    best = max(best, site(n)*0.56)
        if obs.phase in ("opening_road", "roads"):
            return best
        improvement = best - max((site(v)+3 for v in available), default=0)
        route = len(own_roads) >= 3 and obs.longest != seat
        rating = improvement*0.82 - weights[8] + (weights[9] if route else 0)
        if close and route:
            if current_length is None:
                current_length = route_length(board, obs.buildings, own_roads, seat)
                opposition_lengths = [route_length(board, obs.buildings,
                    {e for e, owner in enumerate(obs.roads) if owner == other}, other)
                    for other in range(4) if other != seat and obs.roads.count(other) >= 5]
            length = route_length(board, obs.buildings, own_roads | {e}, seat)
            if length > current_length:
                rating += weights[12]*min(1.8, 0.15 + own_score*0.12)
            if length >= 5 and length > max(opposition_lengths, default=0):
                rating += 100 if own_score >= 8 else weights[12] + 4
        return rating

    before = None
    fallback = None

    def value(action):
        nonlocal before, fallback
        kind, *args = action
        if before is None and kind in ("bank", "plenty", "monopoly"):
            before = utility(hand)
        if kind == "settlement":
            return 30+site(args[0])
        if kind == "road":
            return road(args[0])
        if kind == "city":
            return 20+sum(pips[args[0]])*.45 + 2*(own_score == 9)
        if kind == "buy":
            return weights[7]+5 + (own_score >= 8)*3
        if kind == "bank":
            give, get = args
            rate = min((2 if resource == RESOURCES[give] else 3
                        for e, resource in board.ports if resource in (None, RESOURCES[give])
                        and any(v in owned for v in board.edges[e])), default=4)
            after = list(hand)
            after[give] -= rate
            after[get] += 1
            return (utility(after)-before)*1.8 - 0.7 + (sum(hand) >= 9)*0.8
        if kind in ("plenty", "monopoly"):
            after = list(hand)
            for i in args:
                after[i] += 1 if kind == "plenty" else 19-obs.bank[i]-hand[i]
            return (utility(after)-before)*1.65 + (sum(after)-sum(hand)-2)*1.25 - 0.2
        if kind == "discard":
            remaining = tuple(h-n for h, n in zip(hand, args[0]))
            return utility(remaining)*2 + sum(min(n, 3)*w for n, w in zip(remaining, scarcity))
        if kind == "knight":
            blocked = sum(piece[1] for v in board.corners[obs.robber]
                          if (piece := obs.buildings[v]) and piece[0] == seat)
            return 1.5+blocked*4 + (obs.knights[seat] < 3 and obs.army != seat)*3
        if kind == "roads":
            return max((road(i) for i, owner in enumerate(obs.roads)
                        if owner is None and any(v in connected and
                        (not obs.buildings[v] or obs.buildings[v][0] == seat)
                        for v in board.edges[i])), default=0) + 3
        if kind in ("end", "decline"):
            return 0
        if kind == "roll":
            return 3
        if fallback is None:
            fallback = {move: val for val, move in ranked(obs, BASE)}
        return fallback[action]

    options = sorted(((value(action), action) for action in obs.actions), key=lambda pair: -pair[0])
    if len(weights) == 15 and obs.phase == "opening":
        return opening_plan(obs, options, weights, pips)
    return options


@lru_cache(maxsize=128)
def production(board):
    return tuple(tuple(sum(6-abs(7-board.tiles[t].number) for t in tiles
                           if board.tiles[t].resource == resource)
                       for resource in RESOURCES) for tiles in board.adjoining)


def suggested_offer(obs, weights=BASE):
    if obs.phase != "action" or obs.traded:
        return None
    if len(weights) == 14:
        return targeted_offer(obs, weights[-1])
    seat, hand = obs.seat, obs.hand
    if max(hand) < 3:
        return None
    needs = set()
    for kind in ("settlement", "city", "buy"):
        if kind == "buy" and not obs.deck_size:
            continue
        if kind == "city" and (seat, 1) not in obs.buildings:
            continue
        needed = [i for i, n in enumerate(COSTS[kind]) for _ in range(max(0, n-hand[i]))]
        if len(needed) == 1:
            needs.add(needed[0])
    if not needs:
        return None
    for target in sorted(range(4), key=lambda p: -(obs.card_totals[p])):
        if target == seat or not obs.card_totals[target]:
            continue
        for get in sorted(needs):
            if 19-obs.bank[get]-hand[get] <= 0:
                continue
            for give in sorted(range(5), key=lambda i: -hand[i]):
                if give != get and hand[give] >= 3:
                    return ("offer", target, tuple(int(i == give) for i in range(5)),
                            tuple(int(i == get) for i in range(5)))
    return None


def public_minimum(obs):
    """Conservative per-resource lower bounds from visible transfers."""
    hands = [[0]*5 for _ in range(4)]
    opening = 0

    def change(seat, resource, amount):
        hands[seat][resource] = max(0, hands[seat][resource] + amount)

    for seat, kind, args in obs.history:
        if seat == "production":
            for player, bundle in enumerate(args):
                for resource, amount in enumerate(bundle):
                    change(player, resource, amount)
        elif kind == "settlement" and opening < 8:
            if opening >= 4:
                for t in obs.board.adjoining[args[0]]:
                    tile = obs.board.tiles[t]
                    if tile.resource:
                        change(seat, RESOURCES.index(tile.resource), 1)
            opening += 1
        elif kind in COSTS and not (kind == "road" and opening < 8):
            # Free setup/development roads lack a reliable cost marker in the
            # action log. Subtracting their cost only weakens the lower bound.
            for resource, amount in enumerate(COSTS[kind]):
                change(seat, resource, -amount)
        elif kind == "bank":
            give, get, rate = args
            change(seat, give, -rate)
            change(seat, get, 1)
        elif kind == "accept":
            sender, give, get = args
            for resource, (a, b) in enumerate(zip(give, get)):
                change(sender, resource, b-a)
                change(seat, resource, a-b)
        elif kind == "discard" or (kind == "rob" and args[1] is not None):
            player, amount = (seat, args[0]) if kind == "discard" else (args[1], 1)
            for resource in range(5):
                change(player, resource, -amount)
        elif kind == "plenty":
            for resource in args:
                change(seat, resource, 1)
        elif kind == "monopoly":
            resource, amounts = args
            for player, amount in enumerate(amounts):
                hands[player][resource] = 0 if player != seat else hands[player][resource] + sum(amounts)
    if obs.offer:
        for resource, quantity in enumerate(obs.offer[1]):
            sender = obs.offer[3]
            hands[sender][resource] = max(hands[sender][resource], quantity)
    hands[obs.seat] = list(obs.hand)
    return hands


def explain(obs, action):
    kind, *args = action
    reason = REASONS[kind]
    if kind in ("settlement", "city"):
        pips = production(obs.board)[args[0]]
        if sum(pips):
            holdings = ", ".join(f"{RESOURCES[i]} {n}" for i, n in enumerate(pips) if n)
            reason += f" Site production weights are {holdings} out of 36 dice outcomes."
    elif kind == "rob":
        tile, victim = args
        number = obs.board.tiles[tile].number
        weight = (6-abs(7-number)) if number else 0
        opponent_pieces = sum(piece[1] for v in obs.board.corners[tile]
                              if (piece := obs.buildings[v]) and piece[0] != obs.seat)
        own_pieces = sum(piece[1] for v in obs.board.corners[tile]
                         if (piece := obs.buildings[v]) and piece[0] == obs.seat)
        reason += f" On 36 rolls, this tile averages {weight*opponent_pieces} blocked opposing"
        reason += f" resources and {weight*own_pieces} blocked personal resources while occupied."
        if victim is not None:
            reason += f" The chosen opponent has {obs.card_totals[victim]} resources before stealing."
    elif kind == "monopoly":
        i = args[0]
        reason += f" Opponents collectively hold {19-obs.bank[i]-obs.hand[i]} {RESOURCES[i]}."
    elif kind == "offer":
        opponent = args[0]
        reason += f" This recipient has {obs.card_totals[opponent]} resources."
    return reason


def opening_plan(obs, options, weights, pips):
    """Forecast likely opening competition before committing a first settlement."""
    board, seat = obs.board, obs.seat
    rivals = site_values(board, BASE[:5])
    occupied = {v for v, piece in enumerate(obs.buildings) if piece}
    available = {v for _, (_, v) in options}
    segments = [({v} | set(board.neighbors[v])) for v in range(len(board.vertices))]
    existing = {p: [v for v in occupied if obs.buildings[v][0] == p] for p in range(4)}

    def roads_from(vertex, space):
        quality = [max((rivals[n] for n in board.neighbors[neighbor] if n in space), default=0)
                   for neighbor in board.neighbors[vertex] if neighbor not in occupied]
        return max(quality, default=0)

    def forecast(vertex):
        space = available - segments[vertex]
        if obs.setup >= 4:
            return weights[14]*roads_from(vertex, space)
        chosen = {p: locations[:] for p, locations in existing.items()}
        for p in (obs.seating[i] for i in SETUP[obs.setup+1:]):
            if p == seat:
                break
            seen = {i for v in chosen[p] for i, n in enumerate(pips[v]) if n}
            pick = max(space, key=lambda v: (rivals[v]+2.5*sum(
                bool(n) and i not in seen for i, n in enumerate(pips[v])), -v))
            chosen[p].append(pick)
            space.difference_update(segments[pick])
        alternatives = [(sum(pips[v][i]*weights[i] + min(pips[v][i], max(0, 7-pips[vertex][i]))*.65
                            for i in range(5)), v) for v in space]
        future, second = max(alternatives)
        return weights[13]*future + weights[14]*(roads_from(vertex, space) +
                                                  roads_from(second, space - segments[second])*.5)

    scored = [(score+forecast(action[1]), action) for score, action in options[:10]]
    floor = min(score for score, _ in scored)
    scored.extend((min(score, floor-0.001), action) for score, action in options[10:])
    return sorted(scored, key=lambda pair: -pair[0])


def targeted_offer(obs, strength):
    seat, hand, board = obs.seat, obs.hand, obs.board
    reachable = {v for edge, owner in enumerate(obs.roads) if owner == seat
                 for v in board.edges[edge] if not obs.buildings[v] and
                 not any(obs.buildings[n] for n in board.neighbors[v])}
    goals = []
    if reachable and obs.buildings.count((seat, 1)) < 5:
        goals.append(("settlement", 3.8))
    if (seat, 1) in obs.buildings and obs.buildings.count((seat, 2)) < 4:
        goals.append(("city", 3.4))
    if obs.deck_size:
        goals.append(("buy", 2.1))
    requests = []
    for kind, goal_value in goals:
        cost = COSTS[kind]
        missing = [i for i, required in enumerate(cost) if hand[i] < required]
        if len(missing) == 1 and cost[missing[0]]-hand[missing[0]] == 1:
            requests.append((missing[0], cost, goal_value))
    if not requests:
        return None
    remaining = [19-n-h for n, h in zip(obs.bank, hand)]
    pips = production(board)
    points = [sum(piece[1] for piece in obs.buildings if piece and piece[0] == p)
              + 2*((obs.longest == p)+(obs.army == p)) for p in range(4)]
    best = None
    best_value = 0.0
    for other, total in enumerate(obs.card_totals):
        if other == seat or not total or points[other] >= 9:
            continue
        income = [sum(pips[v][i]*piece[1] for v, piece in enumerate(obs.buildings)
                      if piece and piece[0] == other) for i in range(5)]
        resource_mass = [amount*(6+p) for amount, p in zip(remaining, income)]
        total_mass = sum(resource_mass)
        if not total_mass:
            continue
        for get, cost, benefit in requests:
            if remaining[get] == 0:
                continue
            probability = 1-(1-resource_mass[get]/total_mass)**total
            for give, quantity in enumerate(hand):
                spare = quantity-cost[give]
                if give == get or spare < 1:
                    continue
                offer_count = 2 if strength >= 1.5 and spare >= 2 and quantity >= 4 else 1
                possession = resource_mass[give]/total_mass
                recipient_need = (1-possession)**total
                utility = probability*(benefit*0.75 + recipient_need*strength
                                       + 0.18*min(spare, 5) - 0.25*points[other]
                                       - 0.6*(offer_count-1))
                if utility > best_value:
                    send = tuple(offer_count if i == give else 0 for i in range(5))
                    want = tuple(int(i == get) for i in range(5))
                    best_value, best = utility, ("offer", other, send, want)
    return best
