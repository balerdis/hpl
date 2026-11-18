"""When Pegasus or DARQ is installed for this OS user, HPL must not be installed.

They write the same names into the same CLI configuration, so the installer
detects the earlier products first, says so, and either uninstalls them (with a
yes) or stops without writing anything. The detection is a module of its own
(`hpl.predecessors`); these tests drive it directly, through `hpl install`,
and through the TUI's install flow, always against a throwaway home and fake
`pegasus` and `darq` programs that record what they were asked.
"""
from __future__ import annotations

import io
import json
import os
import stat
import sys
import unittest
from pathlib import Path
from unittest import mock

from hpl import cli, predecessors as conflict
from hpl.tui import session
from hpl.tui.navigator import Action, InstallPlanScreen, Menu, Navigator, Placeholder
import test_cli
from test_cli import AT, CLI

FAKE_PROGRAM = """#!{python}
import json, os, sys
name = os.path.basename(sys.argv[0])
with open(os.environ["FAKE_LOG"], "a") as log:
    log.write(name + " " + " ".join(sys.argv[1:]) + "\\n")
sys.stdout.write("fake " + " ".join(sys.argv[1:]) + "\\n")
path = os.environ["FAKE_JOURNAL_" + name.upper()]
document = json.load(open(path))
if not os.environ.get("FAKE_LEAVE"):
    for install in document["installs"]:
        if install["cli"] == sys.argv[sys.argv.index("--cli") + 1]:
            install["entries"] = []
json.dump(document, open(path, "w"))
"""


def journal_document(*clis: str, entries: bool = True) -> dict:
    return {
        "schema": conflict.JOURNAL_SCHEMA,
        "pegasus_version": "9.3.2",
        "installs": [
            {
                "cli": name,
                "config_dir": f"/somewhere/{name}",
                "release": {},
                "entries": [{"id": "x"}] if entries else [],
                "links": [],
            }
            for name in clis
        ],
    }


PEGASUS, DARQ = conflict.PRODUCTS


class PegasusHome(test_cli.RealHomeTestCase):
    """A throwaway home that can hold either product's journal and fake program."""

    def setUp(self):
        super().setUp()
        self.bin = self.home / "fakebin"
        self.bin.mkdir()
        self.log = self.home / "fake.log"
        self.variables = {"PATH": str(self.bin)}

    @property
    def journal(self) -> Path:
        return self.journal_of(PEGASUS)

    def journal_of(self, product) -> Path:
        return conflict.data_dir(self.variables, self.home, product) / conflict.JOURNAL_NAME

    def plant(self, document, product=PEGASUS) -> None:
        path = self.journal_of(product)
        path.parent.mkdir(parents=True, exist_ok=True)
        text = document if isinstance(document, str) else json.dumps(document)
        path.write_text(text)

    def plant_program(self, product=PEGASUS, *, leave: bool = False, where: Path | None = None) -> None:
        directory = where or self.bin
        directory.mkdir(parents=True, exist_ok=True)
        program = directory / product.program
        program.write_text(FAKE_PROGRAM.format(python=sys.executable))
        program.chmod(program.stat().st_mode | stat.S_IXUSR)
        self.variables.update(
            {"FAKE_LOG": str(self.log), f"FAKE_JOURNAL_{product.program.upper()}": str(self.journal_of(product))}
        )
        if leave:
            self.variables["FAKE_LEAVE"] = "1"

    def calls(self) -> list[str]:
        return self.log.read_text().splitlines() if self.log.exists() else []

    def occupied(self, product=PEGASUS) -> tuple[str, ...]:
        return conflict.occupied_clis(self.filesystem, self.home, self.variables, product)

    def runtime(self, *, identity=None) -> cli.Runtime:
        return cli.Runtime(
            filesystem=self.filesystem, home=self.home, now=AT, out=io.StringIO(), variables=self.variables
        )


