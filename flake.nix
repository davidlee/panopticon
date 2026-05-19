{
  description = "panopticon — local desktop-behaviour capture";

  inputs = {
    nixpkgs.url = "github:NixOS/nixpkgs/nixos-unstable";
    flake-utils.url = "github:numtide/flake-utils";
  };

  outputs = { self, nixpkgs, flake-utils }:
    flake-utils.lib.eachDefaultSystem (system:
      let
        pkgs = import nixpkgs { inherit system; };
        panopticon = pkgs.python3Packages.buildPythonApplication {
          pname = "panopticon";
          version = "0.1.0";
          pyproject = true;
          src = ./.;
          build-system = with pkgs.python3Packages; [ hatchling ];
          dependencies = with pkgs.python3Packages; [ i3ipc ];
          nativeCheckInputs = with pkgs.python3Packages; [ pytestCheckHook ];
        };
      in {
        packages.default = panopticon;
        packages.panopticon = panopticon;

        devShells.default = pkgs.mkShell {
          packages = [
            (pkgs.python3.withPackages (ps: with ps; [ i3ipc pytest ]))
            pkgs.ruff
            pkgs.uv
          ];
        };
      });
}
