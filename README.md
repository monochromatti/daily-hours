# daily-hours

CLI tool to show uptime hours per day on NixOS/systemd systems.

Parses `journalctl --list-boots` and renders a per-day timeline with both working-window hours (06:00–17:00) and total hours using [Rich](https://github.com/Textualize/rich).

## Usage

```
daily-hours [-w WEEKS] [-s SUBTRACT]
```

| Flag | Description |
|------|-------------|
| `-w`, `--weeks` | Number of weeks to show (default: 1, current week) |
| `-s`, `--subtract` | Subtract this number from all hours |

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