class DetectionTest(PegasusHome):
    def test_no_journal_is_not_installed(self):
        self.assertEqual(self.occupied(), ())

    def test_a_malformed_journal_is_not_installed(self):
        for text in ("{not json", "[]", '"x"', "null", '{"schema": "pegasus-harness/journal/v4", "installs": 3}'):
            with self.subTest(text=text):
                self.plant(text)
                self.assertEqual(self.occupied(), ())

    def test_another_schema_is_not_installed(self):
        self.plant({**journal_document("opencode"), "schema": "something/else"})
        self.assertEqual(self.occupied(), ())

    def test_installs_with_empty_entries_are_not_installed(self):
        self.plant(journal_document("opencode", "claudecode", entries=False))
        self.assertEqual(self.occupied(), ())

    def test_an_unreadable_journal_is_not_installed(self):
        self.plant(journal_document("opencode"))
        self.journal.chmod(0)
        self.addCleanup(self.journal.chmod, 0o600)
        self.assertEqual(self.occupied(), ())

    def test_entries_for_one_cli(self):
        self.plant(journal_document("opencode"))
        self.assertEqual(self.occupied(), ("opencode",))

    def test_entries_for_two_clis(self):
        self.plant(journal_document("opencode", "claudecode"))
        self.assertEqual(self.occupied(), ("opencode", "claudecode"))

    def test_only_the_installs_with_entries_count(self):
        document = journal_document("opencode", "claudecode")
        document["installs"][0]["entries"] = []
        self.plant(document)
        self.assertEqual(self.occupied(), ("claudecode",))

    def test_xdg_data_home_is_honoured(self):
        xdg = self.home / "elsewhere"
        self.variables["XDG_DATA_HOME"] = str(xdg)
        self.assertEqual(conflict.data_dir(self.variables, self.home, PEGASUS), xdg / PEGASUS.data_name)
        self.plant(journal_document("opencode"))
        self.assertTrue((xdg / PEGASUS.data_name / conflict.JOURNAL_NAME).is_file())
        self.assertEqual(self.occupied(), ("opencode",))

    def test_a_blank_xdg_data_home_falls_back_to_the_home(self):
        self.variables["XDG_DATA_HOME"] = "  "
        self.assertEqual(
            conflict.data_dir(self.variables, self.home, PEGASUS),
            self.home / ".local" / "share" / PEGASUS.data_name,
        )


class DarqDetectionTest(PegasusHome):
    def test_the_products_are_pegasus_then_darq(self):
        self.assertEqual([p.display_name for p in conflict.PRODUCTS], ["Pegasus", "DARQ"])
        self.assertEqual(DARQ.data_name, "darq")
        self.assertEqual(DARQ.program, "darq")

    def test_darq_entries_are_read_from_its_own_directory(self):
        self.plant(journal_document("claudecode"), DARQ)
        self.assertEqual(self.occupied(DARQ), ("claudecode",))
        self.assertEqual(self.occupied(PEGASUS), ())
        self.assertEqual(
            self.journal_of(DARQ), self.home / ".local" / "share" / "darq" / conflict.JOURNAL_NAME
        )

    def test_xdg_data_home_is_honoured_for_darq(self):
        xdg = self.home / "elsewhere"
        self.variables["XDG_DATA_HOME"] = str(xdg)
        self.plant(journal_document("opencode"), DARQ)
        self.assertTrue((xdg / "darq" / conflict.JOURNAL_NAME).is_file())
        self.assertEqual(self.occupied(DARQ), ("opencode",))
        self.assertEqual([p for p, _ in conflict.installed(self.filesystem, self.home, self.variables)], [DARQ])

    def test_a_blank_xdg_data_home_falls_back_for_darq(self):
        self.variables["XDG_DATA_HOME"] = " "
        self.assertEqual(conflict.data_dir(self.variables, self.home, DARQ), self.home / ".local" / "share" / "darq")

    def test_the_program_is_looked_up_by_its_own_name(self):
        self.plant_program(DARQ)
        self.assertEqual(conflict.find_program(self.variables, self.home, DARQ), self.bin / "darq")
        self.assertIsNone(conflict.find_program(self.variables, self.home, PEGASUS))


class ProgramLookupTest(PegasusHome):
    def test_found_on_path(self):
        self.plant_program()
        self.assertEqual(conflict.find_program(self.variables, self.home, PEGASUS), self.bin / "pegasus")

    def test_found_in_the_local_bin_when_not_on_path(self):
        self.plant_program(where=self.home / ".local" / "bin")
        self.assertEqual(conflict.find_program(self.variables, self.home, PEGASUS), self.home / ".local" / "bin" / "pegasus")

    def test_not_found(self):
        self.assertIsNone(conflict.find_program(self.variables, self.home, PEGASUS))


