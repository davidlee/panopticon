{
  description = "panopticon — local desktop-behaviour capture";

  inputs = {
    nixpkgs.url = "github:NixOS/nixpkgs/nixos-unstable";
    flake-utils.url = "github:numtide/flake-utils";
    devshell.url = "github:numtide/devshell";
    doctrine.url = "github:davidlee/doctrine";
  };

  outputs = {
    self,
    nixpkgs,
    flake-utils,
    devshell,
    doctrine,
  }:
    flake-utils.lib.eachDefaultSystem (system: let
      pkgs = import nixpkgs {
        inherit system;
        overlays = [devshell.overlays.default];
      };

      panopticon = pkgs.python3Packages.buildPythonApplication {
        pname = "panopticon";
        inherit ((builtins.fromTOML (builtins.readFile ./pyproject.toml)).project) version;
        pyproject = true;
        src = ./.;
        build-system = with pkgs.python3Packages; [hatchling];
        dependencies = with pkgs.python3Packages; [evdev i3ipc lxml markdownify];
        # git: the git-poller suite (tests/test_git_poller.py) shells out to a
        # real git binary — the sandbox has none unless we add it here.
        nativeCheckInputs =
          (with pkgs.python3Packages; [pytestCheckHook pytest-asyncio])
          ++ [pkgs.git];
        meta.mainProgram = "panopticon-desktop";
      };

      doctrine-pkg = doctrine.packages.${system}.default;

      # Project tools injected into each jail so agents can run the same
      # build/test/lint loop a human would.
      projectPkgs = with pkgs; [
        (python3.withPackages (ps:
          with ps; [
            evdev
            i3ipc
            pytest
            pytest-asyncio
            lxml
            markdownify
          ]))
        web-ext
        ruff
        uv
        just
        bun
      ];
    in {
      packages = {
        default = panopticon;
        panopticon = panopticon;

        # The same `projectPkgs` the jails and the devshell get, as one
        # package: dev-envs jails and forms take it, and so does oubliette's
        # microVM. One list, so they and this devshell cannot drift.
        dev-tools = pkgs.buildEnv {
          name = "panopticon-dev-tools";
          paths = projectPkgs;
          ignoreCollisions = true;
        };
        # What the VM takes: `dev-tools` plus doctrine. The devshell and
        # jails use the host's install (agents' hostDoctrine), which a VM
        # does not have.
        capsule-tools = pkgs.buildEnv {
          name = "panopticon-capsule-tools";
          paths = projectPkgs ++ [doctrine-pkg];
          ignoreCollisions = true;
        };
      };

      devShells.default = pkgs.devshell.mkShell {
        packages = projectPkgs;
      };
    });
}
