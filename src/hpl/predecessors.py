"""Earlier products of the same family cannot share one OS user with this one.

HPL is an evolution of Pegasus, and DARQ is a sibling of it. Each writes the
same names into the same OpenCode and Claude Code configuration (agents,
commands, skills, the default agent, the permissions), so an install over a
live one would overwrite it and a later uninstall of it would remove what HPL
put there. The installer therefore detects them first and either has them
uninstalled, with a yes, or stops before writing anything.

Everything known about them lives in :data:`PRODUCTS` and the named constants
below, checked on real installs. This module is the only place that knows them;
`hpl.cli` and `hpl.tui.session` call it and show its sentences. It sits at the
package root, next to the composition root, because it names other products by
design -- the engine packages (`core`, `ports`, `infra`, `tui` apart from
`session`) must not.
"""
from __future__ import annotations

import json
import os
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Mapping, TextIO

from hpl.infra.fs_posix import PosixFileSystem
from hpl.ports.filesystem import FileSystem


@dataclass(frozen=True)
class Product:
    """One earlier product: how it is called, where its record lives, what
    program uninstalls it."""

    display_name: str
    #: Its data directory name under `$XDG_DATA_HOME` (or `~/.local/share`).
    data_name: str
    #: Its program: looked up on PATH, then under `~/.local/bin`.
    program: str


#: The known products, in the order they are shown and uninstalled.
PRODUCTS = (
    Product("Pegasus", "pegasus-harness", "pegasus"),
    Product("DARQ", "darq", "darq"),
)

#: The install record inside the data directory, and the schema it carries
#: (the same for every product above).
JOURNAL_NAME = "journal-v4.json"
JOURNAL_SCHEMA = "pegasus-harness/journal/v4"
PROGRAM_FALLBACK = (".local", "bin")
#: `<program> uninstall --cli <cli>`: removes one CLI's install and asks nothing.
UNINSTALL_ARGUMENTS = ("uninstall", "--cli")
#: What the CLI flag that answers the question in advance is called.
UNINSTALL_FLAG = "--uninstall-previous"

#: The other way out, as a clause that follows "or".
FALLBACK = (
    "install {product} in another Linux user on this machine instead "
    "(each user has its own copy of them, or none, so they never meet)"
)

#: What is installed: each product with the CLIs it occupies.
Held = tuple[tuple[Product, tuple[str, ...]], ...]


class Blocked(Exception):
    """The way is not clear and the install must not go on; the message says why."""


def data_dir(variables: Mapping[str, str], home: Path, product: Product) -> Path:
    """The product's data directory, resolved by the same rule as this product's own."""
    return PosixFileSystem(dict(variables), product_id=product.data_name).data_dir(home)


def occupied_clis(
    filesystem: FileSystem, home: Path, variables: Mapping[str, str], product: Product
) -> tuple[str, ...]:
    """The CLIs the product holds for this user, in the order its record lists them.

    Empty when there is no record, or it cannot be read, parsed or recognised,
    or no install in it has entries: never block on a file that cannot be read.
    """
    try:
        document = json.loads(filesystem.read_bytes(data_dir(variables, home, product) / JOURNAL_NAME))
    except Exception:  # noqa: BLE001 - any failure to read it means "not installed"
        return ()
    if not isinstance(document, dict) or document.get("schema") != JOURNAL_SCHEMA:
        return ()
    installs = document.get("installs")
    if not isinstance(installs, list):
        return ()
    held = []
    for install in installs:
        if not isinstance(install, dict) or not install.get("entries"):
            continue
        name = install.get("cli")
        if isinstance(name, str) and name and name not in held:
            held.append(name)
    return tuple(held)


def installed(filesystem: FileSystem, home: Path, variables: Mapping[str, str]) -> Held:
    """Every product that counts as installed, with its CLIs; empty when none does."""
    found = []
    for product in PRODUCTS:
        clis = occupied_clis(filesystem, home, variables, product)
        if clis:
            found.append((product, clis))
    return tuple(found)


