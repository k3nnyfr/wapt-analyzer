"""Terminal progress bars (rich), disabled automatically when stderr is not a terminal."""

from __future__ import annotations

from rich.console import Console
from rich.progress import (
    BarColumn,
    DownloadColumn,
    Progress,
    SpinnerColumn,
    TaskProgressColumn,
    TextColumn,
    TimeElapsedColumn,
    TimeRemainingColumn,
    TransferSpeedColumn,
)

console = Console(stderr=True)


def phase_progress(transfer: bool = True) -> Progress:
    """One progress display per phase: download / sign / upload.

    ``transfer`` adds byte counters, speed and ETA (download, upload); signing shows elapsed time.
    """
    columns = [
        SpinnerColumn(),
        TextColumn("[bold]{task.fields[phase]:<11}"),
        BarColumn(bar_width=30),
        TaskProgressColumn(),
    ]
    if transfer:
        columns += [DownloadColumn(binary_units=True), TransferSpeedColumn(), TimeRemainingColumn()]
    else:
        columns += [TextColumn("{task.completed:.0f}/{task.total:.0f}"), TimeElapsedColumn()]
    columns.append(TextColumn("[dim]{task.fields[current]}", justify="left"))
    return Progress(*columns, console=console, transient=False, disable=not console.is_terminal)
