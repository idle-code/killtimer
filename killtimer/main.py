#!/usr/bin/env python
import argparse
import asyncio
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
import wave
import pyaudio
from dataclasses import dataclass
from typing import Optional, List, Callable
from desktop_notifier import DesktopNotifier, Urgency
from rich.progress import Progress, SpinnerColumn, TextColumn, BarColumn, TaskProgressColumn
from rich.console import Console
from rich import print as rprint

from alsa_utils import noalsaerr


def format_time(t: datetime.datetime) -> str:
    return t.strftime("%H:%M")


def format_duration(duration: datetime.timedelta, round_up: bool = False) -> str:
    total_seconds = duration.total_seconds()
    total_seconds = math.ceil(total_seconds) if round_up else math.floor(total_seconds)
    return humanfriendly.format_timespan(humanfriendly.coerce_seconds(total_seconds))


def parse_timedelta(time_delta_representation: str) -> datetime.timedelta:
    return datetime.timedelta(seconds=pytimeparse.parse(time_delta_representation))


@dataclass
class RuntimeConfiguration:
    start_time: datetime.datetime
    minimal_effort_duration: datetime.timedelta = datetime.timedelta(minutes=10)
    work_duration: datetime.timedelta = datetime.timedelta(hours=1)
    overtime_duration: datetime.timedelta = datetime.timedelta(minutes=15)
    title: Optional[str] = None
    command_to_run: Optional[List[str]] = None
    log_file_path: Optional[str] = None
    notification_sound_path: Optional[str] = None


def parse_configuration(args: [str]) -> RuntimeConfiguration:
    parser = argparse.ArgumentParser(
        prog="killtimer",
        description="Close application when time runs out",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter
    )
    parser.add_argument(
        "-m", "--minimal-effort",
        type=parse_timedelta,
        default=RuntimeConfiguration.minimal_effort_duration,
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
        default=RuntimeConfiguration.overtime_duration,
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
        type=str,
        default=None,
        metavar="sound_file",
        help="Sound file to play when minimal effort or work period is reached"
    )
    parser.add_argument(
        "command_to_run",
        nargs="*",
        metavar="command",
        help="Executable (with arguments) to run"
    )

    config = parser.parse_args(args)

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


notify = DesktopNotifier(app_name="Killtimer")
event_loop = asyncio.get_event_loop()

console = Console()

runtime_config: RuntimeConfiguration

AUDIO_CHUNK_SIZE = 1024


def play_notification_sound():
    if runtime_config.notification_sound_path:
        # TODO: make playback async
        with noalsaerr(), wave.open(runtime_config.notification_sound_path, 'rb') as wf:
            pa = pyaudio.PyAudio()
            stream = pa.open(format=pa.get_format_from_width(wf.getsampwidth()),
                             channels=wf.getnchannels(),
                             rate=wf.getframerate(),
                             output=True)

            # TODO: For Python 3.8 use while len(data := wf.readframes(AUDIO_CHUNK_SIZE))
            while True:
                data = wf.readframes(AUDIO_CHUNK_SIZE)
                if not data:
                    break
                stream.write(data)

            stream.close()
            pa.terminate()


def show_notification(message: str, icon_name: str, stay_visible: bool = False):
    urgency = Urgency.Critical if stay_visible else Urgency.Normal
    event_loop.run_until_complete(notify.send(title="", message=message, icon=icon_name, sound=True, urgency=urgency))


def finished_minimal_effort_notification():
    play_notification_sound()
    show_notification(f"Minimal effort (<i>{format_duration(runtime_config.minimal_effort_duration)}</i>) done!", "data-information")


def finished_work_notification():
    play_notification_sound()
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
        os.killpg(os.getpgid(user_command.pid), signal.SIGTERM)
        # CHECK: wait a bit and kill it if still running?

    event_loop.run_until_complete(notify.clear_all())

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
        user_command = subprocess.Popen(" ".join(["exec"] + runtime_config.command_to_run), shell=True,
                                        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                                        preexec_fn=os.setsid)
        time.sleep(1)
        if user_command.poll() is not None:
            rprint("[red]Could not launch monitored command![/red]")
            sys.exit(1)
    return user_command


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
