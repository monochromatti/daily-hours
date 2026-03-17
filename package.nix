{
  python3,
  writeShellApplication,
}:
let
  pythonSet = python3.withPackages (ps: [ ps.rich ]);
in
writeShellApplication {
  name = "daily-hours";
  runtimeInputs = [ pythonSet ];
  text = ''
    exec python3 ${./uptime.py} "$@"
  '';
}
