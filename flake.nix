{
  description = "CLI tool to show uptime hours per day on NixOS/systemd systems";

  inputs = {
    nixpkgs.url = "github:NixOS/nixpkgs/nixos-25.11";
    flake-parts.url = "github:hercules-ci/flake-parts";
  };

  outputs =
    inputs@{ flake-parts, ... }:
    flake-parts.lib.mkFlake { inherit inputs; } {
      systems = [
        "x86_64-linux"
        "aarch64-linux"
        "x86_64-darwin"
        "aarch64-darwin"
      ];

      perSystem =
        { pkgs, ... }:
        let
          daily-hours = pkgs.callPackage ./package.nix { };
        in
        {
          packages = {
            inherit daily-hours;
            default = daily-hours;
          };
        };
    };
}