def find_program(variables: Mapping[str, str], home: Path, product: Product) -> Path | None:
    """The product's program on PATH, else under `~/.local/bin`; `None` when neither is there."""
    for directory in (variables.get("PATH") or "").split(os.pathsep):
        if directory:
            candidate = Path(directory) / product.program
            if candidate.is_file() and os.access(candidate, os.X_OK):
                return candidate
    candidate = home.joinpath(*PROGRAM_FALLBACK) / product.program
    return candidate if candidate.is_file() and os.access(candidate, os.X_OK) else None


def _names(held: Held) -> str:
    names = [product.display_name for product, _ in held]
    return names[0] if len(names) == 1 else f"{', '.join(names[:-1])} and {names[-1]}"


def _occupying(held: Held) -> str:
    return "; ".join(f"{product.display_name} in {', '.join(clis)}" for product, clis in held)


def _are(held: Held) -> str:
    return "is" if len(held) == 1 else "are"


def prompt(held: Held) -> str:
    """The question asked at a terminal, naming what will be uninstalled."""
    return f"Uninstall {_names(held)} now? [y/N] "


def explanation(display_name: str, held: Held) -> tuple[str, ...]:
    """What to tell the person, one line each, with the two ways out."""
    lines = []
    for product, clis in held:
        sentence = f"{product.display_name} is installed for this user in {', '.join(clis)}."
        if product.display_name == "Pegasus":
            sentence = f"{display_name} is an evolution of Pegasus. {sentence}"
        lines.append(sentence)
    names = _names(held)
    lines.append(
        f"{display_name} and {names} use the same OpenCode and Claude Code configuration, so "
        f"{names} must be uninstalled before {display_name} is installed."
    )
    lines.append(f"Either uninstall {names} now, or {FALLBACK.format(product=display_name)}")
    return tuple(lines)


def refusal(display_name: str, held: Held) -> str:
    """The error for a run that cannot ask: names the flag and the other-user way out."""
    return (
        f"{_names(held)} {_are(held)} installed for this user ({_occupying(held)}); {display_name} cannot share their "
        f"OpenCode and Claude Code configuration; rerun with {UNINSTALL_FLAG} to uninstall "
        f"{_names(held)} first, or {FALLBACK.format(product=display_name)}"
    )


Runner = Callable[..., "subprocess.CompletedProcess[str]"]


def uninstall(
    filesystem: FileSystem,
    home: Path,
    variables: Mapping[str, str],
    out: TextIO,
    *,
    display_name: str,
    run: Runner = subprocess.run,
) -> None:
    """Run each installed product's `<program> uninstall --cli <cli>` for every
    CLI it occupies, showing its output, then check every product again.
    Returns only when none counts as installed; otherwise raises
    :class:`Blocked` with what is left. A program that is missing stops it
    before any uninstall runs."""
    held = installed(filesystem, home, variables)
    if not held:
        return
    programs = {}
    for product, _ in held:
        program = find_program(variables, home, product)
        if program is None:
            raise Blocked(
                f"the {product.program} program was not found on PATH or in "
                f"{home.joinpath(*PROGRAM_FALLBACK)}, so {product.display_name} cannot be "
                f"uninstalled from here; nothing was uninstalled; "
                f"{FALLBACK.format(product=display_name)}"
            )
        programs[product] = program
    for product, clis in held:
        for name in clis:
            out.write(f"Running: {product.program} {' '.join(UNINSTALL_ARGUMENTS)} {name}\n")
            try:
                done = run(
                    [str(programs[product]), *UNINSTALL_ARGUMENTS, name],
                    capture_output=True,
                    text=True,
                    env=dict(variables),
                    stdin=subprocess.DEVNULL,
                )
            except OSError as error:
                raise Blocked(f"could not run {programs[product]}: {error}") from error
            out.write(done.stdout or "")
            out.write(done.stderr or "")
            if done.returncode != 0:
                out.write(f"{product.program} exited with status {done.returncode}\n")
    remaining = installed(filesystem, home, variables)
    if remaining:
        raise Blocked(
            f"{_names(remaining)} still {_are(remaining)} installed for this user ({_occupying(remaining)}) "
            f"after the uninstall ran; "
            f"{display_name} was not installed; you can still "
            f"{FALLBACK.format(product=display_name)}"
        )
