#!/usr/bin/env python
import argparse
import csv
import datetime
import sys
from collections import defaultdict

from dataclasses import dataclass
from typing import List

from main import parse_timedelta


@dataclass
class RuntimeConfiguration:
    # start_time: Optional[datetime.datetime]
    # end_time: Optional[datetime.datetime]
    log_file_path: str
    stat_total_duration_worked: bool = False


def parse_configuration(args: [str]) -> RuntimeConfiguration:
    parser = argparse.ArgumentParser(
        prog="killtimer-stats",
        description="Generate insight from log file generated by killtimer",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter
    )
    parser.add_argument(
        type=str,
        dest="log_file",
        metavar="log_file",
        help="Log file where amount of work done is stored"
    )
    parser.add_argument(
        "-t", "--total-duration",
        action="store_true",
        help="Report total work duration grouped by executed program"
    )

    config = parser.parse_args(args)

    return RuntimeConfiguration(
        log_file_path=config.log_file,
        stat_total_duration_worked=config.total_duration
    )


runtime_config: RuntimeConfiguration


@dataclass
class WorkLogRecord:
    start_time: datetime.datetime
    minimal_effort_duration: datetime.timedelta
    work_duration: datetime.timedelta
    overtime_duration: datetime.timedelta
    total_work_duration: datetime.timedelta
    command: str

    @staticmethod
    def from_row(row: List[str]) -> "WorkLogRecord":
        return WorkLogRecord(
            start_time=datetime.datetime.fromisoformat(row[0]),
            minimal_effort_duration=parse_timedelta(row[1]),
            work_duration=parse_timedelta(row[2]),
            overtime_duration=parse_timedelta(row[3]),
            total_work_duration=parse_timedelta(row[4]),
            command=row[5]
        )


def load_log_file(log_file_path: str) -> List[WorkLogRecord]:
    with open(log_file_path) as log_file:
        csv_reader = csv.reader(log_file, delimiter=',', quotechar='"')
        return list(map(WorkLogRecord.from_row, csv_reader))


def main() -> int:
    args = sys.argv[1:]
    global runtime_config
    runtime_config = parse_configuration(args)

    # Load log file
    work_log = load_log_file(runtime_config.log_file_path)
    print(f"{len(work_log)} records loaded")

    # (Optional) Filter data to fit requested range

    # Generate stats
    groupings = defaultdict(list)
    for record in work_log:
        groupings[record.command].append(record)

    # TODO: Use rich to generate pretty tables
    if runtime_config.stat_total_duration_worked:
        print("Program\tEntry count\tTotal worked duration")
        for program, records in groupings.items():
            duration_sum = sum(map(lambda r: r.total_work_duration, records), datetime.timedelta())
            print(f"{program}\t{len(records)}\t{duration_sum}")

    return 0


if __name__ == '__main__':
    sys.exit(main())
