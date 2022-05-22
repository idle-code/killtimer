#!/usr/bin/env python
import argparse
import datetime
import subprocess
import sys
import time
from dataclasses import dataclass
from typing import Optional, List, Callable

from rich.progress import Progress, SpinnerColumn, TextColumn, BarColumn, TaskProgressColumn

MINIMAL_WORK_DURATION = datetime.timedelta(seconds=5)
WORK_DURATION = datetime.timedelta(seconds=5) - MINIMAL_WORK_DURATION
OVERTIME_DURATION = datetime.timedelta(seconds=3)


def format_time(t: datetime.datetime) -> str:
    return t.strftime("%H:%M")


@dataclass
class RuntimeConfiguration:
    minimal_effort_duration: datetime.timedelta = MINIMAL_WORK_DURATION
    work_duration: datetime.timedelta = WORK_DURATION - MINIMAL_WORK_DURATION
    overtime_duration: datetime.timedelta = OVERTIME_DURATION
    command_to_run: Optional[List[str]] = None


def parse_configuration(args: [str]) -> RuntimeConfiguration:
    parser = argparse.ArgumentParser(
        prog="killtimer",
        description="Close application when time runs out"
    )
    parser.add_argument(
        "program_to_run",
        nargs="*",
        help="Executable (with arguments) to run"
    )

    config = parser.parse_args(args)

    return RuntimeConfiguration(
        command_to_run=config.program_to_run
    )


def main(args: [str]):
    config = parse_configuration(args)

    # Show deadlines
    start_time = datetime.datetime.now()
    print(f"Task start:                 {format_time(start_time)}")
    print(f"Minimal effort finishes on: {format_time(start_time + MINIMAL_WORK_DURATION)}")
    print(f"Work will be done on:       {format_time(start_time + WORK_DURATION)}")

    # TODO: Start program under time limit
    user_command: Optional[subprocess.Popen] = None
    if config.command_to_run:
        print(f"Running {config.command_to_run}")
        # TODO: Redirect stdout/err to null
        # TODO: Check if "exec" is still necessary
        user_command = subprocess.Popen(" ".join(["exec"] + config.command_to_run), shell=True)
        print(f"New process PID: {user_command.pid}")

    def should_countdown_continue() -> bool:
        return user_command is None or user_command.poll() is None

    # Report progress
    progress_display_columns = (
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        BarColumn(bar_width=None),
        TaskProgressColumn(),
        TextColumn("{task.fields[left]}")
    )
    with Progress(*progress_display_columns, expand=True) as progress:
        show_time_progress(should_countdown_continue, progress, "[green]Minimal effort", start_time, start_time + MINIMAL_WORK_DURATION)
        if not should_countdown_continue():
            return
        show_time_progress(should_countdown_continue, progress, "[bold white]Work", start_time, start_time + WORK_DURATION)
        if not should_countdown_continue():
            return
        # TODO: Show warning toast message
        start_time = datetime.datetime.now()
        show_time_progress(should_countdown_continue, progress, "[red]Overtime", start_time, start_time + OVERTIME_DURATION)

    # Kill program under test if it is still running
    if user_command and user_command.poll() is None:
        print("Killing user command")
        user_command.terminate()
        # CHECK: wait a bit and kill it if still running?
    # TODO: Show total time spent


def show_time_progress(should_countdown_continue: Callable[[], bool], progress: Progress, label: str, start_time: datetime.datetime, end_time: datetime.datetime):
    task_duration = (end_time - start_time)
    task_progress = progress.add_task(label, total=task_duration.total_seconds(), left="--:--")
    elapsed = datetime.datetime.now() - start_time
    while elapsed < task_duration:
        time_left = task_duration - elapsed
        minutes_left, seconds_left = divmod(time_left.total_seconds(), 60)
        progress.update(task_progress, completed=elapsed.total_seconds(), left=f"{int(minutes_left)}:{int(seconds_left):02}")
        time.sleep(1)
        elapsed = datetime.datetime.now() - start_time
        if not should_countdown_continue():
            return
    progress.update(task_progress, completed=task_duration.total_seconds(), left="DONE")


if __name__ == '__main__':
    main(sys.argv[1:])
