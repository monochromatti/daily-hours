# daily-hours

CLI tool to show explicit work hours per day.

`daily-hours` tracks work time from user-controlled `on`/`off` events stored as JSONL in `${XDG_STATE_HOME:-~/.local/state}/daily-hours/work-events.jsonl`. Reports render a per-day timeline with both working-window hours (06:00–17:00) and total hours using [Rich](https://github.com/Textualize/rich).

## Usage

Show report:

```bash
daily-hours [-w WEEKS] [-s SUBTRACT]
```

Control work tracking:

```bash
daily-hours work status
daily-hours work on [--source SOURCE] [--at TIMESTAMP]
daily-hours work off [--source SOURCE] [--at TIMESTAMP]
daily-hours work toggle [--source SOURCE] [--at TIMESTAMP]
```

| Flag | Description |
|------|-------------|
| `-w`, `--weeks` | Number of weeks to show (default: 1, current week) |
| `-s`, `--subtract` | Subtract this number from all hours |
| `--source` | Caller label persisted with new work events (default: `cli`) |
| `--at` | ISO 8601 timestamp with timezone offset, useful for tests/manual fixes |

If current state is `on`, reports count the open interval until now. Running `work on` while already on, or `work off` while already off, is a no-op.

## Examples

```bash
daily-hours work on
# ...work...
daily-hours work off

daily-hours work toggle --source noctalia

daily-hours work on --source startup
daily-hours work off --source shutdown
```

## Installation

### With Nix flakes

```bash
nix run github:monochromatti/daily-hours
```

### In a NixOS / Home Manager config

```nix
{
  inputs.daily-hours.url = "github:monochromatti/daily-hours";

  # then, in a module:
  home.packages = [ inputs.daily-hours.packages.${system}.default ];
}
```
