{
  description = "panopticon — local desktop-behaviour capture";

  inputs = {
    nixpkgs.url = "github:NixOS/nixpkgs/nixos-unstable";
    flake-utils.url = "github:numtide/flake-utils";
    devshell.url = "github:numtide/devshell";
    pub.url = "github:davidlee/nix-config?dir=flakes/pub";
    llm-agents.url = "github:numtide/llm-agents.nix";
    doctrine.url = "github:davidlee/doctrine";
  };

  outputs = {
    self,
    nixpkgs,
    flake-utils,
    devshell,
    pub,
    llm-agents,
    doctrine,
  }:
    flake-utils.lib.eachDefaultSystem (system: let
      pkgs = import nixpkgs {
        inherit system;
        overlays = [devshell.overlays.default];
      };
      inherit (pkgs.stdenv) isLinux;

      panopticon = pkgs.python3Packages.buildPythonApplication {
        pname = "panopticon";
        version = "0.2.1";
        pyproject = true;
        src = ./.;
        build-system = with pkgs.python3Packages; [hatchling];
        dependencies = with pkgs.python3Packages; [i3ipc lxml markdownify trafilatura];
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
        web-ext
        (python3.withPackages (ps: with ps; [i3ipc pytest lxml markdownify trafilatura]))
        ruff
        uv
        doctrine-pkg
      ];

      agents = pub.lib.${system}.mkJailedAgents {inherit llm-agents;};

      jailPkgs = {
        jailed-pi = agents.makeJailedPi {
          profile = "specDev";
          extraPkgs = projectPkgs;
          allowSelfAsSubagent = true;
          maxSubagentDepth = 2;
        };
        jailed-claude = agents.makeJailedClaude {
          profile = "specDev";
          extraPkgs = projectPkgs;
        };
        jailed-codex = agents.makeJailedCodex {
          profile = "specDev";
          extraPkgs = projectPkgs;
        };
        jailed-gemini = agents.makeJailedGemini {
          profile = "specDev";
          extraPkgs = projectPkgs;
        };
        jailed-opencode = agents.makeJailedOpencode {
          profile = "specDev";
          extraPkgs = projectPkgs;
        };
      };
    in {
      packages =
        {
          default = panopticon;
          panopticon = panopticon;
        }
        // pkgs.lib.optionalAttrs isLinux jailPkgs;

      devShells.default = pkgs.devshell.mkShell {
        packages =
          projectPkgs
          ++ pkgs.lib.optionals isLinux (pkgs.lib.attrValues jailPkgs);

        commands = pkgs.lib.optionals isLinux [
          {
            name = "jpi";
            help = "op run -- jailed-pi $@";
            command = "op run -- jailed-pi \"$@\"";
          }
          {
            name = "jcl";
            help = "jailed-claude (--dangerously-skip-permissions for interactive)";
            command = ''
              case "''${1:-}" in
                marketplace|update|config|mcp) jailed-claude "$@" ;;
                *) jailed-claude --dangerously-skip-permissions "$@" ;;
              esac
            '';
          }
        ];
      };
    });
}
