#!/usr/bin/env python
import argparse
import csv
import datetime
import math
import subprocess
import sys
import os
import signal
import time

import humanfriendly
import pytimeparse
from dataclasses import dataclass
from typing import Optional, List, Callable
from desktop_notifier import DesktopNotifierSync, Icon, Sound, Urgency
from rich.progress import Progress, SpinnerColumn, TextColumn, BarColumn, TaskProgressColumn
from rich.console import Console
from rich import print as rprint


def format_time(t: datetime.datetime) -> str:
    return t.strftime("%H:%M")


def format_duration(duration: datetime.timedelta, round_up: bool = False) -> str:
    total_seconds = duration.total_seconds()
    total_seconds = math.ceil(total_seconds) if round_up else math.floor(total_seconds)
    return humanfriendly.format_timespan(humanfriendly.coerce_seconds(total_seconds))


def parse_timedelta(time_delta_representation: str) -> datetime.timedelta:
    return datetime.timedelta(seconds=pytimeparse.parse(time_delta_representation))


def existing_file_path(path: str) -> str:
    # The notification server runs in a different working directory, so it needs an absolute path
    absolute_path = os.path.abspath(os.path.expanduser(path))
    if not os.path.isfile(absolute_path):
        raise argparse.ArgumentTypeError(f"file not found: {path}")
    return absolute_path


@dataclass
class RuntimeConfiguration:
    start_time: datetime.datetime
    minimal_effort_duration: Optional[datetime.timedelta] = None
    work_duration: datetime.timedelta = datetime.timedelta(hours=1)
    overtime_duration: Optional[datetime.timedelta] = None
    title: Optional[str] = None
    command_to_run: Optional[List[str]] = None
    log_file_path: Optional[str] = None
    notification_sound_path: Optional[str] = None


def parse_configuration(args: [str]) -> RuntimeConfiguration:
    parser = argparse.ArgumentParser(
        prog="killtimer",
        usage="%(prog)s [options] [--] [command [arguments ...]]",
        description="Close application when time runs out",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter
    )
    parser.add_argument(
        "-m", "--minimal-effort",
        type=parse_timedelta,
        metavar="duration",
        help="Minimal work duration"
    )
    parser.add_argument(
        "-w", "--work",
        type=parse_timedelta,
        default=RuntimeConfiguration.work_duration,
        metavar="duration",
        help="Proper work duration"
    )
    parser.add_argument(
        "-o", "--overtime",
        type=parse_timedelta,
        metavar="duration",
        help="Overtime duration"
    )
    parser.add_argument(
        "-l", "--log",
        type=str,
        default=None,
        metavar="log_file",
        help="Log file where to store amount of work done"
    )
    parser.add_argument(
        "-t", "--title",
        type=str,
        default=None,
        metavar="title",
        help="Title to display above progress bars and configuration"
    )
    parser.add_argument(
        "-s", "--sound",
        type=existing_file_path,
        default=None,
        metavar="sound_file",
        help="Sound file to play with the notification when minimal effort or work period is reached "
             "(instead of the default notification sound)"
    )
    parser.add_argument(
        "command_to_run",
        # Everything after the executable name belongs to the command, even arguments looking like options
        nargs=argparse.REMAINDER,
        metavar="command",
        help="Executable (with arguments) to run"
    )

    config = parser.parse_args(args)
    if config.command_to_run[:1] == ["--"]:
        config.command_to_run = config.command_to_run[1:]
    if config.minimal_effort is None:
        config.minimal_effort = 0.50 * config.work
        
    if config.overtime is None:
        config.overtime = 0.25 * config.work

    if config.minimal_effort > config.work:
        print("Minimal effort cannot take longer than actual work!")
        sys.exit(1)

    if config.title:
        notify.app_name = config.title

    return RuntimeConfiguration(
        start_time=datetime.datetime.now(),
        title=config.title,
        command_to_run=config.command_to_run,
        minimal_effort_duration=config.minimal_effort,
        work_duration=config.work,
        overtime_duration=config.overtime,
        log_file_path=config.log,
        notification_sound_path=config.sound
    )