class InstallCommandTest(PegasusHome):
    def run_install(self, *extra, terminal: bool = False, answer: str | None = None):
        context = self.runtime()
        with mock.patch.object(cli, "_stdin_is_a_terminal", return_value=terminal), mock.patch(
            "builtins.input", return_value=answer or ""
        ) as asked:
            code = cli.main(["install", "--cli", CLI, *extra], runtime=context)
        return code, context.out.getvalue(), asked

    def setUp(self):
        super().setUp()
        self.present()

    def test_without_pegasus_nothing_changes(self):
        code, out, asked = self.run_install()
        self.assertEqual(code, 0, out)
        asked.assert_not_called()

    def test_no_terminal_and_no_flag_stops_and_writes_nothing(self):
        self.plant(journal_document("opencode", "claudecode"))
        self.plant_program()
        before = self.snapshot()
        code, out, asked = self.run_install()
        self.assertEqual(code, 1)
        self.assertEqual(self.snapshot(), before)
        self.assertEqual(self.calls(), [])
        asked.assert_not_called()
        self.assertIn("--uninstall-previous", out)
        self.assertIn("another Linux user", out)
        self.assertIn("opencode, claudecode", out)
        self.assertEqual(self.occupied(), ("opencode", "claudecode"))

    def test_the_flag_uninstalls_each_cli_then_installs(self):
        self.plant(journal_document("opencode", "claudecode"))
        self.plant_program()
        code, out, asked = self.run_install("--uninstall-previous")
        self.assertEqual(code, 0, out)
        asked.assert_not_called()
        self.assertEqual(self.calls(), ["pegasus uninstall --cli opencode", "pegasus uninstall --cli claudecode"])
        self.assertIn("fake uninstall --cli opencode", out)
        self.assertEqual(self.occupied(), ())
        self.assertEqual(len(self.installed_entries()) > 0, True)

    def test_an_uninstall_that_leaves_entries_stops_nonzero_and_installs_nothing(self):
        self.plant(journal_document("opencode"))
        self.plant_program(leave=True)
        code, out, _ = self.run_install("--uninstall-previous")
        self.assertEqual(code, 1)
        self.assertEqual(self.calls(), ["pegasus uninstall --cli opencode"])
        self.assertIn("opencode", out)
        self.assert_disk_untouched()

    def test_a_missing_program_stops_nonzero_and_recommends_the_other_user(self):
        self.plant(journal_document("opencode"))
        before = self.snapshot()
        code, out, _ = self.run_install("--uninstall-previous")
        self.assertEqual(code, 1)
        self.assertEqual(self.snapshot(), before)
        self.assertIn("another Linux user", out)
        self.assertIn("pegasus", out)

    def test_at_a_terminal_a_yes_uninstalls_and_installs(self):
        self.plant(journal_document("opencode"))
        self.plant_program()
        code, out, asked = self.run_install(terminal=True, answer="y")
        self.assertEqual(code, 0, out)
        asked.assert_called_once_with("Uninstall Pegasus now? [y/N] ")
        self.assertEqual(self.calls(), ["pegasus uninstall --cli opencode"])

    def test_at_a_terminal_anything_but_an_explicit_yes_stops(self):
        self.plant(journal_document("opencode"))
        self.plant_program()
        before = self.snapshot()
        for answer in ("", "n", "no", "yes please maybe", "  "):
            with self.subTest(answer=answer):
                code, out, _ = self.run_install(terminal=True, answer=answer)
                self.assertEqual(code, 1)
                self.assertEqual(self.snapshot(), before)
                self.assertEqual(self.calls(), [])
                self.assertIn("--uninstall-previous", out)

    def test_json_never_prompts_even_at_a_terminal_and_stops_writing_nothing(self):
        self.plant(journal_document("opencode"))
        self.plant_program()
        before = self.snapshot()
        context = self.runtime()
        with mock.patch.object(cli, "_stdin_is_a_terminal", return_value=True), mock.patch(
            "builtins.input", return_value="y"
        ) as asked:
            code = cli.main(["--json", "install", "--cli", CLI], runtime=context)
        out = context.out.getvalue()
        self.assertNotEqual(code, 0)
        asked.assert_not_called()
        self.assertEqual(self.snapshot(), before)
        self.assertEqual(self.calls(), [])
        report = json.loads(out)
        self.assertIn("--uninstall-previous", json.dumps(report))
        self.assertEqual(self.occupied(), ("opencode",))

    def test_end_of_input_at_the_prompt_is_a_no(self):
        self.plant(journal_document("opencode"))
        self.plant_program()
        context = self.runtime()
        with mock.patch.object(cli, "_stdin_is_a_terminal", return_value=True), mock.patch(
            "builtins.input", side_effect=EOFError
        ):
            code = cli.main(["install", "--cli", CLI], runtime=context)
        self.assertEqual(code, 1)
        self.assertEqual(self.calls(), [])

    def test_darq_alone_is_named_and_uninstalled_then_install_continues(self):
        self.plant(journal_document("claudecode"), DARQ)
        self.plant_program(DARQ)
        before = self.snapshot()
        code, out, asked = self.run_install()
        self.assertEqual(code, 1)
        self.assertEqual(self.snapshot(), before)
        self.assertIn("DARQ", out)
        self.assertNotIn("Pegasus", out)
        self.assertIn("claudecode", out)
        self.assertIn("--uninstall-previous", out)
        code, out, _ = self.run_install("--uninstall-previous")
        self.assertEqual(code, 0, out)
        self.assertEqual(self.calls(), ["darq uninstall --cli claudecode"])
        self.assertEqual(self.occupied(DARQ), ())
        self.assertTrue(self.installed_entries())

    def test_the_prompt_names_every_installed_product(self):
        self.plant(journal_document("opencode"), PEGASUS)
        self.plant(journal_document("opencode"), DARQ)
        self.plant_program(PEGASUS)
        self.plant_program(DARQ)
        code, out, asked = self.run_install(terminal=True, answer="y")
        self.assertEqual(code, 0, out)
        asked.assert_called_once_with("Uninstall Pegasus and DARQ now? [y/N] ")

    def test_both_installed_are_named_uninstalled_in_order_and_install_follows(self):
        self.plant(journal_document("opencode", "claudecode"), PEGASUS)
        self.plant(journal_document("claudecode"), DARQ)
        self.plant_program(PEGASUS)
        self.plant_program(DARQ)
        before = self.snapshot()
        code, out, _ = self.run_install()
        self.assertEqual(code, 1)
        self.assertEqual(self.snapshot(), before)
        self.assertEqual(self.calls(), [])
        self.assertIn("Pegasus", out)
        self.assertIn("DARQ", out)
        self.assertIn("opencode, claudecode", out)
        self.assertIn("another Linux user", out)
        code, out, _ = self.run_install("--uninstall-previous")
        self.assertEqual(code, 0, out)
        self.assertEqual(
            self.calls(),
            [
                "pegasus uninstall --cli opencode",
                "pegasus uninstall --cli claudecode",
                "darq uninstall --cli claudecode",
            ],
        )
        self.assertEqual(self.occupied(PEGASUS), ())
        self.assertEqual(self.occupied(DARQ), ())
        self.assertTrue(self.installed_entries())

    def test_one_product_that_stays_installed_stops_the_install(self):
        self.plant(journal_document("opencode"), PEGASUS)
        self.plant(journal_document("opencode"), DARQ)
        self.plant_program(PEGASUS)
        self.plant_program(DARQ, leave=True)
        code, out, _ = self.run_install("--uninstall-previous")
        self.assertEqual(code, 1)
        self.assertIn("DARQ", out)
        self.assert_disk_untouched()

    def test_a_missing_darq_program_stops_before_any_uninstall_runs(self):
        self.plant(journal_document("opencode"), PEGASUS)
        self.plant(journal_document("opencode"), DARQ)
        self.plant_program(PEGASUS)
        before = self.snapshot()
        code, out, _ = self.run_install("--uninstall-previous")
        self.assertEqual(code, 1)
        self.assertEqual(self.calls(), [])
        self.assertEqual(self.snapshot(), before)
        self.assertIn("darq", out)
        self.assertNotIn("the pegasus program", out)
        self.assertIn("another Linux user", out)
        self.assertEqual(self.occupied(PEGASUS), ("opencode",))

    def test_a_dry_run_writes_nothing_and_is_not_blocked(self):
        self.plant(journal_document("opencode"))
        before = self.snapshot()
        code, out, _ = self.run_install("--dry-run")
        self.assertEqual(code, 0, out)
        self.assertEqual(self.snapshot(), before)


