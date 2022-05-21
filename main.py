#!/usr/bin/env python
import datetime
import math
import sys
import time
from rich.progress import Progress, SpinnerColumn, TextColumn, BarColumn, TaskProgressColumn

MINIMAL_WORK_DURATION = datetime.timedelta(seconds=5)
#MINIMAL_WORK_DURATION = datetime.timedelta(minutes=5)
TARGET_WORK_DURATION = datetime.timedelta(minutes=1) - MINIMAL_WORK_DURATION
#TARGET_WORK_DURATION = datetime.timedelta(hours=1) - MINIMAL_WORK_DURATION
MAXIMUM_WORK_DURATION = datetime.timedelta(minutes=15)


def format_time(t: datetime.datetime) -> str:
    return t.strftime("%H:%M")


def main(args: [str]):
    # Show deadlines
    start_time = datetime.datetime.now()
    print(f"Task start:                 {format_time(start_time)}")
    print(f"Minimal effort finishes on: {format_time(start_time + MINIMAL_WORK_DURATION)}")
    print(f"Work will be done on:       {format_time(start_time + TARGET_WORK_DURATION)}")

    # TODO: Start program under time limit

    # Report progress
    progress_display_columns = (
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        BarColumn(bar_width=None),
        TaskProgressColumn(),
        TextColumn("{task.fields[left]}")
    )
    with Progress(*progress_display_columns, expand=True) as progress:
        start_time = datetime.datetime.now()
        show_time_progress(progress, "[green]Minimal effort", start_time, start_time + MINIMAL_WORK_DURATION)
        show_time_progress(progress, "[bold white]Work", start_time, start_time + TARGET_WORK_DURATION)
        start_time = datetime.datetime.now()
        show_time_progress(progress, "[red]Overtime", start_time, start_time + MAXIMUM_WORK_DURATION)

    # TODO: Show progress bar until there is time
    # TODO: Kill program under test if it still exists
    # TODO: Show actual time consumed


def show_time_progress(progress: Progress, label: str, start_time: datetime.datetime, end_time: datetime.datetime):
    task_duration = (end_time - start_time)
    task_progress = progress.add_task(label, total=task_duration.total_seconds(), left="--:--")
    elapsed = datetime.datetime.now() - start_time
    while elapsed < task_duration:
        time_left = task_duration - elapsed
        minutes_left, seconds_left = divmod(time_left.total_seconds(), 60)
        progress.update(task_progress, completed=elapsed.total_seconds(), left=f"{int(minutes_left)}:{int(seconds_left):02}")
        time.sleep(1)
        elapsed = datetime.datetime.now() - start_time
    progress.update(task_progress, completed=task_duration.total_seconds(), left="DONE")


if __name__ == '__main__':
    main(sys.argv[1:])