notify = DesktopNotifierSync(app_name="Killtimer")
# Same sound that desktop-notifier < 4 used for sound=True
DEFAULT_NOTIFICATION_SOUND = Sound(name="message-new-instant")

console = Console()

runtime_config: RuntimeConfiguration

def notification_sound() -> Sound:
    if runtime_config.notification_sound_path:
        # The notification specification defines the "sound-file" hint as a file path. Sound(path=...) would
        # send it as a file:// URI instead, which some servers (e.g. KDE Plasma) silently ignore.
        return Sound(uri=runtime_config.notification_sound_path)
    return DEFAULT_NOTIFICATION_SOUND


def show_notification(message: str, icon_name: str, stay_visible: bool = False):
    urgency = Urgency.Critical if stay_visible else Urgency.Normal
    notify.send(title="", message=message, icon=Icon(name=icon_name), sound=notification_sound(), urgency=urgency)


def finished_minimal_effort_notification():
    show_notification(f"Minimal effort (<i>{format_duration(runtime_config.minimal_effort_duration)}</i>) done!", "data-information")


def finished_work_notification():
    show_notification(f"Work (<i>{format_duration(runtime_config.work_duration)}</i>) done! <br>"
                       f"Overtime is counting - finish before <b>{format_time(runtime_config.start_time + runtime_config.work_duration + runtime_config.overtime_duration)}</b>!", "data-warning", stay_visible=True)


def main() -> int:
    args = sys.argv[1:]
    global runtime_config
    runtime_config = parse_configuration(args)

    # Start program under time limit
    user_command = start_monitored_command()
    runtime_config.start_time = datetime.datetime.now()

    display_progress_continuously(user_command)

    total_work_duration = datetime.datetime.now() - runtime_config.start_time

    # Kill program under test if it is still running
    if user_command and user_command.poll() is None:
        print("Overtime depleted - terminating user command...")
        terminate_monitored_command(user_command)

    notify.clear_all()

    # Show total time spent
    rprint(f"Total work duration: {format_duration(total_work_duration)}")

    # If log file path was provided - add appropriate entry
    if runtime_config.log_file_path:
        print(f"Saving work proof to {runtime_config.log_file_path}")
        with open(runtime_config.log_file_path, mode="a") as log_file:
            csv_writer = csv.writer(log_file, delimiter=',', quotechar='"')
            csv_writer.writerow([
                runtime_config.start_time.isoformat(),
                runtime_config.minimal_effort_duration,
                runtime_config.work_duration,
                runtime_config.overtime_duration,
                total_work_duration,
                runtime_config.title,
                " ".join(runtime_config.command_to_run)
            ])

    return 0


def display_progress_continuously(user_command: Optional[subprocess.Popen]):
    def should_countdown_continue() -> bool:
        return user_command is None or user_command.poll() is None

    # Report progress
    progress_display_columns = (
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        TextColumn("{task.fields[elapsed]} elapsed"),
        BarColumn(bar_width=None),
        TaskProgressColumn(),
        TextColumn("{task.fields[left]} left")
    )

    with Progress(*progress_display_columns, expand=True, console=console) as progress:
        try:
            console.clear()
            display_configuration()

            show_time_progress(should_countdown_continue, progress, "[green]Minimal effort", runtime_config.start_time,
                               runtime_config.start_time + runtime_config.minimal_effort_duration)
            if not should_countdown_continue():
                return
            finished_minimal_effort_notification()

            show_time_progress(should_countdown_continue, progress, "[bold white]Work", runtime_config.start_time,
                               runtime_config.start_time + runtime_config.work_duration)
            if not should_countdown_continue():
                return
            finished_work_notification()

            overtime_start_time = datetime.datetime.now()
            show_time_progress(should_countdown_continue, progress, "[red]Overtime", overtime_start_time,
                               overtime_start_time + runtime_config.overtime_duration)
        except KeyboardInterrupt:
            return


