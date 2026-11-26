"""Desktop game for one human and three computer players."""
from concurrent.futures import ProcessPoolExecutor
from math import sqrt
from secrets import randbits
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

from .ai import BASE, ranked, suggested_offer
from .coach import OUTCOMES, collect, submit, worker_count
from .board import RESOURCES
from .session import Session, load_policy

INK = "#152b33"
PAPER = "#f5f0df"
WATER = "#163844"
ACCENT = "#99602a"
PLAYER = ("#ffe3a0", "#e98271", "#83c8cd", "#c3a9df")
LAND = ("#427666", "#ac6856", "#7e9f74", "#c4a04e", "#8b93a3")
NAMES = ("You", "Juniper", "Kestrel", "Rowan")
PHASE = dict(opening="Found your settlement", opening_road="Connect your settlement",
             roll="Roll the dice", action="Plan your next move", discard="Return resources",
             robber="Move the robber", roads="Place a free road",
             trade_response="Respond to an offer", finished="Game over")


def bundle(numbers):
    return ", ".join(f"{n} {resource}" for resource, n in zip(RESOURCES, numbers) if n) or "none"


def action_name(action):
    kind, *arg = action
    if kind in ("settlement", "city", "road"):
        return f"{kind.title()} · {arg[0]+1}"
    if kind == "rob":
        victim = f" and steal from {NAMES[arg[1]]}" if arg[1] is not None else ""
        return f"Block island {arg[0]+1}{victim}"
    if kind == "offer":
        return f"Offer {bundle(arg[1])} for {bundle(arg[2])} to {NAMES[arg[0]]}"
    if kind == "bank":
        return f"Exchange {RESOURCES[arg[0]]} for {RESOURCES[arg[1]]}"
    if kind in ("plenty", "monopoly"):
        return f"{kind.title()} · " + " and ".join(RESOURCES[i] for i in arg)
    if kind == "discard":
        return "Return " + bundle(arg[0])
    return dict(buy="Buy a discovery card", end="End turn", knight="Play knight",
                roads="Play road building", roll="Roll dice").get(kind, kind.title())


