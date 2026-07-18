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
        (python3.withPackages (ps:
          with ps; [
            i3ipc
            pytest
            pytest-asyncio
            lxml
            markdownify
            trafilatura
          ]))
        web-ext
        ruff
        uv
        doctrine-pkg
        just
        bun
      ];

      agents = pub.lib.${system}.mkJailedAgents {inherit llm-agents;};

      # Expose the host niri IPC socket to the jails so the compositor/niri
      # capture path (frames() -> $NIRI_SOCKET) can reach the live compositor,
      # mirroring the PULSE_SERVER audio passthrough in baseJailOptions. The
      # socket name carries a per-session suffix (niri.wayland-<id>.sock), so
      # both the env var and the bind resolve at launch time from the host's
      # $NIRI_SOCKET — the apiKeyPassThrough runtime-forward pattern, not a
      # baked constant. Unset on the host -> empty setenv + /dev/null no-op
      # bind, and the watcher backs off (compositor_disconnected) as designed.
      niriOptions = with agents.combinators; [
        (unsafe-add-raw-args "--setenv NIRI_SOCKET \"\${NIRI_SOCKET:-}\"")
        (unsafe-add-raw-args "--bind-try \"\${NIRI_SOCKET:-/dev/null}\" \"\${NIRI_SOCKET:-/dev/null}\"")
      ];

      jailPkgs = {
        jailed-pi = agents.makeJailedPi {
          profile = "specDev";
          extraPkgs = projectPkgs;
          extraOptions = niriOptions;
          allowSelfAsSubagent = true;
          maxSubagentDepth = 2;
        };
        jailed-claude = agents.makeJailedClaude {
          profile = "specDev";
          extraPkgs = projectPkgs;
          extraOptions = niriOptions;
        };
        jailed-codex = agents.makeJailedCodex {
          profile = "specDev";
          extraPkgs = projectPkgs;
          extraOptions = niriOptions;
        };
        jailed-opencode = agents.makeJailedOpencode {
          profile = "specDev";
          extraPkgs = projectPkgs;
          extraOptions = niriOptions;
        };
        claude = agents.agentsByName.claude;
        codex = agents.agentsByName.codex;
        jailed-shell = agents.makeJailedAgent {
          name = "shell";
          agent = pkgs.zsh;
          profile = "specDev";
          extraPkgs = projectPkgs;
          extraOptions = niriOptions;
          subagents = ["pi" "claude"];
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