def start_monitored_command() -> Optional[subprocess.Popen]:
    user_command: Optional[subprocess.Popen] = None
    if runtime_config.command_to_run:
        try:
            # Run the command directly (without a shell) so its arguments are passed through unchanged.
            # A new session makes the command lead its own process group, so it and its children
            # can be terminated together.
            user_command = subprocess.Popen(runtime_config.command_to_run,
                                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                                            start_new_session=True)
        except OSError as e:
            rprint(f"[red]Could not launch monitored command: {e}[/red]")
            sys.exit(1)
        time.sleep(1)
        if user_command.poll() is not None:
            rprint("[red]Could not launch monitored command![/red]")
            sys.exit(1)
    return user_command


TERMINATION_GRACE_PERIOD = 5  # seconds


def is_process_group_alive(process_group_id: int) -> bool:
    try:
        os.killpg(process_group_id, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        pass  # The group exists, but we are not allowed to signal some of its members
    return True


def terminate_monitored_command(user_command: subprocess.Popen):
    # The command was started in a new session, so its process group ID equals its PID
    process_group_id = user_command.pid
    try:
        os.killpg(process_group_id, signal.SIGTERM)
    except ProcessLookupError:
        return  # Already gone

    # Give the command (and its children) a chance to shut down cleanly
    deadline = time.monotonic() + TERMINATION_GRACE_PERIOD
    while time.monotonic() < deadline:
        user_command.poll()  # Reap the main process so it doesn't keep the group alive as a zombie
        if not is_process_group_alive(process_group_id):
            return
        time.sleep(0.1)

    print(f"Command did not exit within {TERMINATION_GRACE_PERIOD} seconds - killing it...")
    try:
        os.killpg(process_group_id, signal.SIGKILL)
    except ProcessLookupError:
        pass
    user_command.wait()


def display_configuration():
    from rich.table import Table
    from rich.text import Text
    from rich.panel import Panel
    from rich.align import Align

    if runtime_config.title:
        title_panel = Panel(Align.center(runtime_config.title))
        console.print(title_panel)

    table = Table(show_header=False, box=None)
    table.add_column("Span", justify="right")
    table.add_column("Duration", justify="left")
    table.add_column("Hour", justify="left")

    table.add_row("Minimal effort",
                  Text(format_duration(runtime_config.minimal_effort_duration), style="green"),
                  "until " + format_time(runtime_config.start_time + runtime_config.minimal_effort_duration))
    table.add_row("Work",
                  Text(format_duration(runtime_config.work_duration), style="bold white"),
                  "until " + format_time(runtime_config.start_time + runtime_config.work_duration))
    table.add_row("Overtime",
                  Text(format_duration(runtime_config.overtime_duration), style="red"),
                  "until " + format_time(runtime_config.start_time + runtime_config.work_duration + runtime_config.overtime_duration))
    if runtime_config.command_to_run:
        table.add_row("Monitored command", runtime_config.command_to_run[0], " ".join(runtime_config.command_to_run[1:]))

    console.print(table)


def show_time_progress(should_countdown_continue: Callable[[], bool], progress: Progress, label: str, start_time: datetime.datetime, end_time: datetime.datetime):
    task_duration = (end_time - start_time)
    task_progress = progress.add_task(label, total=task_duration.total_seconds(), elapsed="0:00", left="--:--")
    elapsed = datetime.datetime.now() - start_time
    while elapsed < task_duration:
        time_left = task_duration - elapsed
        if int(elapsed.total_seconds()) % 30 == 0:
            console.clear()
            display_configuration()
        progress.update(task_progress,
                        completed=elapsed.total_seconds(),
                        elapsed=format_duration(elapsed),
                        left=format_duration(time_left, round_up=True))
        time.sleep(1)
        elapsed = datetime.datetime.now() - start_time
        if not should_countdown_continue():
            return

    time_left = task_duration - elapsed
    progress.update(task_progress,
                    completed=elapsed.total_seconds(),
                    elapsed=format_duration(elapsed),
                    left=format_duration(time_left, round_up=True))


if __name__ == '__main__':
    sys.exit(main())