class Desktop:
    def __init__(self, root):
        self.root = root
        self.session = Session(randbits(64))
        self.weights = load_policy()
        self.executor = None
        self.revision = 0
        self.hint_futures = ()
        self.explicit_selection = False
        self.trade_window = None
        root.title("Hex Strategy")
        root.configure(bg=PAPER)
        root.minsize(940, 690)
        root.geometry("1140x788")
        root.protocol("WM_DELETE_WINDOW", self.close)
        style = ttk.Style(root)
        style.theme_use("clam")
        style.configure("TButton", font=("Helvetica", 10), padding=(9, 6))
        header = tk.Frame(root, bg=PAPER, padx=20, pady=10)
        header.pack(fill="x")
        tk.Label(header, text="HEX STRATEGY", bg=PAPER, fg=INK,
                 font=("Helvetica", 22, "bold")).pack(side="left")
        for title, callback in (("New", self.new), ("Open", self.open), ("Save", self.save),
                                ("Rules", self.rules)):
            ttk.Button(header, text=title, command=callback).pack(side="right", padx=3)
        self.difficulty = tk.StringVar(value="Hard")
        control = ttk.Combobox(header, values=("Easy", "Standard", "Hard"), state="readonly",
                               width=10, textvariable=self.difficulty)
        control.pack(side="right", padx=8)
        control.bind("<<ComboboxSelected>>", self.set_difficulty)
        body = tk.Frame(root, bg=PAPER, padx=14)
        body.pack(fill="both", expand=True)
        body.columnconfigure(0, weight=1)
        body.rowconfigure(0, weight=1)
        self.canvas = tk.Canvas(body, bg=WATER, highlightthickness=0)
        self.canvas.grid(row=0, column=0, sticky="nsew", padx=(0, 12))
        self.canvas.bind("<Configure>", lambda event: self.draw())
        panel = tk.Frame(body, bg=PAPER, width=330)
        panel.grid(row=0, column=1, sticky="ns")
        self.title = self.label(panel, 17, True)
        self.state = self.label(panel)
        self.player_rows = []
        for color in PLAYER:
            row = tk.Frame(panel, bg=PAPER)
            row.pack(fill="x")
            swatch = tk.Canvas(row, width=14, height=14, bg=PAPER, highlightthickness=0)
            swatch.create_oval(2, 2, 12, 12, fill=color, outline=INK)
            swatch.pack(side="left")
            self.player_rows.append(self.label(row))
        self.hand = self.label(panel)
        self.cards = self.label(panel)
        self.trade_info = self.label(panel)
        action_frame = tk.Frame(panel, bg=PAPER)
        action_frame.pack(fill="both", expand=True, pady=8)
        self.list = tk.Listbox(action_frame, width=35, height=12, bg="#fffaf0", fg=INK,
                               selectbackground=WATER, selectforeground=PAPER, exportselection=False, activestyle="none")
        scrollbar = ttk.Scrollbar(action_frame, orient="vertical", command=self.list.yview)
        self.list.configure(yscrollcommand=scrollbar.set)
        scrollbar.pack(side="right", fill="y")
        self.list.pack(side="left", fill="both", expand=True)
        self.list.bind("<Double-Button-1>", lambda event: self.commit())
        self.list.bind("<<ListboxSelect>>", self.select_move)
        controls = tk.Frame(panel, bg=PAPER)
        controls.pack(fill="x", pady=(0, 10))
        self.confirm = ttk.Button(controls, text="Play move", command=self.commit)
        self.confirm.pack(side="left")
        self.trade = ttk.Button(controls, text="Trade", command=self.trade_dialog)
        self.trade.pack(side="left", padx=5)
        self.hint = ttk.Button(controls, text="Coach", command=self.coach)
        self.hint.pack(side="left")
        self.footer = self.label(root)
        self.actions = []
        self.refresh()
        root.after(200, self.ai_turn)

    @property
    def game(self):
        return self.session.game

    def label(self, parent, size=10, bold=False):
        label = tk.Label(parent, justify="left", anchor="w", wraplength=310, bg=PAPER, fg=INK,
                         font=("Helvetica", size, "bold" if bold else "normal"))
        label.pack(fill="x", padx=2, pady=3)
        return label

    def select_move(self, event):
        self.explicit_selection = True
        self.draw()

    def draw(self):
        canvas, game = self.canvas, self.game
        canvas.delete("all")
        width, height = canvas.winfo_width(), canvas.winfo_height()
        scale = max(8, min(width/10.6, height/10.6))
        ox, oy = width/2, height/2
        board = game.board

        def xy(point):
            x, y = point
            return ox + x*scale*sqrt(3)/2, oy - y*scale/2

        def play_at(*actions):
            options = [a for a in self.actions if a in actions]
            if len(options) == 1:
                self.move(options[0])
            elif options:
                index = self.actions.index(options[0])
                self.list.selection_clear(0, "end")
                self.list.selection_set(index)
                self.list.see(index)
                self.explicit_selection = True
                self.draw()

        selection = self.list.curselection()
        highlighted = self.actions[selection[0]] if selection and selection[0] < len(self.actions) else ()
        for i, tile in enumerate(board.tiles):
            corners = [c for v in board.corners[i] for c in xy(board.vertices[v])]
            tag = f"tile{i}"
            selected_tile = bool(highlighted and highlighted[0] == "rob" and highlighted[1] == i)
            canvas.create_polygon(*corners, fill=LAND[RESOURCES.index(tile.resource)]
                                  if tile.resource else "#bba886", outline=PAPER if selected_tile else WATER, width=3, tags=tag)
            x, y = xy(tile.center)
            canvas.create_oval(x-14, y-16, x+14, y+12, fill=PAPER, outline="", tags=tag)
            canvas.create_text(x, y-2, text=tile.number or "–", tags=tag,
                               fill="#8c382d" if tile.number in (6, 8) else INK,
                               font=("Helvetica", 13, "bold"))
            canvas.create_text(x, y+21, text=(tile.resource or "waste").upper(),
                               fill="white", tags=tag, font=("Helvetica", 7, "bold"))
            canvas.create_text(x, y-23, text="✦" if i == game.robber else str(i+1),
                               fill=PAPER, tags=tag)
            canvas.tag_bind(tag, "<Button-1>", lambda event, tile=i: play_at(
                *(a for a in self.actions if a[0] == "rob" and a[1] == tile)))
        for e, (a, b) in enumerate(board.edges):
            x, y = xy(board.vertices[a])
            xx, yy = xy(board.vertices[b])
            owner = game.roads[e]
            candidate = ("road", e) in self.actions
            tag = f"edge{e}"
            if owner is not None or candidate:
                canvas.create_line(x, y, xx, yy, width=7 if owner is not None or highlighted == ("road", e) else 4,
                                   fill=PLAYER[owner] if owner is not None else "#fcf6dd",
                                   dash=() if owner is not None else (3, 5), tags=tag)
                canvas.tag_bind(tag, "<Button-1>", lambda event, edge=e: play_at(("road", edge)))
        for edge, resource in board.ports:
            a, b = board.edges[edge]
            x, y = xy(board.vertices[a])
            xx, yy = xy(board.vertices[b])
            mx, my = (x+xx)/2, (y+yy)/2
            distance = max(abs(mx-ox), abs(my-oy), 1)
            px, py = mx + (mx-ox)/distance*27, my + (my-oy)/distance*27
            canvas.create_line(mx, my, px, py, fill="#8bb6bc", width=1)
            canvas.create_text(px, py, text=f"{resource.upper()} 2:1" if resource else "3:1",
                               fill=PAPER, font=("Helvetica", 7, "bold"))
        for v, piece in enumerate(game.buildings):
            x, y = xy(board.vertices[v])
            action = ("city" if piece else "settlement", v)
            if piece or action in self.actions:
                tag = f"vertex{v}"
                if piece:
                    owner, level = piece
                    if level == 2:
                        shape = (x-12, y+8, x-12, y-4, x-5, y-4, x-5, y-11,
                                 x+3, y-11, x+11, y-3, x+11, y+8)
                    else:
                        shape = (x-8, y+7, x-8, y, x, y-8, x+8, y, x+8, y+7)
                    canvas.create_polygon(*shape, fill=PLAYER[owner], outline=INK,
                                          width=2, tags=tag)
                else:
                    size = 8 if highlighted == action else 6
                    canvas.create_oval(x-size, y-size, x+size, y+size,
                                       fill=PLAYER[0] if highlighted == action else PAPER,
                                       outline=INK, tags=tag)
                canvas.tag_bind(tag, "<Button-1>", lambda event, a=action: play_at(a))
        stock = "   ·   ".join(f"{resource.title()} {n}" for resource, n in zip(RESOURCES, game.bank))
        canvas.create_text(18, 18, text="Supply   " + stock, anchor="nw", fill=PAPER,
                           font=("Helvetica", 10, "bold"))

    def refresh(self):
        game = self.game
        self.actions = list(game.observe(0).actions)
        self.explicit_selection = False
        self.list.delete(0, "end")
        for action in self.actions:
            self.list.insert("end", action_name(action))
        if self.actions:
            self.list.selection_set(0)
        self.title.configure(text=(f"{NAMES[game.winner]} win" if game.winner == 0 else
                                   f"{NAMES[game.winner]} wins") if game.winner is not None
                             else PHASE[game.phase])
        dice = f" · Dice {game.dice[0]} + {game.dice[1]}" if game.dice else ""
        self.state.configure(text=f"{NAMES[game.actor]} to act{dice}" if game.winner is None else "")
        for i, (name, label) in enumerate(zip(NAMES, self.player_rows)):
            score = game.score(i, i == 0 or i == game.winner)
            resources = sum(game.players[i].hand)
            discoveries = len(game.players[i].cards)
            awards = "".join(("  ·  Route" if game.longest == i else "",
                              "  ·  Army" if game.army == i else ""))
            label.configure(text=f"{name}   {score} VP   {resources} resources   "
                                 f"{discoveries} discoveries{awards}")
        self.hand.configure(text="Your resources\n" + bundle(game.players[0].hand))
        self.cards.configure(text="Your discoveries\n" + (", ".join(
            f"{card} (new)" if turn == game.turn else card
            for card, turn in game.players[0].cards) or "none"))
        self.trade_info.configure(text=(f"Offer from {NAMES[game.offer[3]]}\n"
            f"You receive {bundle(game.offer[1])}\nYou give {bundle(game.offer[2])}")
            if game.phase == "trade_response" and game.actor == 0 else "")
        self.confirm.configure(state="normal" if self.actions else "disabled")
        self.hint.configure(state="normal" if self.actions and not self.hint_futures else "disabled")
        responding = game.phase == "trade_response" and game.actor == 0
        can_trade = game.phase == "action" or responding
        self.trade.configure(state="normal" if can_trade and any(game.players[0].hand)
                             else "disabled", text="Counteroffer" if responding else "Trade")
        self.draw()

    def move(self, action):
        self.session.step(action)
        self.revision += 1
        for future in self.hint_futures:
            future.cancel()
        self.refresh()

    def commit(self):
        selected = self.list.curselection()
        if selected:
            self.move(self.actions[selected[0]])

    def set_difficulty(self, event):
        self.session.difficulty = self.difficulty.get()

    def ai_turn(self):
        self.play_ai_move()
        delay = 475 if self.game.phase == "action" and self.game.actor != 0 else 175
        self.root.after(delay, self.ai_turn)

    def play_ai_move(self):
        game = self.game
        if game.actor != 0 and game.winner is None and self.trade_window is None:
            observation = game.observe(game.actor)
            weights = self.weights if self.session.difficulty == "Hard" else BASE
            choices = ranked(observation, weights)
            pick = 0
            if self.session.difficulty == "Easy":
                pick = min(len(choices)-1, (len(self.session.moves)*7) % 3)
            action = choices[pick][1]
            if action == ("end",):
                action = suggested_offer(observation, weights) or action
            self.move(action)

    def trade_dialog(self):
        dialog = tk.Toplevel(self.root)
        self.trade_window = dialog
        dialog.title("Propose a trade")
        dialog.transient(self.root)
        dialog.grab_set()
        if self.game.phase == "trade_response":
            names = (NAMES[self.game.offer[3]],)
        elif self.game.active != 0:
            names = (NAMES[self.game.active],)
        else:
            names = NAMES[1:]
        recipient = ttk.Combobox(dialog, values=names, state="readonly")
        recipient.current(0)

        def dismiss():
            self.trade_window = None
            dialog.destroy()

        dialog.protocol("WM_DELETE_WINDOW", dismiss)
        recipient.grid(row=0, column=0, columnspan=3, padx=10, pady=8)
        ttk.Label(dialog, text="You give").grid(row=1, column=1)
        ttk.Label(dialog, text="You receive").grid(row=1, column=2)
        values = []
        for row, resource in enumerate(RESOURCES, 2):
            ttk.Label(dialog, text=resource.title()).grid(row=row, column=0, padx=8)
            fields = []
            for col in (1, 2):
                field = ttk.Spinbox(dialog, from_=0, to=19, width=5)
                field.set("0")
                field.grid(row=row, column=col, padx=6, pady=2)
                fields.append(field)
            values.append(fields)

        def draft():
            target = NAMES.index(recipient.get())
            give, get = (tuple(int(row[column].get()) for row in values) for column in (0, 1))
            return ("offer", *self.game.validate_trade_offer(target, give, get, 0))

        def send():
            try:
                self.move(draft())
                dismiss()
            except ValueError as error:
                messagebox.showerror("Trade", str(error), parent=dialog)

        def compare():
            try:
                self.coach(draft())
            except ValueError as error:
                messagebox.showerror("Trade", str(error), parent=dialog)

        ttk.Button(dialog, text="Send offer", command=send).grid(row=7, column=0, columnspan=2, pady=8)
        ttk.Button(dialog, text="Compare offer", command=compare).grid(row=7, column=2, pady=8)

    def coach(self, extra=None):
        if (not self.actions and extra is None) or self.hint_futures:
            return
        observation = self.game.observe(0)
        revision = self.revision
        candidates = [action for _, action in ranked(observation, self.weights)[:3]]
        selected = self.list.curselection()
        if self.explicit_selection and selected and self.actions[selected[0]] not in candidates:
            candidates.append(self.actions[selected[0]])
        if extra is not None:
            if not candidates:
                candidates.append(("wait",))
            candidates.append(extra)
        else:
            offer = suggested_offer(observation, self.weights)
            if offer:
                candidates.append(offer)
        if self.executor is None:
            self.executor = ProcessPoolExecutor(max_workers=worker_count())
        opponents = self.weights if self.session.difficulty == "Hard" else BASE
        jobs = submit(self.executor, observation, candidates, randbits(64), self.weights, opponents)
        self.hint_futures = tuple(future for futures in jobs.values() for future in futures)
        self.hint.configure(state="disabled")
        self.footer.configure(text=f"Coach is simulating {len(candidates)*OUTCOMES:,} continuations…")

        def check():
            completed = sum(future.done() for future in self.hint_futures)
            if completed < len(self.hint_futures):
                progress = completed / len(self.hint_futures)
                self.footer.configure(text=f"Coach simulations · {progress:.0%} complete")
                self.root.after(250, check)
                return
            self.hint_futures = ()
            self.footer.configure(text="")
            if self.actions:
                self.hint.configure(state="normal")
            if revision != self.revision:
                return
            try:
                results = collect(observation, jobs)
            except Exception as error:
                messagebox.showerror("Coach", str(error), parent=self.root)
                return
            window = tk.Toplevel(self.root)
            window.title("Coaching results")
            summary = ttk.Label(window, text=f"Compared {len(results)} moves · {len(observation.actions)} listed board and turn actions",
                                padding=12)
            summary.pack(anchor="w")
            for rank, result in enumerate(results, 1):
                lo, hi = result.interval
                difference = results[0].probability-result.probability
                comparison = f" {difference*100:.1f} percentage-point gap from the top estimate." if rank > 1 else ""
                ttk.Label(window, text=f"{rank}. {action_name(result.action)}   ·   "
                    f"{result.probability:.1%} win estimate   ·   95% interval {lo:.1%}–{hi:.1%}\n"
                    f"{result.wins}/{result.games:,} wins, {result.unresolved} unfinished. "
                    f"{result.explanation}{comparison}", wraplength=650, padding=(12, 5)).pack(anchor="w")

        self.root.after(250, check)

    def new(self):
        if self.session.moves and self.game.winner is None and not messagebox.askyesno(
                "Start a new game", "Replace the current game?"):
            return
        self.session = Session(randbits(64), self.difficulty.get())
        self.revision += 1
        for future in self.hint_futures:
            future.cancel()
        self.refresh()

    def save(self):
        path = filedialog.asksaveasfilename(defaultextension=".hex.json",
                                            filetypes=[("Hex Strategy saves", "*.hex.json")])
        if path:
            try:
                self.session.save(path)
            except OSError as error:
                messagebox.showerror("Save game", str(error))

    def open(self):
        path = filedialog.askopenfilename(filetypes=[("Hex Strategy saves", "*.hex.json")])
        if path:
            try:
                self.session = Session.load(path)
                self.difficulty.set(self.session.difficulty)
                self.revision += 1
                for future in self.hint_futures:
                    future.cancel()
                self.refresh()
            except (ValueError, TypeError, KeyError, OSError) as error:
                messagebox.showerror("Open game", str(error))

    def rules(self):
        messagebox.showinfo("Rules", "Reach 10 points on your turn. Settlements score one "
                            "point and cities score two. The route and army awards score two "
                            "each. Establish two settlements and roads, then roll to produce "
                            "resources. A seven triggers discards and moves the robber. "
                            "Build via the board or action list, or propose a trade. "
                            "See RULES.md for full controls and rules.")

    def close(self):
        if self.executor:
            self.executor.shutdown(wait=False, cancel_futures=True)
        self.root.destroy()


def main():
    root = tk.Tk()
    Desktop(root)
    root.mainloop()


if __name__ == "__main__":
    main()
