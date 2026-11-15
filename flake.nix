{
  description = "Development shell for Tifis (Python + numpy)";

  # Same input as before, so the existing flake.lock still applies.
  inputs = {
    nixpkgs = {
      type = "github";
      owner = "NixOS";
      repo = "nixpkgs";
      ref = "nixpkgs-unstable";
    };
  };

  outputs = {nixpkgs, ...}: let
    inherit (nixpkgs) lib;
    forAllSystems = f:
      lib.genAttrs lib.systems.flakeExposed (system: f nixpkgs.legacyPackages.${system});

    # numpy is the only runtime dependency; astropy cross-checks the WCS in
    # the tests and runs docs/operaciones.ipynb.
    pythonFor = pkgs:
      pkgs.python3.withPackages (ps: with ps; [numpy astropy pytest]);

    # Serves the app, the IRSA/Gaia proxy and the engine from one origin: IRSA
    # sends no CORS headers, so the browser cannot query it directly.
    makeServeWeb = pkgs:
      pkgs.writeShellApplication {
        name = "serve-web";
        runtimeInputs = [(pythonFor pkgs)];
        text = ''
          exec python -m spherex --addr ":''${PORT:-8080}" "$@"
        '';
      };

    # Kept so old habits still work: there is nothing to compile any more.
    makeBuildWeb = pkgs:
      pkgs.writeShellApplication {
        name = "build-web";
        text = ''
          echo "Nothing to build: the web app is served straight from ui/. Run serve-web."
        '';
      };
  in {
    devShells = forAllSystems (pkgs: {
      default = pkgs.mkShell {
        packages = [
          (pythonFor pkgs)
          (makeServeWeb pkgs)
          (makeBuildWeb pkgs)
        ];
      };
    });
  };
}