class TuiGateTest(PegasusHome):
    def setUp(self):
        super().setUp()
        self.present()

    def plan_navigator(self, runtime) -> Navigator:
        option = next(o for o in session.detect_clis(runtime) if o.id == CLI)
        navigator = Navigator.starting(session.detect_clis(runtime), (), display_name="X")
        _, report = cli.safe_report("install", lambda: cli.install(CLI, runtime, dry_run=True, mcp=[]))
        return navigator.opened(InstallPlanScreen(cli=option, report=report))

    def test_no_screen_without_pegasus(self):
        runtime = self.runtime()
        self.assertIsNone(session.install_gate(self.plan_navigator(runtime), runtime))

    def test_the_gate_screen_names_the_clis_and_offers_two_choices(self):
        self.plant(journal_document("opencode", "claudecode"))
        runtime = self.runtime()
        gated = session.install_gate(self.plan_navigator(runtime), runtime)
        screen = gated.current
        self.assertIsInstance(screen, Menu)
        text = " ".join(screen.preface)
        self.assertIn("opencode, claudecode", text)
        self.assertIn("another Linux user", text)
        self.assertEqual(len(screen.entries), 2)
        self.assertEqual(screen.entries[0].label, "Uninstall now")
        self.assertEqual(screen.entries[1].label, "Exit")

    def test_step_on_the_plan_opens_the_gate_and_writes_nothing(self):
        self.plant(journal_document("opencode"))
        runtime = self.runtime()
        before = self.snapshot()
        stepped = session.step(self.plan_navigator(runtime), runtime, Action.CHOOSE)
        self.assertIsInstance(stepped.current, Menu)
        self.assertEqual(self.snapshot(), before)

    def test_the_gate_screen_lists_every_installed_product(self):
        self.plant(journal_document("opencode"), PEGASUS)
        self.plant(journal_document("claudecode"), DARQ)
        runtime = self.runtime()
        screen = session.install_gate(self.plan_navigator(runtime), runtime).current
        text = " ".join(screen.preface)
        self.assertIn("Pegasus", text)
        self.assertIn("DARQ", text)
        self.assertIn("opencode", text)
        self.assertIn("claudecode", text)
        self.assertEqual(screen.entries[0].label, "Uninstall now")
        self.assertEqual(screen.entries[1].label, "Exit")

    def test_uninstall_now_runs_both_programs_and_returns_to_the_plan(self):
        self.plant(journal_document("opencode"), PEGASUS)
        self.plant(journal_document("opencode"), DARQ)
        self.plant_program(PEGASUS)
        self.plant_program(DARQ)
        runtime = self.runtime()
        gated = session.install_gate(self.plan_navigator(runtime), runtime)
        after = session.step(gated, runtime, Action.CHOOSE)
        self.assertEqual(self.calls(), ["pegasus uninstall --cli opencode", "darq uninstall --cli opencode"])
        self.assertIsInstance(after.current, InstallPlanScreen)

    def test_the_main_loop_shows_the_gate_instead_of_installing(self):
        import curses

        from hpl.tui import app as app_module
        from test_tui_app import _FakeInstallWindow

        self.plant(journal_document("opencode"))
        runtime = self.runtime()
        window = _FakeInstallWindow(getch_script=[curses.KEY_ENTER, curses.KEY_DOWN, curses.KEY_ENTER])
        before = self.snapshot()
        with mock.patch.object(app_module.session, "plan_task") as planned, mock.patch.object(
            app_module.curses, "flushinp"
        ):
            final = app_module._main_loop(
                window,
                self.plan_navigator(runtime),
                runtime=runtime,
                accent_attr=curses.A_BOLD,
                notice=app_module.UpdateNotice(running="1.0.0"),
                holder=app_module._UpdateCheckHolder(),
            )
        planned.assert_not_called()
        self.assertTrue(final.quit)
        self.assertEqual(self.snapshot(), before)

    def test_exit_quits_without_writing(self):
        self.plant(journal_document("opencode"))
        runtime = self.runtime()
        before = self.snapshot()
        gated = session.install_gate(self.plan_navigator(runtime), runtime)
        gated = gated.handle(Action.MOVE_DOWN)
        quit_ = session.step(gated, runtime, Action.CHOOSE)
        self.assertTrue(quit_.quit)
        self.assertEqual(self.snapshot(), before)
        self.assertEqual(self.calls(), [])

    def test_uninstall_runs_the_program_and_returns_to_the_plan(self):
        self.plant(journal_document("opencode", "claudecode"))
        self.plant_program()
        runtime = self.runtime()
        gated = session.install_gate(self.plan_navigator(runtime), runtime)
        after = session.step(gated, runtime, Action.CHOOSE)
        self.assertEqual(self.calls(), ["pegasus uninstall --cli opencode", "pegasus uninstall --cli claudecode"])
        self.assertIsInstance(after.current, InstallPlanScreen)
        self.assertIsNone(session.install_gate(after, runtime))

    def test_a_failed_uninstall_shows_why_and_stays_blocked(self):
        self.plant(journal_document("opencode"))
        self.plant_program(leave=True)
        runtime = self.runtime()
        gated = session.install_gate(self.plan_navigator(runtime), runtime)
        after = session.step(gated, runtime, Action.CHOOSE)
        self.assertIsInstance(after.current, Placeholder)
        self.assertIn("opencode", after.current.note)

    def test_a_missing_program_shows_the_fallback(self):
        self.plant(journal_document("opencode"))
        runtime = self.runtime()
        gated = session.install_gate(self.plan_navigator(runtime), runtime)
        after = session.step(gated, runtime, Action.CHOOSE)
        self.assertIsInstance(after.current, Placeholder)
        self.assertIn("another Linux user", after.current.note)


if __name__ == "__main__":
    unittest.main()
