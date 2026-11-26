# Architecture and evaluation

## Information flow

`game.py` owns the deck, dice, resource inventories, legal actions, and state transitions. AI policies receive an immutable player observation containing their own hand and developmental cards, board state, resource supply, other players' public card counts, and public transfers. A policy never receives the authoritative game instance or its random seed. GUI saves store a seed and action replay locally, so access to a save can reveal hidden information.

Coaching samples hidden inventories and development cards consistent with visible totals and known lower bounds. The lower bounds use public production, payments, trades, and the number of discarded or stolen cards. Unknown transfers and shuffled development cards retain uncertainty. Simulated players each receive their own observation. Rollouts compare alternative first actions using the same sampled worlds and random seeds, then follow the rollout policy to victory or the cutoff. The random streams can diverge when actions consume different numbers of draws.

Each displayed action has at least 1,000 full continuations. Estimates report wins divided by all attempted continuations and a 95% Wilson interval for wins by the cutoff. Unfinished games are shown separately. The interval covers simulation sampling variation under the assumed continuation policy. It does not capture the difference between that policy and real human play. The ordinary hint compares a shortlist. Select a different action in the move list to include it in the next comparison.

## Policy development

The Standard opponent weighs production, diversity, build affordability, expansion, and robber denial. Hard automatically loads weights selected through seeded match experiments. Candidate policies consider resource scarcity, production planning, routes, and opponent decisions during setup. The candidates compete as seat zero against three Standard opponents with independently randomized boards, order, decks, and dice. Training batches reuse seed sets across candidates for a controlled comparison. Holdouts use separate seed sets.

- [Training search](artifacts/training.json) and [strategic policy holdout](artifacts/strategic-holdout.json).
- [Route refinement](artifacts/refinement.json) and [refinement holdout](artifacts/refinement-holdout.json).
- [Opening search](artifacts/opening-search.json), [opening holdout](artifacts/opening-holdout.json), and [loaded policy](artifacts/policy.json).
- [Coaching measurements](artifacts/coaching.json), including per-action outcome counts, intervals, and system details.

The 70% win-rate target and three-second hint target remain open. The benchmark records full matches with a turn cutoff. Single-policy match results do not establish performance against expert human players. The automated desktop test drives a full graphical match through the same move handlers used for play, saves in midgame, reopens the save, and verifies the result display.
