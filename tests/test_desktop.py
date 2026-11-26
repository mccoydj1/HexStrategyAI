"""Run with a display or under Xvfb."""
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch


@unittest.skipUnless(os.getenv("DISPLAY") or os.name in ("nt",), "A graphical display is required.")
class DesktopMatch(unittest.TestCase):
    def test_full_graphical_match_save_and_resume(self):
        import tkinter as tk
        from hexstrategy.__main__ import Desktop
        from hexstrategy.ai import choose

        root = tk.Tk()
        desktop = None
        try:
            with patch("hexstrategy.__main__.randbits", return_value=421):
                desktop = Desktop(root)
            root.update()
            self.assertTrue(desktop.use_search)
            saved = False
            for _ in range(2500):
                game = desktop.game
                if game.winner is not None:
                    break
                if game.actor == 0:
                    action = choose(game.observe(0))
                    if action in desktop.actions:
                        desktop.list.selection_clear(0, "end")
                        desktop.list.selection_set(desktop.actions.index(action))
                        desktop.commit()
                    else:
                        desktop.move(action)
                else:
                    desktop.play_ai_move()
                if not saved and game.turn == 12:
                    with tempfile.TemporaryDirectory() as directory:
                        filename = str(Path(directory) / "session.hex.json")
                        with patch("hexstrategy.__main__.filedialog.asksaveasfilename", return_value=filename):
                            desktop.save()
                        with patch("hexstrategy.__main__.filedialog.askopenfilename", return_value=filename):
                            desktop.open()
                    self.assertEqual(desktop.game.observe(0), game.observe(0))
                    saved = True
            self.assertTrue(saved)
            self.assertIn(desktop.game.winner, range(4))
            self.assertIn("win", desktop.title.cget("text"))
        finally:
            desktop.close() if desktop is not None else root.destroy()

    def test_coach_reuses_completed_evidence_until_context_changes(self):
        from concurrent.futures import Future
        import tkinter as tk

        from hexstrategy.__main__ import Desktop

        root = tk.Tk()
        desktop = None
        try:
            with patch("hexstrategy.__main__.randbits", return_value=421):
                desktop = Desktop(root)
            while desktop.game.actor != 0:
                desktop.play_ai_move()
            completed = Future()
            completed.set_result((1000, 400, 0))
            with (patch.object(desktop, "executor", object()),
                  patch("hexstrategy.__main__.submit", side_effect=lambda _, obs, actions, *args:
                        {action: [completed] for action in actions}) as submit,
                  patch.object(root, "after", side_effect=lambda _, callback: callback()),
                  patch.object(desktop, "show_coaching") as display):
                desktop.coach()
                desktop.coach()
                self.assertEqual(submit.call_count, 1)
                self.assertEqual(display.call_count, 2)
                self.assertEqual(display.call_args.args[1][0].games, 1000)
                desktop.difficulty.set("Standard")
                desktop.set_difficulty(None)
                desktop.coach()
                self.assertEqual(submit.call_count, 2)
                desktop.move(desktop.actions[0])
                desktop.coach()
                self.assertEqual(submit.call_count, 3)
        finally:
            desktop.close() if desktop is not None else root.destroy()
