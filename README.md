# Killtimer - do more working less!
This utility helps limit the amount of time devoted to work by keeping track of clearly defined work periods.
It's like a timer which cannot be stopped but will kill the passed command forcing the user to finish the job.

This may sound counterintuitive, but a lot of studies show that limiting time for a task forces the person to use the time more effectively.

## Features
- CLI interface
- Three configurable effort levels:
  - Minimal
  - Work
  - Overtime
- Keep track of user-provided command and kill it if it has been running too long (after overtime)
- Utilizes desktop notifications to inform users about the finished period
- Optionally can play a sound when minimal effort/work period is done
- Allow storing amount of work done as CSV file for further analysis 

## Install
```console
$ pip install [--user] killtimer
```

## Usage

![Screencast](screencast.gif)

```usage
usage: killtimer [-h] [-m duration] [-w duration] [-o duration] [-l log_file] [-t title] [-s sound_file] [command [command ...]]

Close application when time runs out

positional arguments:
  command               Executable (with arguments) to run (default: None)

optional arguments:
  -h, --help            show this help message and exit
  -m duration, --minimal-effort duration
                        Minimal work duration (default: 0:10:00)
  -w duration, --work duration
                        Proper work duration (default: 1:00:00)
  -o duration, --overtime duration
                        Overtime duration (default: 0:15:00)
  -l log_file, --log log_file
                        Log file where to store amount of work done (default: None)
  -t title, --title title
                        Title to display above progress bars and configuration (default: None)
  -s sound_file, --sound sound_file
                        Sound file to play when minimal effort or work period is reached (default: None)
```

Usually you would want to create alias in your `*rc` file like:
```shell
alias blender-work="killtimer -m 10m -w 1h -o 10m -t 'Creative work' -l /path/to/worklog.csv blender"
```